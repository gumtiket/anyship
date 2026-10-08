from __future__ import annotations

import json
import re
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Literal

import yaml

from ai.detectors import RepoView, detect, detect_framework, detect_signals
from ai.diagnose import enrich
from ai.gate.retry import run_with_retry
from ai.llm.base import ValidatingClient
from ai.llm.cost import CostTracker
from ai.llm.trace import TRACE_NAMES, TraceRecorder
from ai.llm.tracked import TrackedLLM
from ai.models import AnalysisResult, Diagnosis, GateReport, Recommendation, WarningItem
from ai.security import SourceMasker
from ai.spec.cost_table import CostAssumptions
from ai.spec.recommend import recommend
from ai.spec.service import generate_spec
from ai.spec.tfvars_schema import CommonVars
from ai.stages import LogFn, Stage, default_log
from ai.transform import propose
from ai.transform.context import prepare_context
from ai.transform.dockerfile import DOCKERIGNORE, generate_dockerfile
from ai.transform.workspace import Workspace, make_diff, source_files

if TYPE_CHECKING:
    from ai.gate.runner import ContainerRunner
    from ai.llm.base import LLMClient

OUTPUT_NAMES = (
    "diagnosis.json",
    "changes.diff",
    "Dockerfile",
    "deploy-spec.yaml",
    "recommendation.json",
    "gate-report.json",
    "cost.json",
)


