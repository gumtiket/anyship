import json
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError, ReadTimeoutError
from pydantic import BaseModel, ConfigDict

from ai.llm import (
    BedrockClient,
    CostTracker,
    FakeLLMClient,
    LLMError,
    LLMResult,
    SchemaValidationError,
)
from ai.llm.bedrock import BedrockCallError, classify_denial


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool


ENV = {
    "BEDROCK_REGION": "dummy-region",
    "BEDROCK_MODEL_ID_STRONG": "dummy-strong",
    "BEDROCK_MODEL_ID_FAST": "dummy-fast",
}


def response(text, tokens=10):
    return {
        "output": {"message": {"content": [{"text": text}]}},
        "usage": {"inputTokens": tokens, "outputTokens": 5},
    }


def aws_error(code):
    return ClientError({"Error": {"Code": code, "Message": "dummy-secret-do-not-use"}}, "Converse")


def test_fake_schema_retry_and_json_serialization():
    fake = FakeLLMClient(["broken", '{"ok": true}'])
    result = fake.complete("rules", "request", tier="fast", schema=Answer, stage="diagnose")
    assert result.parsed.ok
    assert result.model_dump(mode="json")["parsed"] == {"ok": True}
    assert len(fake.calls) == 2
    assert '"type": "boolean"' in fake.calls[0].system
    assert "검증 오류" in fake.calls[1].user


def test_fake_stage_queues_and_code_fence():
    fake = FakeLLMClient({"second": ['```json\n{"ok": true}\n```'], "first": ["text"]})
    assert fake.complete("", "", tier="strong", schema=Answer, stage="second").parsed.ok
    assert fake.complete("", "", tier="fast", schema=None, stage="first").text == "text"


@pytest.mark.parametrize("transport", ["fake", "bedrock"])
def test_three_invalid_responses_raise_without_leaking_rejected_value(transport):
    text = '{"ok": "dummy-secret-do-not-use"}'
    if transport == "fake":
        llm = FakeLLMClient([text] * 3)
    else:
        client = Mock()
        client.converse.side_effect = [response(text)] * 3
        llm = BedrockClient(client=client, environ=ENV)
    with pytest.raises(SchemaValidationError) as error:
        llm.complete("", "", tier="strong", schema=Answer, stage="transform")
    assert error.value.attempts == 3
    assert len(llm.tracker.calls) == 3
    assert "dummy-secret-do-not-use" not in str(error.value)
    if transport == "fake":
        assert "dummy-secret-do-not-use" not in llm.calls[1].user
    else:
        assert client.converse.call_count == 3
        assert "dummy-secret-do-not-use" not in str(client.converse.call_args)


def test_bedrock_retry_records_all_usage_and_uses_converse_contract():
    client = Mock()
    client.converse.side_effect = [response("broken", 11), response('{"ok": true}', 12)]
    llm = BedrockClient(client=client, environ=ENV)
    result = llm.complete("rules", "request", tier="fast", schema=Answer, stage="diagnose")
    request = client.converse.call_args.kwargs
    assert request["modelId"] == "dummy-fast"
    assert request["inferenceConfig"]["temperature"] == 0
    assert request["messages"][0]["role"] == "user"
    assert result.parsed.ok
    assert llm.tracker.report().total.input_tokens == 23
    assert llm.tracker.report().total.output_tokens == 10
    assert llm.tracker.report().total.cost_usd is None


def test_transient_error_has_bounded_exponential_backoff():
    client = Mock()
    client.converse.side_effect = [
        aws_error("ThrottlingException"),
        aws_error("ServiceUnavailableException"),
        response("ok"),
    ]
    sleeps = []
    llm = BedrockClient(client=client, environ=ENV, sleep=sleeps.append)
    assert llm.complete("", "", tier="fast", schema=None, stage="check").text == "ok"
    assert sleeps == [1, 2]
    assert len(llm.tracker.calls) == 1


def test_transient_error_stops_at_limit():
    client = Mock()
    client.converse.side_effect = aws_error("ThrottlingException")
    llm = BedrockClient(client=client, environ=ENV, sleep=lambda _: None)
    with pytest.raises(BedrockCallError):
        llm.complete("", "", tier="fast", schema=None, stage="check")
    assert client.converse.call_count == 3


@pytest.mark.parametrize("code", ["AccessDeniedException", "ValidationException"])
def test_non_transient_error_is_not_retried_or_leaked(code):
    client = Mock()
    client.converse.side_effect = aws_error(code)
    with pytest.raises(BedrockCallError) as error:
        BedrockClient(client=client, environ=ENV).complete("", "", tier="fast", stage="check")
    assert client.converse.call_count == 1
    assert "dummy-secret-do-not-use" not in str(error.value)


def test_uncertain_timeout_is_not_retried():
    client = Mock()
    client.converse.side_effect = ReadTimeoutError(endpoint_url="https://dummy.invalid")
    with pytest.raises(BedrockCallError):
        BedrockClient(client=client, environ=ENV).complete("", "", tier="fast", stage="check")
    assert client.converse.call_count == 1


