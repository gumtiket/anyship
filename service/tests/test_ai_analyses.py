"""Real fake-AI pipeline with GitHub HTTP fixtures and isolated database only."""
import base64
import json
import time
import uuid
from dataclasses import replace
from pathlib import Path
from threading import Event

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import ai_analyses
from app.ai_snapshot import SnapshotError, git_blob_sha, snapshot
from app.app import create_app
from app.config import Settings
from app.db import AIAnalysis, Base
from app.github_api import GitHubAPI, GitHubFailure
from tests.test_real_workflow import BASE, NAME, ORIGIN, TREE, GitHubHTTP, login

SAMPLE = Path(__file__).resolve().parents[2] / "AI/samples/todo"


class AnalysisGitHub(GitHubHTTP):
    def __init__(self, files=None):
        super().__init__()
        self.files = files if files is not None else {
            p.relative_to(SAMPLE).as_posix(): p.read_bytes()
            for p in SAMPLE.rglob("*") if p.is_file() and p.suffix in (".py", ".txt")
        }
        self.entries = [{"path": name, "type": "blob", "mode": "100644", "sha": git_blob_sha(data), "size": len(data)}
                        for name, data in self.files.items()]
        self.blobs = {git_blob_sha(data): data for data in self.files.values()}
        self.corrupt_blob = False
        self.truncated = False

    def __call__(self, request):
        path = request.url.path
        if request.method == "GET" and ("/git/trees/" in path or "/git/blobs/" in path):
            assert request.url.host == "api.github.com"
            assert request.headers["Authorization"] == "Bearer test-user-token"
            self.calls.append(("GET", path, {}))
            if "/git/trees/" in path:
                assert request.url.params["recursive"] == "1"
                return httpx.Response(200, json={"sha": TREE, "tree": self.entries, "truncated": self.truncated})
            sha = path.rsplit("/", 1)[1]
            data = self.blobs[sha]
            return httpx.Response(200, json={"sha": sha, "size": len(data), "encoding": "base64",
                "content": base64.b64encode(b"corrupt" if self.corrupt_blob else data).decode()})
        return super().__call__(request)


@pytest.fixture
def fake_web(database_url, monkeypatch):
    remote = AnalysisGitHub()
    with httpx.Client(transport=httpx.MockTransport(remote)) as transport:
        monkeypatch.setattr(httpx, "request", transport.request)
        settings = Settings(database_url=database_url, token_key=Fernet.generate_key().decode(),
            github_client_id="test", github_client_secret="test", github_app_slug="test", ai_mode="fake")
        app = create_app(settings)
        Base.metadata.create_all(app.state.engine)
        with TestClient(app, base_url=ORIGIN) as client:
            headers = login(client)
            response = client.post("/api/projects", headers=headers, json={"repository_url": f"https://github.com/{NAME}", "branch": "main"})
            assert response.status_code == 201
            endpoint = f"/api/projects/{response.json()['id']}"
            yield app, client, remote, headers, endpoint, settings


def start(web, request_id=None):
    _, client, _, headers, endpoint, _ = web
    return client.post(endpoint + "/ai-analyses", headers=headers, json={"request_id": request_id or str(uuid.uuid4())})


def finished(web, identifier):
    _, client, _, _, endpoint, _ = web
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        response = client.get(f"{endpoint}/ai-analyses/{identifier}")
        assert response.status_code == 200
        row = response.json()
        if not row["busy"]:
            return row
        time.sleep(0.05)
    pytest.fail("analysis did not finish")


