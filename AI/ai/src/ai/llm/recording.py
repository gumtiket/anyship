"""Opt-in transport recording and strict offline replay for owned samples only."""

import hashlib
import json
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

from pydantic import Field

from ai.detectors import RepoView
from ai.llm.base import LLMResult, Tier, ValidatingClient
from ai.llm.cost import CostTracker, ModelPricing
from ai.models import OutputModel
from ai.security import SourceMasker
from ai.transform.service import identify_sample

STAGES = {"diagnose", "transform", "dockerfile", "spec", "recommend", "repair"}
DEFAULT_FIXTURES = Path(__file__).resolve().parents[3] / "tests/fixtures/llm"


class PlaybackError(Exception):
    """Fatal replay error; cannot be swallowed by normal LLM fallback handlers."""


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def prompt_digest(system: str, user: str, tier: str, parameters: dict) -> str:
    return digest({"system": system, "user": user, "tier": tier, "parameters": parameters})


def assert_public(text: str) -> None:
    patterns = (
        r"(?<!\d)(?!0{12}(?!\d)|1{12}(?!\d))\d{12}(?!\d)",
        r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
        r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b",
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s\"'<>/@]+:[^\s\"'<>/@]+@",
        r"/(?:Users|home)/[^/\s]+/",
        r"(?i)(?:password|secret[_-]?key|api[_-]?key|access[_-]?token)[\"']?\s*[:=]\s*"
        r"[\"'](?!dummy-secret-do-not-use|\[REDACTED\])[^\"']+",
    )
    # Image/tree SHA strings can contain twelve adjacent digits. They are not account IDs.
    without_hashes = re.sub(r"\b[a-f0-9]{24,64}\b", "[HASH]", text)
    if re.search(patterns[0], without_hashes) or any(
        re.search(pattern, text) for pattern in patterns[1:]
    ):
        raise PlaybackError("fixture_sensitive_material: 원문을 저장하거나 출력하지 않습니다.")


def write_json(path: Path, value: dict) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    assert_public(text)
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise PlaybackError("fixture_symlink_forbidden")
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
        temporary = Path(file.name)
        try:
            file.write(text)
            file.flush()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


class Entry(OutputModel):
    tier: Literal["strong", "fast"]
    prompt_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    response_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    response: dict


class Fixture(OutputModel):
    format_version: Literal[1] = 1
    sample: Literal["todo", "todo-scheduler"]
    stage: str
    origin: str
    parameters: dict
    entries: list[Entry] = Field(min_length=1, max_length=50)


def sample_inputs(repo: str | Path, fixture_root: Path) -> tuple[str, SourceMasker]:
    view = RepoView(repo)
    sample = identify_sample(view)
    masker = SourceMasker(view)
    if sample is None or view.warnings or masker.blocked_files:
        raise PlaybackError("record/replay는 해시로 확인한 두 자체 샘플만 지원합니다.")
    source = view.root
    target = fixture_root.resolve()
    if target.is_relative_to(source) or source.is_relative_to(target):
        raise PlaybackError("원본 보호: fixture는 입력 레포와 분리하세요.")
    return sample, masker


class RecordingClient(ValidatingClient):
    def __init__(self, backend: ValidatingClient, repo: str | Path, root: Path = DEFAULT_FIXTURES):
        super().__init__(tracker=CostTracker(backend.tracker.prices))
        self.sample, self.masker = sample_inputs(repo, root)
        self.backend = backend
        self.root = root
        self.models = getattr(backend, "models", {})
        self.recordings: dict[str, Fixture] = {}

    def request_parameters(self, tier: Tier) -> dict:
        return self.backend.request_parameters(tier)

    def _invoke(self, system: str, user: str, *, tier: Tier, stage: str) -> LLMResult:
        if stage not in STAGES:
            raise PlaybackError("fixture_stage_invalid")
        if stage in self.recordings and len(self.recordings[stage].entries) >= 50:
            raise PlaybackError("fixture_stage_limit")
        result = self.backend._invoke(system, user, tier=tier, stage=stage)
        response = result.model_dump(mode="json", exclude={"parsed"})
        # Preserve complete response bytes except recognized secret/credential substitutions.
        safe_text = self.masker.text(result.text, allow_dummy=True)
        safe_text = re.sub(
            r"([a-z][a-z0-9+.-]*://)[^\s/@]+:[^\s/@]+@",
            r"\1[REDACTED]@",
            safe_text,
            flags=re.I,
        )
        safe_text = re.sub(r"(?<!\d)\d{12}(?!\d)", "[ACCOUNT_ID]", safe_text)
        assert_public(safe_text)
        response["text"] = safe_text
        parameters = self.request_parameters(tier)
        entry = Entry(
            tier=tier,
            prompt_hash=prompt_digest(system, user, tier, parameters),
            response_hash=digest(response),
            response=response,
        )
        if stage not in self.recordings:
            self.recordings[stage] = Fixture(
                sample=self.sample,
                stage=stage,
                origin=type(self.backend).__name__,
                parameters=parameters,
                entries=[entry],
            )
        else:
            self.recordings[stage].entries.append(entry)
        fixture = self.recordings[stage]
        write_json(self.root / self.sample / f"{stage}.json", fixture.model_dump(mode="json"))
        return result.model_copy(update={"text": safe_text})


