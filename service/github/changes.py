from pathlib import Path

from github.repository import run_git


def get_changes(repo_path: Path) -> str:
    return run_git(
        ["status", "--short"],
        cwd=repo_path,
    )


def get_diff(repo_path: Path) -> str:
    return run_git(
        ["diff", "HEAD", "--"],
        cwd=repo_path,
    )


def stage_changes(repo_path: Path) -> str:
    run_git(["add", "-A"], cwd=repo_path)
    return run_git(["diff", "--cached", "--stat"], cwd=repo_path)


def commit_changes(
    repo_path: Path,
    message: str = "chore: apply automated code changes",
    *,
    author_name: str | None = "Team Bronze Bot",
    author_email: str | None = "team-bronze-bot@example.com",
) -> None:
    author_options: list[str] = []
    if author_name is not None:
        author_options.extend(["-c", f"user.name={author_name}"])
    if author_email is not None:
        author_options.extend(["-c", f"user.email={author_email}"])

    run_git([*author_options, "commit", "-m", message], cwd=repo_path)


def push_branch(
    repo_path: Path,
    branch: str,
    token: str,
) -> None:
    run_git(
        ["push", "origin", branch],
        cwd=repo_path,
        token=token,
    )
