import json
from pathlib import Path

import pytest
from pydantic import Field, ValidationError

from ai.detectors import RepoView
from ai.gate.retry import FailureAnalysis, repair_context, run_with_retry
from ai.gate.runner import DockerCliRunner, FakeRunner
from ai.llm.fake import FakeLLMClient, recommendation_response
from ai.models import Signal
from ai.pipeline import OUTPUT_NAMES, run_analysis
from ai.security import SourceMasker
from ai.spec.cost_table import RATES, CostAssumptions, estimate_monthly
from ai.spec.models import Workload
from ai.spec.recommend import recommend, select_set
from ai.spec.tfvars_schema import PENDING, ContainerVars, ServerlessVars, make_tfvars
from ai.transform.workspace import Workspace, make_diff

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def sample(tmp_path):
    result = run_analysis(ROOT / "samples/todo", out_dir=tmp_path / "base", log=lambda *_: None)
    yield result
    result.build_context.cleanup()


@pytest.mark.parametrize(
    "env,signal,seconds,expected,rule",
    [
        ("aws", None, 10, "aws-serverless", "short_request"),
        ("aws", None, 25, "aws-serverless", "short_request"),
        ("aws", None, 26, "aws-always-on", "request_over_threshold"),
        ("aws", "scheduler", 10, "aws-always-on", "scheduler"),
        ("aws", "websocket", 10, "aws-always-on", "websocket"),
        ("aws", "long_request", 30, "aws-always-on", "request_over_threshold"),
        ("onprem", None, 10, "onprem", "target_onprem"),
        ("onprem", "scheduler", 100, "onprem", "target_onprem"),
    ],
)
def test_selection_rules_and_boundary(sample, env, signal, seconds, expected, rule):
    diagnosis = sample.diagnosis.model_copy(deep=True)
    diagnosis.signals = (
        [Signal(name=signal, file="app/main.py", line=1, evidence="dummy evidence")]
        if signal
        else []
    )
    spec = sample.deploy_spec.model_copy(deep=True)
    spec.workload = Workload(
        type="always-on" if signal in {"scheduler", "websocket"} else "request-driven",
        scale_to_zero=signal not in {"scheduler", "websocket"},
        max_request_seconds=seconds,
        websocket=signal == "websocket",
    )
    assert select_set(env, spec, diagnosis) == (expected, rule)


def test_contradictory_rationale_retries_then_uses_rule_fallback(sample):
    fake = FakeLLMClient(
        {
            "recommend": [
                json.dumps({"selected_set": "aws-serverless", "text": "aws-always-on을 선택한다."})
            ]
            * 3
        }
    )
    result = recommend(
        "aws",
        sample.deploy_spec,
        sample.diagnosis,
        sample.transformation,
        fake,
        SourceMasker(RepoView(ROOT / "samples/todo")),
    )
    assert len(fake.calls) == 3
    assert result.set == "aws-serverless" and result.rule_fired == "short_request"
    assert result.rationale_source == "rule"
    assert "recommend_llm_fallback" in {w.code for w in result.warnings}
    assert "검증 오류" in fake.calls[1].user


def test_models_are_separate_strict_and_all_fields_have_pending_label(sample):
    for model in (ServerlessVars, ContainerVars):
        assert all(PENDING in field.description for field in model.model_fields.values())
    serverless, _ = make_tfvars("aws-serverless", sample.deploy_spec)
    container, _ = make_tfvars("aws-always-on", sample.deploy_spec)
    assert "timeout_s" in serverless.model_dump(by_alias=True)
    assert "instances" not in serverless.model_dump(by_alias=True)
    assert "instances" in container.model_dump(by_alias=True)
    assert "timeout_s" not in container.model_dump(by_alias=True)
    for value in (0, 127, 3009, True, "256"):
        with pytest.raises(ValidationError):
            ServerlessVars(memory_limit_mb=value)


@pytest.mark.parametrize(
    "selected,overrides",
    [
        ("aws-serverless", {"memory_mb": 9999}),
        ("aws-serverless", {"timeout_s": 0}),
        ("aws-serverless", {"instances": 1}),
        ("aws-always-on", {"timeout_s": 30}),
        ("aws-always-on", {"instances": 2}),
        ("onprem", {"port": 9000}),
        ("aws-serverless", {"image_tag": "unexpected:tag"}),
    ],
)
def test_bad_tfvars_fall_back_without_clamping(sample, selected, overrides):
    actual, replaced = make_tfvars(selected, sample.deploy_spec, overrides=overrides)
    expected, _ = make_tfvars(selected, sample.deploy_spec)
    assert replaced and actual == expected


