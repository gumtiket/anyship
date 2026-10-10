"""실제 배포의 대상 선택, 작업 선점, 상태 전이, 로그 저장(DB 조작). 모의 배포(`mock_deployments.py`)와 별개다.

배포를 실제로 실행하는 부분은 이 모듈의 실행기가 이 함수들을 불러서 한다. 여기의 함수는 AWS도 소스도 만지지 않는다.

상태 변경은 모두 조건부 갱신이다. 선점은 `active_job_id`와 `lease_until`로 한다. 공용 기반을 만드는 데 약 20분이 걸려서 유효 시간을
30분으로 잡고, 실행 중에는 늘려 준다. 선점이 만료되면(워커가 죽었거나 멈춤) 다음 요청이 그 작업을 `interrupted`로 정리하고 선점한다.
늦게 끝난 옛 작업이 새 작업의 선점이나 배포 상태를 덮어쓰지 못하게, 끝내기와 해제도 "아직 내 작업일 때만" 갱신한다.
"""
import json
import time
import uuid

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from .db import AwsEnvironment, DeployJob, Deployment
from .deploy_state import assign_env_id

LEASE_SECONDS = 30 * 60
ACTIVE = ("queued", "running")
REAL_SETS = ("aws-always-on",)  # 실제로 배포할 수 있는 세트(aws-serverless는 아직 없다)
MAX_EVENTS, KEEP_FIRST, MAX_MESSAGE = 400, 100, 500
OMITTED = "(중간 로그 일부 생략)"


class DeploymentError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _error(code: str, message: str, status: int = 409) -> DeploymentError:
    return DeploymentError(status, code, message)


def _failure(code: str, message: str, retryable: bool = True) -> str:
    return json.dumps({"ok": False, "error": {"code": code, "message": message, "retryable": retryable}}, ensure_ascii=False)


def select_target(session, project_id: str, environment: AwsEnvironment, set_name: str) -> Deployment:
    """프로젝트가 배포될 환경과 세트를 정한다. 한 번도 배포한 적이 없고 진행 중인 작업이 없을 때만 바꿀 수 있다."""
    if environment.status != "CONNECTED" or not environment.role_arn:
        raise _error("environment_not_connected", "AWS 연결이 확인된 환경만 선택할 수 있습니다.")
    if set_name not in REAL_SETS:
        raise _error("set_not_supported", "아직 지원하지 않는 배포 방식입니다.", 422)
    target = session.get(Deployment, project_id)
    if target and (target.aws_environment_id, target.set_name) == (environment.id, set_name):
        return target
    assign_env_id(session, environment)
    if target is None:
        target = Deployment(project_id=project_id, aws_environment_id=environment.id, set_name=set_name)
        session.add(target)
    else:
        changed = session.execute(update(Deployment).where(
            Deployment.project_id == project_id, Deployment.active_job_id.is_(None), Deployment.image_tag == "",
        ).values(aws_environment_id=environment.id, set_name=set_name))
        if changed.rowcount != 1:
            session.rollback()
            raise _error("target_in_use", "이미 배포했거나 진행 중인 작업이 있어 환경을 바꿀 수 없습니다.")
    session.commit()
    session.refresh(target)
    return target


def claim(session, project_id: str, request_id, runtime_id: str, *, image_tag: str = "", now: int | None = None):
    """배포 작업을 만들고 선점한다. (작업, 새로 만들었는지). 같은 요청 ID가 다시 오면 기존 작업을 돌려준다."""
    now = int(time.time()) if now is None else now
    existing = select(DeployJob).where(DeployJob.project_id == project_id, DeployJob.request_id == str(request_id))
    if previous := session.scalar(existing):
        return previous, False
    target = session.get(Deployment, project_id)
    if target is None:
        raise _error("target_required", "배포할 환경을 먼저 선택해 주세요.")
    if target.active_job_id and target.lease_until <= now:  # 만료된 선점: 죽은 작업을 중단으로 정리한다
        session.execute(update(DeployJob).where(DeployJob.id == target.active_job_id, DeployJob.status.in_(ACTIVE)).values(
            status="interrupted", finished_at=now * 1000,
            result_json=_failure("lease_expired", "작업이 제한 시간 안에 끝나지 않아 중단 처리했습니다.")))
    identifier = str(uuid.uuid4())
    claimed = session.execute(update(Deployment).where(
        Deployment.project_id == project_id, or_(Deployment.active_job_id.is_(None), Deployment.lease_until <= now),
    ).values(active_job_id=identifier, lease_until=now + LEASE_SECONDS))
    if claimed.rowcount != 1:
        session.rollback()
        raise _error("deploy_job_running", "이미 배포 작업을 처리하고 있습니다.")
    job = DeployJob(id=identifier, project_id=project_id, request_id=str(request_id), runtime_id=runtime_id,
                    action="deploy", set_name=target.set_name, image_tag=image_tag, created_at=now * 1000)
    session.add(job)
    try:
        session.commit()
    except IntegrityError:  # 같은 요청 ID가 동시에 들어왔다
        session.rollback()
        if previous := session.scalar(existing):
            return previous, False
        raise
    return job, True


