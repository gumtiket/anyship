"""Service contract and actual offline AI pipeline tests on Windows and POSIX."""
import hashlib
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from dataclasses import replace

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app import ai_analyses, ai_publication
from app.app import create_app
from app.config import Settings
from app.db import AIAnalysis, Base
from tests.test_ai_analyses import AnalysisGitHub, finished
from tests.test_real_workflow import BASE, NAME, ORIGIN, TREE, login


class BranchGitHub(AnalysisGitHub):
    def __init__(self):
        super().__init__()
        self.permissions = {"contents": "write"}  # PR permission is unnecessary.
        self.fail_update = False
        self.lose_update_response = False
        self.race_update = False
        self.collision = False
        self.entries[0]["mode"] = "100755"

    def __call__(self, request):
        path, method = request.url.path, request.method
        if path.endswith("/branches"):
            self.calls.append((method, path, {}))
            return httpx.Response(200, json=[{"name": "main", "commit": {"sha": self.head}},
                {"name": "release/v1", "commit": {"sha": BASE}}])
        if path.endswith("/branches/release/v1"):
            self.calls.append((method, path, {}))
            return httpx.Response(200, json={"name": "release/v1", "commit": {"sha": BASE}})
        if method in ("POST", "PATCH") and "/git/" in path:
            assert request.headers["Authorization"] == "Bearer test-user-token"
            body = json.loads(request.content)
            self.calls.append((method, path, body))
            if path.endswith("/git/refs"):
                branch = body["ref"].removeprefix("refs/heads/")
                assert branch.startswith("anyship/ai-") and body["sha"] == BASE
                if branch in self.refs or self.collision:
                    return httpx.Response(422, json={})
                self.refs[branch] = body["sha"]
                if self.lose_ref_response:
                    self.lose_ref_response = False
                    raise httpx.ReadTimeout("lost create response", request=request)
                return httpx.Response(201, json={"object": {"sha": body["sha"]}})
            if path.endswith("/git/trees"):
                assert body["base_tree"] == TREE
                sha = hashlib.sha1(request.content).hexdigest()
                self.trees[sha] = body["tree"]
                return httpx.Response(201, json={"sha": sha})
            if path.endswith("/git/commits"):
                assert body["parents"] == [BASE]
                sha = hashlib.sha1(request.content).hexdigest()
                self.commits[sha] = {"sha": sha, "tree": {"sha": body["tree"]}, "parents": [{"sha": BASE}]}
                return httpx.Response(201, json={"sha": sha})
            if "/git/refs/heads/" in path:
                assert method == "PATCH" and body["force"] is False
                branch = path.split("/git/refs/heads/")[1]
                if self.fail_update:
                    return httpx.Response(403, json={})
                if self.race_update:
                    self.refs[branch] = "d" * 40
                if self.refs.get(branch) not in (BASE, body["sha"]):
                    return httpx.Response(422, json={})
                self.refs[branch] = body["sha"]
                if self.lose_update_response:
                    self.lose_update_response = False
                    raise httpx.ReadTimeout("lost update response", request=request)
                return httpx.Response(200, json={"object": {"sha": body["sha"]}})
            raise AssertionError((method, path))
        return super().__call__(request)


@pytest.fixture(params=["contract", "pipeline"])
def branch_web(database_url, monkeypatch, request):
    if request.param == "contract":
        from tests.ai_contract_fixture import worker_response
        monkeypatch.setattr(ai_analyses, "run_worker", worker_response)
    remote = BranchGitHub()
    with httpx.Client(transport=httpx.MockTransport(remote)) as transport:
        monkeypatch.setattr(httpx, "request", transport.request)
        settings = Settings(database_url=database_url, token_key=Fernet.generate_key().decode(),
            github_client_id="test", github_client_secret="test", github_app_slug="test", ai_mode="fake")
        app = create_app(settings)
        Base.metadata.create_all(app.state.engine)
        with TestClient(app, base_url=ORIGIN) as client:
            headers = login(client)
            response = client.post("/api/projects", headers=headers,
                json={"repository_url": f"https://github.com/{NAME}", "branch": "main"})
            assert response.status_code == 201
            yield app, client, remote, headers, f"/api/projects/{response.json()['id']}", settings


def start_branch(web, request_id=None, base_branch="release/v1"):
    _, client, _, headers, endpoint, _ = web
    return client.post(endpoint + "/ai-analyses", headers=headers, json={
        "request_id": request_id or str(uuid.uuid4()), "create_branch": True, "base_branch": base_branch})


