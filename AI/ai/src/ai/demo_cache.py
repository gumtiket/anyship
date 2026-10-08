"""Explicit replay of historical sample results; never authorizes deployment."""

import hashlib
import json
import time
from importlib.resources import files
from pathlib import Path

import yaml

from ai.detectors import RepoView
from ai.llm.recording import PlaybackError, assert_public, digest, write_json
from ai.models import AnalysisResult, CostReport, Diagnosis, GateReport, Recommendation
from ai.spec.models import DeploySpec
from ai.stages import Stage
from ai.transform.service import identify_sample

DEFAULT_CACHE = Path(__file__).resolve().parents[2] / "demo-cache"
NAMES = (
    "diagnosis.json",
    "changes.diff",
    "Dockerfile",
    "deploy-spec.yaml",
    "recommendation.json",
    "gate-report.json",
    "cost.json",
)


def code_hash(repo: str | Path) -> str:
    view = RepoView(repo)
    if view.warnings:
        raise ValueError("cache_incomplete_source_scan")
    return digest({name: view.read(name) for name in view.files()})


def engine_hash() -> str:
    root = Path(str(files("ai")))
    return digest(
        {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*"))
            if path.is_file()
            and path.suffix in {".py", ".json", ".txt"}
            and "__pycache__" not in path.parts
        }
    )


def settings_key(
    sample: str,
    *,
    target_env="aws",
    commit=None,
    source_repo=None,
    profile="dev",
    image_reference=None,
    tfvars_overrides=None,
    cost_assumptions=None,
    compare_original=True,
) -> dict:
    return {
        "target_env": target_env,
        "commit": commit,
        "source_repo": source_repo or f"sample://{sample}",
        "profile": profile,
        "image_reference": image_reference,
        "tfvars_overrides": tfvars_overrides or {},
        "cost_assumptions": cost_assumptions.model_dump(mode="json") if cost_assumptions else None,
        "compare_original": compare_original,
    }


def save_cache(
    repo: str | Path,
    result: AnalysisResult,
    events: list[dict],
    *,
    root: Path = DEFAULT_CACHE,
    settings: dict | None = None,
) -> Path:
    view = RepoView(repo)
    sample = identify_sample(view)
    if (
        sample is None
        or result.gate_report.status != "passed"
        or result.gate_report.runner != "docker"
        or result.diagnosis.enrichment_status != "completed"
        or result.recommendation.rationale_source != "llm"
        or not result.cost.calls
        or any(
            not call.model_id.startswith(("global.anthropic.", "global.openai.", "us."))
            for call in result.cost.calls
        )
        or result.execution_source != "current_run"
    ):
        raise ValueError("demo_cache_requires_actual_bedrock_and_docker_sample_result")
    destination = root / sample
    source = view.root
    if root.resolve().is_relative_to(source) or source.is_relative_to(root.resolve()):
        raise ValueError("cache_output_overlaps_input")
    payloads = {name: Path(result.output_files[name]).read_text() for name in NAMES}
    for text in payloads.values():
        assert_public(text)
    # Relative file names only: portable snapshots contain no live host paths/context owner.
    snapshot = result.model_dump(mode="json")
    snapshot["output_files"] = {name: name for name in NAMES}
    snapshot["build_context"] = None
    manifest = {
        "format_version": 1,
        "sample": sample,
        "code_hash": code_hash(repo),
        "engine_hash": engine_hash(),
        "settings": settings or settings_key(sample),
        "out_hashes": {
            name: hashlib.sha256(text.encode()).hexdigest() for name, text in payloads.items()
        },
        "result": snapshot,
        "events": events,
        "provenance": "Actual Bedrock responses and Docker sample gate; historical result",
    }
    assert_public(json.dumps(manifest, ensure_ascii=False))
    for name, text in payloads.items():
        path = destination / "out" / name
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
            raise ValueError("cache_symlink_forbidden")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    write_json(destination / "manifest.json", manifest)
    return destination