def test_real_fake_pipeline_snapshot_review_history_and_no_remote_writes(fake_web):
    app, client, remote, headers, endpoint, settings = fake_web
    identifier = str(uuid.uuid4())
    response = start(fake_web, identifier)
    assert response.status_code == 202
    row = finished(fake_web, response.json()["id"])
    assert row["status"] == "completed", row
    result = row["result"]
    assert result["analysis_status"] == "diagnosed" and result["llm_mode"] == "fake"
    assert result["gate"]["status"] == "skipped" and result["gate"]["pr_eligible"] is False
    assert result["cost"]["total"]["input_tokens"] == result["cost"]["total"]["output_tokens"] == 0
    assert result["transformation"]["needs_approval"] is True
    assert "data_migration_unsupported" in {w["code"] for w in result["diagnosis"]["warnings"]}
    assert ".dockerignore" in result["bundle"]["paths"] and len(result["bundle"]["paths"]) > 1
    assert row["base_sha"] == BASE and len(row["source_digest"]) == 64
    serialized = json.dumps(row)
    assert "build_context" not in result and "output_files" not in result
    assert "test-user-token" not in serialized and "anyship-ai-" not in serialized
    assert start(fake_web, identifier).json()["id"] == row["id"]
    review_path = f"{endpoint}/ai-analyses/{row['id']}/review"
    body = {"review_hash": row["review_hash"], "selected_bundle_ids": ["all-changes"]}
    assert client.post(review_path, headers=headers, json={**body, "selected_bundle_ids": []}).status_code == 422
    assert client.post(review_path, headers=headers, json={**body, "review_hash": "0" * 64}).status_code == 409
    assert client.post(review_path, headers=headers, json=body).json()["status"] == "reviewed"
    assert client.post(review_path, headers=headers, json=body).json()["status"] == "reviewed"
    assert client.post(endpoint + "/changes/pr", headers=headers, json={"review_hash": row["review_hash"]}).status_code == 503
    assert not remote.writes
    # A fresh app process can read the stored result without re-running AI.
    with TestClient(create_app(replace(settings, ai_mode="unavailable")), base_url=ORIGIN) as reopened:
        reopened.cookies.update(client.cookies)
        assert reopened.get(f"{endpoint}/ai-analyses/{row['id']}").json()["status"] == "reviewed"
    remote.head = "c" * 40
    assert client.post(review_path, headers=headers, json=body).status_code == 409
    remote.head = BASE
    with app.state.sessions() as session:
        saved = session.get(AIAnalysis, row["id"])
        saved.diff += "tampered"
        session.commit()
    assert client.post(review_path, headers=headers, json=body).status_code == 409
    assert client.delete(endpoint, headers=headers).status_code == 204
    with app.state.sessions() as session:
        assert session.get(AIAnalysis, row["id"]) is None


def test_source_failure_persists_and_retry_uses_new_job(fake_web):
    _, _, remote, _, _, _ = fake_web
    remote.corrupt_blob = True
    first = start(fake_web).json()
    row = finished(fake_web, first["id"])
    assert row["status"] == "failed" and row["result"] == {} and not row["review_hash"]
    remote.corrupt_blob = False
    second = start(fake_web)
    assert second.status_code == 202 and second.json()["id"] != first["id"]
    assert finished(fake_web, second.json()["id"])["status"] == "completed"


def test_auth_ownership_and_csrf(fake_web):
    _, client, remote, headers, endpoint, settings = fake_web
    assert client.post(endpoint + "/ai-analyses", json={"request_id": str(uuid.uuid4())}).status_code == 403
    row = finished(fake_web, start(fake_web).json()["id"])
    remote.user_id = 22
    with TestClient(create_app(settings), base_url=ORIGIN) as other:
        assert other.get(endpoint + "/ai-analyses").status_code == 401
        other_headers = login(other)
        assert other.get(endpoint + "/ai-analyses").status_code == 404
        assert other.get(f"{endpoint}/ai-analyses/{row['id']}").status_code == 404
        assert other.post(f"{endpoint}/ai-analyses/{row['id']}/review", headers=other_headers,
            json={"review_hash": row["review_hash"], "selected_bundle_ids": ["all-changes"]}).status_code == 404
    remote.user_id = 1
    remote.revoked = True
    assert start(fake_web).status_code == 404
    assert not remote.writes


def test_busy_job_blocks_duplicates_deletion_and_expires_without_late_success(fake_web, monkeypatch):
    app, client, _, headers, endpoint, _ = fake_web
    entered, release = Event(), Event()
    original = ai_analyses.run_worker
    def held(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)
    monkeypatch.setattr(ai_analyses, "run_worker", held)
    try:
        row = start(fake_web).json()
        assert entered.wait(5)
        assert start(fake_web).status_code == 409
        assert client.delete(endpoint, headers=headers).status_code == 409
        with app.state.sessions() as session:
            session.get(AIAnalysis, row["id"]).lease_until = 0
            session.commit()
        assert client.get(f"{endpoint}/ai-analyses/{row['id']}").json()["status"] == "interrupted"
    finally:
        release.set()
    app.state.ai_runner.executor.shutdown(wait=True)
    assert client.get(f"{endpoint}/ai-analyses/{row['id']}").json()["status"] == "interrupted"


def test_unsupported_app_has_no_selectable_bundle(fake_web):
    _, _, remote, _, _, _ = fake_web
    unsupported = AnalysisGitHub({"Main.java": b"class Main {}\n"})
    remote.entries, remote.blobs = unsupported.entries, unsupported.blobs
    row = finished(fake_web, start(fake_web).json()["id"])
    assert row["status"] == "completed" and row["result"]["analysis_status"] == "unsupported"
    assert not row["review_hash"] and not row["diff"]


@pytest.mark.parametrize("path", ["../escape.py", "/root.py", "C:/bad.py", "dir\\bad.py", "CON.py", "dir./bad.py", ".git/../bad.py"])
def test_snapshot_rejects_unsafe_paths(path, tmp_path):
    remote = AnalysisGitHub({path: b"pass\n"})
    with httpx.Client(transport=httpx.MockTransport(remote)) as transport:
        gateway = GitHubAPI()
        gateway._request = lambda method, url, **kwargs: transport.request(method, url, **kwargs).json()
        with pytest.raises(SnapshotError, match="invalid_source_path"):
            snapshot(gateway, "test-user-token", NAME, BASE, tmp_path / "source")
    assert not (tmp_path / "source").exists()


