from pathlib import Path
from shutil import copytree

import pytest
import yaml

from ai.pipeline import run_analysis


def postgres_app(root: Path, *, driver=True, existing=None, migration=True):
    root.mkdir()
    (root / "app").mkdir()
    (root / "app/__init__.py").write_text("")
    (root / "app/main.py").write_text(
        "from fastapi import FastAPI\nfrom app.db import engine\napp = FastAPI()\n"
        '@app.get("/healthz")\ndef health():\n    return {"status": "ok"}\n'
    )
    (root / "app/db.py").write_text(
        "import os\nfrom sqlalchemy import create_engine\n"
        "from sqlalchemy.orm import DeclarativeBase\n"
        'engine = create_engine(os.environ["DATABASE_URL"])\n'
        "class Base(DeclarativeBase):\n    pass\n"
    )
    (root / "requirements.txt").write_text(
        "fastapi==0.115.6\nSQLAlchemy==2.0.36\n" + ("psycopg2-binary==2.9.10\n" if driver else "")
    )
    if migration:
        (root / "app/migrate.py").write_text(
            "from app.db import Base, engine\n"
            "def main():\n    Base.metadata.create_all(engine)\n"
            'if __name__ == "__main__":\n    main()\n'
        )
    if existing is not None:
        (root / "deploy-spec.yaml").write_text(existing)
    return root


def analyze(root, output):
    return run_analysis(root, out_dir=output, log=lambda *_: None, no_gate=True)


@pytest.mark.parametrize("existing", [None, "backing_services: []\n"])
def test_existing_postgres_is_bound_without_a_sqlite_conversion(tmp_path, existing):
    root = postgres_app(tmp_path / "repo", existing=existing)
    result = analyze(root, tmp_path / "out")
    assert not result.transformation.addressed_ids
    assert result.deploy_spec is not None
    assert [item.type for item in result.deploy_spec.backing_services] == ["postgres"]
    assert result.deploy_spec.release.migrate == "python -m app.migrate"
    assert all(item.name != "DATABASE_URL" for item in result.deploy_spec.env)
    assert result.transformation.needs_approval is False


