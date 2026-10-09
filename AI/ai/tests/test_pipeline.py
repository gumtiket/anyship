import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from ai.pipeline import OUTPUT_NAMES, run_analysis
from ai.stages import Stage


def test_pipeline_outputs_placeholders_without_touching_input_or_calling_dependencies(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "main.py"
    source.write_text("raise RuntimeError('must not execute')\n")
    db = repo / "todo.db"
    db.write_bytes(b"dummy-db-do-not-use")
    before = {file.name: file.read_bytes() for file in repo.iterdir()}
    llm, runner = Mock(), Mock()
    logs = []
    result = run_analysis(
        repo,
        out_dir=tmp_path / "out",
        llm=llm,
        runner=runner,
        log=lambda stage, message: logs.append((stage, message)),
    )
    assert {file.name: file.read_bytes() for file in repo.iterdir()} == before
    assert set(result.output_files) == set(OUTPUT_NAMES)
    assert result.model_dump(mode="json")["status"] == "unsupported"
    assert result.diagnosis.support_grade == "unsupported"
    assert result.gate_report.status == "skipped"
    assert not llm.mock_calls and not runner.mock_calls
    assert logs[-1][0] == Stage.FAILED
    for name in OUTPUT_NAMES:
        assert (tmp_path / "out" / name).is_file()


def test_cli_from_other_working_directory(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    command = [sys.executable, "-m", "ai", "analyze", str(repo), "--env", "onprem", "--out", "out"]
    run = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True)
    assert run.returncode == 1, run.stderr
    assert "규칙 진단" in run.stdout
    assert set(p.name for p in (tmp_path / "out").iterdir()) == set(OUTPUT_NAMES)
    assert json.loads((tmp_path / "out" / "gate-report.json").read_text())["status"] == "skipped"


def test_cli_rejects_missing_repo(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ai",
            "analyze",
            str(tmp_path / "missing"),
            "--out",
            str(tmp_path / "out"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert not (tmp_path / "out").exists()


def test_output_inside_repo_is_rejected_before_writes(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(ValueError, match="원본 보호"):
        run_analysis(repo, out_dir=repo / "out")
    assert not (repo / "out").exists()


def test_symlink_output_file_cannot_overwrite_source(tmp_path):
    repo, output = tmp_path / "repo", tmp_path / "out"
    repo.mkdir()
    output.mkdir()
    original = repo / "main.py"
    original.write_text("dummy-original")
    (output / "Dockerfile").symlink_to(original)
    with pytest.raises(ValueError, match="심볼릭"):
        run_analysis(repo, out_dir=output)
    assert original.read_text() == "dummy-original"
    assert list(output.iterdir()) == [output / "Dockerfile"]


def test_hardlinked_output_and_repeat_run_preserve_original(tmp_path):
    repo, output = tmp_path / "repo", tmp_path / "out"
    repo.mkdir()
    output.mkdir()
    original = repo / "main.py"
    original.write_text("dummy-original")
    os.link(original, output / "Dockerfile")
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    with pytest.raises(ValueError, match="output_not_empty"):
        run_analysis(repo, out_dir=output, log=lambda *_: None)
    assert original.read_text() == "dummy-original"
    assert before == {p.name: p.read_bytes() for p in output.iterdir()}


def test_no_fixed_external_project_paths_in_runtime_code():
    sources = Path(__file__).resolve().parents[1] / "src" / "ai"
    for file in sources.rglob("*.py"):
        assert "/Users/" not in file.read_text(), file
