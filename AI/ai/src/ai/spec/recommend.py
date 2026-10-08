import json
from importlib.resources import files
from typing import Literal

from pydantic import Field, model_validator

from ai.llm.base import LLMClient
from ai.models import Diagnosis, OutputModel, Recommendation, TransformReport, WarningItem
from ai.security import SourceMasker
from ai.spec.cost_table import CostAssumptions, estimate_monthly
from ai.spec.models import DeploySpec
from ai.spec.tfvars_schema import make_tfvars

REQUEST_THRESHOLD_SECONDS = 25  # Placement demo rule, not a claimed platform timeout limit.
SETS = ("aws-serverless", "aws-always-on", "onprem")


def select_set(target_env: str, spec: DeploySpec, diagnosis: Diagnosis) -> tuple[str, str]:
    if target_env == "onprem":
        return "onprem", "target_onprem"
    if target_env != "aws":
        raise ValueError("target_env_invalid")
    if any(s.name == "scheduler" for s in diagnosis.signals):
        return "aws-always-on", "scheduler"
    if spec.workload.websocket or any(s.name == "websocket" for s in diagnosis.signals):
        return "aws-always-on", "websocket"
    if spec.workload.max_request_seconds > REQUEST_THRESHOLD_SECONDS:
        return "aws-always-on", "request_over_threshold"
    return "aws-serverless", "short_request"


class Rationale(OutputModel):
    selected_set: Literal["aws-serverless", "aws-always-on", "onprem"]
    text: str = Field(min_length=1, max_length=2000)


def recommend(
    target_env: str,
    spec: DeploySpec,
    diagnosis: Diagnosis,
    transformation: TransformReport,
    llm: LLMClient | None,
    masker: SourceMasker,
    *,
    image_reference: str | None = None,
    tfvars_overrides: dict | None = None,
    cost_assumptions: CostAssumptions | None = None,
) -> Recommendation:
    selected, fired = select_set(target_env, spec, diagnosis)
    variables, replaced = make_tfvars(
        selected, spec, image_reference=image_reference, overrides=tfvars_overrides
    )
    memory = variables.memory_limit_mb
    amount, assumptions = estimate_monthly(selected, memory_mb=memory, assumptions=cost_assumptions)
    rationale = (
        f"규칙 {fired}에 따라 {selected}를 선택했습니다. "
        "요청 시간은 후보 값이며 실제 동작·인프라 계약은 별도 확인해야 합니다."
    )
    rationale_source = "rule"
    warnings = list(transformation.warnings)
    warnings.append(
        WarningItem(
            code="provisional_infra_contract",
            message=(
                "확인 필요(C 확정 전): tfvars 스키마·단가를 실제 인프라에 바로 적용하지 마세요."
            ),
        )
    )
    if replaced:
        warnings.append(
            WarningItem(
                code="tfvars_validation_failed",
                message=(
                    "임시 tfvars 검증 실패로 기본값을 사용했습니다. 입력을 클램프하지 않았습니다."
                ),
            )
        )
    if image_reference is None:
        assumptions.append("이미지 식별자 미제공: A가 실제 빌드된 이미지 태그/digest를 확정해야 함")
    if any(s.name == "long_request" for s in diagnosis.signals):
        warnings.append(
            WarningItem(
                code="request_duration_needs_review",
                message=(
                    "긴 요청 후보 신호가 있습니다. "
                    "max_request_seconds는 실측 시간이나 실행 보장이 아닙니다."
                ),
            )
        )
    if llm is not None:

        class SelectedRationale(Rationale):
            @model_validator(mode="after")
            def consistent(self):
                if self.selected_set != selected or any(
                    s in self.text.lower() for s in SETS if s != selected
                ):
                    raise ValueError("rationale_contradicts_rule")
                return self

        try:
            response = llm.complete(
                files("ai").joinpath("prompts/recommend.txt").read_text(),
                json.dumps(
                    {
                        "selected_set": selected,
                        "rule_fired": fired,
                        "signals": [s.model_dump(mode="json") for s in diagnosis.signals],
                        "workload": spec.workload.model_dump(mode="json"),
                    },
                    ensure_ascii=False,
                ),
                tier="fast",
                schema=SelectedRationale,
                stage="recommend",
            )
            if not isinstance(response.parsed, SelectedRationale):
                raise ValueError("rationale_invalid")
            rationale = masker.text(response.parsed.text)
            rationale_source = "llm"
        except (ValueError, RuntimeError):
            warnings.append(
                WarningItem(
                    code="recommend_llm_fallback",
                    message="LLM 설명 검증 실패로 규칙 템플릿 근거를 사용했습니다.",
                )
            )
    return Recommendation(
        status="completed",
        set=selected,
        rule_fired=fired,
        signals=diagnosis.signals,
        rationale=rationale,
        rationale_source=rationale_source,
        needs_approval=transformation.needs_approval,
        estimated_monthly_cost=amount,
        assumptions=assumptions,
        tfvars=variables.model_dump(mode="json", by_alias=True, exclude_none=True),
        needs_confirmation=["tfvars_schema", "cost_table"],
        warnings=warnings,
    )
