from unittest.mock import Mock

from ai.llm.check import error_hint, list_models, main


def test_model_listing_paginates_profiles_and_filters_anthropic(capsys):
    control = Mock()
    control.list_inference_profiles.side_effect = [
        {
            "inferenceProfileSummaries": [{"inferenceProfileId": "dummy-profile-1"}],
            "nextToken": "dummy-next",
        },
        {"inferenceProfileSummaries": [{"inferenceProfileId": "dummy-profile-2"}]},
    ]
    control.list_foundation_models.return_value = {"modelSummaries": [{"modelId": "dummy-model"}]}
    list_models(control)
    assert control.list_inference_profiles.call_args.kwargs == {"nextToken": "dummy-next"}
    control.list_foundation_models.assert_called_once_with(byProvider="Anthropic")
    output = capsys.readouterr().out
    assert "dummy-profile-1" in output and "dummy-profile-2" in output


def test_check_missing_region_does_not_call_aws(monkeypatch):
    monkeypatch.delenv("BEDROCK_REGION", raising=False)
    sdk = Mock()
    monkeypatch.setattr("ai.llm.check.boto3.Session", sdk)
    assert main([]) == 2
    sdk.assert_not_called()


def test_list_only_does_not_construct_inference_client(monkeypatch):
    monkeypatch.setenv("BEDROCK_REGION", "dummy-region")
    control = Mock()
    control.list_inference_profiles.return_value = {}
    control.list_foundation_models.return_value = {}
    constructor = Mock()
    constructor.return_value.client.return_value = control
    inference = Mock()
    monkeypatch.setattr("ai.llm.check.boto3.Session", constructor)
    monkeypatch.setattr("ai.llm.check.BedrockClient", inference)
    assert main(["--list-only"]) == 0
    constructor.assert_called_once_with(region_name="dummy-region")
    assert constructor.return_value.client.call_args.kwargs["region_name"] == "dummy-region"
    inference.assert_not_called()


def test_actionable_korean_hints():
    assert "권한" in error_hint("AccessDeniedException")
    assert "프로필" in error_hint("ValidationException")
    assert "AWS_PROFILE" in error_hint("NoCredentialsError")
    assert "AWS_DEFAULT_REGION" in error_hint("NoRegionError")
