import subprocess
import urllib.error
from pathlib import Path

import pytest

from anyship_adapters import render_stack
from anyship_adapters import compose_host
from anyship_adapters.compose_host import ComposeHost, wait_healthy
from anyship_adapters.ssh import SshConnection, SshRunner

from fakes import FakePopen, FakeServer
from specs import GENERATED

HOST = "todo.demo.onprem.anyship.cloud"


def make(fail_path_suffix=None, popen=None):
    server = FakeServer(fail_path_suffix)
    ssh = SshRunner(SshConnection("3.38.88.141", Path("/key")), runner=server)
    kwargs = {"popen": popen} if popen else {}
    return ComposeHost(ssh, **kwargs), server


def stack(**kw):
    return render_stack(GENERATED, host=HOST, image_tag=kw.pop("image_tag", "3f2a9c1"), **kw)


# --- 파일 쓰기와 이전 값 읽기 ----------------------------------------------------------------
def test_write_stack_creates_the_directory_then_writes_secrets_files_before_the_compose_file():
    host, server = make()
    result = host.write_stack("todo", stack())
    assert result.ok
    assert server.commands[0] == ["mkdir", "-p", "/opt/apps/todo"]
    assert server.written() == [".env", "app.env", "compose.yaml"]
    modes = {Path(c[4]).name: c[5] for c in server.commands if c[:2] == ["sh", "-c"]}
    assert modes == {".env": "0600", "app.env": "0600", "compose.yaml": "0644"}


def test_write_stack_stops_at_the_first_failure():
    host, server = make(fail_path_suffix="app.env")
    result = host.write_stack("todo", stack())
    assert not result.ok and result.stderr == "disk full"
    assert ".env" in server.written() and "compose.yaml" not in server.written()


def test_the_files_on_the_server_hold_exactly_what_was_rendered():
    host, server = make()
    rendered = stack()
    host.write_stack("todo", rendered)
    assert server.files["/opt/apps/todo/compose.yaml"].decode() == rendered.compose_yaml
    assert server.files["/opt/apps/todo/app.env"].decode() == rendered.app_env


def test_first_deploy_has_no_previous_values():
    assert make()[0].read_previous_env("todo") == {}


def test_a_redeploy_reuses_the_generated_secrets_found_on_the_server():
    host, _ = make()
    first = stack()
    host.write_stack("todo", first)
    previous = host.read_previous_env("todo")
    assert {"SECRET_KEY", "POSTGRES_PASSWORD"} <= set(previous)
    second = stack(image_tag="bbbbbbb", previous_env=previous)
    assert second.generated == ()
    assert second.app_env == first.app_env and second.compose_env == first.compose_env


def test_lines_that_are_not_plain_quoted_assignments_are_ignored_when_reading():
    host, server = make()
    server.files["/opt/apps/todo/app.env"] = b"GOOD='1'\nBAD=2\nlower='x'\nALSO_BAD='a'b'\n# comment\n"
    assert host.read_previous_env("todo") == {"GOOD": "1"}


# --- 이미지 전달 -----------------------------------------------------------------------------
def test_the_image_is_streamed_from_docker_save_into_docker_load_on_the_server():
    saves = []
    host, server = make(popen=lambda cmd, **kw: saves.append(FakePopen(cmd, **kw)) or saves[-1])
    result = host.load_image("todo:3f2a9c1")
    assert result.ok
    assert saves[0].cmd == ["docker", "save", "todo:3f2a9c1"]
    assert server.last() == ["docker", "load"]
    assert "stdin" in server.kwargs[-1] and "input" not in server.kwargs[-1]
    assert set(saves[0].kwargs["env"]) <= {"PATH", "HOME", "LANG"}


def test_a_failing_docker_save_is_reported_even_if_the_remote_side_succeeded():
    host, _ = make(popen=lambda cmd, **kw: FakePopen(cmd, code=1, errors=b"No such image", **kw))
    result = host.load_image("todo:3f2a9c1")
    assert not result.ok and result.returncode == 1 and "No such image" in result.stderr


