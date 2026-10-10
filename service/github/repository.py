import base64
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse


def parse_repo_url(url: str) -> str:
    parsed = urlparse(url)

    if (
        parsed.scheme != "https"
        or parsed.netloc != "github.com"
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise ValueError("GitHub HTTPS URL만 지원합니다.")

    path = parsed.path.strip("/").removesuffix(".git")

    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", path):
        raise ValueError("올바른 GitHub 레포 URL이 아닙니다.")

    if any(part in (".", "..") for part in path.split("/")):
        raise ValueError("올바른 GitHub 레포 URL이 아닙니다.")

    return path


def run_git(
    args: list[str],
    cwd: Path,
    token: str | None = None,
) -> str:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"

    if token:
        credentials = f"x-access-token:{token}".encode()
        encoded_credentials = base64.b64encode(credentials).decode()

        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "http.https://github.com/.extraheader"
        env["GIT_CONFIG_VALUE_0"] = f"AUTHORIZATION: basic {encoded_credentials}"

    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    return result.stdout.strip()


def clone_repository(
    repo: str,
    branch: str,
    destination: Path,
    token: str,
    depth: int | None = None,
) -> Path:
    """`depth`를 주면 그 개수만큼의 최근 커밋만 받는다(배포용 소스처럼 이력이 필요 없을 때)."""
    run_git(
        [
            "clone",
            "--single-branch",
            "--branch",
            branch,
            *(["--depth", str(depth)] if depth is not None else []),
            f"https://github.com/{repo}.git",
            str(destination),
        ],
        cwd=destination.parent,
        token=token,
    )
    return destination


def create_branch(repo_path: Path, name: str) -> None:
    run_git(
        ["checkout", "-b", name],
        cwd=repo_path,
    )
