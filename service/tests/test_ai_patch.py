import difflib

import pytest

from app.ai_patch import apply_patch, patch_paths


def diff_for(name, before, after):
    lines = difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile="a/" + name, tofile="b/" + name)
    return "".join(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n" for line in lines)


@pytest.mark.parametrize("newline", ["\n", "\r\n", ""])
def test_publication_preserves_unicode_and_exact_newlines(newline):
    name = "app/한글.py"
    before, after = "# 이전" + newline, "# 수정" + newline
    diff = diff_for(name, before, after)
    paths = patch_paths(diff, {name})
    assert apply_patch({name: before}, diff, paths) == {name: after}


def test_hunk_content_that_looks_like_headers_is_not_a_path():
    before, after = "-- old\n", "++ new\n"
    diff = diff_for("data.txt", before, after)
    assert patch_paths(diff, {"data.txt"}) == {"data.txt"}
    assert apply_patch({"data.txt": before}, diff, {"data.txt"}) == {"data.txt": after}


@pytest.mark.parametrize("diff", [
    "--- a/file.py\n+++ b/../escape.py\n@@ -1 +1 @@\n-old\n+new\n",
    "--- a/file.py\n+++ b/other.py\n@@ -1 +1 @@\n-old\n+new\n",
    "--- a/file.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-old\n",
    "diff --git a/file.py b/file.py\nold mode 100644\nnew mode 120000\n",
    "diff --git a/file.py b/file.py\nGIT binary patch\nliteral 0\n",
    "--- /dev/null\n+++ b/.git/config\n@@ -0,0 +1 @@\n+bad\n",
])
def test_publication_rejects_paths_deletion_renaming_modes_and_binary(diff):
    with pytest.raises(ValueError):
        patch_paths(diff, {"file.py", "other.py", ".git/config", "../escape.py"})


def test_publication_fails_if_patch_does_not_match_snapshot():
    diff = diff_for("file.py", "old\n", "new\n")
    with pytest.raises(ValueError, match="patch_apply_failed"):
        apply_patch({"file.py": "different\n"}, diff, {"file.py"})


def test_publication_rejects_case_colliding_new_paths():
    diff = "--- /dev/null\n+++ b/APP/new.py\n@@ -0,0 +1 @@\n+pass\n"
    with pytest.raises(ValueError, match="case_colliding_paths"):
        apply_patch({"app/main.py": "pass\n"}, diff, {"APP/new.py"})