def extend_lease(session, job_id: str, *, now: int | None = None) -> None:
    now = int(time.time()) if now is None else now
    session.execute(update(Deployment).where(Deployment.active_job_id == job_id).values(lease_until=now + LEASE_SECONDS))
    session.commit()


def finish(session, job_id: str, *, ok: bool, result: dict, stage: str = "", deployed: dict | None = None,
           now: int | None = None) -> bool:
    """작업을 끝내고 선점을 풀며, 성공이면 배포 상태(`deployed`: image_tag, url, app_name)를 반영한다. 이미 끝났거나 중단된 작업이면 False."""
    now = int(time.time()) if now is None else now
    done = session.execute(update(DeployJob).where(DeployJob.id == job_id, DeployJob.status.in_(ACTIVE)).values(
        status="succeeded" if ok else "failed", stage=stage, finished_at=now * 1000,
        result_json=json.dumps(result, ensure_ascii=False)))
    if done.rowcount != 1:
        session.rollback()
        return False
    values = {"active_job_id": None, "lease_until": 0}
    if ok and deployed:
        values.update(image_tag=deployed["image_tag"], url=deployed["url"], app_name=deployed["app_name"])
    session.execute(update(Deployment).where(Deployment.active_job_id == job_id).values(**values))
    session.commit()
    return True


def interrupt_all(session, code: str, message: str, *, now: int | None = None) -> int:
    """진행 중이던 작업을 모두 중단으로 정리하고 선점을 푼다(서버를 다시 시작할 때)."""
    now = int(time.time()) if now is None else now
    stopped = session.execute(update(DeployJob).where(DeployJob.status.in_(ACTIVE)).values(
        status="interrupted", finished_at=now * 1000, result_json=_failure(code, message)))
    session.execute(update(Deployment).where(Deployment.active_job_id.is_not(None)).values(active_job_id=None, lease_until=0))
    session.commit()
    return stopped.rowcount


def add_events(events: list, new: list) -> list:
    """로그를 이어 붙인다. MAX_EVENTS를 넘으면 앞쪽 KEEP_FIRST개와 최근 것만 남기고 가운데를 생략 표시 하나로 바꾼다."""
    body = events + [{**e, "message": str(e.get("message", ""))[:MAX_MESSAGE]} for e in new]
    if len(body) <= MAX_EVENTS:
        return body
    body = [e for e in body if e.get("message") != OMITTED]  # 이전에 넣은 표시는 걷어내고 새로 하나만 넣는다
    return body[:KEEP_FIRST] + [_omitted()] + body[-(MAX_EVENTS - KEEP_FIRST - 1):]


def _omitted() -> dict:
    return {"level": "warn", "step": 0, "total": 0, "name": "", "message": OMITTED}


def append_logs(session, job_id: str, new: list) -> None:
    row = session.get(DeployJob, job_id)
    row.logs_json = json.dumps(add_events(json.loads(row.logs_json), new), ensure_ascii=False)
    session.commit()


def job_json(row: DeployJob) -> dict:
    return {"id": row.id, "request_id": row.request_id, "action": row.action, "set_name": row.set_name,
            "image_tag": row.image_tag, "status": row.status, "stage": row.stage, "logs": json.loads(row.logs_json),
            "result": json.loads(row.result_json), "created_at": row.created_at, "finished_at": row.finished_at}
