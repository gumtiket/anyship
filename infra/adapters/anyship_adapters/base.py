"""The interface the service calls. Every environment adapter (and the mock)
implements it, so the service never needs to know how an environment works.

All methods block until the work is finished; the service runs them in a
background worker and streams the log events to the user. Failures are returned
as a result with `ok=False`, they are not raised (unexpected bugs still raise).
"""
from typing import Callable, Protocol

from .models import (
    CheckResult,
    DeployResult,
    DestroyResult,
    Environment,
    LogEvent,
    Secrets,
    Spec,
    StatusResult,
)
from .sets import SetName

LogFn = Callable[[LogEvent], None]


class Adapter(Protocol):
    def check(self, env: Environment, log: LogFn) -> CheckResult:
        """Can we reach and manage this environment? (connection, permissions, prerequisites)"""
        ...

    def deploy(
        self,
        env: Environment,
        spec: Spec,
        image_tag: str,
        secrets: Secrets,
        log: LogFn,
        *,
        set_name: SetName,
    ) -> DeployResult:
        """Deploy `spec` at `image_tag` with the chosen set and return the public URL.

        `secrets` lives in memory only. The adapter writes it to the environment's
        secret store (AWS Secrets Manager, or the server's .env) and never logs it.
        """
        ...

    def status(self, env: Environment, app: str) -> StatusResult:
        """Is the app running and healthy right now?"""
        ...

    def rollback(self, env: Environment, app: str, image_tag: str, log: LogFn) -> DeployResult:
        """Run the previous image tag again. Database schema is not reverted."""
        ...

    def destroy(self, env: Environment, app: str, log: LogFn) -> DestroyResult:
        """Remove what a deploy created for this app."""
        ...