def test_denial_classification_keeps_only_safe_action_names_and_flags():
    message = (
        "dummy-secret-do-not-use: not authorized to aws-marketplace:Subscribe and "
        "aws-marketplace:ViewSubscriptions because subscription setup failed; "
        "user arn:aws:iam::000000000000:user/dummy-user"
    )
    details = classify_denial(message)
    assert details["marketplace"] and details["subscription"]
    assert details["reported_actions"] == [
        "aws-marketplace:Subscribe",
        "aws-marketplace:ViewSubscriptions",
    ]
    assert "dummy-secret" not in json.dumps(details) and "arn:" not in json.dumps(details)


def test_missing_configuration_fails_before_creating_sdk_client(monkeypatch):
    sdk = Mock()
    monkeypatch.setattr("ai.llm.bedrock.boto3.Session", sdk)
    with pytest.raises(ValueError, match="BEDROCK_REGION"):
        BedrockClient(environ={})
    sdk.assert_not_called()


def test_sdk_client_uses_default_credentials_chain_and_no_nested_retry(monkeypatch):
    sdk = Mock()
    sdk.return_value.client.return_value.converse.return_value = response("ok")
    monkeypatch.setattr("ai.llm.bedrock.boto3.Session", sdk)
    BedrockClient(environ=ENV).complete("", "", tier="strong", stage="check")
    sdk.assert_called_once_with(region_name="dummy-region")
    kwargs = sdk.return_value.client.call_args.kwargs
    assert set(kwargs) == {"region_name", "config"}
    assert kwargs["config"].retries["total_max_attempts"] == 1


def test_fake_invalid_response_tokens_are_not_lost():
    tracker = CostTracker()
    fake = FakeLLMClient(
        [
            LLMResult(text="broken", input_tokens=5, output_tokens=3, model_id="dummy-model"),
            LLMResult(text='{"ok": true}', input_tokens=7, output_tokens=4, model_id="dummy-model"),
        ],
        tracker=tracker,
    )
    fake.complete("", "", tier="fast", schema=Answer, stage="diagnose")
    assert json.loads(tracker.report().model_dump_json())["total"]["input_tokens"] == 12


def test_empty_bedrock_text_is_not_reported_as_success_and_usage_is_preserved():
    client = Mock()
    client.converse.return_value = response("")
    llm = BedrockClient(client=client, environ=ENV)
    with pytest.raises(LLMError, match="텍스트"):
        llm.complete("", "", tier="fast", stage="check")
    assert llm.tracker.report().total.input_tokens == 10


@pytest.mark.parametrize(
    ("model_id", "thinking"),
    [
        ("global.anthropic.claude-sonnet-5-5", "between_tools"),
        ("anthropic.claude-sonnet-5-5", "between_tools"),
        ("us.anthropic.claude-haiku-5-5", "disabled"),
        ("global.anthropic.claude-haiku-5-5", "disabled"),
        (
            "arn:aws:bedrock:dummy-region:000000000000:inference-profile/"
            "global.anthropic.claude-sonnet-5-5",
            "between_tools",
        ),
    ],
)
def test_claude55_omits_sampling_and_handles_reasoning_blocks(model_id, thinking):
    sdk = Mock()
    payload = response('{"ok":true}')
    payload["output"]["message"]["content"].insert(
        0, {"reasoningContent": {"reasoningText": {"text": "dummy-thought", "signature": "dummy"}}}
    )
    payload["stopReason"] = "end_turn"
    payload["usage"]["cacheReadInputTokens"] = 100
    sdk.converse.return_value = payload
    env = {**ENV, "BEDROCK_MODEL_ID_FAST": model_id}
    llm = BedrockClient(client=sdk, environ=env)
    exchanges = []
    with llm.observing(exchanges.append):
        result = llm.complete("", "", tier="fast", schema=Answer, stage="test")
    request = sdk.converse.call_args.kwargs
    assert request["inferenceConfig"] == {"maxTokens": 4096}
    assert request["additionalModelRequestFields"] == {
        "thinking": {"type": thinking},
        "output_config": {"effort": "low"},
    }
    assert exchanges[0].request_parameters["inferenceConfig"] == {"maxTokens": 4096}
    assert result.parsed.ok and result.text == '{"ok":true}'
    assert exchanges[0].stop_reason == "end_turn"
    assert exchanges[0].usage["cacheReadInputTokens"] == 100
    assert "dummy-thought" not in exchanges[0].model_dump_json()


@pytest.mark.parametrize(
    ("reason", "status"),
    [("max_tokens", "truncated_response"), ("refusal", "refused")],
)
def test_truncation_or_refusal_records_usage_without_repeated_paid_call(reason, status):
    sdk = Mock()
    payload = response('{"ok":true}')
    payload["stopReason"] = reason
    sdk.converse.return_value = payload
    llm = BedrockClient(client=sdk, environ=ENV)
    exchanges = []
    with pytest.raises(LLMError), llm.observing(exchanges.append):
        llm.complete("", "", tier="fast", schema=Answer, stage="test")
    assert sdk.converse.call_count == 1
    assert exchanges[0].status == status and exchanges[0].parsed is None
    assert llm.tracker.report().total.input_tokens == 10
    assert llm.tracker.report().total.usage_complete


@pytest.mark.bedrock
def test_live_bedrock_opt_in():
    llm = BedrockClient(max_tokens=32)
    result = llm.complete("한 단어로만 응답하세요.", "안녕", tier="fast", stage="live_check")
    assert result.text.strip()
    assert result.input_tokens > 0
