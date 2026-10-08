import subprocess

from github.changes import commit_changes, stage_changes


def test_stage_and_commit_real_repository(tmp_path):
    def git(*args):
        result = subprocess.run(
            ["git", *args],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    git("init")
    (tmp_path / "example.txt").write_text("first change", encoding="utf-8")
    assert "example.txt" in stage_changes(tmp_path)
    commit_changes(tmp_path)
    assert git("status", "--porcelain") == ""
    assert git("show", "HEAD:example.txt") == "first change"
    assert stage_changes(tmp_path) == ""
