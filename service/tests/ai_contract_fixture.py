"""Explicit Service test double; this never replaces production AI execution."""
import difflib
from pathlib import Path


def worker_response(request, directory):
    source = Path(request["source"])
    name = next(name for name in sorted(request["manifest"]) if name.endswith(".py"))
    original = (source / name).read_bytes().decode("utf-8")
    changes = {name: (original, "# Service contract fixture: 한글\n" + original),
               ".dockerignore": ("", "__pycache__/\n")}
    chunks = []
    for path, (before, after) in changes.items():
        for line in difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                fromfile="a/" + path if path in request["manifest"] else "/dev/null", tofile="b/" + path):
            chunks.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    return {"diff": "".join(chunks), "result": {
        "contract_status": "service_test_double", "analysis_status": "diagnosed",
        "llm_mode": request["provider"], "base_sha": request["base_sha"],
        "gate": {"status": "skipped", "pr_eligible": False},
        "bundle": {"id": "all-changes", "paths": sorted(changes), "patch_valid": True},
    }}
