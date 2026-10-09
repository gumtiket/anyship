import ast
from pathlib import Path
from unittest.mock import Mock

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from ai.detectors import RepoView
from ai.gate.runner import DockerCliRunner, FakeRunner
from ai.models import Diagnosis, TransformReport
from ai.pipeline import run_analysis
from ai.security import SourceMasker
from ai.spec.cost_table import estimate_monthly
from ai.spec.env_policy import allowed_name
from ai.spec.models import Environment, Release
from ai.spec.service import generate_spec
from ai.transform.service import _patch_candidate
from ai.transform.workspace import make_diff

ROOT = Path(__file__).resolve().parents[2]


def repo(tmp_path, source):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "main.py").write_text("from fastapi import FastAPI\napp=FastAPI()\n" + source)
    (root / "requirements.txt").write_text("fastapi==0.115.0\n")
    return root


@pytest.mark.parametrize(
    "name",
    [
        "COMPOSE_PROJECT_NAME",
        "TRAEFIK_TOKEN",
        "LD_AUDIT",
        "POSTGRES",
        "POSTGRES_PASSWORD",
        "POSTGRESQL_TOKEN",
        "DATABASE_URL",
        "STORAGE_URL",
        "PATH",
        "HOME",
    ],
)
def test_c_reserved_names_rejected_by_model_and_schema(name):
    data = {"name": name, "value": "value"}
    assert not allowed_name(name)
    with pytest.raises(ValidationError):
        Environment.model_validate(data)
    assert list(Draft202012Validator(Environment.model_json_schema()).iter_errors(data))


@pytest.mark.parametrize(
    "name", ["POSTGRES_PASSWORD", "COMPOSE_TOKEN", "TRAEFIK_TOKEN", "LD_TOKEN"]
)
def test_reserved_secret_extraction_is_deferred_without_renaming(tmp_path, name):
    root = repo(tmp_path, f'{name}="dummy-secret-do-not-use"\n')
    before = (root / "main.py").read_bytes()
    result = run_analysis(root, out_dir=tmp_path / "out", log=lambda *_: None)
    assert result.transformation.deferred_ids
    assert not result.transformation.addressed_ids
    assert "environment_name_forbidden" in {w.code for w in result.transformation.warnings}
    assert not result.deploy_spec.env
    diff = Path(result.output_files["changes.diff"]).read_text()
    assert f'os.environ["{name}"]' not in diff
    assert (root / "main.py").read_bytes() == before


@pytest.mark.parametrize("value", ["x" * 1025, "don't", "a\nb", "a\rb"])
def test_invalid_plain_setting_is_omitted_with_warning(tmp_path, value):
    root = repo(tmp_path, f"import os\nMESSAGE=os.getenv('APP_MESSAGE', {value!r})\n")
    result = run_analysis(root, out_dir=tmp_path / "out", log=lambda *_: None)
    assert not result.deploy_spec.env
    assert "environment_value_unsafe" in {w.code for w in result.transformation.warnings}
    data = {"name": "APP_MESSAGE", "value": value}
    with pytest.raises(ValidationError):
        Environment.model_validate(data)
    assert list(Draft202012Validator(Environment.model_json_schema()).iter_errors(data))


def test_value_boundary_is_characters_not_bytes():
    assert Environment(name="MESSAGE", value="가" * 1024).value == "가" * 1024


@pytest.mark.parametrize("value", ["x" * 501, "python -m app.migrate\n", "cmd\rnext"])
def test_migration_line_and_length_limits(value):
    with pytest.raises(ValidationError):
        Release(migrate=value)
    assert list(Draft202012Validator(Release.model_json_schema()).iter_errors({"migrate": value}))


def test_migration_boundary():
    assert Release(migrate="x" * 500).migrate == "x" * 500


def test_invalid_migration_is_omitted_with_warning():
    transform = TransformReport(migrate_command="python -m app.migrate\nother")
    spec, _ = generate_spec("todo", "local://todo", None, "dev", Diagnosis(), transform, None)
    assert spec.release is None and transform.migrate_command is None
    assert "release_migrate_deferred" in {w.code for w in transform.warnings}


