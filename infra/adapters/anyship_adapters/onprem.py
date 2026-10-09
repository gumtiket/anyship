"""온프레미스 어댑터: 사용자의 서버에 SSH로 접속해 Compose로 앱을 배포한다.

공용 부품을 조립한다: spec(검증), compose(파일), ssh와 compose_host(서버 조작), redact(비밀).
이 환경에만 해당하는 것은 앱 주소 규칙(`<앱>.<환경ID>.onprem.<도메인>`)과 앱 전용 DB 컨테이너다.

이 조각의 범위는 check와 deploy다. status, rollback, destroy와 DNS 레코드 자동 생성은
다음 조각에서 추가한다(그 전까지 Adapter 인터페이스를 전부 만족하지는 않는다).
"""
import ipaddress
from pathlib import Path
from typing import Callable

from .base import LogFn
from .compose import render_stack
from .compose_host import ComposeHost, wait_healthy
from .models import AdapterError, CheckResult, DeployResult, LogEvent, OnpremEnvironment, Secrets, Spec
from .redact import make_safe_log, redact_text
from .sets import ONPREM, SetName
from .spec import SpecError, parse_spec
from .ssh import CommandResult, SshConnection, SshRunner


def _err(code: str, message: str, hint: str | None = None, retryable: bool = False) -> AdapterError:
    return AdapterError(code=code, message=message, hint=hint, retryable=retryable)


def _ssh_error(result: CommandResult) -> AdapterError:
    if result.connection_failed or result.timed_out:
        return _err("ssh_unreachable", "서버에 SSH로 접속할 수 없습니다.",
                    hint="서버 주소, 22번 포트(서비스 서버 IP 허용), 준비 스크립트 실행 여부를 확인해 주세요.",
                    retryable=True)
    return _err("ssh_command_failed", "서버에서 명령을 실행하지 못했습니다.")


def _step(log: LogFn, step: int, total: int, name: str, message: str) -> None:
    log(LogEvent(step=step, total=total, name=name, message=message))


