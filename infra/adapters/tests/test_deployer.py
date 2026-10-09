from pathlib import Path

import pytest

from anyship_adapters import AdapterError, AwsEnvironment, CheckResult, DeployResult, LogEvent, OnpremEnvironment
from anyship_adapters.deployer import Deployer
from anyship_adapters.foundation import FoundationSettings
from anyship_adapters.image_builder import BuildError, BuiltImage
from anyship_adapters.terraform_runner import TerraformError

from fakes import Log
from specs import GENERATED, make

SHA, SRC = "abc1234", Path("/srv/source")
URL = "https://todo.test.aws.anyship.cloud"
BUCKET = "anyship-tfstate-223455088214-ap-northeast-2-2b9b6060"
FILLED = dict(host="43.201.158.8", db_address="anyship-test-db.abc.ap-northeast-2.rds.amazonaws.com", db_port=5432,
              db_secret_arn="arn:aws:secretsmanager:ap-northeast-2:223455088214:secret:rds!db-abc-Xy1")
SETTINGS = FoundationSettings("203.0.113.10", "ssh-ed25519 AAAA deploy", "ops@example.com")
ENV = AwsEnvironment(env_id="test", role_arn="arn:aws:iam::223455088214:role/deploy-service-role",
                     external_id="ext-id-0123456789abcdef", state_bucket=BUCKET, host="1.1.1.1")  # 서비스에 저장된 낡은 값
ONPREM_ENV = OnpremEnvironment(env_id="demo", host="203.0.113.5")
USER_SECRET = "sk-live-0123456789abcdef"


def err(code, message="boom", **extra):
    return AdapterError(code=code, message=message, **extra)


class Parts:
    """부품들이 부른 순서를 order 하나에 모은다."""

    def __init__(self):
        self.order, self.builds, self.checks, self.deploys, self.applied = [], [], [], [], []
        self.build_error = self.runner_reads = self.check_result = self.deploy_result = self.prune_error = None
        self.deploy_raises = None
        self.runner_reads = ["ok"]


def make_deployer(parts, *, runner=True, kinds=("aws-always-on", "onprem")):
    class Builder:
        def build(self, source_dir, app, sha, log, *, dockerfile="Dockerfile"):
            parts.order.append("build")
            parts.builds.append((Path(source_dir), app, sha, dockerfile))
            log(LogEvent(step=2, total=2, name="이미지 빌드", message="빌드 로그 줄"))
            if parts.build_error:
                raise parts.build_error
            return BuiltImage(image=f"{app}:{sha}", image_id="sha256:abc")

        def prune(self, app, keep):
            parts.order.append("prune")
            if parts.prune_error:
                raise parts.prune_error
            return [f"{app}:old1"]

    class Runner:
        def read_foundation(self, env, log):
            parts.order.append("read")
            log(LogEvent(step=2, total=2, name="terraform output", message="출력을 읽는 중"))
            result = parts.runner_reads.pop(0)
            if isinstance(result, Exception):
                raise result
            return env.model_copy(update=FILLED)

        def apply(self, env, variables, log):
            parts.order.append("apply")
            parts.applied.append(variables)
            log(LogEvent(step=2, total=2, name="terraform apply", message="만드는 중"))

    class Adapter:
        def check(self, env, log):
            parts.order.append("check")
            parts.checks.append(env)
            log(LogEvent(step=1, total=5, name="접속 확인", message="접속하는 중"))
            return parts.check_result or CheckResult(ok=True)

        def deploy(self, env, spec, image_tag, secrets, log, *, set_name):
            parts.order.append("deploy")
            parts.deploys.append((env, image_tag, dict(secrets), set_name))
            log(LogEvent(step=3, total=8, name="앱 시작", message=f"시작 {USER_SECRET if secrets else ''}".strip()))
            if parts.deploy_raises:
                raise parts.deploy_raises
            return parts.deploy_result or DeployResult(ok=True, url=URL, image_tag=image_tag, details={"database": "app_todo"})

    adapters = {name: Adapter() for name in kinds}
    kwargs = dict(runner=Runner(), foundation=SETTINGS) if runner else {}
    return Deployer(adapters, Builder(), **kwargs)


def run(parts=None, env=ENV, spec=None, sha=SHA, secrets=None, set_name="aws-always-on", **deployer_options):
    parts = parts or Parts()
    log = Log()
    result = make_deployer(parts, **deployer_options).deploy(env, spec or GENERATED, SRC, sha, secrets or {}, log, set_name=set_name)
    return result, parts, log


MISSING = TerraformError(err("foundation_missing", "공용 기반이 아직 만들어지지 않았습니다."))


