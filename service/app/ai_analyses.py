"""Pinned branch analysis, bundle review, and publication to a separate work branch."""
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import BoundedSemaphore
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from .ai_snapshot import SHA, SnapshotError, snapshot, source_digest
from .db import AIAnalysis, LoginSession, Membership, Project
from . import ai_publication

ACTIVE = ("queued", "running", "publishing")
LEASE_SECONDS = 600
WORKER_TIMEOUT = 90
MAX_RESULT_BYTES = 3 * 1024 * 1024


class StartInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    create_branch: bool = False
    base_branch: str | None = Field(default=None, min_length=1, max_length=255)


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    selected_bundle_ids: list[Literal["all-changes"]] = Field(min_length=1, max_length=1)


def expire_jobs(session, project_id):
    session.execute(update(AIAnalysis).where(AIAnalysis.project_id == project_id,
        AIAnalysis.status == "publishing", AIAnalysis.lease_until <= int(time.time())
    ).values(status="publish_failed", active_project_id=None, lease_until=0, publish_token="",
             error="커밋 저장이 중단되었습니다. 같은 수정안으로 저장을 다시 요청하면 GitHub 상태를 확인합니다."))
    session.execute(update(AIAnalysis).where(AIAnalysis.project_id == project_id,
        AIAnalysis.status.in_(("queued", "running")), AIAnalysis.lease_until <= int(time.time())
    ).values(status="interrupted", active_project_id=None, lease_until=0,
             finished_at=int(time.time()), error="분석이 중단되었습니다. 새 분석을 요청해 주세요."))


def clear_jobs(session, project_id):
    expire_jobs(session, project_id)
    session.execute(delete(AIAnalysis).where(AIAnalysis.project_id == project_id, AIAnalysis.status.notin_(ACTIVE)))
    if session.scalar(select(AIAnalysis.id).where(AIAnalysis.project_id == project_id)):
        raise HTTPException(409, "AI 분석 중입니다. 완료 후 저장소 연결을 삭제해 주세요.")


def review_digest(row, project):
    value = [row.id, project.id, project.repository_id, project.full_name, project.branch,
             row.base_sha, row.base_tree, row.source_digest, row.result_json, row.diff, "all-changes"]
    if row.work_branch:
        value.extend([row.base_branch, row.work_branch, row.provider])
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()


def job_json(row, *, detail=True):
    value = {"id": row.id, "request_id": row.request_id, "status": row.status, "provider": row.provider,
             "base_sha": row.base_sha, "created_at": row.created_at, "finished_at": row.finished_at,
             "busy": row.status in ACTIVE, "error": row.error, "base_branch": row.base_branch,
             "work_branch": row.work_branch, "branch_created": row.branch_created, "commit_sha": row.commit_sha}
    if detail:
        value.update(result=json.loads(row.result_json), diff=row.diff, logs=json.loads(row.logs_json),
                     review_hash=row.review_hash, source_digest=row.source_digest)
    return value


def run_worker(request, directory):
    request_file, response_file = directory / "request.json", directory / "response.json"
    request_file.write_text(json.dumps(request), encoding="utf-8")
    temporary = directory / "tmp"
    temporary.mkdir()
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "COMSPEC"}}
    provider = request.get("provider", "fake")
    if provider == "bedrock":
        # Only the model provider gets the explicitly allowlisted AWS credential chain.
        # GitHub/session/database secrets are never passed to the worker or model.
        allowed = {"BEDROCK_REGION", "BEDROCK_MODEL_ID_STRONG", "BEDROCK_MODEL_ID_FAST",
            "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE",
            "AWS_DEFAULT_PROFILE", "AWS_SHARED_CREDENTIALS_FILE", "AWS_CONFIG_FILE",
            "AWS_WEB_IDENTITY_TOKEN_FILE", "AWS_ROLE_ARN", "AWS_ROLE_SESSION_NAME",
            "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "AWS_CONTAINER_CREDENTIALS_FULL_URI",
            "AWS_CONTAINER_AUTHORIZATION_TOKEN", "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE", "HOME", "USERPROFILE"}
        env.update({key: value for key, value in os.environ.items() if key in allowed})
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", TEMP=str(temporary), TMP=str(temporary),
               TMPDIR=str(temporary), GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    # Fixed module/arguments. The repository is data, never the subprocess cwd or executable.
    result = subprocess.run([sys.executable, "-B", "-m", "app.ai_worker", str(request_file), str(response_file)],
        cwd=Path(__file__).resolve().parents[1], env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=420 if provider == "bedrock" else WORKER_TIMEOUT)
    if result.returncode or not response_file.is_file() or response_file.stat().st_size > MAX_RESULT_BYTES:
        raise ValueError("invalid_worker_result")
    payload = json.loads(response_file.read_text(encoding="utf-8"))
    if payload.get("error"):
        raise ValueError("ai_analysis_failed")
    if (payload["result"]["base_sha"] != request["base_sha"] or payload["result"]["llm_mode"] != provider
            or payload["result"]["gate"]["status"] != "skipped" or payload["result"]["gate"]["pr_eligible"]):
        raise ValueError("invalid_worker_result")
    return payload