def action(web, row, suffix, **changes):
    _, client, _, headers, endpoint, _ = web
    return client.post(f"{endpoint}/ai-analyses/{row['id']}/{suffix}", headers=headers,
        json={"review_hash": row["review_hash"], "selected_bundle_ids": ["all-changes"], **changes})


def prepare(web):
    response = start_branch(web)
    assert response.status_code == 202, response.text
    row = finished(web, response.json()["id"])
    assert row["status"] == "completed", row
    assert action(web, row, "review").status_code == 200
    return row


def test_branch_created_before_analysis_pin_selected_branch_and_commit_reviewed_diff(branch_web, monkeypatch):
    _, client, remote, _, endpoint, _ = branch_web
    original = ai_analyses.run_worker
    def check_before_analysis(request, directory):
        assert remote.refs == {request["work_branch"]: BASE}
        return original(request, directory)
    monkeypatch.setattr(ai_analyses, "run_worker", check_before_analysis)
    assert client.get(endpoint + "/branches").status_code == 200
    request_id = str(uuid.uuid4())
    response = start_branch(branch_web, request_id)
    row = finished(branch_web, response.json()["id"])
    assert row["base_branch"] == "release/v1" and row["base_sha"] == BASE and row["branch_created"]
    assert start_branch(branch_web, request_id).json()["id"] == row["id"]
    assert start_branch(branch_web, request_id, "main").status_code == 409
    assert action(branch_web, row, "commit").status_code == 409
    assert action(branch_web, row, "review", review_hash="0" * 64).status_code == 409
    remote.head = "e" * 40  # Original branch may move; the pinned work branch is independent.
    assert action(branch_web, row, "review").status_code == 200
    result = action(branch_web, row, "commit")
    assert result.status_code == 200, result.text
    saved = result.json()
    assert saved["status"] == "published" and saved["commit_sha"] == remote.refs[row["work_branch"]]
    assert remote.head == "e" * 40 and len(remote.refs) == 1
    tree = remote.trees[remote.commits[saved["commit_sha"]]["tree"]["sha"]]
    assert {entry["path"] for entry in tree} == set(row["result"]["bundle"]["paths"])
    modes = {entry["path"]: entry["mode"] for entry in remote.entries}
    assert all(entry["mode"] == modes.get(entry["path"], "100644") for entry in tree)
    assert any(entry["path"] == ".dockerignore" and entry["content"] for entry in tree)
    writes = len(remote.writes)
    assert action(branch_web, row, "commit").json()["commit_sha"] == saved["commit_sha"]
    assert len(remote.writes) == writes and not remote.prs
    assert not any("/deployments" in path or path.endswith("/pulls") for _, path, _ in remote.calls)


@pytest.mark.parametrize("lost", ["lose_ref_response", "lose_update_response"])
def test_ambiguous_remote_response_reconciles_without_duplicate_branch_or_commit(branch_web, lost):
    remote = branch_web[2]
    setattr(remote, lost, True)
    row = prepare(branch_web)
    saved = action(branch_web, row, "commit")
    assert saved.status_code == 200, saved.text
    assert len(remote.refs) == 1
    assert len([p for _, p, _ in remote.writes if p.endswith("/git/commits")]) == 1


def test_failed_publication_reuses_checkpoint_after_app_restart(branch_web):
    app, client, remote, headers, endpoint, settings = branch_web
    row = prepare(branch_web)
    remote.fail_update = True
    assert action(branch_web, row, "commit").status_code == 502
    failed = client.get(f"{endpoint}/ai-analyses/{row['id']}").json()
    assert failed["status"] == "publish_failed" and failed["commit_sha"]
    assert remote.refs[row["work_branch"]] == BASE
    count = len(remote.writes)
    remote.fail_update = False
    with TestClient(create_app(settings), base_url=ORIGIN) as reopened:
        reopened.cookies.update(client.cookies)
        recovered = action((app, reopened, remote, headers, endpoint, settings), row, "commit")
    assert recovered.json()["commit_sha"] == failed["commit_sha"]
    assert len(remote.writes) == count


