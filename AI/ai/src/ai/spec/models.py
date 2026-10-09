from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai.credentials import credential_urls
from ai.spec.env_policy import (
    APP_NAME,
    DENIED_NAMES,
    ENV_NAME,
    MAX_ENV_BYTES,
    allowed_name,
    known_env_bytes,
)


class SpecModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class Source(SpecModel):
    repo: str
    commit: str | None = None


class Build(SpecModel):
    dockerfile: Literal["Dockerfile"] = "Dockerfile"
    runtime_hint: Literal["python3.12"] = "python3.12"


class Environment(SpecModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"secret": {"const": True}}, "required": ["secret"]},
                    "then": {"properties": {"value": {"type": "null"}}},
                    "else": {"required": ["value"], "properties": {"value": {"type": "string"}}},
                },
                {
                    "if": {"properties": {"generate": {"const": True}}, "required": ["generate"]},
                    "then": {"required": ["secret"], "properties": {"secret": {"const": True}}},
                },
                {
                    "if": {"properties": {"name": {"pattern": "_URL$"}}, "required": ["name"]},
                    "then": {"properties": {"generate": {"const": False}}},
                },
            ]
        },
    )
    name: str = Field(
        pattern=ENV_NAME,
        max_length=128,
        json_schema_extra={
            "not": {
                "anyOf": [{"enum": sorted(DENIED_NAMES)}, {"pattern": "^(AWS_|DOCKER_|LAMBDA_)"}]
            }
        },
    )
    secret: bool = False
    generate: bool = False
    value: str | None = Field(
        default=None,
        max_length=4096,
        json_schema_extra={"not": {"type": "string", "pattern": r"[\r\n\x00]"}},
    )

    @model_validator(mode="after")
    def safe_configuration(self):
        if not allowed_name(self.name):
            raise ValueError("environment_name_forbidden")
        if self.secret and self.value is not None:
            raise ValueError("secret_value_forbidden")
        if not self.secret and self.value is None:
            raise ValueError("environment_value_required")
        if self.generate and (not self.secret or self.name.endswith("_URL")):
            raise ValueError("environment_generation_forbidden")
        if self.value is not None and (
            credential_urls(self.value)
            or len(self.value.encode()) > MAX_ENV_BYTES
            or any(c in self.value for c in "\r\n\x00")
        ):
            raise ValueError("environment_value_unsafe")
        return self


class BackingService(SpecModel):
    type: Literal["postgres", "object_storage"]
    bind_as: Literal["DATABASE_URL", "STORAGE_URL"]

    @model_validator(mode="after")
    def matching_binding(self):
        expected = "DATABASE_URL" if self.type == "postgres" else "STORAGE_URL"
        if self.bind_as != expected:
            raise ValueError("backing_service_binding_mismatch")
        return self


class Workload(SpecModel):
    type: Literal["request-driven", "always-on"]
    scale_to_zero: bool
    max_request_seconds: int = Field(ge=1, le=3600)
    websocket: bool

    @model_validator(mode="after")
    def persistent_connections(self):
        if (self.type == "always-on" or self.websocket) and self.scale_to_zero:
            raise ValueError("persistent_workload_cannot_scale_to_zero")
        return self


class Web(SpecModel):
    instances: Literal[1] = 1


class Processes(SpecModel):
    web: Web = Field(default_factory=Web)


class Release(SpecModel):
    migrate: str


class DeploySpec(SpecModel):
    app: str = Field(pattern=APP_NAME)
    source: Source
    build: Build = Field(default_factory=Build)
    port: Literal[8080] = 8080
    healthcheck: Literal["/healthz"] = "/healthz"
    ingress: Literal["public"] = "public"
    env: list[Environment]
    backing_services: list[BackingService] = Field(
        json_schema_extra={
            "not": {
                "contains": {
                    "properties": {"type": {"const": "object_storage"}},
                    "required": ["type"],
                }
            }
        }
    )
    workload: Workload
    processes: Processes = Field(default_factory=Processes)
    release: Release | None = None
    profile: Literal["dev", "prod"] = "dev"

    @model_validator(mode="after")
    def environment_contract(self):
        if any(b.type == "object_storage" for b in self.backing_services):
            raise ValueError("object_storage_mvp_unsupported")
        names = [e.name for e in self.env] + [b.bind_as for b in self.backing_services]
        if len(names) != len(set(names)):
            raise ValueError("duplicate_environment_binding")
        values = {e.name: e.value or "" for e in self.env}
        values.update({b.bind_as: "" for b in self.backing_services})
        values["PORT"] = str(self.port)
        if known_env_bytes(values) > MAX_ENV_BYTES:
            raise ValueError("environment_total_size_exceeded")
        return self


class SpecProposal(SpecModel):
    max_request_seconds: int = Field(default=10, ge=1, le=3600)
    scale_to_zero: bool = True
    ingress: Literal["public", "internal"] = "public"
