from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SpecModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class Source(SpecModel):
    repo: str
    commit: str | None = None


class Build(SpecModel):
    dockerfile: Literal["Dockerfile"] = "Dockerfile"
    runtime_hint: Literal["python3.12"] = "python3.12"


class Environment(SpecModel):
    name: str = Field(pattern=r"^[A-Z_][A-Z0-9_]*$")
    secret: bool = False
    generate: bool = False
    value: str | None = None


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
    app: str
    source: Source
    build: Build = Field(default_factory=Build)
    port: Literal[8080] = 8080
    healthcheck: Literal["/healthz"] = "/healthz"
    ingress: Literal["public", "internal"] = "public"
    env: list[Environment]
    backing_services: list[BackingService]
    workload: Workload
    processes: Processes = Field(default_factory=Processes)
    release: Release | None = None
    profile: Literal["dev", "prod"] = "dev"


class SpecProposal(SpecModel):
    max_request_seconds: int = Field(default=10, ge=1, le=3600)
    scale_to_zero: bool = True
    ingress: Literal["public", "internal"] = "public"