class AnalysisRunner:
    def __init__(self, sessions, github):
        self.sessions, self.github = sessions, github
        self.executor = None
        self.slots = BoundedSemaphore(2)
        self.authorize = None

    def start(self):
        if self.executor is None:
            self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="anyship-ai")

    def close(self):
        if self.executor is not None:
            self.executor.shutdown(wait=True)
            self.executor = None

    def log(self, identifier, message):
        with self.sessions() as session:
            row = session.get(AIAnalysis, identifier)
            if row and row.status in ACTIVE:
                events = json.loads(row.logs_json)
                events.append({"ts": int(time.time()), "message": message})
                row.logs_json = json.dumps(events[-20:], ensure_ascii=False)
                session.commit()

    def execute(self, identifier, login_id):
        try:
            with self.sessions() as session:
                row = session.get(AIAnalysis, identifier)
                login = session.get(LoginSession, login_id)
                if (not row or not login or login.expires_at <= int(time.time())
                        or not session.get(Membership, (login.user_id, login.workspace_id))):
                    raise ValueError("session_expired")
                project, token = self.authorize(row.project_id, login, session)
                if row.status != "queued" or row.lease_until <= int(time.time()):
                    return
                changed = session.execute(update(AIAnalysis).where(AIAnalysis.id == identifier,
                    AIAnalysis.status == "queued", AIAnalysis.lease_until > int(time.time())).values(status="running"))
                if changed.rowcount != 1:
                    return
                session.refresh(row)
                repository, base_sha, project_id = project.full_name, row.base_sha, project.id
                provider, work_branch = row.provider, row.work_branch
                # Hold the row's write lock until creation is recorded. Expiration and
                # deletion cannot race a remote ref creation after checking the lease.
                session.flush()
                if work_branch:
                    ai_publication.create_branch(self.github, token, repository, row)
                session.commit()
            if work_branch:
                self.log(identifier, "선택한 기준 커밋에서 새 작업 브랜치를 생성했습니다.")
            self.log(identifier, "기준 커밋의 코드를 읽고 파일 해시를 확인합니다.")
            with TemporaryDirectory(prefix="anyship-ai-") as temporary:
                directory = Path(temporary)
                tree, manifest, excluded = snapshot(self.github, token, repository, base_sha, directory / "source")
                del token
                self.log(identifier, f"코드 {len(manifest)}개를 확인했습니다. 제외 파일 {excluded}개.")
                self.log(identifier, ("Bedrock" if provider == "bedrock" else "Fake 응답") + "으로 AI 진단·수정안을 생성합니다.")
                payload = run_worker({"source": str(directory / "source"), "output": str(directory / "output"),
                    "manifest": manifest, "base_sha": base_sha, "repository": repository,
                    "app_name": "app-" + project_id.replace("-", "")[:20],
                    "provider": provider, "work_branch": work_branch}, directory)
                payload["result"]["source"] = {"file_count": len(manifest), "excluded_count": excluded,
                    "scope": "bounded_utf8_source", "base_tree": tree}
            with self.sessions() as session:
                row = session.get(AIAnalysis, identifier)
                if not row or row.status not in ACTIVE or row.lease_until <= int(time.time()):
                    return
                project = session.get(Project, project_id)
                # Calculate on a detached copy, then conditionally commit while the
                # lease is still ours. Expiration/deletion must win over late work.
                session.expunge(row)
                row.base_tree, row.source_digest = tree, source_digest(manifest)
                row.result_json = json.dumps(payload["result"], ensure_ascii=False, sort_keys=True)
                row.diff = payload["diff"]
                row.status = "failed" if payload["result"]["analysis_status"] == "failed" else "completed"
                if row.status == "failed":
                    row.error = "AI 분석이 실패 상태를 반환했습니다. 진단과 보류 항목을 확인해 주세요."
                row.review_hash = review_digest(row, project) if row.diff and row.status == "completed" else ""
                logs = json.loads(row.logs_json)
                logs.append({"ts": int(time.time()), "message": "수정안을 저장했습니다. 전체 diff를 검토한 뒤 작업 브랜치에 커밋할 수 있습니다." if work_branch else "검토할 수정안을 저장했습니다."})
                session.execute(update(AIAnalysis).where(AIAnalysis.id == identifier,
                    AIAnalysis.status == "running", AIAnalysis.lease_until > int(time.time())
                ).values(base_tree=row.base_tree, source_digest=row.source_digest, result_json=row.result_json,
                    diff=row.diff, status=row.status, error=row.error, review_hash=row.review_hash,
                    logs_json=json.dumps(logs, ensure_ascii=False), active_project_id=None,
                    lease_until=0, finished_at=int(time.time())))
                session.commit()
        except Exception as error:
            message = error.detail if isinstance(error, HTTPException) else ("코드 스냅샷을 검증하지 못했습니다. 경로·파일 크기·기준 커밋을 확인해 주세요."
                       if isinstance(error, SnapshotError) else
                       "분석을 완료하지 못했습니다. GitHub 권한·AI 설치·실행 시간을 확인하고 새 분석을 요청해 주세요.")
            with self.sessions() as session:
                session.execute(update(AIAnalysis).where(AIAnalysis.id == identifier,
                    AIAnalysis.status.in_(("queued", "running"))).values(status="failed", error=message,
                    active_project_id=None, lease_until=0, finished_at=int(time.time())))
                session.commit()
        finally:
            self.slots.release()


