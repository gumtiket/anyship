import json
from pathlib import Path

import pytest

from ai.detectors import RepoView, detect, detect_framework, detect_signals
from ai.pipeline import run_analysis

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def view(tmp_path, text, name="main.py"):
    file = tmp_path / name
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text)
    return RepoView(tmp_path)


@pytest.mark.parametrize(
    "rule,positive,negative",
    [
        ("sqlite_usage", 'URL = "sqlite:///./todo.db"', 'URL = "https://example.invalid"'),
        (
            "hardcoded_secret",
            'API_KEY = "dummy-secret-do-not-use"',
            'API_KEY = os.environ["API_KEY"]',
        ),
        (
            "file_log",
            'import logging as log\nlog.FileHandler("app.log")',
            "import logging\nlogging.StreamHandler()",
        ),
        (
            "fixed_port",
            'from uvicorn import run as serve\nserve("app:app", port=8000)',
            'import uvicorn\nuvicorn.run("app:app", port=int(os.environ["PORT"]))',
        ),
        ("local_file_write", 'open("./data/export.json", "w")', 'open("./data/export.json", "r")'),
        (
            "hardcoded_db_url",
            'URL = "postgresql://dummy:dummy-secret-do-not-use@db/todo"',
            'URL = os.environ["DATABASE_URL"]',
        ),
    ],
)
def test_rule_positive_and_negative(tmp_path, rule, positive, negative):
    assert rule in {v.rule for v in detect(view(tmp_path, positive))}
    assert rule not in {v.rule for v in detect(view(tmp_path, negative))}


def test_unpinned_dependency_rule_aggregates_per_manifest(tmp_path):
    actual = detect(view(tmp_path, "fastapi\nSQLAlchemy>=2\nuvicorn\n", "requirements.txt"))
    assert len(actual) == 1 and actual[0].rule == "unpinned_dependency"
    assert not detect(view(tmp_path, "fastapi==0.1\nSQLAlchemy==2.0\n", "requirements.txt"))


@pytest.mark.parametrize("spec", ["fastapi~=0.1", "fastapi==0.*", "fastapi>=0.1"])
def test_version_ranges_are_not_exact_pins(tmp_path, spec):
    assert detect(view(tmp_path, spec, "requirements.txt"))[0].rule == "unpinned_dependency"


def test_pyproject_dependency_detection(tmp_path):
    findings = detect(
        view(tmp_path, '[project]\ndependencies = ["fastapi", "pydantic==2.0"]', "pyproject.toml")
    )
    assert len(findings) == 1 and findings[0].rule == "unpinned_dependency"


def test_sqlite_is_not_counted_twice_and_secret_values_are_not_exported(tmp_path):
    repo = view(tmp_path, 'URL = "sqlite:///./todo.db"\nSECRET_KEY = "dummy-secret-do-not-use"')
    findings = detect(repo)
    assert {v.rule for v in findings} == {"sqlite_usage", "hardcoded_secret"}
    assert "dummy-secret-do-not-use" not in json.dumps(
        [v.model_dump(mode="json") for v in findings]
    )
    assert next(v for v in findings if v.rule == "sqlite_usage").change_class == "risky"


def test_database_credentials_are_not_exported_and_yaml_is_detected(tmp_path):
    findings = detect(
        view(
            tmp_path,
            'db_url: "postgresql://dummy:dummy-secret-do-not-use@db/todo"',
            "settings.yaml",
        )
    )
    assert [v.rule for v in findings] == ["hardcoded_db_url"]
    assert "dummy-secret-do-not-use" not in findings[0].model_dump_json()


def test_local_write_is_a_review_candidate_and_mkdir_is_not_a_finding(tmp_path):
    findings = detect(
        view(
            tmp_path,
            'from pathlib import Path\np = Path("data/file.txt")\n'
            'p.parent.mkdir()\np.write_text("hello")',
        )
    )
    assert len(findings) == 1
    assert findings[0].confidence == "needs_review"
    assert findings[0].change_class == "risky"
    assert not findings[0].auto_fixable