def _write_output(path: Path, text: str) -> None:
    # Replacing the directory entry also preserves a source file hard-linked to old output.
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write(text)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def run_analysis(
    repo_path: str | Path,
    *,
    target_env: Literal["aws", "onprem"] = "aws",
    commit: str | None = None,
    out_dir: str | Path = "out",
    log: LogFn = default_log,
    llm: LLMClient | None = None,
    runner: ContainerRunner | None = None,
    artifact_llm: LLMClient | None = None,
    source_repo: str | None = None,
    profile: Literal["dev", "prod"] = "dev",
    save_llm_trace: bool = False,
    decision_llm: LLMClient | None = None,
    repair_llm: LLMClient | None = None,
    image_reference: str | None = None,
    tfvars_overrides: dict | None = None,
    cost_assumptions: CostAssumptions | None = None,
    no_gate: bool = False,
    compare_original: bool = True,
) -> AnalysisResult:
    """P5: diagnosis/proposals/packaging/recommendation and sample-only bounded repair.

    artifact_llm is separate so existing Bedrock analysis does not add paid packaging calls.
    Sample BuildContext contains proposed changes only; caller owns cleanup after gate use.
    """
    started = time.monotonic()
    timings = {}

    @contextmanager
    def measured(name: str, stage: Stage = Stage.ANALYZING):
        phase_started = time.monotonic()
        log(stage, f"{name} 시작")
        try:
            yield
        finally:
            timings[name] = time.monotonic() - phase_started
            log(stage, f"{name} 완료: {timings[name]:.3f}초")

    try:
        CommonVars(image_reference=image_reference)
    except ValueError:
        raise ValueError("이미지 식별자 형식 오류. 원문은 출력하지 않습니다.") from None
    repo = Path(repo_path).resolve()
    output = Path(out_dir).resolve()
    if not repo.is_dir():
        raise ValueError("입력 레포 경로는 존재하는 디렉터리여야 합니다.")
    if target_env not in {"aws", "onprem"}:
        raise ValueError("target_env는 aws 또는 onprem이어야 합니다.")
    if output.is_relative_to(repo) or repo.is_relative_to(output):
        raise ValueError("원본 보호: 출력은 입력 레포와 분리된 디렉터리에 지정하세요.")
    if profile not in {"dev", "prod"}:
        raise ValueError("profile는 dev 또는 prod여야 합니다.")
    if commit is not None and not re.fullmatch(r"[0-9a-fA-F]{7,40}", commit):
        raise ValueError("commit은 7~40자리 Git SHA여야 합니다.")
    if source_repo is not None and re.search(r"://[^/]*@", source_repo):
        raise ValueError("source_repo에는 자격 증명을 넣을 수 없습니다.")
    # Reject symlinked files before writing any output into a user repository.
    output_names = (*OUTPUT_NAMES, *TRACE_NAMES) if save_llm_trace else OUTPUT_NAMES
    if any((output / name).is_symlink() for name in (*output_names, ".dockerignore")):
        raise ValueError("원본 보호: 출력 파일 심볼릭 링크는 허용하지 않습니다.")
    if save_llm_trace and any(
        client is not None and not isinstance(client, ValidatingClient)
        for client in (llm, artifact_llm, decision_llm, repair_llm)
    ):
        raise ValueError(
            "요청별 기록은 ValidatingClient 기반 Bedrock/Fake 클라이언트만 지원합니다."
        )

    log(
        Stage.ANALYZING,
        "P5: 규칙 진단·변경안·패키징·추천 시작 — 원본 코드·DB는 수정하지 않습니다.",
    )
    view = RepoView(repo)
    framework = detect_framework(view)
    violations = detect(view) if framework.support_grade != "unsupported" else []
    signals = detect_signals(view) if framework.support_grade != "unsupported" else []
    warnings = list(view.warnings)
    if framework.support_grade != "supported":
        warnings.append(WarningItem(code="framework_not_supported", message=framework.reason))
    diagnosis = Diagnosis(
        status="completed",
        support_grade=framework.support_grade,
        framework=framework,
        violations=violations,
        signals=signals,
        warnings=warnings,
    )
    timings["scan"] = time.monotonic() - started
    tracked_clients = []

    def tracking(client):
        if client is None or framework.support_grade == "unsupported":
            return None
        for original_client, wrapper in tracked_clients:
            if original_client is client:
                return wrapper
        wrapper = TrackedLLM(client)
        tracked_clients.append((client, wrapper))
        return wrapper

    tracked = tracking(llm)
    artifact_tracked = tracking(artifact_llm)
    decision_tracked = tracking(decision_llm)
    repair_tracked = tracking(repair_llm)
    masker = SourceMasker(view)
    baseline = enrich(diagnosis, view, None, masker)
    recorder = (
        TraceRecorder(
            masker,
            "+".join(
                sorted(
                    {
                        type(client).__name__
                        for client in (llm, artifact_llm, decision_llm, repair_llm)
                        if client is not None
                    }
                )
            )
            or "none",
        )
        if save_llm_trace
        else None
    )
    dockerfile = "# unsupported: 배포용 산출물이 아닙니다.\n"
    spec = None
    build_context = None
    packaging_warnings = []
    with ExitStack() as stack:
        clients = []
        for client in (llm, artifact_llm, decision_llm, repair_llm):
            if (
                recorder is not None
                and client is not None
                and all(client is not item for item in clients)
            ):
                stack.enter_context(client.observing(recorder.record))
                clients.append(client)
        with measured("diagnosis"):
            diagnosis = enrich(baseline, view, tracked, masker)
        timings["analysis"] = timings["scan"] + timings["diagnosis"]
        with measured("transform"):
            diff, transformation = propose(view, diagnosis, tracked)
        with measured("packaging"):
            if framework.support_grade == "supported" and transformation.status != "failed":
                dockerfile, docker_fallback = generate_dockerfile(
                    framework.entrypoint, artifact_tracked
                )
                spec, spec_fallback = generate_spec(
                    repo.name,
                    source_repo or str(repo_path),
                    commit,
                    profile,
                    diagnosis,
                    transformation,
                    artifact_tracked,
                )
                for code, fallback in (
                    ("dockerfile_llm_fallback", docker_fallback),
                    ("spec_llm_fallback", spec_fallback),
                ):
                    if fallback:
                        packaging_warnings.append(
                            WarningItem(
                                code=code,
                                message=(
                                    "LLM 제안 검증 실패로 고정 템플릿/규칙 기본값을 사용했습니다."
                                ),
                            )
                        )
                if transformation.sample_name and not masker.blocked_files:
                    build_context = prepare_context(view, diff, dockerfile)
                else:
                    packaging_warnings.append(
                        WarningItem(
                            code="build_context_skipped",
                            message=(
                                "샘플 밖의 DB 변경안은 적용하지 않습니다. "
                                "임시 빌드 트리와 컨테이너 검증을 생략합니다."
                            ),
                        )
                    )
        with measured("recommendation"):
            recommendation = (
                recommend(
                    target_env,
                    spec,
                    diagnosis,
                    transformation,
                    decision_tracked
                    if diagnosis.enrichment_status != "failed" or decision_llm is not llm
                    else None,
                    masker,
                    image_reference=image_reference,
                    tfvars_overrides=tfvars_overrides,
                    cost_assumptions=cost_assumptions,
                )
                if spec is not None
                else Recommendation(
                    status="unsupported",
                    needs_approval=transformation.needs_approval,
                    warnings=list(transformation.warnings),
                )
            )
        gate = GateReport(status="skipped", reason="P5: 게이트 생략 또는 자체 샘플이 아닙니다.")
        with measured("gate", Stage.VALIDATING if runner is not None else Stage.ANALYZING):
            if (
                runner is not None
                and not no_gate
                and build_context is not None
                and spec is not None
            ):
                original_context = (
                    prepare_context(view, "", dockerfile) if compare_original else None
                )
                try:
                    gate, updated = run_with_retry(
                        build_context,
                        spec,
                        runner,
                        log,
                        repair_tracked,
                        original_context=original_context,
                    )
                    if updated is not build_context:
                        build_context.cleanup()
                        build_context = updated
                        dockerfile = (Path(updated.root) / "Dockerfile").read_text()
                        candidate = source_files(RepoView(updated.root))
                        original = source_files(view)
                        final_sources = dict(original)
                        for name, content in candidate.items():
                            # Retain the initial dependency edits as well as repaired Python.
                            if name.endswith(".py") or name in transformation.changed_files:
                                final_sources[name] = content
                        diff = make_diff(original, final_sources)
                        with Workspace(original) as workspace:
                            workspace.apply(diff)
                            if not workspace.compile():
                                gate.status = "failed"
                                gate.retry_stop_reason = "final_compile_failed"
                        transformation.changed_files = sorted(
                            name
                            for name in final_sources
                            if final_sources[name] != original.get(name)
                        )
                finally:
                    if original_context is not None:
                        original_context.cleanup()
    costs = CostTracker()
    trackers = [wrapper for _, wrapper in tracked_clients]
    unique_trackers = []
    for item in trackers:
        if any(
            item is seen or (item.source is not None and item.source is seen.source)
            for seen in unique_trackers
        ):
            continue
        unique_trackers.append(item)
        report = item.report()
        costs.calls.extend(report.calls)
        for stage, summary in report.stages.items():
            costs.unobserved_stages.extend([stage] * summary.unobserved_requests)
    diagnosis.transformation = transformation
    diagnosis.warnings.extend(transformation.warnings)
    diagnosis.warnings.extend(packaging_warnings)
    recommendation.warnings.extend(packaging_warnings)
    output.mkdir(parents=True, exist_ok=True)
    result = AnalysisResult(
        status="failed"
        if transformation.status == "failed" or gate.status == "failed"
        else "partial"
        if diagnosis.enrichment_status == "failed"
        else "diagnosed"
        if framework.support_grade == "supported"
        else framework.support_grade,
        diagnosis=diagnosis,
        recommendation=recommendation,
        gate_report=gate,
        cost=costs.report(),
        deploy_spec=spec,
        build_context=build_context,
        packaging_warnings=packaging_warnings,
        timings_s=timings,
        output_files={name: str(output / name) for name in output_names},
        transformation=transformation,
    )
    data = {
        "diagnosis.json": result.diagnosis,
        "recommendation.json": result.recommendation,
        "gate-report.json": result.gate_report,
        "cost.json": result.cost,
    }
    for name, model in data.items():
        _write_output(
            output / name,
            json.dumps(model.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )
    _write_output(output / "changes.diff", diff)
    _write_output(output / "Dockerfile", dockerfile)
    _write_output(
        output / "deploy-spec.yaml",
        yaml.safe_dump(
            spec.model_dump(mode="json", exclude_none=True), allow_unicode=True, sort_keys=False
        )
        if spec
        else "# unsupported: 명세 생성 생략\n",
    )
    if spec is not None:
        _write_output(output / ".dockerignore", DOCKERIGNORE)
        log(
            Stage.ANALYZING,
            f"Dockerfile lint·배포 명세 스키마 검증 완료. 게이트 결과: {gate.status}.",
        )
    if recorder is not None:
        for name, text in recorder.artifacts(baseline, result).items():
            _write_output(output / name, text)
        log(
            Stage.ANALYZING,
            f"LLM 요청별 기록·규칙 비교 저장: {len(recorder.exchanges)}개 요청. "
            "실제 사용 모델은 llm-trace.json에서 확인하세요.",
        )
    log(
        Stage.ANALYZING,
        f"규칙 진단 완료: {framework.support_grade}, "
        f"위반 {len(diagnosis.violations)}개, 신호 {len(signals)}개, "
        f"변경 파일 {len(transformation.changed_files)}개. 출력 7종 기록.",
    )
    if transformation.status == "failed":
        log(Stage.FAILED, "변경안 검증 실패. 빈 diff와 원인 경고를 결과에 기록했습니다.")
    if diagnosis.enrichment_status == "failed":
        log(
            Stage.FAILED,
            "LLM 보강 실패. 규칙·템플릿 결과만 유지했습니다. "
            "실제 AI 검증 성공이 아닙니다. 원인은 llm-trace.json에서 확인하세요."
            if save_llm_trace
            else "LLM 보강 실패. 규칙·템플릿 결과만 유지했습니다. 실제 AI 검증 성공이 아닙니다.",
        )
    timings["total"] = time.monotonic() - started
    result.timings_s = timings
    log(Stage.ANALYZING, f"전체 완료: {timings['total']:.3f}초")
    if framework.support_grade == "unsupported":
        log(Stage.FAILED, "지원하지 않는 프레임워크: 진단 사유만 기록했습니다.")
    return result