@pytest.mark.parametrize("when", ["before_review", "before_commit", "during_update", "deleted"])
def test_external_work_branch_change_is_never_overwritten(branch_web, when):
    remote = branch_web[2]
    row = finished(branch_web, start_branch(branch_web).json()["id"])
    if when == "before_review":
        remote.refs[row["work_branch"]] = "d" * 40
        assert action(branch_web, row, "review").status_code == 409
    else:
        assert action(branch_web, row, "review").status_code == 200
        if when == "before_commit":
            remote.refs[row["work_branch"]] = "d" * 40
        elif when == "deleted":
            del remote.refs[row["work_branch"]]
        else:
            remote.race_update = True
        assert action(branch_web, row, "commit").status_code in (409, 502)
    assert remote.refs.get(row["work_branch"]) == (None if when == "deleted" else "d" * 40)
    assert remote.head == BASE


def test_expired_publication_cannot_update_ref_and_can_retry(branch_web, monkeypatch):
    app, _, remote, _, _, _ = branch_web
    row = prepare(branch_web)
    original = ai_publication.changes_tree
    def expire(*args):
        entries = original(*args)
        with app.state.sessions() as session:
            session.get(AIAnalysis, row["id"]).lease_until = 0
            session.commit()
        return entries
    monkeypatch.setattr(ai_publication, "changes_tree", expire)
    assert action(branch_web, row, "commit").status_code == 409
    assert not any(method == "PATCH" for method, _, _ in remote.calls)
    assert remote.refs[row["work_branch"]] == BASE
    monkeypatch.setattr(ai_publication, "changes_tree", original)
    assert action(branch_web, row, "commit").json()["status"] == "published"


def test_collision_and_revoked_permissions_never_run_ai_or_write_commit(branch_web, monkeypatch):
    remote = branch_web[2]
    def forbidden(*args):
        pytest.fail("AI must not run after branch failure")
    monkeypatch.setattr(ai_analyses, "run_worker", forbidden)
    remote.collision = True
    row = finished(branch_web, start_branch(branch_web).json()["id"])
    assert row["status"] == "failed" and not row["branch_created"] and not remote.refs
    remote.permissions["contents"] = "read"
    assert start_branch(branch_web).status_code == 403


def test_commit_requires_csrf_ownership_and_untampered_review(branch_web):
    app, client, remote, _, endpoint, settings = branch_web
    row = prepare(branch_web)
    path = f"{endpoint}/ai-analyses/{row['id']}/commit"
    body = {"review_hash": row["review_hash"], "selected_bundle_ids": ["all-changes"]}
    assert client.post(path, json=body).status_code == 403
    remote.user_id = 22
    with TestClient(create_app(settings), base_url=ORIGIN) as other:
        headers = login(other)
        assert other.post(path, headers=headers, json=body).status_code == 404
    remote.user_id = 1
    with app.state.sessions() as session:
        session.get(AIAnalysis, row["id"]).work_branch = "main"
        session.commit()
    assert action(branch_web, row, "commit").status_code == 409
    assert remote.head == BASE and not any(method == "PATCH" for method, _, _ in remote.calls)


