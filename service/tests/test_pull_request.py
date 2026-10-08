from unittest.mock import Mock, patch

import pytest
import requests

from github.pull_request import create_pull_request, get_default_branch


def test_get_default_branch():
    response = Mock()
    response.json.return_value = {"default_branch": "develop"}

    with patch("github.pull_request.requests.get", return_value=response) as get:
        assert get_default_branch("owner/repo", "test-token") == "develop"

    assert get.call_args.args == ("https://api.github.com/repos/owner/repo",)
    assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer test-token"
    assert get.call_args.kwargs["timeout"] == 20
    response.raise_for_status.assert_called_once()


def test_create_draft_pull_request():
    response = Mock()
    response.json.return_value = {
        "number": 42,
        "html_url": "https://github.com/owner/repo/pull/42",
    }

    with patch("github.pull_request.requests.post", return_value=response) as post:
        result = create_pull_request("owner/repo", "work", "main", "test-token")

    assert result == {
        "number": 42,
        "url": "https://github.com/owner/repo/pull/42",
    }
    assert post.call_args.args == ("https://api.github.com/repos/owner/repo/pulls",)
    payload = post.call_args.kwargs["json"]
    assert payload["head"] == "work"
    assert payload["base"] == "main"
    assert payload["draft"] is True
    response.raise_for_status.assert_called_once()


@pytest.mark.parametrize("operation", ["get", "post"])
def test_http_failure_is_propagated(operation):
    response = Mock()
    response.raise_for_status.side_effect = requests.HTTPError("GitHub rejected request")

    with patch(f"github.pull_request.requests.{operation}", return_value=response):
        with pytest.raises(requests.HTTPError):
            if operation == "get":
                get_default_branch("owner/repo", "test-token")
            else:
                create_pull_request("owner/repo", "work", "main", "test-token")

    response.json.assert_not_called()
