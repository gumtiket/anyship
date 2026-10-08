import json
from importlib.resources import files
from typing import Literal

from jsonschema import Draft202012Validator

from ai.llm.base import LLMClient
from ai.models import Diagnosis, TransformReport
from ai.security import credential_name
from ai.spec.models import (
    BackingService,
    DeploySpec,
    Environment,
    Release,
    Source,
    SpecProposal,
    Workload,
)


def validate_spec(spec: DeploySpec) -> None:
    schema = json.loads(files("ai").joinpath("spec/schema.json").read_text())
    Draft202012Validator(schema).validate(spec.model_dump(mode="json", exclude_none=True))


def generate_spec(
    app: str,
    source_repo: str,
    commit: str | None,
    profile: Literal["dev", "prod"],
    diagnosis: Diagnosis,
    transformation: TransformReport,
    llm: LLMClient | None,
) -> tuple[DeploySpec, bool]:
    proposal = SpecProposal()
    fallback = False
    if llm is not None:
        try:
            response = llm.complete(
                files("ai").joinpath("prompts/spec.txt").read_text(),
                json.dumps({"signals": [s.model_dump(mode="json") for s in diagnosis.signals]}),
                tier="fast",
                schema=SpecProposal,
                stage="spec",
            )
            if not isinstance(response.parsed, SpecProposal):
                raise ValueError("spec_proposal_invalid")
            proposal = response.parsed
        except (ValueError, RuntimeError):
            fallback = True
    websocket = any(signal.name == "websocket" for signal in diagnosis.signals)
    persistent = websocket or any(signal.name == "scheduler" for signal in diagnosis.signals)
    postgres = any(
        v.rule == "sqlite_usage" and v.id in transformation.addressed_ids
        for v in diagnosis.violations
    )
    env = []
    for variable in transformation.env_vars:
        if postgres and variable.name == "DATABASE_URL":
            continue  # Adapter injects backing service URLs; it must not generate random DB URLs.
        secret = variable.secret or credential_name(variable.name)
        env.append(
            Environment(
                name=variable.name,
                secret=secret,
                generate=secret,
                value=None if secret else variable.default,
            )
        )
    spec = DeploySpec(
        app=app,
        source=Source(repo=source_repo, commit=commit),
        env=env,
        backing_services=[BackingService(type="postgres", bind_as="DATABASE_URL")]
        if postgres
        else [],
        workload=Workload(
            type="always-on" if persistent else "request-driven",
            scale_to_zero=False if persistent else proposal.scale_to_zero,
            max_request_seconds=proposal.max_request_seconds,
            websocket=websocket,
        ),
        ingress=proposal.ingress,
        release=Release(migrate=transformation.migrate_command)
        if transformation.migrate_command
        else None,
        profile=profile,
    )
    validate_spec(spec)
    return spec, fallback