class OnpremAdapter:
    def __init__(self, key_path: Path, *, base_domain: str = "anyship.cloud", verify_tls: bool = True,
                 connect: Callable[[OnpremEnvironment], tuple[SshRunner, ComposeHost]] | None = None,
                 healthy=wait_healthy):
        self._key = key_path
        self._domain = base_domain
        self._verify_tls = verify_tls  # False는 Let's Encrypt staging 인증서를 시험할 때만
        self._connect = connect or self._default_connect  # 시험에서는 가짜 서버로 바꿔 끼운다
        self._healthy = healthy

    def _default_connect(self, env: OnpremEnvironment) -> tuple[SshRunner, ComposeHost]:
        ssh = SshRunner(SshConnection(env.host, self._key, env.ssh_user, env.ssh_port))
        return ssh, ComposeHost(ssh)

    def check(self, env: OnpremEnvironment, log: LogFn) -> CheckResult:
        ssh, _ = self._connect(env)
        _step(log, 1, 4, "접속 확인", "서버에 SSH로 접속하는 중")
        reached = ssh.run(["true"])
        if not reached.ok:
            return CheckResult(ok=False, error=_ssh_error(reached))
        _step(log, 2, 4, "Docker 확인", "Docker와 Compose가 있는지 확인하는 중")
        if not ssh.run(["docker", "compose", "version"]).ok:
            return CheckResult(ok=False, error=_err(
                "docker_missing", "서버에 Docker 또는 Docker Compose가 없습니다.",
                hint="서버 준비 스크립트(setup.sh)를 실행해 주세요."))
        _step(log, 3, 4, "프록시 확인", "HTTPS를 처리하는 Traefik이 실행 중인지 확인하는 중")
        # 컨테이너 이름(traefik-traefik-1 등)은 Compose 설정에 따라 달라지므로, 이름이 아니라
        # Compose가 붙이는 라벨(프로젝트 traefik의 서비스 traefik)로 실행 중인 것을 찾는다.
        proxy = ssh.run(["docker", "ps",
                         "--filter", "label=com.docker.compose.project=traefik",
                         "--filter", "label=com.docker.compose.service=traefik",
                         "--filter", "status=running", "--format", "{{.Names}}"])
        if not proxy.stdout.strip():
            return CheckResult(ok=False, error=_err(
                "proxy_not_ready", "서버에서 Traefik이 실행 중이지 않습니다.",
                hint="/opt/apps/traefik에서 Traefik을 먼저 시작해 주세요."))
        _step(log, 4, 4, "공개 IP 확인", "서버의 공개 IP를 조회하는 중")
        found = ssh.run(["curl", "-fsS", "--max-time", "10", "https://checkip.amazonaws.com"])
        public_ip = found.stdout.strip()
        if not found.ok or not _is_public_ipv4(public_ip):
            return CheckResult(ok=False, error=_err(
                "public_ip_unknown", "서버의 공개 IP를 확인할 수 없습니다.",
                hint="서버가 인터넷으로 나갈 수 있어야 하고, 공인 IP가 있어야 합니다.", retryable=True))
        return CheckResult(ok=True, details={"public_ip": public_ip})

    def deploy(self, env: OnpremEnvironment, spec: Spec, image_tag: str, secrets: Secrets,
               log: LogFn, *, set_name: SetName) -> DeployResult:
        if set_name != ONPREM:
            return DeployResult(ok=False, error=_err(
                "set_not_supported", f"온프레미스 환경에서는 '{set_name}' 세트를 사용할 수 없습니다."))
        try:
            parsed = parse_spec(spec)
        except SpecError as exc:
            return DeployResult(ok=False, error=exc.error)

        total, app = 6, parsed.app
        known = dict(secrets)  # 걸러낼 비밀. 서버에서 읽은 값도 아래에서 여기에 더한다(같은 딕셔너리를 참조).
        safe = make_safe_log(log, known)

        def fail(error: AdapterError, result: CommandResult | None = None) -> DeployResult:
            safe(LogEvent(level="error", message=error.message))
            details = {"stderr": redact_text(result.stderr[-500:], known)} if result and result.stderr else {}
            return DeployResult(ok=False, error=error, image_tag=image_tag, details=details)

        address = f"{app}.{env.env_id}.onprem.{self._domain}"
        try:  # 서버에 접속하기 전에, 서버 없이 알 수 있는 입력 오류(태그, 비밀 누락 등)부터 거른다.
            render_stack(spec, host=address, image_tag=image_tag, secrets=secrets)
        except SpecError as exc:
            return fail(exc.error)

        ssh, host = self._connect(env)
        _step(safe, 1, total, "환경 점검", "서버에 접속하고 이전 설정을 읽는 중")
        reached = ssh.run(["true"])
        if not reached.ok:
            return fail(_ssh_error(reached), reached)
        previous = host.read_previous_env(app)
        known.update(previous)
        try:  # 이번에는 서버의 이전 비밀을 반영해서 다시 변환한다(서버의 값이 잘못됐을 수 있다).
            stack = render_stack(spec, host=address, image_tag=image_tag, secrets=secrets, previous_env=previous)
        except SpecError as exc:
            return fail(exc.error)
        for warning in stack.warnings:
            safe(LogEvent(level="warn", message=warning))

        _step(safe, 2, total, "이미지 전달", f"이미지 {app}:{image_tag}를 서버로 보내는 중")
        sent = host.load_image(f"{app}:{image_tag}")
        if not sent.ok:
            return fail(_err("image_transfer_failed", "이미지를 서버로 전달하지 못했습니다.",
                             hint="서비스 서버에 이 이미지가 있는지, 서버의 디스크 여유가 있는지 확인해 주세요.",
                             retryable=True), sent)
        _step(safe, 3, total, "파일 쓰기", "앱 설정 파일을 서버에 쓰는 중")
        written = host.write_stack(app, stack)
        if not written.ok:
            return fail(_err("server_write_failed", "서버에 설정 파일을 쓰지 못했습니다.",
                             hint="/opt/apps 디렉터리의 쓰기 권한과 디스크 여유를 확인해 주세요."), written)
        _step(safe, 4, total, "앱 시작", "컨테이너를 시작하는 중")
        started = host.up(app)
        if not started.ok:
            return fail(_err("container_start_failed", "앱 컨테이너를 시작하지 못했습니다.",
                             hint="서버에서 docker compose logs로 시작 오류를 확인해 주세요.", retryable=True), started)
        if parsed.migrate:
            _step(safe, 5, total, "마이그레이션", "데이터베이스 마이그레이션을 실행하는 중")
            migrated = host.migrate(app, parsed.migrate)
            if not migrated.ok:
                return fail(_err("migration_failed", "데이터베이스 마이그레이션이 실패했습니다.",
                                 hint="마이그레이션 명령과 데이터베이스 연결 설정을 확인해 주세요."), migrated)
        else:
            _step(safe, 5, total, "마이그레이션", "명세에 마이그레이션이 없어 건너뜁니다")
        _step(safe, 6, total, "헬스체크", "공개 주소로 앱이 응답하는지 확인하는 중")
        healthy, status = self._healthy(f"https://{address}{parsed.healthcheck}", verify_tls=self._verify_tls)
        if not healthy:
            return fail(_err("healthcheck_failed", f"앱이 시작됐지만 헬스체크를 통과하지 못했습니다(마지막 응답: {status}).",
                             hint="앱이 PORT 환경변수의 포트에서 요청을 받고 /healthz가 200을 반환하는지 확인해 주세요.",
                             retryable=True))
        return DeployResult(ok=True, url=f"https://{address}", image_tag=image_tag,
                            details={"warnings": list(stack.warnings), "generated": list(stack.generated)})


def _is_public_ipv4(text: str) -> bool:
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return False
    return ip.version == 4 and ip.is_global