@pytest.mark.parametrize(
    "code,name",
    [
        ("from apscheduler.schedulers.background import BackgroundScheduler", "scheduler"),
        ("import schedule", "scheduler"),
        ("from celery import Celery", "scheduler"),
        ("import websockets", "websocket"),
        ('@app.websocket("/ws")\nasync def ws(): pass', "websocket"),
        ("import asyncio\nasyncio.sleep(60)", "long_request"),
        (
            "from starlette.responses import StreamingResponse\nStreamingResponse(iter([]))",
            "long_request",
        ),
        ('import requests\nrequests.get("https://example.invalid", timeout=60)', "long_request"),
    ],
)
def test_signals_with_evidence(tmp_path, code, name):
    signals = detect_signals(view(tmp_path, code))
    assert [s.name for s in signals] == [name]
    assert signals[0].file == "main.py" and signals[0].line > 0


def test_short_sleep_and_unused_fastapi_websocket_import_are_not_signals(tmp_path):
    assert not detect_signals(
        view(tmp_path, "from fastapi import WebSocket\nimport time\ntime.sleep(1)")
    )


@pytest.mark.parametrize(
    "code,grade",
    [
        ("from fastapi import FastAPI as API\napp = API()", "supported"),
        ("from fastapi import FastAPI\ndef create_app(): return FastAPI()", "partial"),
        ("from flask import Flask\napp = Flask(__name__)", "partial"),
        ("print('not a web app')", "unsupported"),
    ],
)
def test_framework_grades(tmp_path, code, grade):
    assert detect_framework(view(tmp_path, code)).support_grade == grade


def test_bad_python_is_reported_without_execution_or_source_leak(tmp_path):
    repo = view(tmp_path, 'SECRET_KEY = "dummy-secret-do-not-use"\nsyntax broken!!!')
    assert repo.warnings[0].code == "python_syntax_error"
    assert "dummy-secret-do-not-use" not in repo.warnings[0].message


def test_gitignore_nested_negation_binary_dotenv_and_symlinks(tmp_path):
    (tmp_path / ".gitignore").write_text("ignored.py\n*.txt\n!requirements.txt\n")
    for name in ("ignored.py", "kept.py", "other.txt", "requirements.txt", ".env"):
        (tmp_path / name).write_text("dummy-secret-do-not-use")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / ".gitignore").write_text("hidden.py\n")
    (nested / "hidden.py").write_text("pass")
    (tmp_path / "binary.dat").write_bytes(b"\0data")
    (tmp_path / "link.py").symlink_to(tmp_path / "kept.py")
    (tmp_path / "truth.expected.json").write_text("[]")
    repo = RepoView(tmp_path)
    assert "kept.py" in repo.files() and "requirements.txt" in repo.files()
    assert not set(repo.files()) & {
        "ignored.py",
        "other.txt",
        ".env",
        "binary.dat",
        "link.py",
        "truth.expected.json",
        "nested/hidden.py",
    }


@pytest.mark.parametrize("name", ["todo", "todo-scheduler"])
def test_sample_golden(name):
    repo = RepoView(SAMPLES / name)
    findings = detect(repo)
    expected = json.loads((SAMPLES / f"{name}.expected.json").read_text())
    assert {(v.rule, v.file) for v in findings} == {(v["rule"], v["file"]) for v in expected}
    assert len(findings) == len(expected) == 6
    assert detect_framework(repo).support_grade == "supported"
    assert {s.name for s in detect_signals(repo)} == (
        {"scheduler"} if name == "todo-scheduler" else set()
    )
    assert [v.model_dump(mode="json") for v in detect(repo)] == [
        v.model_dump(mode="json") for v in findings
    ]


def test_memo_app_is_unsupported():
    assert detect_framework(RepoView(SAMPLES / "memo-app")).support_grade == "unsupported"


@pytest.mark.parametrize("name", ["todo", "todo-scheduler"])
def test_pipeline_sample_diagnosis_no_llm_and_no_gate(tmp_path, name):
    result = run_analysis(SAMPLES / name, out_dir=tmp_path / "out", log=lambda *_: None)
    assert result.status == "diagnosed" and result.diagnosis.status == "completed"
    assert len(result.diagnosis.violations) == 6
    assert result.gate_report.status == "skipped"
    assert result.cost.total.calls == 0
    assert result.recommendation.status == "completed"