@pytest.mark.parametrize(
    "name,value,reason",
    [
        ("POSTGRES_TOKEN", "safe", "environment_name_forbidden"),
        ("APP_MESSAGE", "x" * 1025, "environment_value_unsafe"),
        ("APP_MESSAGE", "don't", "environment_value_unsafe"),
    ],
)
def test_llm_patch_cannot_introduce_forbidden_env(tmp_path, name, value, reason):
    root = repo(tmp_path, "MESSAGE='safe'\n")
    before = {"main.py": (root / "main.py").read_text()}
    after = {
        "main.py": before["main.py"].replace(
            "MESSAGE='safe'", f"import os\nMESSAGE=os.getenv({name!r}, {value!r})"
        )
    }
    with pytest.raises(ValueError, match=reason):
        _patch_candidate(
            before, make_diff(before, after), {"main.py"}, SourceMasker(RepoView(root))
        )


@pytest.mark.parametrize(
    "sample,env,selected",
    [
        ("todo", "aws", "aws-serverless"),
        ("todo-scheduler", "aws", "aws-always-on"),
        ("todo", "onprem", "onprem"),
    ],
)
def test_tfvars_contract_and_fixed_rationale(tmp_path, sample, env, selected):
    result = run_analysis(
        ROOT / "samples" / sample, target_env=env, out_dir=tmp_path / "out", log=lambda *_: None
    )
    try:
        assert result.recommendation.set == selected
        if selected == "aws-serverless":
            assert result.recommendation.tfvars == {"port": 8080, "memory_mb": 256, "timeout_s": 30}
            assert "C Lambda 세트 미정의" in result.recommendation.rationale
            assert "tfvars_schema" in result.recommendation.needs_confirmation
        else:
            assert result.recommendation.tfvars == {}
            assert "C: 앱별 tfvars 없음" in result.recommendation.rationale
            assert "tfvars_schema" not in result.recommendation.needs_confirmation
    finally:
        result.build_context.cleanup()


def test_shared_environment_cost_is_not_guessed_app_total():
    amount, assumptions = estimate_monthly("aws-always-on", memory_mb=512)
    assert amount is None
    text = " ".join(assumptions)
    assert all(
        s in text for s in ("t3.small", "db.t4g.micro", "20GB", "30GB", "탄력적 IP", "여러 앱")
    )


def test_transformed_database_url_preserves_ssl_query(tmp_path):
    result = run_analysis(ROOT / "samples/todo", out_dir=tmp_path / "out", log=lambda *_: None)
    try:
        tree = ast.parse((Path(result.build_context.root) / "app/db.py").read_text())
        call = next(
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "create_engine"
        )
        original = "postgresql://gate:dummy-secret-do-not-use@db/gate?sslmode=require"
        fake_os = Mock(environ={"DATABASE_URL": original})
        value = eval(
            compile(ast.Expression(call.args[0]), "url-expression", "eval"), {"os": fake_os}
        )
        assert make_url(value).drivername == "postgresql+psycopg2"
        assert make_url(value).query == make_url(original).query == {"sslmode": "require"}
    finally:
        result.build_context.cleanup()


def test_gate_migrates_in_started_app_and_retains_security_flags(tmp_path):
    fake = FakeRunner()
    result = run_analysis(
        ROOT / "samples/todo", out_dir=tmp_path / "out", runner=fake, log=lambda *_: None
    )
    try:
        steps = [s.name for s in result.gate_report.transformed.steps]
        assert steps.index("app_start") < steps.index("migrate") < steps.index("healthcheck")
        assert len(fake.exec_commands) == 1
        name, command = fake.exec_commands[0]
        assert name.endswith("-app") and command == ["python", "-m", "app.migrate"]
        assert not any("-migrate" in args for args in fake.commands)
        for args in fake.commands:
            assert args[args.index("--memory") + 1] == "512m"
            assert args[args.index("--cpus") + 1] == "1"
            assert "--read-only" in args and args[args.index("--tmpfs") + 1].startswith("/tmp:")
        assert not fake.containers and not fake.networks and not fake.images
    finally:
        result.build_context.cleanup()


def test_exec_cannot_target_unowned_container_or_host_shell():
    runner = DockerCliRunner()
    runner._call = Mock()
    with pytest.raises(ValueError, match="unowned"):
        runner.exec("other-app", ["python", "-m", "app.migrate"])
    runner.containers.add("bronze-gate-012345abcdef-app")
    with pytest.raises(ValueError, match="command_not_allowed"):
        runner.exec("bronze-gate-012345abcdef-app", ["sh", "-c", "anything"])
    runner._call.assert_not_called()
