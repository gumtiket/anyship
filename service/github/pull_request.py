import requests


def github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_default_branch(repo: str, token: str) -> str:
    response = requests.get(
        f"https://api.github.com/repos/{repo}",
        headers=github_headers(token),
        timeout=20,
    )
    response.raise_for_status()
    return response.json()["default_branch"]


def create_pull_request(
    repo: str,
    branch: str,
    base: str,
    token: str,
    *,
    title: str = "Automated Code Changes",
    body: str = "코드 수정 도구가 생성한 자동 코드 변경 사항입니다.",
    draft: bool = True,
) -> dict:
    response = requests.post(
        f"https://api.github.com/repos/{repo}/pulls",
        headers=github_headers(token),
        json={
            "title": title,
            "head": branch,
            "base": base,
            "body": body,
            "draft": draft,
        },
        timeout=20,
    )
    response.raise_for_status()

    data = response.json()
    return {
        "number": data["number"],
        "url": data["html_url"],
    }
