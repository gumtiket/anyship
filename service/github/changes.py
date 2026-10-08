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


def commit_changes(repo_path: Path) -> None:
    run_git(
        ["config", "user.name", "Team Bronze Bot"],
        cwd=repo_path,
    )
    run_git(
        ["config", "user.email", "team-bronze-bot@example.com"],
        cwd=repo_path,
    )

    run_git(
        ["commit", "-m", "chore: apply automated code changes"],
        cwd=repo_path,
    )


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