def test_existing_binding_and_custom_migration_survive_reanalysis(tmp_path):
    original = (
        "backing_services:\n- type: postgres\n  bind_as: DATABASE_URL\n"
        "release:\n  migrate: alembic upgrade head\n"
    )
    root = postgres_app(tmp_path / "repo", driver=False, existing=original)
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    first = analyze(root, tmp_path / "first")
    assert first.deploy_spec.release.migrate == "alembic upgrade head"
    assert len(first.deploy_spec.backing_services) == 1
    assert before == {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    (root / "deploy-spec.yaml").write_text(Path(first.output_files["deploy-spec.yaml"]).read_text())
    second = analyze(root, tmp_path / "second")
    assert second.deploy_spec == first.deploy_spec


def test_database_type_is_not_guessed_from_variable_name(tmp_path):
    result = analyze(postgres_app(tmp_path / "repo", driver=False), tmp_path / "out")
    assert result.status == "failed"
    assert result.deploy_spec is None
    assert "postgres_binding_unresolved" in {w.code for w in result.packaging_warnings}


@pytest.mark.parametrize(
    "existing",
    [
        "backing_services: [",
        "backing_services: null\n",
        "backing_services:\n- type: postgres\n  bind_as: WRONG\n",
        "backing_services: []\nbacking_services: []\n",
        "backing_services:\n- type: object_storage\n  bind_as: STORAGE_URL\n",
        "release:\n  migrate: '   '\n",
        "release:\n  migrate: 123\n",
        "release:\n  migrate: ok\n  unexpected: value\n",
    ],
)
def test_invalid_existing_contract_is_not_silently_overwritten(tmp_path, existing):
    root = postgres_app(tmp_path / "repo", existing=existing)
    result = analyze(root, tmp_path / "out")
    assert result.status == "failed" and result.deploy_spec is None
    assert (root / "deploy-spec.yaml").read_text() == existing
    assert "existing_spec_invalid" in {w.code for w in result.packaging_warnings}


def test_sensitive_existing_migration_is_not_exported(tmp_path):
    secret = "unique-fixture-password-74"
    root = postgres_app(
        tmp_path / "repo",
        existing=(
            "release:\n  migrate: python migrate.py postgresql://user:"
            + secret
            + "@db.invalid/app\n"
        ),
    )
    result = analyze(root, tmp_path / "out")
    assert result.status == "failed" and result.deploy_spec is None
    assert all(secret not in p.read_text() for p in (tmp_path / "out").iterdir())


def test_unrelated_driver_and_migration_filename_do_not_add_resources(tmp_path):
    root = postgres_app(tmp_path / "repo", existing=None)
    (root / "app/main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    (root / "app/db.py").unlink()
    result = analyze(root, tmp_path / "out")
    assert result.deploy_spec.backing_services == []
    assert result.deploy_spec.release is None


def test_filename_alone_does_not_invent_a_migration(tmp_path):
    root = postgres_app(tmp_path / "repo")
    (root / "app/migrate.py").write_text("# Migration instructions only\n")
    result = analyze(root, tmp_path / "out")
    assert result.deploy_spec.release is None


def test_missing_migration_dependency_does_not_invent_a_release(tmp_path):
    root = postgres_app(tmp_path / "repo")
    (root / "app/main.py").write_text(
        "import os\nfrom fastapi import FastAPI\napp = FastAPI()\n"
        'DATABASE_URL = os.environ["DATABASE_URL"]\n'
    )
    (root / "app/db.py").unlink()
    result = analyze(root, tmp_path / "out")
    assert result.deploy_spec.backing_services[0].type == "postgres"
    assert result.deploy_spec.release is None


def test_generated_contract_injects_database_and_migration_in_adapter(tmp_path):
    from anyship_adapters.compose import render_stack
    from anyship_adapters.spec import parse_spec

    result = analyze(postgres_app(tmp_path / "repo"), tmp_path / "out")
    spec = yaml.safe_load(Path(result.output_files["deploy-spec.yaml"]).read_text())
    parsed = parse_spec(spec)
    assert parsed.postgres and parsed.migrate == "python -m app.migrate"
    stack = render_stack(spec, host="todo.example.org", image_tag="a" * 12)
    assert "DATABASE_URL:" in stack.compose_yaml
    assert "  db:" in stack.compose_yaml


def test_sqlite_conversion_can_be_analyzed_again_without_losing_resources(tmp_path):
    source = Path(__file__).resolve().parents[2] / "samples/todo"
    first = analyze(source, tmp_path / "first")
    try:
        root = tmp_path / "converted"
        copytree(first.build_context.root, root)
        (root / "deploy-spec.yaml").write_text(
            Path(first.output_files["deploy-spec.yaml"]).read_text()
        )
        second = analyze(root, tmp_path / "second")
        assert not any(v.rule == "sqlite_usage" for v in second.diagnosis.violations)
        assert second.deploy_spec.backing_services == first.deploy_spec.backing_services
        assert second.deploy_spec.release == first.deploy_spec.release
    finally:
        first.build_context.cleanup()


@pytest.mark.parametrize(
    "evidence",
    [
        "import psycopg2\n",
        "from psycopg import connect\n",
        'PREFIX = "postgresql+psycopg2://"\n',
    ],
)
def test_runtime_postgres_evidence_is_recognized_without_driver_declaration(tmp_path, evidence):
    root = postgres_app(tmp_path / "repo", driver=False)
    with (root / "app/db.py").open("a") as stream:
        stream.write(evidence)
    result = analyze(root, tmp_path / "out")
    assert result.deploy_spec.backing_services[0].type == "postgres"


@pytest.mark.parametrize(
    "path,source",
    [
        ("tests/test_db.py", "import psycopg2\n"),
        ("app/db.py", '"""postgresql:// is only a documentation example"""\n'),
        ("app/db.py", "import psycopg2\nimport pymysql\n"),
    ],
)
def test_test_only_or_ambiguous_evidence_does_not_guess_database(tmp_path, path, source):
    root = postgres_app(tmp_path / "repo", driver=False)
    (root / path).parent.mkdir(exist_ok=True)
    with (root / path).open("a") as stream:
        stream.write(source)
    result = analyze(root, tmp_path / "out")
    assert result.deploy_spec is None and result.status == "failed"


def test_required_unsupported_external_binding_blocks_packaging(tmp_path):
    root = postgres_app(tmp_path / "repo")
    with (root / "app/main.py").open("a") as stream:
        stream.write('import os\nREDIS_URL = os.environ["REDIS_URL"]\n')
    result = analyze(root, tmp_path / "out")
    assert result.status == "failed" and result.deploy_spec is None
    assert "external_binding_unresolved" in {w.code for w in result.packaging_warnings}


def test_database_used_only_in_tests_does_not_add_a_runtime_database(tmp_path):
    root = postgres_app(tmp_path / "repo")
    (root / "app/main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    (root / "app/db.py").unlink()
    (root / "conftest.py").write_text('import os\nDB = os.environ["DATABASE_URL"]\n')
    result = analyze(root, tmp_path / "out")
    assert result.deploy_spec.backing_services == []
    assert result.deploy_spec.release is None


def test_adapter_compatible_implicit_postgres_binding_is_preserved(tmp_path):
    root = postgres_app(
        tmp_path / "repo", driver=False, existing="backing_services:\n- type: postgres\n"
    )
    result = analyze(root, tmp_path / "out")
    assert result.deploy_spec.backing_services[0].bind_as == "DATABASE_URL"
