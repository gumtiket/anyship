"""실제 서버에서 OnpremAdapter를 시험하는 수동 시험(자동 테스트가 아니다).

서비스 서버에서 실행한다. 작은 시험 앱 이미지를 만들고 check, deploy, 재배포를 차례로 해 본다.

    python scripts/smoke_onprem.py --host 3.38.88.141 --env-id demo --staging

시험이 끝난 뒤 서버의 시험 앱을 지우는 방법은 마지막에 출력한다(destroy는 아직 없다).
"""
import argparse
import json
import ssl
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from anyship_adapters import OnpremEnvironment
from anyship_adapters.onprem import OnpremAdapter

APP = "smoke"

# 시험 앱: 표준 라이브러리만 쓰는 작은 웹 서버. /healthz와 /에서 200을 돌려준다.
SERVER = '''import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        ok = self.path in ("/", "/healthz")
        body = json.dumps({
            "app": "smoke", "path": self.path,
            "has_database_url": "DATABASE_URL" in os.environ,
            "has_secret_key": "SECRET_KEY" in os.environ,
        }).encode()
        self.send_response(200 if ok else 404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


HTTPServer(("0.0.0.0", int(os.environ["PORT"])), Handler).serve_forever()
'''
DOCKERFILE = """FROM public.ecr.aws/docker/library/python:3.12-slim
COPY server.py /app/server.py
USER 65532
CMD ["python", "/app/server.py"]
"""
SPEC = {
    "app": APP,
    "port": 8080,
    "healthcheck": "/healthz",
    "env": [
        {"name": "LOG_LEVEL", "value": "INFO"},
        {"name": "SECRET_KEY", "secret": True, "generate": True},
    ],
    "backing_services": [{"type": "postgres", "bind_as": "DATABASE_URL"}],
    "release": {"migrate": "echo migration-ran"},
}


def build(tag: str) -> None:
    with tempfile.TemporaryDirectory() as directory:
        Path(directory, "server.py").write_text(SERVER, encoding="utf-8")
        Path(directory, "Dockerfile").write_text(DOCKERFILE, encoding="utf-8")
        subprocess.run(["docker", "build", "-q", "-t", f"{APP}:{tag}", directory], check=True)


def log(event) -> None:
    prefix = f"[{event.step}/{event.total}] {event.name}" if event.step else f"({event.level})"
    print(f"    {prefix}: {event.message}")


def show(result) -> None:
    print("   ->", "성공" if result.ok else f"실패 {result.error.code}: {result.error.message}")
    if not result.ok and result.error.hint:
        print("      조치:", result.error.hint)
    if result.details:
        print("      details:", json.dumps(result.details, ensure_ascii=False))


def fetch(url: str, staging: bool) -> str:
    context = ssl._create_unverified_context() if staging else None
    with urllib.request.urlopen(url, timeout=10, context=context) as response:
        return f"{response.status} {response.read().decode()}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True, help="온프레미스 서버 주소")
    parser.add_argument("--env-id", default="demo")
    parser.add_argument("--key", default=str(Path.home() / ".ssh" / "onprem_deploy"))
    parser.add_argument("--domain", default="anyship.cloud")
    parser.add_argument("--staging", action="store_true", help="Let's Encrypt staging 인증서면 TLS 검증을 끈다")
    args = parser.parse_args()

    env = OnpremEnvironment(env_id=args.env_id, host=args.host)
    adapter = OnpremAdapter(Path(args.key), base_domain=args.domain, verify_tls=not args.staging)

    print("1) check")
    checked = adapter.check(env, log)
    show(checked)
    if not checked.ok:
        return 1

    for number, tag in ((2, "1111111"), (3, "2222222")):
        print(f"{number}) {'deploy' if number == 2 else '재배포(서버의 비밀을 재사용하는지 확인)'}  이미지 {APP}:{tag}")
        build(tag)
        deployed = adapter.deploy(env, SPEC, tag, {}, log, set_name="onprem")
        show(deployed)
        if not deployed.ok:
            return 1
        print("      응답:", fetch(deployed.url + "/", args.staging))

    print(f"\n정리(서버의 시험 앱 삭제): ssh -i {args.key} deploy@{args.host} "
          f"'cd /opt/apps/{APP} && docker compose down -v'  그다음  rm -r /opt/apps/{APP}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
