"""실제 배포 실행기. 요청 안에서 작업을 만들고, 오래 걸리는 배포는 백그라운드 스레드에서 `Deployer`로 실행한다.

요청 안(`submit`)에서는 빠르게 끝나는 검사만 한다: 환경, 소스. 소스 오류는 작업을 만들기 전에 곧바로 응답한다. 스레드(`_run`)는 상태 버킷 확인,
배포, 로그 저장, 선점 연장, 결과 반영을 한다. 사용자 비밀은 스레드로 **메모리에서만** 넘기고 DB에는 쓰지 않는다. 서버가 다시 시작되면
그 작업은 `interrupted`가 되고 비밀은 사라지므로 다시 입력해야 한다.

프로세스당 하나의 워커만 허용한다(파일 잠금). 선점과 로그 상태가 DB에 있어도 실행 스레드는 한 프로세스 안에만 있기 때문이다.
서버를 멈출 때 진행 중인 `terraform apply`가 있으면 Terraform state 잠금이 남을 수 있다. 다음 배포가 `terraform_locked`로 실패하면
잠금을 풀어야 한다(infra/adapters/README.md).
"""
import hashlib
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from anyship_adapters import AdapterError, DeployResult, redact_event, redact_model
from anyship_adapters.aws_always_on import AwsAlwaysOnAdapter
from anyship_adapters.deployer import Deployer
from anyship_adapters.dns import WildcardRecords
from anyship_adapters.foundation import FoundationSettings
from anyship_adapters.image_builder import ImageBuilder
from anyship_adapters.terraform_runner import TerraformRunner

from .db import AwsEnvironment, DeployJob, Deployment
from .deploy_state import DeployStateError, adapter_environment, ensure_state_bucket, save_foundation
from .deployments import ACTIVE, append_logs, claim, extend_lease, finish, interrupt_all
from .source import SourceError, SourceProvider

FLUSH_EVENTS, FLUSH_SECONDS = 20, 2.0


def _public_key(private_key: Path) -> str:
    try:
        value = Path(str(private_key) + ".pub").read_text(encoding="utf-8").strip()
    except OSError:
        raise RuntimeError("The SSH public key (APP_DEPLOY_SSH_KEY + '.pub') cannot be read.") from None
    if not value.startswith("ssh-"):
        raise RuntimeError("APP_DEPLOY_SSH_KEY.pub is not an SSH public key.")
    return value


def _lock(directory: Path, database_url: str):
    directory.mkdir(parents=True, exist_ok=True)
    handle = (directory / (hashlib.sha256(database_url.encode()).hexdigest() + ".lock")).open("a+b")
    if handle.seek(0, 2) == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError("Real deployments support one Service process per database; stop the other worker.") from None
    return handle


class LogSink:
    """어댑터 로그를 모았다가 DB에 쓴다. 쓰기가 실패해도 배포는 멈추지 않고 다음 기회에 다시 쓴다."""

    def __init__(self, write, secrets=None, clock=time.monotonic):
        self._write, self._secrets, self._clock, self._buffer, self._last = write, secrets, clock, [], clock()
        self._lock = threading.Lock()

    def add(self, event) -> None:
        item = redact_event(event, self._secrets).model_dump(mode="json")
        item.pop("data", None)  # 임의 진단 데이터는 서비스 DB에 복사하지 않는다
        with self._lock:
            self._buffer.append(item)
            if len(self._buffer) >= FLUSH_EVENTS or self._clock() - self._last >= FLUSH_SECONDS:
                self._flush()

    def flush(self) -> None:
        with self._lock:
            self._flush()

    def _flush(self) -> None:
        self._last = self._clock()
        if not self._buffer:
            return
        try:
            self._write(list(self._buffer))
            self._buffer.clear()
        except Exception:
            pass  # 버퍼를 남겨 두고 다음 기회에 다시 쓴다


