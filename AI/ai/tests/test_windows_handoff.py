"""Offline service handoff preserves LF/CRLF bytes on every host."""
import pytest

from ai.gate.runner import DockerCliRunner, RunnerError
from ai.pipeline import _write_output
from ai.transform.workspace import Workspace, make_diff


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_patch_and_output_preserve_original_bytes(tmp_path, newline):
    before = {"main.py": f"value = 1{newline}"}
    after = {"main.py": f"value = 2{newline}"}
    diff = make_diff(before, after)
    output = tmp_path / "changes.diff"
    _write_output(output, diff)
    assert output.read_bytes() == diff.encode("utf-8")
    with Workspace(before) as workspace:
        assert (workspace.root / "main.py").read_bytes() == before["main.py"].encode()
        workspace.apply(output.read_bytes().decode())
        assert workspace.read({"main.py"}) == after
        assert workspace.compile()


def test_real_docker_gate_fails_explicitly_on_non_posix(monkeypatch):
    runner = DockerCliRunner()
    monkeypatch.setattr("ai.gate.runner.os.name", "nt")
    with pytest.raises(RunnerError, match="docker_gate_requires_posix"):
        runner.preflight()