def router(settings, runner, db, current, mutation, owned_project, real_project, access_token):
    api = APIRouter(prefix="/api/projects/{project_id}/ai-analyses")
    if runner:
        runner.authorize = lambda pid, login, session: (real_project(pid, login, session), access_token(login))

    def available():
        if not settings.ai_configured or runner is None or runner.executor is None:
            raise HTTPException(503, "AI 설정을 확인해 주세요. Bedrock 모드는 리전과 Strong/Fast 모델 ID가 필요합니다.")

    def owned_job(identifier, project_id, session):
        row = session.get(AIAnalysis, identifier)
        if not row or row.project_id != project_id:
            raise HTTPException(404, "분석 작업을 찾을 수 없습니다.")
        return row

    @api.get("")
    def list_jobs(project_id: str, limit: int = Query(20, ge=1, le=50), login=Depends(current), session=Depends(db)):
        owned_project(project_id, login, session)
        expire_jobs(session, project_id)
        session.commit()
        rows = session.scalars(select(AIAnalysis).where(AIAnalysis.project_id == project_id)
            .order_by(AIAnalysis.created_at.desc(), AIAnalysis.id.desc()).limit(limit))
        return [job_json(row, detail=False) for row in rows]

    @api.get("/{identifier}")
    def get_job(project_id: str, identifier: str, login=Depends(current), session=Depends(db)):
        owned_project(project_id, login, session)
        expire_jobs(session, project_id)
        session.commit()
        return job_json(owned_job(identifier, project_id, session))

    @api.post("", status_code=202)
    def start(project_id: str, body: StartInput, response: Response, login=Depends(mutation), session=Depends(db)):
        available()
        project = real_project(project_id, login, session)
        # Same parent lock as deletion; the active key also protects SQLite callers.
        session.scalar(select(Project).where(Project.id == project_id).with_for_update())
        expire_jobs(session, project_id)
        request_id = str(body.request_id)
        previous = session.scalar(select(AIAnalysis).where(AIAnalysis.project_id == project_id, AIAnalysis.request_id == request_id))
        if previous:
            if bool(previous.work_branch) != body.create_branch or (body.base_branch and previous.base_branch != body.base_branch):
                raise HTTPException(409, "같은 요청 ID의 기준 브랜치와 작업 방식은 변경할 수 없습니다.")
            session.commit()
            response.status_code = 200
            return job_json(previous)
        if session.scalar(select(AIAnalysis.id).where(AIAnalysis.active_project_id == project_id)):
            raise HTTPException(409, "이 프로젝트의 분석이 진행 중입니다.")
        if not runner.slots.acquire(blocking=False):
            raise HTTPException(409, "다른 분석을 처리 중입니다. 잠시 후 다시 요청해 주세요.")
        submitted = False
        row = None
        try:
            base_branch = body.base_branch or project.branch
            if not body.create_branch and base_branch != project.branch:
                raise HTTPException(422, "다른 기준 브랜치 선택에는 새 작업 브랜치 생성이 필요합니다.")
            sha = runner.github.branch(access_token(login), project.full_name, base_branch)["commit"]["sha"]
            if not SHA.fullmatch(sha):
                raise HTTPException(409, "기준 커밋을 확인할 수 없습니다.")
            identifier = str(uuid.uuid4())
            row = AIAnalysis(id=identifier, project_id=project_id, active_project_id=project_id,
                request_id=request_id, base_sha=sha, base_branch=base_branch, provider=settings.ai_mode,
                work_branch="anyship/ai-" + identifier if body.create_branch else "",
                created_at=int(time.time()), lease_until=int(time.time()) + LEASE_SECONDS)
            session.add(row)
            session.commit()
            value = job_json(row)
            try:
                runner.executor.submit(runner.execute, row.id, login.id)
            except RuntimeError:
                row.status, row.active_project_id, row.lease_until = "failed", None, 0
                row.error, row.finished_at = "분석 실행기가 종료되었습니다. 서버 재시작 후 새 분석을 요청해 주세요.", int(time.time())
                session.commit()
                raise HTTPException(503, row.error) from None
            submitted = True
            return value
        except IntegrityError:
            session.rollback()
            previous = session.scalar(select(AIAnalysis).where(AIAnalysis.project_id == project_id, AIAnalysis.request_id == request_id))
            if previous:
                response.status_code = 200
                return job_json(previous)
            raise HTTPException(409, "분석이 이미 진행 중이거나 프로젝트가 삭제되었습니다.") from None
        finally:
            if not submitted:
                runner.slots.release()

    @api.post("/{identifier}/review")
    def review(project_id: str, identifier: str, body: ReviewInput, login=Depends(mutation), session=Depends(db)):
        available()
        project = real_project(project_id, login, session)
        row = owned_job(identifier, project_id, session)
        if (row.status not in ("completed", "reviewed") or not row.review_hash
                or not secrets.compare_digest(body.review_hash, row.review_hash)
                or not secrets.compare_digest(row.review_hash, review_digest(row, project))):
            raise HTTPException(409, "현재 수정안 전체를 다시 확인해 주세요.")
        head = (runner.github.ref(access_token(login), project.full_name, row.work_branch) if row.work_branch else
                runner.github.branch(access_token(login), project.full_name, project.branch)["commit"]["sha"])
        if head != row.base_sha:
            raise HTTPException(409, "기준 브랜치가 변경되었습니다. 새 분석을 요청해 주세요.")
        changed = session.execute(update(AIAnalysis).where(AIAnalysis.id == row.id,
            AIAnalysis.status.in_(("completed", "reviewed")), AIAnalysis.review_hash == body.review_hash
        ).values(status="reviewed"))
        if changed.rowcount != 1:
            raise HTTPException(409, "분석 기록이 변경되었습니다. 다시 확인해 주세요.")
        session.commit()
        session.refresh(row)
        return job_json(row)

    @api.post("/{identifier}/commit")
    def publish(project_id: str, identifier: str, body: ReviewInput, login=Depends(mutation), session=Depends(db)):
        available()
        project = real_project(project_id, login, session)
        session.scalar(select(Project).where(Project.id == project_id).with_for_update())
        expire_jobs(session, project_id)
        row = owned_job(identifier, project_id, session)
        if (not row.work_branch or not row.branch_created or not row.review_hash
                or not secrets.compare_digest(body.review_hash, row.review_hash)
                or not secrets.compare_digest(row.review_hash, review_digest(row, project))):
            raise HTTPException(409, "이 작업 브랜치의 전체 수정안을 다시 검토해 주세요.")
        if row.status == "published":
            return job_json(row)
        if row.status not in ("reviewed", "publish_failed"):
            raise HTTPException(409, "전체 수정안 검토를 완료한 뒤 저장해 주세요.")
        if session.scalar(select(AIAnalysis.id).where(AIAnalysis.active_project_id == project_id)):
            raise HTTPException(409, "프로젝트의 다른 작업이 진행 중입니다.")
        lease_token = str(uuid.uuid4())
        try:
            changed = session.execute(update(AIAnalysis).where(AIAnalysis.id == identifier,
                AIAnalysis.status.in_(("reviewed", "publish_failed"))).values(status="publishing", error="",
                active_project_id=project_id, lease_until=int(time.time()) + LEASE_SECONDS, publish_token=lease_token))
            if changed.rowcount != 1:
                raise HTTPException(409, "커밋 저장이 이미 진행 중입니다.")
            session.commit()
        except IntegrityError:
            session.rollback()
            raise HTTPException(409, "프로젝트의 다른 작업이 진행 중입니다.") from None
        try:
            ai_publication.publish(session, runner.github, access_token(login), project, row, lease_token)
        except Exception as error:
            session.rollback()
            message = error.detail if isinstance(error, HTTPException) else "커밋을 저장하지 못했습니다. GitHub 권한·브랜치 규칙을 확인한 뒤 같은 수정안으로 다시 시도해 주세요."
            session.execute(update(AIAnalysis).where(AIAnalysis.id == identifier,
                AIAnalysis.status == "publishing", AIAnalysis.publish_token == lease_token).values(
                    status="publish_failed", error=message, active_project_id=None, lease_until=0, publish_token=""))
            session.commit()
            raise HTTPException(error.status_code if isinstance(error, HTTPException) else 502, message) from None
        session.refresh(row)
        return job_json(row)

    return api
