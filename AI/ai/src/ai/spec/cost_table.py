"""단가 미확인: illustrative planning rates, not AWS prices or a billing quote.

TODO: C must confirm region, resource shapes, actual prices and usage before deployment.
No exchange-rate conversion or free-tier discount is applied.
"""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CostAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    region: str = "ap-northeast-2"
    monthly_requests: int = Field(default=100000, ge=0)
    running_hours: float = Field(default=730.0, ge=0, le=744)
    average_request_seconds: float = Field(default=0.2, gt=0)
    storage_gb: float = Field(default=20.0, ge=0)
    free_tier_excluded: Literal[True] = True


@dataclass(frozen=True)
class Rate:
    value: float
    unit: str
    label: str = "단가 미확인"


# Each number is a deliberately unconfirmed planning assumption. Not an AWS quotation.
RATES = {
    "aws-serverless": {
        "requests": Rate(0.20, "USD / 백만 요청"),
        "duration": Rate(0.00002, "USD / GB-second"),
        "database": Rate(0.03, "USD / DB 시간"),
        "storage": Rate(0.15, "USD / GB-month"),
    },
    "aws-always-on": {
        "host": Rate(0.035, "USD / 서버 시간"),
        "storage": Rate(0.15, "USD / GB-month"),
    },
    "onprem": {"host": Rate(0.015, "USD / 기존 서버 전력·운영 시간")},
}


def estimate_monthly(
    selected: str, *, memory_mb: int, assumptions: CostAssumptions | None = None
) -> tuple[float, list[str]]:
    usage = assumptions or CostAssumptions()
    if not usage.free_tier_excluded:
        raise ValueError("free_tier_calculation_not_supported")
    rates = RATES[selected]
    if selected == "aws-serverless":
        amount = (
            usage.monthly_requests / 1000000 * rates["requests"].value
            + usage.monthly_requests
            * usage.average_request_seconds
            * memory_mb
            / 1024
            * rates["duration"].value
            + usage.running_hours * rates["database"].value
            + usage.storage_gb * rates["storage"].value
        )
    else:
        amount = usage.running_hours * rates["host"].value
        if "storage" in rates:
            amount += usage.storage_gb * rates["storage"].value
    notes = [
        "임시 추정치: 단가 미확인, C 확정 전. 실제 AWS 요금이나 청구 견적이 아닙니다.",
        f"리전 가정: {usage.region}"
        if selected != "onprem"
        else "리전 가정: onprem-local (기존 서버)",
        f"월 요청 수 가정: {usage.monthly_requests}",
        f"상시 가동 시간 가정: 월 {usage.running_hours:g}시간",
        "프리티어·크레딧·할인 적용 제외",
        "통화 USD, 환율 변환 미적용",
        f"요청당 평균 실행 시간 가정: {usage.average_request_seconds:g}초 (실측/최대 시간 아님)",
        f"저장 용량 가정: {usage.storage_gb:g}GB, 메모리 입력: {memory_mb}MB",
        "데이터 전송·NAT·백업·로그·세금·환율·DB 고가용성·하드웨어 구입비는 계산하지 않음",
        "서버리스는 소형 단일 DB 가정; 상시 컨테이너는 DB도 동일 서버에서 실행하는 가정",
    ]
    notes.extend(
        f"{name}: {rate.value:g} {rate.unit} — {rate.label}" for name, rate in rates.items()
    )
    return round(amount, 4), notes
