"""Read a bounded, immutable GitHub source snapshot. Never clone or execute it."""
import base64
import hashlib
import json
import re
import time
from pathlib import PurePosixPath

SHA = re.compile(r"^[0-9a-f]{40}$")
MAX_FILES = 200
MAX_FILE_BYTES = 524288
MAX_TOTAL_BYTES = 5 * 1024 * 1024
EXCLUDED = {".git", ".aws", ".ssh", ".venv", "venv", "node_modules", "__pycache__", "build", "dist", "out"}
PRIVATE_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".db", ".sqlite", ".sqlite3", ".log")
RESERVED = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\.|$)", re.I)


class SnapshotError(ValueError):
    """The code is an allowlisted diagnostic; no remote response is retained."""


def safe_path(name):
    if not isinstance(name, str) or not name or len(name) > 200:
        raise SnapshotError("invalid_source_path")
    parts = name.split("/")
    if (len(parts) > 16 or any(p in ("", ".", "..") or p.endswith((" ", ".")) or RESERVED.match(p) for p in parts)
            or any(ord(c) < 32 or c in '<>:"\\|?*' for c in name)
            or PurePosixPath(name).is_absolute()):
        raise SnapshotError("invalid_source_path")
    return name


def git_blob_sha(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def source_digest(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def snapshot(github, token, repository, base_sha, destination):
    if not SHA.fullmatch(base_sha):
        raise SnapshotError("invalid_base_sha")
    deadline = time.monotonic() + 60
    commit = github.git_commit(token, repository, base_sha)
    tree_sha = commit.get("tree", {}).get("sha", "")
    if commit.get("sha") != base_sha or not SHA.fullmatch(tree_sha):
        raise SnapshotError("commit_mismatch")
    tree = github.recursive_tree(token, repository, tree_sha)
    entries = tree.get("tree")
    if tree.get("sha") != tree_sha or tree.get("truncated") or not isinstance(entries, list) or len(entries) > 5000:
        raise SnapshotError("incomplete_source_tree")
    candidates, seen, excluded = [], {}, 0
    for entry in entries:
        name = safe_path(entry.get("path"))
        # Include parent prefixes so case-sensitive directories cannot alias on Windows.
        for i in range(1, len(name.split("/")) + 1):
            prefix = "/".join(name.split("/")[:i])
            old = seen.setdefault(prefix.casefold(), prefix)
            if old != prefix:
                raise SnapshotError("case_colliding_paths")
        kind, mode = entry.get("type"), entry.get("mode")
        if kind == "tree" and mode == "040000":
            continue
        if kind != "blob" or mode not in ("100644", "100755"):
            raise SnapshotError("unsupported_source_entry")
        parts = name.lower().split("/")
        if any(p in EXCLUDED or p.startswith(".env") for p in parts) or name.lower().endswith(PRIVATE_SUFFIXES):
            excluded += 1
            continue
        size = entry.get("size")
        if type(size) is not int or not 0 <= size <= MAX_FILE_BYTES or not SHA.fullmatch(entry.get("sha", "")):
            raise SnapshotError("source_file_limit")
        candidates.append(entry)
    if len(candidates) > MAX_FILES or sum(e["size"] for e in candidates) > MAX_TOTAL_BYTES:
        raise SnapshotError("source_size_limit")
    destination.mkdir()
    manifest = {}
    for entry in candidates:
        if time.monotonic() > deadline:
            raise SnapshotError("source_timeout")
        blob = github.blob(token, repository, entry["sha"])
        content = blob.get("content", "")
        if (blob.get("sha") != entry["sha"] or blob.get("encoding") != "base64"
                or blob.get("size") != entry["size"] or not isinstance(content, str)
                or len(content) > 2 * MAX_FILE_BYTES):
            raise SnapshotError("blob_mismatch")
        try:
            data = base64.b64decode("".join(content.split()), validate=True)
        except (ValueError, TypeError):
            raise SnapshotError("blob_mismatch") from None
        if len(data) != entry["size"] or git_blob_sha(data) != entry["sha"]:
            raise SnapshotError("blob_mismatch")
        try:
            data.decode("utf-8")
        except UnicodeError:
            excluded += 1
            continue
        if b"\0" in data:
            excluded += 1
            continue
        target = destination / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise SnapshotError("duplicate_source_path")
        target.write_bytes(data)
        manifest[entry["path"]] = entry["sha"]
    return tree_sha, manifest, excluded