def test_changing_only_schema_alias_changes_export(sample, monkeypatch):
    import ai.spec.tfvars_schema as schema

    class Renamed(ServerlessVars):
        memory_limit_mb: int = Field(
            default=256, alias="renamed_memory", ge=128, le=3008, description=PENDING
        )

    monkeypatch.setattr(schema, "ServerlessVars", Renamed)
    result, replaced = make_tfvars(
        "aws-serverless", sample.deploy_spec, overrides={"renamed_memory": 512}
    )
    assert not replaced and result.memory_limit_mb == 512
    assert result.model_dump(by_alias=True)["renamed_memory"] == 512
    assert "memory_mb" not in result.model_dump(by_alias=True)


def test_estimate_arithmetic_and_every_rate_is_unconfirmed():
    assert all(rate.label == "단가 미확인" for rates in RATES.values() for rate in rates.values())
    cost, assumptions = estimate_monthly("aws-serverless", memory_mb=256)
    assert cost == pytest.approx(25.02)
    assert any("리전" in s for s in assumptions)
    assert any("월 요청 수" in s for s in assumptions)
    assert any("상시 가동" in s for s in assumptions)
    assert any("프리티어" in s for s in assumptions)
    assert any("실제 AWS 요금" in s for s in assumptions)
    with pytest.raises(ValidationError):
        CostAssumptions(free_tier_excluded=False)


class FailingBuilds(FakeRunner):
    def __init__(self, count):
        super().__init__()
        self.failure_count = count
        self.transformed_builds = 0

    def build(self, root, tag):
        if "DATABASE_URL" in (root / "app/db.py").read_text():
            self.transformed_builds += 1
            self.fail_at = "build" if self.transformed_builds <= self.failure_count else None
        return super().build(root, tag)


def repair_responses(context):
    name = "app/main.py"
    initial = (Path(context.root) / name).read_text()
    first = initial + "\n# protocol retry one\n"
    second = first + "\n# protocol retry two\n"
    return [
        json.dumps(
            {"summary": "Fake 프로토콜 검사용 수정", "diff": make_diff({name: a}, {name: b})}
        )
        for a, b in ((initial, first), (first, second))
    ]


@pytest.mark.parametrize("failures,success", [(2, True), (3, False)])
def test_runtime_attempt_cap_and_cleanup(sample, failures, success):
    runner = FailingBuilds(failures)
    fake = FakeLLMClient({"repair": repair_responses(sample.build_context)})
    report, context = run_with_retry(
        sample.build_context, sample.deploy_spec, runner, lambda *_: None, fake, timeout_s=2
    )
    try:
        assert len(report.attempts) == 3 and runner.transformed_builds == 3
        assert len(fake.calls) == 2
        assert report.transformed.status == ("passed" if success else "failed")
        assert report.status == ("skipped" if success else "failed")
        assert report.retry_stop_reason == (None if success else "attempt_limit")
        assert not runner.networks and not runner.containers and not runner.images
        assert not report.pr_eligible
    finally:
        if context is not sample.build_context:
            context.cleanup()


def test_repeated_proposal_stops_early(sample):
    response = repair_responses(sample.build_context)[0]
    fake = FakeLLMClient({"repair": [response, response]})
    runner = FailingBuilds(3)
    report, context = run_with_retry(
        sample.build_context, sample.deploy_spec, runner, lambda *_: None, fake, timeout_s=2
    )
    assert report.status == "failed" and report.retry_stop_reason == "repeated_patch"
    assert len(report.attempts) == 2
    context.cleanup()


def test_infrastructure_failure_does_not_call_repair_llm(sample):
    fake = FakeLLMClient([])
    report, _ = run_with_retry(
        sample.build_context, sample.deploy_spec, FakeRunner("preflight"), lambda *_: None, fake
    )
    assert report.retry_stop_reason == "non_code_failure" and not fake.calls


def test_repair_rejects_security_bypass_api_changes_and_traversal(sample):
    context = sample.build_context
    before = (Path(context.root) / "app/main.py").read_text()
    changes = [
        FailureAnalysis(
            summary="dummy",
            dockerfile=(Path(context.root) / "Dockerfile")
            .read_text()
            .replace("USER 10001:10001", "USER root"),
        ),
        FailureAnalysis(
            summary="dummy", diff=make_diff({"../outside.py": "a\n"}, {"../outside.py": "b\n"})
        ),
        FailureAnalysis(
            summary="dummy",
            diff=make_diff(
                {"app/main.py": before},
                {
                    "app/main.py": before.replace(
                        'title="Bronze Todo Sample"', 'title="changed"'
                    ).replace('return {"status": "ok"}', 'return {"status": "changed"}')
                },
            ),
        ),
    ]
    for change in changes:
        with pytest.raises(ValueError):
            repair_context(context, change)
    assert context.verify_sample()