class DeployRunner:
    def __init__(self, settings, sessions, *, source: SourceProvider, deployer, access=None, executor=None,
                 lock_dir: Path | None = None):
        self.settings, self.sessions, self.source, self.deployer = settings, sessions, source, deployer
        self.access, self._executor_override = access, executor
        self.lock_dir = lock_dir or Path(__file__).resolve().parents[1] / "workspaces" / "deploy"
        self.runtime_id, self.executor, self.lock_file = str(uuid.uuid4()), None, None

    @classmethod
    def from_settings(cls, settings, sessions):
        from .source import LocalFolderSource
        for name, path, check in (("APP_DEPLOY_SOURCE_DIR", settings.deploy_source_dir, Path.is_dir),
                                  ("APP_DEPLOY_SSH_KEY", settings.deploy_ssh_key, Path.is_file),
                                  ("APP_DEPLOY_TERRAFORM_DIR", settings.deploy_terraform_dir, Path.is_dir)):
            if not check(Path(path)):
                raise RuntimeError(f"{name} does not point to an existing {'folder' if check is Path.is_dir else 'file'}.")
        adapter = AwsAlwaysOnAdapter(settings.deploy_ssh_key, base_domain=settings.deploy_base_domain,
                                     verify_tls=settings.deploy_verify_tls)
        runner = TerraformRunner(settings.deploy_terraform_dir, plugin_cache_dir=settings.deploy_plugin_cache)
        foundation = FoundationSettings(settings.deploy_service_ip, _public_key(settings.deploy_ssh_key),
                                        settings.deploy_acme_email)
        # 서비스 서버 역할로 Route 53의 이 도메인에서 *.<환경ID>.aws.<도메인> 레코드만 바꾼다. 끄면 사람이 직접 맞춘다.
        dns = WildcardRecords(scope="aws", base_domain=settings.deploy_base_domain) if settings.deploy_dns else None
        deployer = Deployer({"aws-always-on": adapter}, ImageBuilder(timeout=900), runner=runner, foundation=foundation,
                            dns=dns)
        return cls(settings, sessions, source=LocalFolderSource(settings.deploy_source_dir), deployer=deployer)

    def start(self) -> None:
        self.lock_file = _lock(self.lock_dir, self.settings.database_url)
        try:
            self.runtime_id = str(uuid.uuid4())
            with self.sessions() as session:
                interrupt_all(session, "worker_restarted", "서버가 재시작되어 작업이 중단됐습니다. 새 요청으로 다시 시도해 주세요.")
            self.executor = self._executor_override or ThreadPoolExecutor(max_workers=2, thread_name_prefix="anyship-deploy")
        except Exception:
            self.lock_file.close()
            self.lock_file = None
            raise

    def close(self) -> None:
        if self.executor:
            self.executor.shutdown(wait=False, cancel_futures=True)  # 20분짜리 작업을 기다리지 않는다
            self.executor = None
            with self.sessions() as session:
                interrupt_all(session, "worker_stopping", "서버 종료로 작업이 중단됐습니다. 다시 시도해 주세요.")
        if self.lock_file:
            self.lock_file.close()
            self.lock_file = None

    def submit(self, session, project, request_id, secrets: dict):
        """요청 안에서: 환경과 소스를 확인하고 작업을 선점해 스레드에 넘긴다. (작업, 새로 만들었는지)."""
        target = session.get(Deployment, project.id)
        environment = session.get(AwsEnvironment, target.aws_environment_id) if target else None
        if environment is not None:
            adapter_environment(environment)  # 연결이 확인되지 않은 환경은 여기서 거절한다
        fetched = self.source.fetch(project.full_name) if environment is not None else None
        job, created = claim(session, project.id, request_id, self.runtime_id,
                             image_tag=fetched.commit_sha if fetched else "")
        if created:
            try:
                self.executor.submit(self._run, job.id, environment.id, fetched, dict(secrets))
            except RuntimeError:
                finish(session, job.id, ok=False, stage="runner", result=self._failure(
                    "worker_stopping", "서버 종료 중입니다. 다시 시도해 주세요."))
                session.refresh(job)
        return job, created

    @staticmethod
    def _failure(code: str, message: str, hint: str | None = None, retryable: bool = True) -> dict:
        return {"ok": False, "error": {"code": code, "message": message, "hint": hint, "retryable": retryable}}

    def _run(self, job_id: str, environment_id: str, fetched, secrets: dict) -> None:
        known = dict(secrets)
        sink = LogSink(lambda events: self._store(job_id, events), known)
        try:
            with self.sessions() as session:
                job = session.get(DeployJob, job_id)
                if job is None or job.status not in ACTIVE:
                    return
                job.status = "running"
                set_name = job.set_name
                session.commit()
                row = session.get(AwsEnvironment, environment_id)
                try:
                    ensure_state_bucket(session, row, self.access or _default_access())
                    env = adapter_environment(row)
                except Exception as exc:  # AwsAccessError, DeployStateError
                    error = getattr(exc, "error", None) or AdapterError(
                        code=getattr(exc, "code", "environment_unavailable"),
                        message=getattr(exc, "message", "환경 정보를 준비하지 못했습니다."), retryable=False)
                    return self._end(job_id, DeployResult(ok=False, error=error, details={"stage": "environment"}), fetched, known)
            result = self.deployer.deploy(env, fetched.spec, fetched.path, fetched.commit_sha, secrets, sink.add,
                                          set_name=set_name)
        except Exception as exc:
            # 예기치 않은 예외의 원문에는 비밀이 섞일 수 있다. 종류만 남긴다.
            result = DeployResult(ok=False, error=AdapterError(
                code="deploy_runner_error", message="배포 중 예기치 않은 오류가 발생했습니다.",
                hint="서비스 서버의 로그를 확인해 주세요.", retryable=True), details={"stage": "runner", "exception": type(exc).__name__})
        sink.flush()
        self._end(job_id, result, fetched, known)

    def _store(self, job_id: str, events: list) -> None:
        with self.sessions() as session:
            append_logs(session, job_id, events)
            extend_lease(session, job_id)

    def _end(self, job_id: str, result: DeployResult, fetched, known: dict) -> None:
        data = redact_model(result, known).model_dump(mode="json")
        deployed = None
        with self.sessions() as session:
            if result.ok:
                job = session.get(DeployJob, job_id)
                foundation = (result.details or {}).get("foundation")
                try:
                    if foundation:
                        row = session.get(AwsEnvironment, session.get(Deployment, job.project_id).aws_environment_id)
                        save_foundation(session, row, foundation)
                except DeployStateError:
                    pass  # 배포는 성공했다. 기반 값은 다음 배포가 state에서 다시 읽는다
                deployed = {"image_tag": result.image_tag or job.image_tag, "url": result.url or "",
                            "app_name": str(fetched.spec.get("app", ""))}
            finish(session, job_id, ok=result.ok, result=data, deployed=deployed,
                   stage="" if result.ok else str((result.details or {}).get("stage", "")))


def _default_access():
    from anyship_adapters.aws_access import AwsAccess
    return AwsAccess()
