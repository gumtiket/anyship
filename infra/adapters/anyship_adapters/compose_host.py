"""서버 한 대 위의 Compose 앱을 다루는 부품(온프레미스와 aws-always-on이 함께 쓴다).

SshRunner 위에서 하는 일: 앱 디렉터리와 파일 쓰기, 서버에 남은 이전 비밀 읽기, 이미지 전달,
compose 실행, 마이그레이션, 헬스체크. 어떤 환경인지(주소 규칙, DB 방식)는 모른다.
"""
import re
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from typing import Callable

from .compose import RenderedStack
from .models import APP_NAME_PATTERN
from .ssh import MAX_OUTPUT, CommandResult, SshRunner, safe_env

APPS_DIR = "/opt/apps"
_APP = re.compile(APP_NAME_PATTERN)
_IMAGE = re.compile(r"^[a-z][a-z0-9-]{2,62}:[0-9a-f]{7,40}$")  # <앱>:<커밋 SHA>
_ENV_LINE = re.compile(r"^([A-Z_][A-Z0-9_]{0,63})='([^'\r\n\0]*)'$")


class ComposeHost:
    def __init__(self, ssh: SshRunner, *, apps_dir: str = APPS_DIR, popen=subprocess.Popen):
        self._ssh = ssh
        self._dir = apps_dir
        self._popen = popen  # 시험에서는 가짜로 바꿔 끼운다

    def _app_dir(self, app: str) -> str:
        if not _APP.match(app):
            raise ValueError("invalid app name")
        return f"{self._dir}/{app}"

    def read_previous_env(self, app: str) -> dict[str, str]:
        """서버에 이미 있는 .env와 app.env의 값. 생성한 비밀을 재배포 때 재사용하려고 읽는다.
        비밀이 들어 있으니 메모리에서만 쓰고 로그에 남기지 않는다."""
        values: dict[str, str] = {}
        for name in (".env", "app.env"):
            done = self._ssh.run(["cat", f"{self._app_dir(app)}/{name}"])
            for line in done.stdout.splitlines() if done.ok else []:
                match = _ENV_LINE.match(line)
                if match:
                    values[match.group(1)] = match.group(2)
        return values

    def write_stack(self, app: str, stack: RenderedStack) -> CommandResult:
        """앱 디렉터리를 만들고 파일을 쓴다. 비밀이 든 파일(.env, app.env)은 권한 600."""
        directory = self._app_dir(app)
        result = self._ssh.run(["mkdir", "-p", directory])
        for name, content, mode in ((".env", stack.compose_env, "0600"),
                                    ("app.env", stack.app_env, "0600"),
                                    ("compose.yaml", stack.compose_yaml, "0644")):
            if not result.ok:
                break
            result = self._ssh.put(f"{directory}/{name}", content, mode=mode)
        return result

    def load_image(self, image: str, *, timeout: float = 900) -> CommandResult:
        """서비스 서버의 이미지를 서버로 흘려보낸다(docker save | ssh docker load, 레지스트리 없음)."""
        if not _IMAGE.match(image):
            raise ValueError("invalid image reference")
        save = self._popen(["docker", "save", image], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, env=safe_env())
        try:
            loaded = self._ssh.run(["docker", "load"], stdin=save.stdout, timeout=timeout)
        finally:
            save.stdout.close()
        if loaded.timed_out:
            save.kill()
        errors = save.stderr.read().decode("utf-8", errors="replace")[:MAX_OUTPUT]
        code = save.wait()
        return loaded if code == 0 else CommandResult(code, stderr=errors)

    def up(self, app: str, *, timeout: float = 300) -> CommandResult:
        return self._ssh.run(["docker", "compose", "--project-directory", self._app_dir(app),
                              "up", "-d", "--remove-orphans"], timeout=timeout)

    def migrate(self, app: str, command: str, *, timeout: float = 300) -> CommandResult:
        """앱 컨테이너 안에서만 마이그레이션 명령을 실행한다(서버의 셸에서 실행하지 않는다)."""
        return self._ssh.run(["docker", "compose", "--project-directory", self._app_dir(app),
                              "run", "--rm", "web", "sh", "-c", command], timeout=timeout)


def _status(url: str, verify_tls: bool, timeout: float = 5) -> int | None:
    context = None if verify_tls else ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(url, timeout=timeout, context=context) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except (urllib.error.URLError, OSError):
        return None


def wait_healthy(url: str, *, attempts: int = 30, delay: float = 2.0, verify_tls: bool = True,
                 fetch: Callable[[str, bool], int | None] = _status,
                 sleep: Callable[[float], None] = time.sleep) -> tuple[bool, int | None]:
    """서비스 서버에서 공개 주소로 요청해 200이 올 때까지 기다린다. (성공 여부, 마지막 상태 코드)

    verify_tls=False는 Let's Encrypt staging 인증서를 시험할 때만 쓴다."""
    if not url.startswith("https://"):
        raise ValueError("health check url must be https")
    status = None
    for attempt in range(attempts):
        status = fetch(url, verify_tls)
        if status == 200:
            return True, status
        if attempt < attempts - 1:
            sleep(delay)
    return False, status