def test_failure_logs_are_masked_before_repair_call(sample):
    class LeakingBuild(FailingBuilds):
        def build(self, root, tag):
            result = super().build(root, tag)
            result.output = "postgresql://gate:dummy-password-do-not-use@db/gate"
            return result

    fake = FakeLLMClient({"repair": repair_responses(sample.build_context)})
    report, context = run_with_retry(
        sample.build_context,
        sample.deploy_spec,
        LeakingBuild(1),
        lambda *_: None,
        fake,
        timeout_s=2,
    )
    assert "dummy-password-do-not-use" not in fake.calls[0].user
    assert "[REDACTED]" in fake.calls[0].user
    assert "dummy-password-do-not-use" not in json.dumps(report.model_dump(mode="json"))
    context.cleanup()


@pytest.mark.parametrize(
    "name,expected", [("todo", "aws-serverless"), ("todo-scheduler", "aws-always-on")]
)
def test_fake_complete_pipeline_and_pending_contract(tmp_path, name, expected):
    fake = FakeLLMClient({"diagnose": ["{}"], "recommend": [recommendation_response]})
    result = run_analysis(
        ROOT / "samples" / name,
        out_dir=tmp_path / "out",
        llm=fake,
        decision_llm=fake,
        runner=FakeRunner(),
        save_llm_trace=True,
        log=lambda *_: None,
    )
    try:
        assert result.recommendation.set == expected
        assert result.recommendation.needs_confirmation == ["tfvars_schema", "cost_table"]
        assert result.recommendation.needs_approval
        assert result.recommendation.rationale_source == "llm"
        assert all((tmp_path / "out" / file).exists() for file in OUTPUT_NAMES)
        assert result.cost.total.calls == 2
        assert set(result.cost.stages) == {"diagnose", "recommend"}
        assert {"analysis", "transform", "gate", "total"} <= set(result.timings_s)
        assert (
            result.gate_report.status == "skipped"
            and result.gate_report.transformed.status == "passed"
        )
        assert "data_migration_unsupported" in {w.code for w in result.recommendation.warnings}
    finally:
        result.build_context.cleanup()


def test_pipeline_repair_final_diff_and_trace_match_updated_context(tmp_path, sample):
    fake = FakeLLMClient({"repair": repair_responses(sample.build_context)})
    result = run_analysis(
        ROOT / "samples/todo",
        out_dir=tmp_path / "out",
        repair_llm=fake,
        runner=FailingBuilds(2),
        save_llm_trace=True,
        log=lambda *_: None,
    )
    try:
        diff = Path(result.output_files["changes.diff"]).read_text()
        assert "protocol retry two" in diff
        with Workspace(
            {
                name: RepoView(ROOT / "samples/todo").read(name)
                for name in RepoView(ROOT / "samples/todo").files()
            }
        ) as workspace:
            workspace.apply(diff)
            assert workspace.compile()
            assert "psycopg2-binary" in (workspace.root / "requirements.txt").read_text()
        assert result.cost.total.calls == 2 and result.cost.stages["repair"].calls == 2
        trace = json.loads(Path(result.output_files["llm-trace.json"]).read_text())
        assert len(trace["exchanges"]) == 2
        assert all(e["stage"] == "repair" for e in trace["exchanges"])
        assert "protocol retry two" in (Path(result.build_context.root) / "app/main.py").read_text()
    finally:
        result.build_context.cleanup()


@pytest.mark.docker
def test_live_missing_import_is_repaired_without_touching_original(sample):
    root = Path(sample.build_context.root)
    good = (root / "app/db.py").read_text()
    broken = good.replace("import os\n", "")
    (root / "app/db.py").write_text(broken)
    sample.build_context._sealed_digest = sample.build_context.tree_digest()
    fake = FakeLLMClient(
        {
            "repair": [
                json.dumps(
                    {
                        "summary": "NameError 원인인 누락된 os import를 복구합니다.",
                        "diff": make_diff({"app/db.py": broken}, {"app/db.py": good}),
                    }
                )
            ]
        }
    )
    runner = DockerCliRunner()
    report, context = run_with_retry(
        sample.build_context, sample.deploy_spec, runner, lambda *_: None, fake, timeout_s=8
    )
    try:
        assert report.status == "passed", report.model_dump(mode="json")
        assert len(report.attempts) == 2 and len(fake.calls) == 1
        assert not runner.containers and not runner.networks and not runner.images
    finally:
        context.cleanup()
