import pytest

from github.repository import parse_repo_url


@pytest.mark.parametrize("suffix", ["", ".git", "/"])
def test_valid_repo_url(suffix):
    url = f"https://github.com/owner/example{suffix}"
    assert parse_repo_url(url) == "owner/example"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/test/repo",
        "https://github.com/test",
        "https://github.com/a/b/c",
        "http://github.com/test/repo",
        "https://user:secret@github.com/a/b",
        "https://github.com/a/b?x=1",
        "https://github.com/a/b#x",
    ],
)
def test_invalid_repo_url(url):
    with pytest.raises(ValueError):
        parse_repo_url(url)