def try_restore(
    repo: Path,
    output: Path,
    log,
    *,
    root: Path = DEFAULT_CACHE,
    settings: dict,
    delay_s: float = 0.01,
    sleep=time.sleep,
) -> AnalysisResult | None:
    # Import at call time to retain the public pipeline's original output helpers.
    from ai.pipeline import _write_output

    started = time.monotonic()
    sample = identify_sample(RepoView(repo))
    try:
        if sample is None:
            raise ValueError("not_owned_sample")
        directory = root / sample
        manifest_path = directory / "manifest.json"
        if (
            manifest_path.is_symlink()
            or any(p.is_symlink() for p in manifest_path.parents)
            or manifest_path.stat().st_size > 1048576
        ):
            raise ValueError("invalid_manifest_file")
        manifest = json.loads(manifest_path.read_text())
        if (
            manifest["format_version"] != 1
            or manifest["sample"] != sample
            or manifest["code_hash"] != code_hash(repo)
            or manifest["engine_hash"] != engine_hash()
            or manifest["settings"] != settings
            or set(manifest["out_hashes"]) != set(NAMES)
        ):
            raise ValueError("cache_identity_or_settings_changed")
        payloads = {}
        for name in NAMES:
            path = directory / "out" / name
            if (
                path.is_symlink()
                or any(parent.is_symlink() for parent in path.parents)
                or path.stat().st_size > 524288
            ):
                raise ValueError("invalid_cache_artifact")
            text = path.read_text()
            assert_public(text)
            if hashlib.sha256(text.encode()).hexdigest() != manifest["out_hashes"][name]:
                raise ValueError("cache_artifact_hash_mismatch")
            payloads[name] = text
        result = AnalysisResult.model_validate(manifest["result"])
        if result.gate_report.status != "passed" or result.gate_report.runner != "docker":
            raise ValueError("cache_gate_not_verified")
        # Check serialized output models agree with the validated snapshot, not just hashes.
        for name, model, expected in (
            ("diagnosis.json", Diagnosis, result.diagnosis),
            ("recommendation.json", Recommendation, result.recommendation),
            ("gate-report.json", GateReport, result.gate_report),
            ("cost.json", CostReport, result.cost),
        ):
            if model.model_validate_json(payloads[name]) != expected:
                raise ValueError("cache_snapshot_mismatch")
        if (
            DeploySpec.model_validate(yaml.safe_load(payloads["deploy-spec.yaml"]))
            != result.deploy_spec
        ):
            raise ValueError("cache_spec_mismatch")
        events = [(Stage(event["stage"]), event["message"]) for event in manifest["events"]]
        if (
            not events
            or len(events) > 200
            or any(not isinstance(message, str) for _, message in events)
        ):
            raise ValueError("cache_events_invalid")
        assert_public(json.dumps(manifest, ensure_ascii=False))
    except (ValueError, KeyError, TypeError, OSError, PlaybackError):
        log(
            Stage.ANALYZING,
            "데모 캐시 없음/코드·설정·구현 변경/검증 실패: 정상 분석으로 실행합니다.",
        )
        return None
    if not 0 <= delay_s <= 0.2:
        raise ValueError("cache_replay_delay_out_of_range")
    log(Stage.ANALYZING, "(사전 실행 결과) 데모 캐시 재생 — 현재 Bedrock/Docker 호출 없음")
    for stage, message in events:
        sleep(delay_s)
        log(stage, "(사전 실행 결과) " + message)
    result.execution_source = "demo_cache"
    result.build_context = None
    result.gate_report.execution_source = "demo_cache"
    result.gate_report.historical_status = result.gate_report.status
    result.gate_report.status = "skipped"
    result.gate_report.pr_eligible = False
    result.gate_report.reason = "(사전 실행 결과) 현재 컨테이너 검증은 실행하지 않았습니다."
    result.cost.execution_source = "demo_cache"
    result.cost.historical = True
    result.cost.external_calls = 0
    result.output_files = {name: str(output / name) for name in NAMES}
    result.timings_s = {"total": time.monotonic() - started}
    payloads["gate-report.json"] = result.gate_report.model_dump_json(indent=2) + "\n"
    payloads["cost.json"] = result.cost.model_dump_json(indent=2) + "\n"
    output.mkdir(parents=True, exist_ok=True)
    for name, text in payloads.items():
        _write_output(output / name, text)
    write_json(
        output / "cache-provenance.json",
        {
            "execution_source": "demo_cache",
            "sample": sample,
            "code_hash": manifest["code_hash"],
            "engine_hash": manifest["engine_hash"],
            "historical_gate_status": "passed",
            "external_calls": 0,
            "historical_timings_s": manifest["result"]["timings_s"],
        },
    )
    return result