# --- 정상 경로 ---------------------------------------------------------------------------------
def test_an_aws_deploy_runs_every_stage_in_order_and_hands_back_the_foundation_values():
    result, parts, _ = run()
    assert result.ok and result.url == URL and result.image_tag == SHA
    assert parts.order == ["build", "read", "check", "deploy", "prune"]
    assert result.details["foundation"] == FILLED and result.details["foundation_created"] is False
    assert result.details["image"] == f"todo:{SHA}" and result.details["pruned"] == ["todo:old1"]
    assert result.details["database"] == "app_todo"  # 어댑터의 details는 그대로 남는다


def test_the_adapter_gets_the_foundation_read_now_not_the_stale_values_the_service_stored():
    _, parts, _ = run()
    assert parts.checks[0].host == "43.201.158.8" and parts.deploys[0][0].host == "43.201.158.8"


def test_a_missing_foundation_is_created_during_the_deploy():
    parts = Parts()
    parts.runner_reads = [MISSING, "ok"]
    result, parts, log = run(parts)
    assert result.ok and result.details["foundation_created"] is True
    assert parts.order == ["build", "read", "apply", "read", "check", "deploy", "prune"]
    assert parts.applied[0]["env_id"] == "test" and parts.applied[0]["account_id"] == "223455088214"
    assert any("새로 만듭니다" in e.message and e.name == "공용 기반 확인" for e in log.events)


def test_the_stages_are_numbered_continuously_and_inner_numbers_stay_in_the_message():
    _, _, log = run()
    steps = [(e.step, e.total, e.name) for e in log.events if e.step]
    assert {total for _, total, _ in steps} == {5}
    names = list(dict.fromkeys(name for _, _, name in steps))
    assert names == ["이미지 빌드", "공용 기반 확인", "연결 확인", "배포", "정리"]
    assert [step for step, _, _ in steps] == sorted(step for step, _, _ in steps)  # 거꾸로 가지 않는다
    assert any(e.name == "배포" and e.message.startswith("[3/8] ") for e in log.events)
    assert any(e.name == "공용 기반 확인" and e.message.startswith("[2/2] ") for e in log.events)


def test_an_onprem_deploy_skips_the_foundation_and_has_four_stages():
    result, parts, log = run(env=ONPREM_ENV, set_name="onprem")
    assert result.ok and parts.order == ["build", "check", "deploy", "prune"]
    assert "foundation" not in result.details and {e.total for e in log.events if e.step} == {4}


def test_without_a_terraform_runner_the_environment_is_used_as_given():
    result, parts, log = run(runner=False)
    assert result.ok and parts.order == ["build", "check", "deploy", "prune"]
    assert parts.checks[0].host == "1.1.1.1" and "foundation" not in result.details
    assert {e.total for e in log.events if e.step} == {4}


def test_the_dockerfile_path_comes_from_the_spec_and_defaults_to_dockerfile():
    _, parts, _ = run(spec=make(build={"dockerfile": "docker/Dockerfile.prod"}))
    assert parts.builds[0] == (SRC, "todo", SHA, "docker/Dockerfile.prod")
    _, parts, _ = run(spec=make())
    assert parts.builds[0][3] == "Dockerfile"


# --- 시작하기 전에 거르는 입력 오류 --------------------------------------------------------------------
NEED_SECRET = make(env=GENERATED["env"] + [{"name": "STRIPE_KEY", "secret": True, "generate": False}])


@pytest.mark.parametrize("kwargs, code", [
    ({"spec": {"port": 8080}}, "invalid_spec"),
    ({"spec": NEED_SECRET}, "missing_secret"),
    ({"sha": "xyz"}, "invalid_image_tag"),
    ({"spec": make(app="a" * 60)}, "invalid_spec"),
    ({"set_name": "aws-serverless"}, "set_not_supported"),  # 이 배포자에 없는 세트
    ({"set_name": "onprem"}, "set_not_supported"),  # aws 환경에 온프레미스 세트
    ({"env": ONPREM_ENV}, "set_not_supported"),  # 온프레미스 환경에 aws 세트
    ({"set_name": "no-such-set"}, "set_not_supported"),
])
def test_input_errors_are_found_before_anything_starts(kwargs, code):
    result, parts, log = run(**kwargs)
    assert not result.ok and result.error.code == code and result.details["stage"] == "spec"
    assert parts.order == [] and not any(e.step for e in log.events)  # 빌드도 기반 생성도 시작하지 않았다


def test_a_user_secret_that_is_provided_passes_the_check():
    result, parts, _ = run(spec=NEED_SECRET, secrets={"STRIPE_KEY": USER_SECRET})
    assert result.ok and parts.deploys[0][2] == {"STRIPE_KEY": USER_SECRET}


