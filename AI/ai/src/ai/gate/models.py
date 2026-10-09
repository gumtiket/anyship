from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GateStep(GateModel):
    name: str
    status: Literal["passed", "failed"]
    duration_s: float = Field(ge=0)
    log: str = ""


class GateExecution(GateModel):
    status: Literal["not_run", "passed", "failed"] = "not_run"
    steps: list[GateStep] = Field(default_factory=list)
    logs: str = ""
    matched_patterns: list[str] = Field(default_factory=list)
    cleanup_errors: list[str] = Field(default_factory=list)
    image_tag: str | None = None


class GateAttempt(GateModel):
    number: int
    status: Literal["skipped", "passed", "failed"]
    reason: str
    transformed: GateExecution
    original: GateExecution
    repair_summary: str | None = None
    repair_status: str | None = None
