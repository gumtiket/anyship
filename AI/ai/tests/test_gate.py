import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from ai.build_context import BuildContext
from ai.cli import main
from ai.gate.runner import CommandResult, DockerCliRunner, FakeRunner, RunnerError
from ai.gate.security import APP_ENV, DB_ENV, SECURITY_FLAGS, run_args, validate_run_args
from ai.gate.service import run_gate, safe_log, tree_tag
from ai.pipeline import run_analysis
from ai.stages import Stage

ROOT = Path(__file__).resolve().parents[2]
NETWORK = "bronze-gate-012345abcdef-net"


def arguments(image="bronze-ai-gate:gate-" + "a" * 24):
    return run_args(
        image=image, name="bronze-gate-012345abcdef-app", network=NETWORK, env={}, command=[]
    )


@pytest.mark.parametrize(
    "flag,value",
    [
        ("--privileged", None),
        ("-p", "8080:8080"),
        ("--publish", "8080"),
        ("-v", "/tmp:/app"),
        ("--mount", "type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock"),
        ("--env-file", ".env"),
        ("--pid", "host"),
        ("--network=host", None),
        ("--read-only=false", None),
        ("--user=0", None),
        ("--entrypoint", "sh"),
    ],
)
def test_validator_rejects_every_unrecognized_docker_option(flag, value):
    args = arguments()
    args[1:1] = [flag] + ([value] if value is not None else [])
    with pytest.raises(ValueError):
        validate_run_args(args, internal_networks={NETWORK}, allowed_env=APP_ENV)


@pytest.mark.parametrize(
    "flag",
    [
        "--read-only",
        "--tmpfs",
        "--cap-drop",
        "--security-opt",
        "--memory",
        "--cpus",
        "--pids-limit",
        "--user",
        "--network",
    ],
)
def test_missing_required_security_option_is_rejected(flag):
    args = arguments()
    index = args.index(flag)
    del args[index : index + (1 if flag == "--read-only" else 2)]
    with pytest.raises(ValueError):
        validate_run_args(args, internal_networks={NETWORK}, allowed_env=APP_ENV)


def test_root_duplicate_overrides_and_parent_env_are_rejected(monkeypatch):
    args = arguments()
    index = args.index("--user")
    args[index + 1] = "0"
    with pytest.raises(ValueError, match="nonroot"):
        validate_run_args(args, internal_networks={NETWORK}, allowed_env=APP_ENV)
    args = arguments()
    args[1:1] = ["--network", "host"]
    with pytest.raises(ValueError, match="duplicate"):
        validate_run_args(args, internal_networks={NETWORK}, allowed_env=APP_ENV)
    monkeypatch.setenv("FAKE_SERVICE_SECRET", "dummy-service-do-not-use")
    assert "FAKE_SERVICE_SECRET" not in " ".join(arguments())
    args = arguments()
    args[1:1] = ["--env", "FAKE_SERVICE_SECRET=dummy-service-do-not-use"]
    with pytest.raises(ValueError, match="environment"):
        validate_run_args(args, internal_networks={NETWORK}, allowed_env=APP_ENV)


def test_real_runner_rejects_unsafe_request_before_docker_invocation():
    runner = DockerCliRunner()
    runner._call = Mock()
    with pytest.raises(ValueError):
        runner.run(image="ubuntu:latest", name="arbitrary", network="host", env={}, command=[])
    runner._call.assert_not_called()


def test_same_content_tag_is_locked_and_preexisting_images_are_preserved(tmp_path, monkeypatch):
    monkeypatch.setattr("ai.gate.runner.gettempdir", lambda: str(tmp_path))
    tag = "bronze-ai-gate:gate-" + "a" * 24
    owner = DockerCliRunner()
    owner._call = Mock(
        side_effect=[CommandResult(code=1), CommandResult(code=0), CommandResult(code=0)]
    )
    assert owner.build(tmp_path, tag).code == 0
    other = DockerCliRunner()
    other._call = Mock(return_value=CommandResult(code=0))
    with pytest.raises(RunnerError, match="image_in_use"):
        other.build(tmp_path, tag)
    other._call.assert_not_called()
    other.image_remove(tag)
    assert tag in owner.images
    owner.image_remove(tag)
    assert not owner.image_locks
    with pytest.raises(RunnerError, match="already_exists"):
        other.build(tmp_path, tag)
    other.image_remove(tag)
    assert other._call.call_count == 1