def test_snapshot_excludes_sensitive_binary_and_verifies_blob_bytes(tmp_path):
    files = {"main.py": b"x = 1\r\n", ".env": b"TOKEN=never-copy", "key.pem": b"never-copy", "image.png": b"\x00binary"}
    remote = AnalysisGitHub(files)
    with httpx.Client(transport=httpx.MockTransport(remote)) as transport:
        gateway = GitHubAPI()
        gateway._request = lambda method, url, **kwargs: transport.request(method, url, **kwargs).json()
        tree, manifest, excluded = snapshot(gateway, "test-user-token", NAME, BASE, tmp_path / "source")
    assert tree == TREE and manifest == {"main.py": git_blob_sha(files["main.py"])} and excluded == 3
    assert (tmp_path / "source/main.py").read_bytes() == files["main.py"]
    assert len(list((tmp_path / "source").iterdir())) == 1


@pytest.mark.parametrize("case,reason", [
    ("file_size", "source_file_limit"),
    ("file_count", "source_size_limit"),
    ("total_size", "source_size_limit"),
    ("file_case", "case_colliding_paths"),
    ("parent_case", "case_colliding_paths"),
    ("truncated", None),
])
def test_snapshot_rejects_incomplete_or_oversized_tree_before_reading_blobs(tmp_path, case, reason):
    remote = AnalysisGitHub({"main.py": b"pass\n"})
    entry = remote.entries[0]
    if case == "file_size":
        entry["size"] = 524289
    elif case == "file_count":
        remote.entries = [{**entry, "path": f"file{i}.py"} for i in range(201)]
    elif case == "total_size":
        remote.entries = [{**entry, "path": f"file{i}.py", "size": 524288} for i in range(11)]
    elif case in ("file_case", "parent_case"):
        names = ["main.py", "MAIN.py"] if case == "file_case" else ["src/main.py", "SRC/other.py"]
        remote.entries = [{**entry, "path": name} for name in names]
    else:
        remote.truncated = True
    with httpx.Client(transport=httpx.MockTransport(remote)) as transport:
        gateway = GitHubAPI()
        gateway._request = lambda method, url, **kwargs: transport.request(method, url, **kwargs).json()
        with pytest.raises(GitHubFailure if case == "truncated" else SnapshotError, match=reason):
            snapshot(gateway, "test-user-token", NAME, BASE, tmp_path / "source")
    assert not (tmp_path / "source").exists()
    assert not any("/git/blobs/" in path for _, path, _ in remote.calls)


@pytest.mark.parametrize("mode,kind", [("120000", "blob"), ("160000", "commit")])
def test_snapshot_rejects_links_and_submodules(tmp_path, mode, kind):
    remote = AnalysisGitHub({"main.py": b"pass\n"})
    remote.entries[0].update(mode=mode, type=kind)
    with httpx.Client(transport=httpx.MockTransport(remote)) as transport:
        gateway = GitHubAPI()
        gateway._request = lambda method, url, **kwargs: transport.request(method, url, **kwargs).json()
        with pytest.raises(SnapshotError, match="unsupported_source_entry"):
            snapshot(gateway, "test-user-token", NAME, BASE, tmp_path / "source")


def test_worker_does_not_inherit_service_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATABASE_URL", "secret-db")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "secret-cloud")
    monkeypatch.setenv("GITHUB_TOKEN", "secret-token")
    def run(args, **kwargs):
        env = kwargs["env"]
        assert not any(key in env for key in ("APP_DATABASE_URL", "AWS_ACCESS_KEY_ID", "GITHUB_TOKEN"))
        assert kwargs["cwd"] != tmp_path
        Path(args[-1]).write_text(json.dumps({"result": {"base_sha": BASE, "llm_mode": "fake", "gate": {"status": "skipped", "pr_eligible": False}}, "diff": ""}))
        return type("Completed", (), {"returncode": 0})()
    monkeypatch.setattr(ai_analyses.subprocess, "run", run)
    ai_analyses.run_worker({"base_sha": BASE}, tmp_path)


def test_production_rejects_fake():
    with pytest.raises(ValueError, match="only available in development"):
        Settings(ai_mode="fake", production=True)


def test_runner_can_start_after_clean_shutdown():
    runner = ai_analyses.AnalysisRunner(None, None)
    runner.start()
    first = runner.executor
    runner.close()
    assert runner.executor is None
    runner.start()
    try:
        assert runner.executor is not first
        assert runner.executor.submit(lambda: "ready").result(timeout=2) == "ready"
    finally:
        runner.close()
