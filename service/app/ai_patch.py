"""Apply reviewed text patches for GitHub publication, without importing the AI package."""
import os
import re
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from .ai_snapshot import safe_path

HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@(?:.*)$")


def patch_paths(diff, allowed):
    """Accept only add/edit unified diffs; Git validates the actual hunk contents."""
    if not diff or len(diff.encode("utf-8")) > 1024 * 1024:
        raise ValueError("invalid_patch_size")
    lines = diff.split("\n")
    paths, index = set(), 0
    while index < len(lines):
        if index == len(lines) - 1 and not lines[index]:
            break
        while index < len(lines) and lines[index].startswith(("diff --git ", "index ")):
            index += 1
        if index + 1 >= len(lines) or not lines[index].startswith("--- ") or not lines[index + 1].startswith("+++ b/"):
            raise ValueError("patch_headers_required")
        old = lines[index][4:].split("\t")[0]
        name = safe_path(lines[index + 1][6:].split("\t")[0])
        if (name not in allowed or name in paths or any(p.casefold() == ".git" for p in name.split("/"))
                or old not in ("/dev/null", "a/" + name)):
            raise ValueError("patch_path_not_allowed")
        paths.add(name)
        index += 2
        saw_hunk = False
        while index < len(lines) and (match := HUNK.fullmatch(lines[index])):
            saw_hunk = True
            before, after = (int(n) if n is not None else 1 for n in match.groups())
            index += 1
            while before or after:
                if index >= len(lines) or not lines[index] or lines[index][0] not in " +-":
                    raise ValueError("invalid_patch_hunk")
                prefix = lines[index][0]
                before -= prefix in " -"
                after -= prefix in " +"
                if before < 0 or after < 0:
                    raise ValueError("invalid_patch_hunk")
                index += 1
                if index < len(lines) and lines[index] == "\\ No newline at end of file":
                    index += 1
        if not saw_hunk:
            raise ValueError("patch_missing_hunk")
    if not paths:
        raise ValueError("patch_missing_hunk")
    return paths


def apply_patch(files, diff, paths):
    # Snapshot files are plain UTF-8 blobs. Preserve their bytes (including CRLF)
    # and avoid personal Git config, filters, hooks or repository-code execution.
    if patch_paths(diff, set(files) | paths) != paths:
        raise ValueError("patch_paths_mismatch")
    with TemporaryDirectory(prefix="anyship-patch-") as temporary:
        root = Path(temporary)
        seen = {}
        for name in set(files) | paths:
            safe_path(name)
            parts = name.split("/")
            if any(p.casefold() == ".git" for p in parts):
                raise ValueError("patch_path_not_allowed")
            for length in range(1, len(parts) + 1):
                prefix = "/".join(parts[:length])
                if seen.setdefault(prefix.casefold(), prefix) != prefix:
                    raise ValueError("case_colliding_paths")
        for name, source in files.items():
            destination = root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.encode("utf-8"))
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_ATTR_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")

        def git(*args, data=None):
            result = subprocess.run(["git", "-c", "core.autocrlf=false", *args], cwd=root,
                env=env, input=data, capture_output=True, timeout=20)
            if result.returncode:
                raise ValueError("patch_apply_failed")
            return result.stdout

        git("init", "--quiet", "--template=")
        data = diff.encode("utf-8")
        parsed = git("apply", "--numstat", "-z", "-", data=data)
        actual_paths = set()
        for entry in parsed.decode("utf-8").rstrip("\0").split("\0"):
            added, removed, name = entry.split("\t", 2)
            if not added.isdigit() or not removed.isdigit():
                raise ValueError("patch_binary_forbidden")
            actual_paths.add(name)
        if actual_paths != paths:
            raise ValueError("patch_paths_mismatch")
        git("apply", "--check", "--whitespace=nowarn", "-", data=data)
        git("apply", "--whitespace=nowarn", "-", data=data)
        return {name: (root / name).read_bytes().decode("utf-8") for name in sorted(paths)}
