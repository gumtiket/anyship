"""Preserve both deployed main and legacy AI schemas while joining their history."""
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import MetaData, Table, create_engine, inspect, select, text
from sqlalchemy.orm import Session

from app.db import AIAnalysis, Base, DeployJob, Deployment, Project, User, Workspace
from tests.test_real_deployment_migration import environment

HEAD = "0010_merge_ai_deployments"


def migration(database_url):
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["database_url"] = database_url
    return config


def snapshot(engine):
    """Remember every existing column and row without assuming the new schema."""
    result = {}
    with engine.connect() as connection:
        for name in inspect(connection).get_table_names():
            if name == "alembic_version":
                continue
            table = Table(name, MetaData(), autoload_with=connection)
            result[name] = (table, set(connection.execute(select(table))))
    return result


@pytest.mark.parametrize("previous", ["0007", "0008", "0009"])
def test_upgrade_preserves_main_and_legacy_ai_rows(database_url, previous):
    config = migration(database_url)
    command.upgrade(config, previous)
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            session.add_all([User(id="u1", github_id=1, login="u", name="기존 사용자"),
                             Workspace(id="w1", name="기존 워크스페이스")])
            session.flush()
            session.add(Project(id="p1", workspace_id="w1", repository_id=1, installation_id=1,
                full_name="owner/repo", branch="main", base_sha="a" * 40, created_by="u1", created_at=1))
            session.commit()
            if previous == "0008":
                session.add(environment("a", env_id="existing", host="example.test", db_port=5432))
                session.flush()
                session.add(Deployment(project_id="p1", aws_environment_id="a", set_name="aws-always-on",
                    image_tag="b" * 40, url="https://example.test", active_job_id="job"))
                session.add(DeployJob(id="job", project_id="p1", request_id="request", runtime_id="runtime",
                    action="deploy", set_name="aws-always-on", status="succeeded", created_at=1))
            elif previous == "0009":
                session.add(AIAnalysis(id="analysis", project_id="p1", request_id="request", status="publish_failed",
                    base_sha="a" * 40, base_branch="main", work_branch="anyship/ai-existing", branch_created=True,
                    commit_sha="b" * 40, review_hash="c" * 64, diff="preserved diff 한글", created_at=1))
            session.commit()
        before = snapshot(engine)
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert list(connection.execute(text("SELECT version_num FROM alembic_version")).scalars()) == [HEAD]
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
            for table, rows in before.values():
                assert set(connection.execute(select(table))) == rows
        assert ScriptDirectory.from_config(config).get_heads() == [HEAD]
    finally:
        engine.dispose()


def test_fresh_database_gets_both_schemas(database_url):
    config = migration(database_url)
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
    finally:
        engine.dispose()


def test_ambiguous_legacy_ai_0008_stops_before_changing_schema(database_url):
    config = migration(database_url)
    command.upgrade(config, "0008_ai_analyses")
    engine = create_engine(database_url)
    try:
        # Reproduce the old AI-only revision identity, not main's deployment schema.
        with engine.begin() as connection:
            connection.execute(text("UPDATE alembic_version SET version_num = '0008'"))
        tables = set(inspect(engine).get_table_names())
        before = snapshot(engine)
        with pytest.raises(RuntimeError, match="Legacy AI revision 0008 requires schema verification"):
            command.upgrade(config, "head")
        assert set(inspect(engine).get_table_names()) == tables
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0008"
            for table, rows in before.values():
                assert set(connection.execute(select(table))) == rows
    finally:
        engine.dispose()