def test_a_timed_out_transfer_stops_docker_save_and_is_reported_as_a_timeout():
    saves = []

    def popen(cmd, **kw):
        saves.append(FakePopen(cmd, code=-9, **kw))  # 죽은 프로세스는 0이 아닌 코드로 끝난다
        return saves[-1]

    def hangs(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)

    host = ComposeHost(SshRunner(SshConnection("3.38.88.141", Path("/key")), runner=hangs), popen=popen)
    result = host.load_image("todo:3f2a9c1", timeout=1)
    assert saves[0].killed
    assert result.timed_out and not result.ok  # 종료 코드 -9가 아니라 시간 초과로 보인다


@pytest.mark.parametrize("image", ["todo:latest", "todo", "Todo:3f2a9c1", "todo:3f2a9c1; echo", ""])
def test_only_app_and_commit_sha_images_are_accepted(image):
    host, server = make()
    with pytest.raises(ValueError):
        host.load_image(image)
    assert server.commands == []


# --- compose 실행과 마이그레이션 ---------------------------------------------------------------
def test_up_runs_compose_in_the_app_directory():
    host, server = make()
    host.up("todo")
    assert server.last() == ["docker", "compose", "--project-directory", "/opt/apps/todo",
                             "up", "-d", "--remove-orphans"]


def test_migrate_runs_inside_the_app_container_and_the_command_stays_one_argument():
    host, server = make()
    host.migrate("todo", "python -m app.migrate; echo done")
    assert server.last()[-4:] == ["web", "sh", "-c", "python -m app.migrate; echo done"]
    assert server.last()[:6] == ["docker", "compose", "--project-directory", "/opt/apps/todo", "run", "--rm"]


@pytest.mark.parametrize("call", [
    lambda h: h.up("Bad Name"), lambda h: h.up("../etc"), lambda h: h.migrate("a", "x"),
    lambda h: h.write_stack("x" * 70, None), lambda h: h.read_previous_env("a;b"),
])
def test_bad_app_names_are_rejected_before_anything_runs(call):
    host, server = make()
    with pytest.raises(ValueError):
        call(host)
    assert server.commands == []


# --- 헬스체크 ----------------------------------------------------------------------------------
URL = "https://todo.demo.onprem.anyship.cloud/healthz"


def test_wait_healthy_retries_until_it_gets_200():
    answers, pauses = iter([None, 502, 502, 200]), []
    ok, status = wait_healthy(URL, fetch=lambda u, v: next(answers), sleep=pauses.append, delay=2.0)
    assert (ok, status) == (True, 200) and pauses == [2.0, 2.0, 2.0]


def test_wait_healthy_gives_up_and_reports_the_last_status_without_a_pointless_last_pause():
    pauses = []
    ok, status = wait_healthy(URL, attempts=3, fetch=lambda u, v: 503, sleep=pauses.append)
    assert (ok, status) == (False, 503) and len(pauses) == 2


def test_wait_healthy_passes_the_tls_choice_through_and_requires_https():
    seen = []
    wait_healthy(URL, attempts=1, verify_tls=False, fetch=lambda u, v: seen.append(v) or 200)
    assert seen == [False]
    with pytest.raises(ValueError):
        wait_healthy("http://todo.example.com/healthz")


def test_status_maps_http_errors_to_their_code_and_connection_problems_to_none(monkeypatch):
    def raise_http(*a, **k):
        raise urllib.error.HTTPError(URL, 502, "bad gateway", {}, None)

    def raise_conn(*a, **k):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(compose_host.urllib.request, "urlopen", raise_http)
    assert compose_host._status(URL, True) == 502
    monkeypatch.setattr(compose_host.urllib.request, "urlopen", raise_conn)
    assert compose_host._status(URL, True) is None