def test_fake_gate_sequence_flags_and_cleanup(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_SERVICE_SECRET", "dummy-service-do-not-use")
    fake = FakeRunner()
    result = run_analysis(
        ROOT / "samples/todo", out_dir=tmp_path / "out", runner=fake, log=lambda *_: None
    )
    report = result.gate_report
    assert report.runner == "fake" and report.status == "skipped" and not report.pr_eligible
    assert report.transformed.status == "passed" and report.original.status == "failed"
    assert report.original.matched_patterns
    assert [s.name for s in report.transformed.steps] == [
        "preflight",
        "build",
        "network",
        "postgres",
        "postgres_ready",
        "migrate",
        "app_start",
        "healthcheck",
        "postgres_crud",
    ]
    assert not fake.networks and not fake.containers and not fake.images
    for args in fake.commands:
        network = args[args.index("--network") + 1]
        validate_run_args(args, internal_networks={network}, allowed_env=APP_ENV | DB_ENV)
        assert "FAKE_SERVICE_SECRET" not in " ".join(args)
        assert all(flag in args for flag in SECURITY_FLAGS)
    passwords = [
        env["POSTGRES_PASSWORD"] for env in fake.envs.values() if "POSTGRES_PASSWORD" in env
    ]
    dumped = json.dumps(report.model_dump(mode="json"))
    assert passwords and all(password not in dumped for password in passwords)
    result.build_context.cleanup()


@pytest.mark.parametrize(
    "failure", ["preflight", "build", "network", "postgres", "migrate", "health"]
)
def test_each_failure_is_reported_and_resources_are_cleaned(tmp_path, failure):
    result = run_analysis(ROOT / "samples/todo", out_dir=tmp_path / "out", log=lambda *_: None)
    fake = FakeRunner(fail_at=failure)
    logs = []
    report = run_gate(
        result.build_context,
        result.deploy_spec,
        fake,
        lambda stage, message: logs.append((stage, message)),
        timeout_s=2,
        sleep=lambda _: None,
    )
    assert logs[-1][0] == Stage.FAILED
    assert report.status == "failed" and report.transformed.status == "failed"
    assert not fake.networks and not fake.containers and not fake.images
    result.build_context.cleanup()


def test_untrusted_or_modified_context_is_never_executed(tmp_path):
    fake = FakeRunner()
    result = run_analysis(ROOT / "samples/todo", out_dir=tmp_path / "out", log=lambda *_: None)
    tag = tree_tag(result.build_context)
    assert tag == tree_tag(result.build_context)
    report = run_gate(BuildContext(root=str(tmp_path)), result.deploy_spec, fake, lambda *_: None)
    assert report.status == "skipped" and not fake.events
    (Path(result.build_context.root) / "app/main.py").write_text("raise RuntimeError('changed')")
    report = run_gate(result.build_context, result.deploy_spec, fake, lambda *_: None)
    assert report.status == "skipped" and not fake.events
    result.build_context.cleanup()


def test_log_masking_and_size_limit():
    dummy_password = "dummy-password-do-not-use"
    logs = "\n".join(
        ["line"] * 300 + [f"postgresql://gate:{dummy_password}@db/gate", dummy_password]
    )
    masked = safe_log(logs, [dummy_password])
    assert dummy_password not in masked and len(masked.splitlines()) <= 200
    assert "postgresql://[REDACTED]@db/gate" in masked


def test_cli_releases_build_context_on_success(tmp_path, monkeypatch):
    result = run_analysis(ROOT / "samples/todo", out_dir=tmp_path / "out", log=lambda *_: None)
    root = Path(result.build_context.root)
    monkeypatch.setattr("ai.cli.run_analysis", lambda *args, **kwargs: result)
    assert main(["analyze", str(ROOT / "samples/todo")]) == 0
    assert not root.exists()


def test_original_database_and_log_files_are_not_read(tmp_path, monkeypatch):
    import shutil

    repo = tmp_path / "sample"
    shutil.copytree(ROOT / "samples/todo", repo)
    for name in ("original.db", "original.db-wal", "original.log"):
        (repo / name).write_bytes(b"dummy-runtime-data-do-not-use")
    original_read = Path.read_bytes

    def guarded_read(path):
        assert path.name not in {"original.db", "original.db-wal", "original.log"}
        return original_read(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read)
    result = run_analysis(repo, out_dir=tmp_path / "out", runner=FakeRunner(), log=lambda *_: None)
    assert result.gate_report.transformed.status == "passed"
    result.build_context.cleanup()


@pytest.mark.docker
@pytest.mark.parametrize("sample", ["todo", "todo-scheduler"])
def test_live_sample_postgres_and_original_failure(tmp_path, sample):
    runner = DockerCliRunner()
    result = run_analysis(
        ROOT / "samples" / sample, out_dir=tmp_path / "out", runner=runner, log=lambda *_: None
    )
    try:
        report = result.gate_report
        assert report.status == "passed", report.model_dump(mode="json")
        assert report.transformed.status == "passed"
        assert report.original.status == "failed" and report.original.matched_patterns
        assert not runner.containers and not runner.networks and not runner.images
        assert not report.pr_eligible
    finally:
        if result.build_context:
            result.build_context.cleanup()
