import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from ai.detectors import RepoView, detect
from ai.llm import BedrockClient, FakeLLMClient, LLMResult
from ai.llm.base import ValidatingClient
from ai.llm.trace import TRACE_NAMES
from ai.pipeline import OUTPUT_NAMES, run_analysis

SAMPLE = Path(__file__).resolve().parents[2] / "samples/todo"
ENV = {
    "BEDROCK_REGION": "dummy-region",
    "BEDROCK_MODEL_ID_STRONG": "dummy-strong",
    "BEDROCK_MODEL_ID_FAST": "dummy-fast",
}


def test_trace_includes_every_schema_attempt_masked_prompts_and_rule_comparison(tmp_path):
    violation = detect(RepoView(SAMPLE))[0]
    response = {
        "explanations": [
            {
                "id": violation.id,
                "factor": violation.factor,
                "description": "AI 테스트 설명",
                "impact": "AI 테스트 영향",
            }
        ],
        "candidates": [
            {
                "factor": 3,
                "file": "app/main.py",
                "line": 1,
                "evidence": "검토용 근거",
                "description": "검토용 후보",
            }
        ],
    }
    raw = json.dumps(response, ensure_ascii=False)
    fake = FakeLLMClient(
        [
            LLMResult(text="invalid JSON", input_tokens=5, output_tokens=2, model_id="dummy-fast"),
            LLMResult(text=raw, input_tokens=7, output_tokens=3, model_id="dummy-fast"),
        ]
    )
    result = run_analysis(
        SAMPLE, out_dir=tmp_path / "out", llm=fake, save_llm_trace=True, log=lambda *_: None
    )
    trace = json.loads(Path(result.output_files["llm-trace.json"]).read_text())
    comparison = json.loads(Path(result.output_files["llm-comparison.json"]).read_text())
    assert set(result.output_files) == set(OUTPUT_NAMES) | set(TRACE_NAMES)
    assert trace["summary"]["schema_requests"] == 2
    assert trace["summary"]["transport_attempts"] == 2
    assert trace["summary"]["cost"]["total"]["input_tokens"] == 12
    assert trace["summary"]["cost"]["total"]["cost_usd"] is None
    assert trace["summary"]["strong_requests"] == 0
    first, second = trace["exchanges"]
    assert first["status"] == "invalid_schema" and first["response_text"] == "invalid JSON"
    assert second["status"] == "parsed" and second["response_text"] == raw
    assert second["parsed"] == response
    assert "검증 오류" in second["request_user"]
    for exchange, request in zip(trace["exchanges"], fake.calls, strict=True):
        assert exchange["request_system"] == request.system
        assert exchange["request_user"] == request.user
        assert "JSON Schema" in exchange["request_system"]
        assert "dummy-secret-do-not-use" not in exchange["request_user"]
        assert "VIOLATIONS.json" not in exchange["request_user"]
    assert comparison["rule_ids_preserved"] and comparison["signals_preserved"]
    assert comparison["factor_reviews_preserved"] and not comparison["rule_field_changes"]
    assert len(comparison["explanation_changes"]) == 1
    assert len(comparison["llm_candidates"]) == 1
    assert "AI 테스트 설명" in Path(result.output_files["llm-trace.md"]).read_text()
    assert fake.trace_observer is None


def test_trace_stores_failed_call_with_transport_count_and_no_sdk_error_text(tmp_path):
    client = Mock()
    client.converse.side_effect = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "dummy-secret-do-not-use"}},
        "Converse",
    )
    llm = BedrockClient(client=client, environ=ENV, sleep=lambda _: None)
    logs = []
    result = run_analysis(
        SAMPLE,
        out_dir=tmp_path / "out",
        llm=llm,
        save_llm_trace=True,
        log=lambda stage, message: logs.append((stage.value, message)),
    )
    saved = Path(result.output_files["llm-trace.json"]).read_text()
    trace = json.loads(saved)
    assert "dummy-secret-do-not-use" not in saved
    assert "Message" not in saved
    assert trace["summary"]["transport_attempts"] == 3
    assert trace["summary"]["responses_received"] == 0
    assert trace["exchanges"][0]["status"] == "request_failed"
    assert trace["exchanges"][0]["error_type"] == "BedrockCallError"
    assert trace["exchanges"][0]["error_code"] == "ThrottlingException"
    assert trace["exchanges"][0]["response_text"] is None
    assert result.diagnosis.enrichment_status == "failed"
    assert result.status == "partial"
    assert result.cost.total.cost_usd is None
    assert result.cost.total.unobserved_requests == 1 and not result.cost.total.usage_complete
    assert any(stage == "실패" and "LLM 보강 실패" in message for stage, message in logs)
    assert "ThrottlingException" in Path(result.output_files["llm-trace.md"]).read_text()
    assert llm.trace_observer is None


