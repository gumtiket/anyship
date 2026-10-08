"""Exercise Service APIs with real auth/session handling and a fake AWS adapter."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
import threading
import time
from urllib.parse import parse_qs, urlsplit
import uuid

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select, update

from app.app import create_app
from app.aws_adapter import AwsCheckError, AwsIdentity
from app.config import Settings
from app.db import AwsEnvironment, Base, LoginSession, Membership
from tests.test_web import FakeGitHub, ORIGIN, oauth_start

ENDPOINT = "/api/aws/environments"
ROLE = "arn:aws:iam::123456789012:role/deploy-service-role"
SERVICE_ROLE = "arn:aws:iam::999999999999:role/service-server"
TEMPLATE = "https://example.s3.ap-northeast-2.amazonaws.com/onboarding.yaml?versionId=one+two&x=1"


class FakeAWS:
    def __init__(self):
        self.calls = []
        self.error = None
        self.account_id = "123456789012"
        self.hook = lambda: None

    def check(self, **values):
        self.calls.append(values)
        self.hook()
        if self.error:
            raise self.error
        return AwsIdentity(self.account_id)


def authenticate(client):
    state = oauth_start(client)
    client.get("/api/auth/github/callback", params={"state": state, "code": "code"})
    return {"Origin": ORIGIN, "X-CSRF-Token": client.get("/api/me").json()["csrf_token"]}


@pytest.fixture
def aws_web(database_url):
    settings = Settings(database_url=database_url, token_key=Fernet.generate_key().decode(),
                        github_client_id="test", github_client_secret="test", github_app_slug="test",
                        aws_template_url=TEMPLATE, aws_service_role_arn=SERVICE_ROLE,
                        aws_regions=("ap-northeast-2", "us-east-1"))
    adapter = FakeAWS()
    app = create_app(settings, FakeGitHub(), aws_adapter=adapter)
    Base.metadata.create_all(app.state.engine)
    with TestClient(app, base_url=ORIGIN) as client:
        yield app, client, adapter, authenticate(client), settings


def create(client, headers, **changes):
    return client.post(ENDPOINT, headers=headers,
                       json={"request_id": str(uuid.uuid4()), "name": "운영 AWS", "region": "ap-northeast-2", **changes})


def verify(client, headers, identifier, role=ROLE, **changes):
    return client.post(f"{ENDPOINT}/{identifier}/verify", headers=headers, json={"role_arn": role, **changes})


def test_url_creation_retries_and_configuration_snapshot(aws_web):
    app, client, adapter, headers, settings = aws_web
    request_id = str(uuid.uuid4())
    response = create(client, headers, request_id=request_id)
    assert response.status_code == 201
    row = response.json()
    assert row["status"] == "PENDING" and row["role_arn"] is None
    parsed = urlsplit(row["cloudformation_url"])
    assert parsed.hostname == "ap-northeast-2.console.aws.amazon.com"
    params = parse_qs(parsed.fragment.split("?", 1)[1])
    assert params["templateURL"] == [TEMPLATE]
    assert params["param_ServiceRoleArn"] == [SERVICE_ROLE]
    assert params["param_RoleName"] == ["deploy-service-role"]
    assert params["stackName"] == [row["stack_name"]]
    with app.state.sessions() as session:
        stored = session.get(AwsEnvironment, row["id"])
        assert params["param_ExternalId"] == [stored.external_id]
        assert len(stored.external_id) == 64
    repeated = create(client, headers, request_id=request_id)
    assert repeated.status_code == 200 and repeated.json() == row
    assert create(client, headers, request_id=request_id, region="us-east-1").status_code == 409
    another = create(client, headers).json()
    assert another["stack_name"] != row["stack_name"]
    assert another["cloudformation_url"] != row["cloudformation_url"]
    assert not adapter.calls
    assert len(client.get(ENDPOINT).json()) == 2
    assert len(client.get(ENDPOINT + "?limit=1&offset=1").json()) == 1
    assert client.get("/api/config").json()["aws_regions"] == list(settings.aws_regions)
    # A restart/settings update must not rotate an already-issued trust contract.
    restarted = create_app(replace(settings, aws_template_url=TEMPLATE + "2"), FakeGitHub(), aws_adapter=adapter)
    with TestClient(restarted, base_url=ORIGIN) as returning:
        returning.cookies.update(client.cookies)
        assert returning.get(ENDPOINT + "/" + row["id"]).json() == row


def test_verified_persistence_idempotence_and_relogin(aws_web):
    app, client, adapter, headers, _ = aws_web
    row = create(client, headers).json()
    with app.state.sessions() as session:
        external_id = session.get(AwsEnvironment, row["id"]).external_id
    response = verify(client, headers, row["id"])
    assert response.status_code == 200
    saved = response.json()
    assert saved["status"] == "CONNECTED"
    assert saved["role_arn"] == ROLE and saved["aws_account_id"] == "123456789012"
    assert saved["verified_at"] and saved["cloudformation_url"] is None
    assert adapter.calls == [{"role_arn": ROLE, "external_id": external_id, "region": "ap-northeast-2"}]
    assert verify(client, headers, row["id"]).json() == saved and len(adapter.calls) == 1
    assert verify(client, headers, row["id"], ROLE + "other").status_code == 409
    client.post("/api/auth/logout", headers=headers)
    authenticate(client)
    assert client.get(ENDPOINT + "/" + row["id"]).json() == saved
    with app.state.sessions() as session:
        stored = session.get(AwsEnvironment, row["id"])
        assert stored.external_id == external_id and stored.verification_token == ""


def test_access_control_and_client_cannot_override_server_values(aws_web):
    app, client, adapter, headers, settings = aws_web
    row = create(client, headers).json()
    assert create(client, {}).status_code == 403
    assert verify(client, {}, row["id"]).status_code == 403
    assert verify(client, {**headers, "Origin": "https://elsewhere.invalid"}, row["id"]).status_code == 403
    assert create(client, headers, external_id="forged").status_code == 422
    assert verify(client, headers, row["id"], external_id="forged").status_code == 422
    other_gateway = FakeGitHub()
    other_gateway.profile = lambda token: {"id": 43, "login": "other", "name": "Other"}
    other_app = create_app(settings, other_gateway, aws_adapter=adapter)
    with TestClient(other_app, base_url=ORIGIN) as other:
        assert other.get(ENDPOINT).status_code == 401
        other_headers = authenticate(other)
        assert other.get(ENDPOINT).json() == []
        assert other.get(ENDPOINT + "/" + row["id"]).status_code == 404
        assert verify(other, other_headers, row["id"]).status_code == 404
        # Membership in the same workspace still does not grant access to another user's request.
        with app.state.sessions() as session:
            original = session.get(AwsEnvironment, row["id"])
            other_login = session.scalar(select(LoginSession).where(LoginSession.csrf == other_headers["X-CSRF-Token"]))
            session.add(Membership(user_id=other_login.user_id, workspace_id=original.workspace_id, role="owner"))
            other_login.workspace_id = original.workspace_id
            session.commit()
        assert other.get(ENDPOINT).json() == []
        assert verify(other, other_headers, row["id"]).status_code == 404
    assert not adapter.calls


@pytest.mark.parametrize("role", ["bad", "arn:aws:iam::123456789012:user/name",
    "arn:aws:sts::123456789012:assumed-role/name/session", "arn:aws-cn:iam::123456789012:role/name"])
def test_invalid_roles_never_reach_aws(aws_web, role):
    _, client, adapter, headers, _ = aws_web
    row = create(client, headers).json()
    assert verify(client, headers, row["id"], role).status_code == 422
    assert not adapter.calls


@pytest.mark.parametrize("error", [AwsCheckError("access_denied"), AwsCheckError("external_id_not_required"),
                                  RuntimeError("SECRET-ACCESS-KEY SESSION-TOKEN")])
def test_failure_is_safe_and_can_retry(aws_web, error, caplog):
    app, client, adapter, headers, _ = aws_web
    row = create(client, headers).json()
    adapter.error = error
    response = verify(client, headers, row["id"])
    assert response.status_code in (403, 422, 503)
    assert "SECRET-ACCESS-KEY" not in response.text + caplog.text
    failed = client.get(ENDPOINT + "/" + row["id"]).json()
    assert failed["status"] == "FAILED" and failed["role_arn"] is None and failed["retryable"]
    assert failed["cloudformation_url"] == row["cloudformation_url"]
    with app.state.sessions() as session:
        assert session.get(AwsEnvironment, row["id"]).aws_account_id is None
    adapter.error = None
    assert verify(client, headers, row["id"]).status_code == 200


def test_expiry_and_account_mismatch_do_not_connect(aws_web):
    app, client, adapter, headers, _ = aws_web
    row = create(client, headers).json()
    adapter.account_id = "000000000000"
    assert verify(client, headers, row["id"]).json()["detail"]["code"] == "account_mismatch"
    with app.state.sessions() as session:
        session.get(AwsEnvironment, row["id"]).expires_at = int(time.time()) - 1
        session.commit()
    expired = client.get(ENDPOINT + "/" + row["id"]).json()
    assert expired["status"] == "EXPIRED" and expired["cloudformation_url"] is None
    assert verify(client, headers, row["id"]).status_code == 410
    assert len(adapter.calls) == 1


@pytest.mark.parametrize("error", [None, AwsCheckError("access_denied")])
def test_lease_recovery_and_late_result_cannot_overwrite_new_attempt(aws_web, error):
    app, client, adapter, headers, _ = aws_web
    row = create(client, headers).json()
    with app.state.sessions() as session:
        stored = session.get(AwsEnvironment, row["id"])
        stored.status, stored.lease_until, stored.verification_token = "VERIFYING", int(time.time()) - 1, "old"
        session.commit()
    assert client.get(ENDPOINT + "/" + row["id"]).json()["error_code"] == "verification_interrupted"
    def supersede():
        with app.state.sessions() as session:
            session.execute(update(AwsEnvironment).where(AwsEnvironment.id == row["id"]).values(verification_token="new"))
            session.commit()
    adapter.hook = supersede
    adapter.error = error
    response = verify(client, headers, row["id"])
    assert response.status_code == 409 and response.json()["detail"]["code"] == "verification_superseded"
    with app.state.sessions() as session:
        stored = session.get(AwsEnvironment, row["id"])
        assert stored.role_arn is None and stored.verification_token == "new"


def test_concurrent_verification_calls_adapter_once(aws_web):
    app, client, adapter, headers, _ = aws_web
    row = create(client, headers).json()
    entered, release = threading.Event(), threading.Event()
    def block():
        entered.set()
        assert release.wait(10)
    adapter.hook = block
    with TestClient(app, base_url=ORIGIN) as second, ThreadPoolExecutor(max_workers=1) as pool:
        second.cookies.update(client.cookies)
        first = pool.submit(verify, client, headers, row["id"])
        try:
            assert entered.wait(10)
            assert second.get(ENDPOINT + "/" + row["id"]).json()["status"] == "VERIFYING"
            assert verify(second, headers, row["id"]).status_code == 409
        finally:
            release.set()
        assert first.result(timeout=10).status_code == 200
    assert len(adapter.calls) == 1


def test_same_verified_role_cannot_be_registered_twice(aws_web):
    app, client, _, headers, _ = aws_web
    first = create(client, headers).json()
    second = create(client, headers).json()
    assert verify(client, headers, first["id"]).status_code == 200
    response = verify(client, headers, second["id"])
    assert response.status_code == 409 and response.json()["detail"]["code"] == "role_already_registered"
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(AwsEnvironment).where(AwsEnvironment.status == "CONNECTED")) == 1
        assert session.get(AwsEnvironment, second["id"]).role_arn is None


def test_configuration_missing_changed_and_unsupported_regions(aws_web):
    _, client, adapter, headers, settings = aws_web
    assert create(client, headers, region="eu-west-1").status_code == 422
    assert create(client, headers, name="  ").status_code == 422
    row = create(client, headers).json()
    for configured, code in ((replace(settings, aws_template_url=""), "aws_not_configured"),
                             (replace(settings, aws_service_role_arn=SERVICE_ROLE + "new"), "configuration_changed")):
        other_app = create_app(configured, FakeGitHub(), aws_adapter=adapter)
        with TestClient(other_app, base_url=ORIGIN) as other:
            other.cookies.update(client.cookies)
            assert verify(other, headers, row["id"]).json()["detail"]["code"] == code
            if code == "aws_not_configured":
                assert create(other, headers).status_code == 503
                assert not other.get("/api/config").json()["aws_available"]
    assert not adapter.calls


@pytest.mark.parametrize("error", [None, AwsCheckError("access_denied")])
def test_request_expiring_during_validation_is_not_saved(aws_web, monkeypatch, error):
    from app import aws_onboarding
    _, client, adapter, headers, _ = aws_web
    row = create(client, headers).json()
    adapter.hook = lambda: monkeypatch.setattr(aws_onboarding, "time", SimpleNamespace(time=lambda: row["expires_at"]))
    adapter.error = error
    response = verify(client, headers, row["id"])
    assert response.status_code == 410 and not response.json()["detail"]["retryable"]
    expired = client.get(ENDPOINT + "/" + row["id"]).json()
    assert expired["role_arn"] is None and expired["status"] == "EXPIRED"


def test_unique_role_name_option_and_demo_registration_disabled(aws_web):
    _, client, adapter, headers, settings = aws_web
    app = create_app(replace(settings, aws_role_name="deploy-service-role-{id}"), FakeGitHub(), aws_adapter=adapter)
    with TestClient(app, base_url=ORIGIN) as alternate:
        alternate.cookies.update(client.cookies)
        row = create(alternate, headers).json()
        assert row["role_name"] == "deploy-service-role-" + uuid.UUID(row["id"]).hex
    demo = create_app(replace(settings, demo=True), aws_adapter=adapter)
    with TestClient(demo, base_url=ORIGIN) as browser:
        browser.post("/api/auth/demo", headers={"Origin": ORIGIN})
        csrf = browser.get("/api/me").json()["csrf_token"]
        assert create(browser, {"Origin": ORIGIN, "X-CSRF-Token": csrf}).status_code == 503
    assert not adapter.calls


def test_concurrent_create_returns_one_request_and_external_id(aws_web):
    app, client, _, headers, _ = aws_web
    request_id = str(uuid.uuid4())
    gate = threading.Barrier(2)
    def start(browser):
        gate.wait(timeout=10)
        return create(browser, headers, request_id=request_id)
    with TestClient(app, base_url=ORIGIN) as second, ThreadPoolExecutor(max_workers=2) as pool:
        second.cookies.update(client.cookies)
        first, another = pool.submit(start, client), pool.submit(start, second)
        results = [first.result(timeout=15), another.result(timeout=15)]
    assert sorted(result.status_code for result in results) == [200, 201]
    assert results[0].json() == results[1].json()
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(AwsEnvironment)) == 1
