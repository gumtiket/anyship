import pytest
from pydantic import TypeAdapter, ValidationError

from anyship_adapters import (
    AdapterError,
    AwsEnvironment,
    CheckResult,
    DeployResult,
    Environment,
    LogEvent,
    OnpremEnvironment,
    SET_NAMES,
    StatusResult,
)

ROLE_ARN = "arn:aws:iam::123456789012:role/deploy-service-role"
EXTERNAL_ID = "a" * 32


def aws(**override):
    values = {"env_id": "demo", "role_arn": ROLE_ARN, "external_id": EXTERNAL_ID}
    return AwsEnvironment(**{**values, **override})


def onprem(**override):
    values = {"env_id": "demo", "host": "3.38.88.141"}
    return OnpremEnvironment(**{**values, **override})


def test_set_names_match_the_ai_side():
    assert set(SET_NAMES) == {"aws-serverless", "aws-always-on", "onprem"}


# --- environments ------------------------------------------------------------------
def test_aws_environment_defaults():
    env = aws()
    assert env.kind == "aws"
    assert env.region == "ap-northeast-2"


@pytest.mark.parametrize(
    "override",
    [
        {"role_arn": "arn:aws:iam::123:role/x"},  # account id must be 12 digits
        {"role_arn": "arn:aws:iam::123456789012:user/someone"},  # roles only
        {"external_id": "short"},  # at least 16 characters
        {"external_id": "has space inside the id!!"},
        {"env_id": "Demo"},  # lowercase only
        {"region": "mars"},
    ],
)
def test_aws_environment_rejects_bad_values(override):
    with pytest.raises(ValidationError):
        aws(**override)


@pytest.mark.parametrize("host", ["-oProxyCommand=x", "a b", "a;ls", "", "host name"])
def test_onprem_rejects_hosts_that_could_reach_a_command_line(host):
    with pytest.raises(ValidationError):
        onprem(host=host)


@pytest.mark.parametrize("override", [{"ssh_port": 0}, {"ssh_port": 70000}, {"ssh_user": "Root"}])
def test_onprem_rejects_bad_connection_values(override):
    with pytest.raises(ValidationError):
        onprem(**override)


def test_environment_union_picks_the_class_from_kind():
    adapter = TypeAdapter(Environment)
    assert isinstance(adapter.validate_python({"kind": "onprem", "env_id": "demo", "host": "h.example.com"}),
                      OnpremEnvironment)
    assert isinstance(adapter.validate_python({"kind": "aws", "env_id": "demo", "role_arn": ROLE_ARN,
                                               "external_id": EXTERNAL_ID}), AwsEnvironment)
    with pytest.raises(ValidationError):
        adapter.validate_python({"kind": "gcp", "env_id": "demo"})


def test_environments_reject_unknown_and_secret_looking_fields():
    with pytest.raises(ValidationError):
        # Split so secret scanners do not flag this fixture as a real key header.
        onprem(ssh_private_key="-----BEGIN " + "OPENSSH PRIVATE KEY" + "-----")
    with pytest.raises(ValidationError):
        aws(access_key="AKIA...")


def test_environments_are_immutable():
    env = aws()
    with pytest.raises(ValidationError):
        env.region = "us-east-1"


# --- log events ----------------------------------------------------------------------
def test_log_event_defaults_and_step_bounds():
    event = LogEvent(message="hello")
    assert event.level == "info" and event.ts.tzinfo is not None
    assert LogEvent(message="x", step=2, total=5, name="image transfer").step == 2
    with pytest.raises(ValidationError):
        LogEvent(message="x", step=6, total=5)
    with pytest.raises(ValidationError):
        LogEvent(message="x" * 2001)
    with pytest.raises(ValidationError):
        LogEvent(message="x", level="debug")


# --- results ---------------------------------------------------------------------------
def test_result_is_either_ok_or_failed_with_an_error():
    assert CheckResult(ok=True).error is None
    failure = CheckResult(ok=False, error=AdapterError(code="ssh_unreachable", message="cannot connect"))
    assert failure.error.code == "ssh_unreachable"
    with pytest.raises(ValidationError):
        CheckResult(ok=False)
    with pytest.raises(ValidationError):
        CheckResult(ok=True, error=AdapterError(code="oops", message="m"))


def test_error_code_must_be_machine_readable():
    for bad in ("Has Space", "UPPER", "1abc", "x"):
        with pytest.raises(ValidationError):
            AdapterError(code=bad, message="m")


def test_deploy_and_status_results_carry_their_extras():
    deployed = DeployResult(ok=True, url="https://todo-a1b2.demo.onprem.anyship.cloud", image_tag="3f2a9c1")
    assert deployed.url.startswith("https://")
    assert StatusResult(ok=True, state="running").state == "running"
    with pytest.raises(ValidationError):
        StatusResult(ok=True, state="flying")