class ReplayClient(ValidatingClient):
    is_replay = True

    def __init__(self, repo: str | Path, root: Path = DEFAULT_FIXTURES):
        super().__init__()
        self.sample, _ = sample_inputs(repo, root)
        self.fixtures = {}
        self.cursors: dict[str, int] = {}
        self.models = {}
        self.parameters = {}
        directory = root / self.sample
        try:
            for path in sorted(directory.glob("*.json")):
                if path.stem not in STAGES or path.is_symlink() or path.stat().st_size > 524288:
                    raise PlaybackError("fixture_file_invalid")
                if any(parent.is_symlink() for parent in path.parents):
                    raise PlaybackError("fixture_symlink_forbidden")
                text = path.read_text()
                assert_public(text)
                fixture = Fixture.model_validate_json(text)
                if fixture.sample != self.sample or fixture.stage != path.stem:
                    raise PlaybackError("fixture_identity_mismatch")
                for entry in fixture.entries:
                    if digest(entry.response) != entry.response_hash:
                        raise PlaybackError("fixture_response_hash_mismatch")
                    result = LLMResult.model_validate(entry.response)
                    self.models[entry.tier] = result.model_id
                    self.parameters[entry.tier] = fixture.parameters
                    self.tracker.prices["replay:" + result.model_id] = ModelPricing(
                        input_usd_per_million=0, output_usd_per_million=0
                    )
                self.fixtures[fixture.stage] = fixture
        except (ValueError, OSError) as error:
            raise PlaybackError(f"fixture_read_invalid: {type(error).__name__}") from None
        if not self.fixtures:
            raise PlaybackError(f"fixture_missing: {self.sample}")

    def request_parameters(self, tier: Tier) -> dict:
        return self.parameters.get(tier, {})

    def _invoke(self, system: str, user: str, *, tier: Tier, stage: str) -> LLMResult:
        fixture = self.fixtures.get(stage)
        index = self.cursors.get(stage, 0)
        if fixture is None or index >= len(fixture.entries):
            raise PlaybackError(f"fixture_request_missing: {self.sample}/{stage} #{index + 1}")
        entry = fixture.entries[index]
        actual = prompt_digest(system, user, tier, self.request_parameters(tier))
        if tier != entry.tier or actual != entry.prompt_hash:
            raise PlaybackError(
                f"prompt_hash_mismatch: {self.sample}/{stage} #{index + 1}; "
                "프롬프트/스키마/입력이 바뀌었습니다. refresh_golden.py로 의도한 변경을 검토하세요."
            )
        self.cursors[stage] = index + 1
        recorded = LLMResult.model_validate(entry.response)
        return LLMResult(
            text=recorded.text,
            input_tokens=0,
            output_tokens=0,
            model_id="replay:" + recorded.model_id,
            transport_attempts=0,
            stop_reason=recorded.stop_reason,
            usage={"source": "llm_replay", "recorded_usage": recorded.usage},
        )

    def assert_consumed(self) -> None:
        if any(self.cursors.get(stage, 0) != len(f.entries) for stage, f in self.fixtures.items()):
            raise PlaybackError("fixture_requests_unused: 기록 당시와 실행 단계가 다릅니다.")
