from pathlib import Path
from tempfile import TemporaryDirectory

from ai.build_context import BuildContext
from ai.detectors.repo import RepoView
from ai.output_session import register_context
from ai.transform.dockerfile import harden_dockerignore
from ai.transform.workspace import Workspace, source_files


def prepare_context(view: RepoView, diff: str, dockerfile: str) -> BuildContext:
    from ai.transform.service import identify_sample

    before = source_files(view)
    with Workspace(before) as workspace:
        workspace.apply(diff)
        names = set(before)
        names.update(
            p.relative_to(workspace.root).as_posix()
            for p in workspace.root.rglob("*.py")
            if ".git" not in p.parts
        )
        proposed = workspace.read(names)
    temporary = TemporaryDirectory(prefix="bronze-build-")
    context = BuildContext(root=temporary.name)
    context._temporary = temporary
    try:
        for name, text in proposed.items():
            path = Path(name)
            if path.suffix in {".db", ".sqlite", ".sqlite3", ".log"} or path.name.startswith(
                ".env"
            ):
                continue
            destination = Path(context.root) / (
                "Dockerfile.source" if name == "Dockerfile" else name
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(text.encode("utf-8"))
        (Path(context.root) / "Dockerfile").write_bytes(dockerfile.encode("utf-8"))
        (Path(context.root) / ".dockerignore").write_text(
            harden_dockerignore(proposed.get(".dockerignore", "")), encoding="utf-8", newline=""
        )
        context._sample_name = identify_sample(view)
        context._sealed_digest = context.tree_digest()
    except Exception:
        context.cleanup()
        raise
    register_context(context)
    return context