def test_an_invalid_sha_is_not_echoed_back_as_the_image_tag():
    result, _, _ = run(sha="../../x")
    assert result.image_tag is None


# --- 단계별 실패 --------------------------------------------------------------------------------
def build_fails(parts):
    parts.build_error = BuildError(err("docker_build_failed", "이미지 빌드가 실패했습니다."), tail="pip failed")


def foundation_fails(parts):
    parts.runner_reads = [TerraformError(err("access_denied", "역할을 맡을 수 없습니다."))]


def check_fails(parts):
    parts.check_result = CheckResult(ok=False, error=err("ssh_unreachable", "서버에 접속할 수 없습니다.", retryable=True))


def deploy_fails(parts):
    parts.deploy_result = DeployResult(ok=False, error=err("healthcheck_failed", "헬스체크 실패"), details={"stderr": "last lines"})


@pytest.mark.parametrize("setup, stage, code, ran", [
    (build_fails, "build", "docker_build_failed", ["build"]),
    (foundation_fails, "foundation", "access_denied", ["build", "read"]),
    (check_fails, "check", "ssh_unreachable", ["build", "read", "check"]),
    (deploy_fails, "deploy", "healthcheck_failed", ["build", "read", "check", "deploy"]),
])
def test_a_failure_stops_at_that_stage_and_names_it(setup, stage, code, ran):
    parts = Parts()
    setup(parts)
    result, parts, log = run(parts)
    assert not result.ok and result.details["stage"] == stage and result.error.code == code
    assert parts.order == ran  # 실패한 단계 뒤는 실행되지 않고, 정리(prune)도 하지 않는다
    assert result.image_tag == SHA and any(e.level == "error" for e in log.events)


def test_the_tail_of_a_failed_build_and_the_adapters_details_are_kept():
    parts = Parts()
    build_fails(parts)
    assert run(parts)[0].details["stderr"] == "pip failed"
    parts = Parts()
    deploy_fails(parts)
    assert run(parts)[0].details["stderr"] == "last lines"


def test_a_failed_foundation_apply_is_reported_as_the_foundation_stage():
    parts = Parts()
    parts.runner_reads = [MISSING, TerraformError(err("terraform_read_after_apply", "다시 읽지 못했습니다."))]
    result, parts, _ = run(parts)
    assert result.details["stage"] == "foundation" and parts.order == ["build", "read", "apply", "read"]


def test_an_unexpected_exception_becomes_a_pipeline_error_without_echoing_its_text():
    parts = Parts()
    parts.deploy_raises = RuntimeError(f"connection string password=hunter2 {USER_SECRET}")
    result, _, log = run(parts, secrets={"K": USER_SECRET})
    assert result.error.code == "deploy_pipeline_error" and result.details == {"exception": "RuntimeError", "stage": "deploy"}
    assert "hunter2" not in result.model_dump_json() and "hunter2" not in log.text()


# --- 정리 -------------------------------------------------------------------------------------
def test_a_failed_cleanup_never_fails_the_deploy_but_leaves_a_warning():
    parts = Parts()
    parts.prune_error = OSError("disk")
    result, _, log = run(parts)
    assert result.ok and result.details["pruned"] == []
    assert any(e.level == "warn" and e.name == "정리" for e in log.events)


# --- 비밀 ---------------------------------------------------------------------------------------
def test_user_secrets_are_masked_in_forwarded_logs_and_in_result_details():
    parts = Parts()
    parts.deploy_result = DeployResult(ok=False, error=err("healthcheck_failed", f"실패 {USER_SECRET}"),
                                       details={"stderr": f"echo {USER_SECRET}"})
    result, _, log = run(parts, secrets={"K": USER_SECRET})
    assert USER_SECRET not in log.text() and USER_SECRET not in result.model_dump_json()
    assert "***" in log.text() and "***" in result.details["stderr"]


def test_a_secret_inside_a_successful_adapter_result_is_masked_too():
    parts = Parts()
    parts.deploy_result = DeployResult(ok=True, url=URL, image_tag=SHA, details={"warnings": [f"사용한 값 {USER_SECRET}"]})
    result, _, _ = run(parts, secrets={"K": USER_SECRET})
    assert result.ok and USER_SECRET not in result.model_dump_json() and "***" in result.details["warnings"][0]


def test_a_successful_result_is_json_serializable_and_holds_no_secret():
    result, _, _ = run(secrets={"K": USER_SECRET})
    assert USER_SECRET not in result.model_dump_json()


def test_the_runner_and_the_foundation_settings_must_be_given_together():
    with pytest.raises(ValueError):
        Deployer({}, object(), runner=object())
    with pytest.raises(ValueError):
        Deployer({}, object(), foundation=SETTINGS)
