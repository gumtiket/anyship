"""Data the service and the adapters exchange.

Rules this module enforces by construction:
  * An environment holds only values that are safe to store in the service DB
    (role ARN, External ID, host name). Private keys and tokens never appear here.
  * A result is either ok or carries an error, never both and never neither.
  * Log events carry structured data, but anything secret is the adapter's job to
    keep out of them (see redact.py).
"""
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Mapping, Union

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

ENV_ID_PATTERN = r"^[a-z][a-z0-9-]{1,20}$"


class AdapterModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- environments ------------------------------------------------------------------
class AwsEnvironment(AdapterModel):
    """A user's AWS account, reached through the cross-account deploy role."""

    kind: Literal["aws"] = "aws"
    env_id: str = Field(pattern=ENV_ID_PATTERN)
    role_arn: str = Field(pattern=r"^arn:aws:iam::[0-9]{12}:role/[\w+=,.@/-]+$")
    external_id: str = Field(min_length=16, max_length=128, pattern=r"^[\w+=,.@:/-]+$")
    region: str = Field(default="ap-northeast-2", pattern=r"^[a-z]{2}(-[a-z]+)+-[0-9]$")


class OnpremEnvironment(AdapterModel):
    """A server the user prepared once (Docker, deploy account, our public key)."""

    kind: Literal["onprem"] = "onprem"
    env_id: str = Field(pattern=ENV_ID_PATTERN)
    host: str = Field(pattern=r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
    ssh_user: str = Field(default="deploy", pattern=r"^[a-z_][a-z0-9_-]{0,31}$")
    ssh_port: int = Field(default=22, ge=1, le=65535)


Environment = Annotated[Union[AwsEnvironment, OnpremEnvironment], Field(discriminator="kind")]

# Deploy spec as produced by the AI side. The adapter does not trust it: it
# re-validates every field it acts on (names, commands, sizes).
Spec = Mapping[str, Any]

# Secret values for one deploy (name -> value). Held in memory only: not stored in
# the service DB, not logged, not echoed in results.
Secrets = Mapping[str, str]


# --- progress log --------------------------------------------------------------------
class LogEvent(AdapterModel):
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    level: Literal["info", "warn", "error"] = "info"
    step: int | None = Field(default=None, ge=1)
    total: int | None = Field(default=None, ge=1)
    name: str | None = Field(default=None, max_length=80)
    message: str = Field(max_length=2000)
    data: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def step_within_total(self):
        if self.step is not None and self.total is not None and self.step > self.total:
            raise ValueError("step must not exceed total")
        return self


# --- results ---------------------------------------------------------------------------
class AdapterError(AdapterModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")  # machine readable, e.g. ssh_unreachable
    message: str = Field(max_length=2000)  # shown to the user
    hint: str | None = Field(default=None, max_length=2000)  # what the user can do about it
    retryable: bool = False


class Result(AdapterModel):
    ok: bool
    error: AdapterError | None = None
    details: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def ok_xor_error(self):
        if self.ok and self.error is not None:
            raise ValueError("a successful result must not carry an error")
        if not self.ok and self.error is None:
            raise ValueError("a failed result must carry an error")
        return self


class CheckResult(Result):
    pass


class DeployResult(Result):
    url: str | None = None
    image_tag: str | None = None


class StatusResult(Result):
    state: Literal["running", "unhealthy", "stopped", "not_deployed", "unknown"] = "unknown"
    url: str | None = None
    image_tag: str | None = None


class DestroyResult(Result):
    pass
