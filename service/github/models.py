from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Workspace:
    repository: str
    path: Path
    branch: str


@dataclass(frozen=True)
class CommitResult:
    created: bool
    sha: str | None
    summary: str


@dataclass(frozen=True)
class PushResult:
    repository: str
    branch: str


@dataclass(frozen=True)
class PullRequest:
    number: int
    url: str
