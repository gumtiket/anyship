"""aws-always-on 어댑터: 사용자 AWS 계정의 공용 EC2 호스트에 Compose로 앱을 배포한다.

온프레미스 어댑터와 같은 부품(ComposeAdapter, ComposeHost, render_stack, SshRunner, redact)을 쓰고, 다음만 다르다.
  * 접속 정보: 사용자가 입력한 서버 주소 대신, 공용 기반(infra/user-account)의 출력이 환경 정보로 들어온다.
  * 접근 권한: 사용자 계정의 역할을 AssumeRole한다(aws_access).
  * 앱 DB: 앱마다 컨테이너가 아니라 공용 RDS 안의 전용 DB와 계정(rds_admin).
  * 주소 규칙: `<앱>.<환경ID>.aws.<도메인>`. DNS 레코드는 미리 만들어 둔 환경을 전제로 한다.

status, rollback, destroy는 공통 클래스(ComposeAdapter)의 것을 쓰고, 호스트 정보가 있는지만 먼저 확인한다.
앱 destroy는 컨테이너와 파일만 지우고 앱 DB는 남긴다. 온프레미스 전용 기능(DNS 자동화 등)은 갖지 않는다.
"""
from pathlib import Path
from typing import Callable

from .aws_access import AwsAccess, AwsAccessError
from .base import LogFn
from .compose_adapter import ComposeAdapter, _err, _ssh_error, _step
from .compose_host import ComposeHost, wait_healthy
from .models import (AdapterError, AwsEnvironment, CheckResult, DeployResult, DestroyResult, StatusResult)
from .ssh import SshRunner

# 기반이 만들어졌는지 보려고 확인하는 필드와, 읽기만 하는 작업(상태, 되돌리기, 삭제)에 필요한 필드.
_FOUNDATION = ("host", "db_address", "db_secret_arn")
_HOST_ONLY = ("host",)


def foundation_error(env: AwsEnvironment, needed: tuple[str, ...] = _FOUNDATION) -> AdapterError | None:
    missing = [name for name in needed if getattr(env, name) is None]
    if not missing:
        return None
    return _err("foundation_missing", "사용자 계정의 공용 기반 정보가 없습니다: " + ", ".join(missing),
                hint="공용 기반(VPC, 앱 호스트, RDS)을 먼저 만들고, 그 출력값을 환경 정보에 넣어 주세요.")


class AwsAlwaysOnAdapter(ComposeAdapter):
    def __init__(self, key_path: Path, *, base_domain: str = "anyship.cloud", verify_tls: bool = True,
                 connect: Callable[[AwsEnvironment], tuple[SshRunner, ComposeHost]] | None = None,
                 healthy=wait_healthy, access: AwsAccess | None = None):
        super().__init__(key_path, base_domain=base_domain, verify_tls=verify_tls, connect=connect, healthy=healthy)
        self._access = access or AwsAccess()

    def _address(self, env: AwsEnvironment, app: str) -> str:
        return f"{app}.{env.env_id}.aws.{self._domain}"

    def check(self, env: AwsEnvironment, log: LogFn) -> CheckResult:
        total = 5
        _step(log, 1, total, "기반 확인", "공용 기반의 출력값이 있는지 확인하는 중")
        missing = foundation_error(env)
        if missing:
            return CheckResult(ok=False, error=missing)
        _step(log, 2, total, "역할 확인", "사용자 계정의 역할을 맡을 수 있는지 확인하는 중")
        try:
            account = self._access.check_role(env)
        except AwsAccessError as exc:
            return CheckResult(ok=False, error=exc.error)
        ssh, _ = self._connect(env)
        _step(log, 3, total, "접속 확인", "앱 호스트에 SSH로 접속하는 중")
        reached = ssh.run(["true"])
        if not reached.ok:
            return CheckResult(ok=False, error=_ssh_error(reached))
        _step(log, 4, total, "Docker 확인", "Docker와 Compose가 있는지 확인하는 중")
        if not ssh.run(["docker", "compose", "version"]).ok:
            return CheckResult(ok=False, error=_err(
                "docker_missing", "앱 호스트에 Docker 또는 Docker Compose가 없습니다.",
                hint="호스트가 처음 부팅하는 중일 수 있습니다. 몇 분 뒤 다시 시도해 주세요.", retryable=True))
        _step(log, 5, total, "프록시 확인", "HTTPS를 처리하는 Traefik이 실행 중인지 확인하는 중")
        proxy = ssh.run(["docker", "ps",
                         "--filter", "label=com.docker.compose.project=traefik",
                         "--filter", "label=com.docker.compose.service=traefik",
                         "--filter", "status=running", "--format", "{{.Names}}"])
        if not proxy.stdout.strip():
            return CheckResult(ok=False, error=_err(
                "proxy_not_ready", "앱 호스트에서 Traefik이 실행 중이지 않습니다.",
                hint="호스트가 처음 부팅하는 중일 수 있습니다. 계속되면 /opt/apps/traefik에서 Traefik을 시작해 주세요.",
                retryable=True))
        return CheckResult(ok=True, details={"account_id": account, "host": env.host})

    # -- 읽기와 정리: 호스트 정보만 있으면 되고, 동작은 온프레미스와 같다 -----------------------------
    def status(self, env: AwsEnvironment, app: str) -> StatusResult:
        error = foundation_error(env, _HOST_ONLY)
        return StatusResult(ok=False, error=error) if error else super().status(env, app)

    def rollback(self, env: AwsEnvironment, app: str, image_tag: str, log: LogFn) -> DeployResult:
        error = foundation_error(env, _HOST_ONLY)
        return DeployResult(ok=False, error=error) if error else super().rollback(env, app, image_tag, log)

    def destroy(self, env: AwsEnvironment, app: str, log: LogFn) -> DestroyResult:
        error = foundation_error(env, _HOST_ONLY)
        return DestroyResult(ok=False, error=error) if error else super().destroy(env, app, log)
