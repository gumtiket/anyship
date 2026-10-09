import importlib.util
import json
from pathlib import Path

import pytest

from ai.models import AnalysisResult, CostReport, Diagnosis, GateReport, Recommendation

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/service_handoff.py"
SPEC = importlib.util.spec_from_file_location("service_handoff_example", SCRIPT)
EXAMPLE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXAMPLE)
ROOT = Path(__file__).resolve().parents[2]


def report(**overrides):
    fields = {
        "diagnosis": Diagnosis(status="completed", support_grade="supported"),
        "recommendation": Recommendation(needs_approval=True, needs_confirmation=["cost_table"]),
        "gate_report": GateReport(status="skipped", reason="not verified"),
        "cost": CostReport(),
        "output_files": {"changes.diff": "/private/local-context/changes.diff"},
    }
    return AnalysisResult(**(fields | overrides))


def test_current_pass_does_not_grant_pr_approval_and_private_logs_are_excluded():
    result = report(gate_report=GateReport(status="passed", reason="sample", pr_eligible=False))
    result.gate_report.transformed.logs = "private container log"
    payload = EXAMPLE.service_payload(result, "a" * 40)
    text = json.dumps(payload)
    assert payload["gate"]["status"] == "passed"
    assert payload["gate"]["pr_eligible"] is False
    assert payload["llm_mode"] == "not_provided"
    assert payload["recommendation"]["needs_approval"] is True
    assert payload["recommendation"]["needs_confirmation"] == ["cost_table"]
    assert "private container log" not in text and "/private/local-context" not in text
    assert "output_files" not in payload and "build_context" not in payload
    assert payload["integration"]["selection_mapping"] == "not_implemented"


def test_cache_preserves_current_skip_historical_pass_and_unknown_historical_cost():
    cost = CostReport(execution_source="demo_cache", historical=True, external_calls=0)
    cost.total.cost_usd = None
    payload = EXAMPLE.service_payload(
        report(
            execution_source="demo_cache",
            gate_report=GateReport(
                status="skipped", historical_status="passed", execution_source="demo_cache"
            ),
            cost=cost,
        ),
        "a" * 40,
    )
    assert payload["gate"]["status"] == "skipped"
    assert payload["gate"]["historical_status"] == "passed"
    assert payload["cost"]["historical"] is True
    assert payload["cost"]["external_calls"] == 0
    assert payload["cost"]["total"]["cost_usd"] is None


@pytest.mark.parametrize("status,grade", [("failed", "supported"), ("partial", "partial")])
def test_failure_and_partial_are_not_reported_as_completed(status, grade):
    payload = EXAMPLE.service_payload(
        report(status=status, diagnosis=Diagnosis(support_grade=grade)), "a" * 40
    )
    assert payload["analysis_status"] == status
    assert payload["diagnosis"]["support_grade"] == grade
    assert payload["gate"]["pr_eligible"] is False


def test_bad_sha_is_rejected_before_creating_client_or_output(tmp_path, monkeypatch):
    def forbidden():
        pytest.fail("client was created")

    monkeypatch.setattr(EXAMPLE, "BedrockClient", forbidden)
    with pytest.raises(ValueError, match="invalid_base_sha"):
        EXAMPLE.run_handoff(ROOT / "samples/todo", tmp_path / "out", base_sha="bad", mode="bedrock")
    assert not (tmp_path / "out").exists()


def test_fake_sample_request_cleans_context_and_keeps_proposal_and_warnings(tmp_path, monkeypatch):
    contexts = []
    original = EXAMPLE.run_analysis

    def capture(*args, **kwargs):
        result = original(*args, **kwargs)
        contexts.append(Path(result.build_context.root))
        return result

    monkeypatch.setattr(EXAMPLE, "run_analysis", capture)
    out = tmp_path / "out"
    payload = EXAMPLE.run_handoff(ROOT / "samples/todo", out, base_sha="a" * 40)
    assert payload["llm_mode"] == "fake"
    assert payload["gate"]["status"] == "skipped"
    assert payload["gate"]["pr_eligible"] is False
    assert payload["transformation"]["needs_approval"] is True
    assert "data_migration_unsupported" in {w["code"] for w in payload["diagnosis"]["warnings"]}
    assert json.loads(json.dumps(payload))["base_sha"] == "a" * 40
    assert contexts and all(not p.exists() for p in contexts)
    with pytest.raises(ValueError):
        EXAMPLE.run_handoff(ROOT / "samples/todo", out, base_sha="a" * 40)


def test_handoff_cleanup_runs_if_serialization_fails(tmp_path, monkeypatch):
    contexts = []
    original = EXAMPLE.run_analysis

    def capture(*args, **kwargs):
        result = original(*args, **kwargs)
        contexts.append(Path(result.build_context.root))
        return result

    def fail(*_, **__):
        raise RuntimeError("serialization failed")

    monkeypatch.setattr(EXAMPLE, "run_analysis", capture)
    monkeypatch.setattr(EXAMPLE, "service_payload", fail)
    with pytest.raises(RuntimeError, match="serialization failed"):
        EXAMPLE.run_handoff(ROOT / "samples/todo", tmp_path / "out", base_sha="a" * 40)
    assert contexts and all(not p.exists() for p in contexts)


def test_real_model_is_only_created_with_explicit_mode(tmp_path, monkeypatch):
    def forbidden():
        pytest.fail("unexpected Bedrock client")

    monkeypatch.setattr(EXAMPLE, "BedrockClient", forbidden)
    payload = EXAMPLE.run_handoff(
        ROOT / "samples/memo-app", tmp_path / "out", base_sha="a" * 40, mode="none"
    )
    assert payload["analysis_status"] == "unsupported"
    assert payload["gate"]["status"] == "skipped"
