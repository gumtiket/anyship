"""Manual browser QA harness. Only fake GitHub HTTP; separate temporary DB/port.

Run from service: python -m tests.browser_fixture
Open http://127.0.0.1:8001/_test_only/login. Never used by app.main or launch scripts.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlencode, parse_qs, urlsplit
import json
import sys
from html import escape

import httpx
import uvicorn
from cryptography.fernet import Fernet
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.testclient import TestClient

from app.app import create_app
from app.config import Settings
from app.db import Base
from .test_real_workflow import GitHubHTTP, login
from .test_ai_analyses import AnalysisGitHub


def main():
    with TemporaryDirectory(prefix="anyship-browser-test-") as directory:
        fake_ai = "--ai" in sys.argv
        fixture = AnalysisGitHub() if fake_ai else GitHubHTTP()
        onboarding = "--onboarding" in sys.argv
        mock = "--mock" in sys.argv
        fixture.repo_selected = not onboarding
        with httpx.Client(transport=httpx.MockTransport(fixture)) as remote:
            # Every outgoing request is intercepted; unknown routes fail closed.
            httpx.request = remote.request
            app = create_app(Settings(
                app_origin="http://127.0.0.1:8001", database_url=f"sqlite:///{Path(directory) / 'test.db'}",
                token_key=Fernet.generate_key().decode(), github_client_id="fixture",
                github_client_secret="fixture", github_app_slug="fixture", ai_mode="fake" if fake_ai else "placeholder",
                deployment_mode="mock" if mock else "unavailable", mock_step_delay=0.15,
            ))
            Base.metadata.create_all(app.state.engine)
            @app.get("/_test_only/login")
            def test_login():
                response = RedirectResponse("/")
                response.set_cookie("app_session", cookie, httponly=True, samesite="lax")
                return response

            if onboarding:
                # Only this explicitly launched harness replaces the external approval page.
                @app.middleware("http")
                async def local_approval(request, call_next):
                    response = await call_next(request)
                    if request.url.path == "/api/github/connection/authorize" and response.status_code == 200:
                        body = b"".join([part async for part in response.body_iterator])
                        state = parse_qs(urlsplit(json.loads(body)["url"]).query)["state"][0]
                        return JSONResponse({"url": "/_test_only/permissions?" + urlencode({"state": state})})
                    return response

                @app.get("/_test_only/permissions")
                def permissions(state: str):
                    target = escape("/_test_only/complete?" + urlencode({"state": state}), quote=True)
                    return HTMLResponse(f'<html lang="ko"><title>테스트 전용 승인 화면</title><h1>테스트 전용 승인 화면</h1><p>실제 GitHub 권한은 변경하지 않습니다.</p><a href="{target}">테스트 접근 허용</a></html>')

                @app.get("/_test_only/complete")
                def complete(state: str):
                    fixture.repo_selected = True
                    return RedirectResponse("/?" + urlencode({"state": state, "installation_id": "9", "setup_action": "install"}))

            with TestClient(app, base_url="http://127.0.0.1:8001") as client:
                login(client)
                cookie = client.cookies.get("app_session")
                if mock or fake_ai:
                    project = client.post("/api/projects", json={"repository_url": "https://github.com/owner/real-repo", "branch": "main"},
                        headers={"Origin": "http://127.0.0.1:8001", "X-CSRF-Token": client.get("/api/me").json()["csrf_token"]})
                    assert project.status_code == 201, project.text
            uvicorn.run(app, host="127.0.0.1", port=8001, access_log=False)


if __name__ == "__main__":
    main()