def test_trace_counts_service_retry_and_json_retry_separately(tmp_path):
    sdk = Mock()
    usage = {"inputTokens": 9, "outputTokens": 2}
    sdk.converse.side_effect = [
        ClientError({"Error": {"Code": "ThrottlingException"}}, "Converse"),
        {"output": {"message": {"content": [{"text": "broken"}]}}, "usage": usage},
        {
            "output": {"message": {"content": [{"text": '{"explanations":[],"candidates":[]}'}]}},
            "usage": usage,
        },
    ]
    llm = BedrockClient(client=sdk, environ=ENV, sleep=lambda _: None)
    result = run_analysis(
        SAMPLE, out_dir=tmp_path / "out", llm=llm, save_llm_trace=True, log=lambda *_: None
    )
    trace = json.loads(Path(result.output_files["llm-trace.json"]).read_text())
    assert sdk.converse.call_count == 3
    assert trace["summary"]["schema_requests"] == 2
    assert trace["summary"]["transport_attempts"] == 3
    assert trace["summary"]["responses_received"] == 2
    assert result.cost.total.input_tokens == 18
    assert result.cost.total.usage_complete


def test_trace_masks_recognized_values_in_raw_and_parsed_responses(tmp_path):
    (tmp_path / "repo").mkdir()
    value = "dummy-secret-do-not-use\n가짜"
    source = 'from fastapi import FastAPI\napp=FastAPI()\nSECRET_KEY="""' + value + '"""\n'
    (tmp_path / "repo/main.py").write_text(source)
    target = detect(RepoView(tmp_path / "repo"))[0]
    raw = json.dumps(
        {
            "explanations": [
                {"id": target.id, "factor": target.factor, "description": value, "impact": value}
            ],
            "candidates": [],
        },
        ensure_ascii=True,
    )
    fake = FakeLLMClient([raw])
    result = run_analysis(
        tmp_path / "repo",
        out_dir=tmp_path / "out",
        llm=fake,
        save_llm_trace=True,
        log=lambda *_: None,
    )
    for name in TRACE_NAMES:
        text = Path(result.output_files[name]).read_text()
        assert value not in text and json.dumps(value)[1:-1] not in text
    trace = json.loads(Path(result.output_files["llm-trace.json"]).read_text())
    assert trace["exchanges"][0]["redacted_for_storage"]
    assert trace["exchanges"][0]["parsed"]["explanations"][0]["description"] == "[REDACTED]"


def test_trace_is_opt_in_and_cli_flag_writes_readable_report(tmp_path):
    run_analysis(SAMPLE, out_dir=tmp_path / "plain", log=lambda *_: None)
    assert not any((tmp_path / "plain" / name).exists() for name in TRACE_NAMES)
    command = [
        sys.executable,
        "-m",
        "ai",
        "analyze",
        str(SAMPLE),
        "--llm",
        "fake",
        "--save-llm-trace",
        "--out",
        str(tmp_path / "recorded"),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    trace = json.loads((tmp_path / "recorded/llm-trace.json").read_text())
    assert trace["summary"]["client_kind"] == "FakeLLMClient"
    assert trace["summary"]["schema_requests"] == 2


def test_trace_output_symlink_rejected_before_call(tmp_path):
    output = tmp_path / "out"
    output.mkdir()
    outside = tmp_path / "original"
    outside.write_text("must not overwrite")
    (output / "llm-trace.md").symlink_to(outside)
    fake = FakeLLMClient([])
    with pytest.raises(ValueError, match="원본 보호"):
        run_analysis(SAMPLE, out_dir=output, llm=fake, save_llm_trace=True)
    assert not fake.calls
    assert outside.read_text() == "must not overwrite"


def test_observer_is_restored_on_unexpected_exception():
    class BrokenClient(ValidatingClient):
        def _invoke(self, *args, **kwargs):
            raise OSError("dummy-error-do-not-store")

    llm = BrokenClient()
    previous = Mock()
    llm.trace_observer = previous
    with pytest.raises(OSError), llm.observing(lambda _: None):
        llm.complete("", "", tier="fast", stage="test")
    assert llm.trace_observer is previous


def test_cli_bedrock_failure_returns_nonzero_and_preserves_diagnostic_files(
    tmp_path, monkeypatch, capsys
):
    from ai.cli import main

    sdk = Mock()
    sdk.converse.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "dummy-secret-do-not-use"}},
        "Converse",
    )
    monkeypatch.setattr("ai.cli.BedrockClient", lambda: BedrockClient(client=sdk, environ=ENV))
    output = tmp_path / "out"
    code = main(
        ["analyze", str(SAMPLE), "--llm", "bedrock", "--save-llm-trace", "--out", str(output)]
    )
    assert code == 1
    assert "[실패] LLM 보강 실패" in capsys.readouterr().out
    assert sdk.converse.call_count == 1
    assert json.loads((output / "diagnosis.json").read_text())["enrichment_status"] == "failed"
    assert json.loads((output / "cost.json").read_text())["total"]["cost_usd"] is None
    assert (output / "changes.diff").read_text()
