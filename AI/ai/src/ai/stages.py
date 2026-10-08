from collections.abc import Callable
from enum import StrEnum


class Stage(StrEnum):
    ANALYZING = "분석 중"
    VALIDATING = "검증 중"
    PR_PENDING = "PR 대기"
    BUILDING = "빌드 중"
    DEPLOYING = "배포 중"
    SUCCEEDED = "성공"
    FAILED = "실패"


LogFn = Callable[[Stage, str], None]


def default_log(stage: Stage, message: str) -> None:
    print(f"[{stage.value}] {message}")