def test_bedrock_worker_inherits_only_provider_configuration(tmp_path, monkeypatch):
    for key in ("APP_DATABASE_URL", "APP_GITHUB_CLIENT_SECRET", "GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(key, "fixture-secret")
    monkeypatch.setenv("BEDROCK_REGION", "us-east-1")
    def run(args, **kwargs):
        env = kwargs["env"]
        assert env["AWS_SECRET_ACCESS_KEY"] == "fixture-secret" and env["BEDROCK_REGION"] == "us-east-1"
        assert not any(key in env for key in ("APP_DATABASE_URL", "APP_GITHUB_CLIENT_SECRET", "GITHUB_TOKEN"))
        assert kwargs["timeout"] < ai_analyses.LEASE_SECONDS
        from pathlib import Path
        Path(args[-1]).write_text(json.dumps({"result": {"base_sha": BASE, "llm_mode": "bedrock",
            "gate": {"status": "skipped", "pr_eligible": False}}, "diff": ""}))
        return type("Completed", (), {"returncode": 0})()
    monkeypatch.setattr(ai_analyses.subprocess, "run", run)
    assert ai_analyses.run_worker({"base_sha": BASE, "provider": "bedrock"}, tmp_path)["result"]["llm_mode"] == "bedrock"


def test_bedrock_missing_configuration_does_not_create_branch(branch_web, monkeypatch):
    app, client, remote, headers, endpoint, settings = branch_web
    for key in ("BEDROCK_REGION", "BEDROCK_MODEL_ID_STRONG", "BEDROCK_MODEL_ID_FAST"):
        monkeypatch.delenv(key, raising=False)
    with TestClient(create_app(replace(settings, ai_mode="bedrock")), base_url=ORIGIN) as other:
        other.cookies.update(client.cookies)
        assert not other.get("/api/config").json()["ai_available"]
        assert start_branch((app, other, remote, headers, endpoint, settings)).status_code == 503
    assert not remote.writes


@pytest.mark.parametrize("with_candidate", [False, True])
def test_bedrock_provider_uses_ai_pipeline_without_container_gate(tmp_path, monkeypatch, with_candidate):
    import ai
    from ai.llm.fake import FakeLLMClient, recommendation_response
    from app.ai_worker import analyze
    from app.ai_snapshot import git_blob_sha
    from tests.test_ai_analyses import SAMPLE
    source = tmp_path / "source"
    source.mkdir()
    manifest = {}
    for path in SAMPLE.rglob("*"):
        if path.is_file() and path.suffix in (".py", ".txt"):
            name = path.relative_to(SAMPLE).as_posix()
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
            manifest[name] = git_blob_sha(path.read_bytes())
    calls = []
    candidates = [{"factor": 2, "file": "app/main.py", "line": 1,
        "evidence": (source / "app/main.py").read_text(encoding="utf-8").splitlines()[0],
        "description": "AI가 제안한 검토 후보"}] if with_candidate else []
    def client(**kwargs):
        calls.append(kwargs)
        return FakeLLMClient({"diagnose": [json.dumps({"explanations": [], "candidates": candidates})],
            "recommend": [recommendation_response], "transform": ['{"diff":"","violation_ids":[]}']})
    monkeypatch.setattr("ai.llm.bedrock.BedrockClient", client)
    original = ai.run_analysis
    def run(*args, **kwargs):
        assert kwargs["no_gate"] is True
        assert kwargs["llm"] is kwargs["decision_llm"]
        return original(*args, **kwargs)
    monkeypatch.setattr(ai, "run_analysis", run)
    result = analyze({"provider": "bedrock", "source": str(source), "manifest": manifest,
        "output": str(tmp_path / "out"), "repository": NAME, "base_sha": BASE,
        "app_name": "app-test", "work_branch": "anyship/ai-test"})
    assert calls and result["result"]["llm_mode"] == "bedrock"
    assert result["result"]["gate"]["status"] == "skipped" and result["diff"]
    diagnosis = result["result"]["diagnosis"]
    assert len(diagnosis["review_candidates"]) == len(candidates)
    candidate_ids = {item["id"] for item in diagnosis["review_candidates"]}
    assert candidate_ids.isdisjoint(item["id"] for item in diagnosis["violations"])
    transformation = result["result"]["transformation"]
    assert candidate_ids.isdisjoint(transformation["addressed_ids"] + transformation["deferred_ids"])


def test_publish_blocks_duplicate_commit_new_analysis_and_deletion(branch_web, monkeypatch):
    _, client, remote, headers, endpoint, _ = branch_web
    row = prepare(branch_web)
    entered, release = Event(), Event()
    original = ai_publication.changes_tree
    def held(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)
    monkeypatch.setattr(ai_publication, "changes_tree", held)
    with ThreadPoolExecutor(max_workers=1) as executor:
        request = executor.submit(action, branch_web, row, "commit")
        try:
            assert entered.wait(5)
            assert action(branch_web, row, "commit").status_code == 409
            assert start_branch(branch_web).status_code == 409
            assert client.delete(endpoint, headers=headers).status_code == 409
        finally:
            release.set()
        assert request.result(timeout=10).status_code == 200
    assert len([p for _, p, _ in remote.writes if p.endswith("/git/commits")]) == 1


def test_unavailable_analysis_runtime_blocks_new_branches_but_allows_saved_review_and_commit(branch_web, monkeypatch):
    _, client, remote, _, endpoint, _ = branch_web
    row = finished(branch_web, start_branch(branch_web).json()["id"])
    monkeypatch.setattr("app.config.find_spec", lambda name: None)
    config = client.get("/api/config").json()
    assert not config["ai_analysis_available"] and config["ai_runtime_issue"]
    count = len(remote.writes)
    assert start_branch(branch_web).status_code == 503
    assert len(remote.writes) == count
    assert client.get(f"{endpoint}/ai-analyses/{row['id']}").status_code == 200
    assert action(branch_web, row, "review").status_code == 200
    assert action(branch_web, row, "commit").json()["status"] == "published"
