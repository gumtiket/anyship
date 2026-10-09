"""Publish a reviewed diff without running repository code or forcing Git refs."""
import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import HTTPException
from sqlalchemy import update

from .ai_snapshot import SHA, safe_path, snapshot, source_digest
from .db import AIAnalysis
from .github_api import GitHubFailure


def create_branch(github, token, repository, row):
    if row.work_branch == row.base_branch or github.ref(token, repository, row.work_branch) is not None:
        raise HTTPException(409, "작업 브랜치가 이미 존재합니다. 새 분석을 요청해 주세요.")
    try:
        github.create_ref(token, repository, row.work_branch, row.base_sha)
    except GitHubFailure as error:
        # Reconcile only an ambiguous transport/server outcome, never claim a collision.
        if error.status != 502 or github.ref(token, repository, row.work_branch) != row.base_sha:
            raise
    if github.ref(token, repository, row.work_branch) != row.base_sha:
        raise HTTPException(409, "작업 브랜치의 기준 커밋이 일치하지 않습니다.")
    row.branch_created = True


def changes_tree(github, token, repository, row):
    from ai.transform.workspace import Workspace, patch_paths

    with TemporaryDirectory(prefix="anyship-publish-") as temporary:
        root = Path(temporary) / "source"
        tree, manifest, _ = snapshot(github, token, repository, row.base_sha, root)
        if tree != row.base_tree or source_digest(manifest) != row.source_digest:
            raise HTTPException(409, "분석한 코드와 스냅샷이 일치하지 않습니다. 새 분석을 요청해 주세요.")
        files = {name: (root / name).read_bytes().decode("utf-8") for name in manifest}
        paths = patch_paths(row.diff, set(files) | {".dockerignore", "app/migrate.py"})
        if not paths or paths != set(json.loads(row.result_json)["bundle"]["paths"]):
            raise HTTPException(409, "검토한 수정 파일 목록이 일치하지 않습니다.")
        entries = github.recursive_tree(token, repository, tree)
        if entries.get("sha") != tree or entries.get("truncated"):
            raise ValueError("invalid_tree")
        existing = {entry["path"]: entry for entry in entries["tree"]}
        for name in paths:
            safe_path(name)
            # An omitted binary/private file must never be replaced as a 'new' file.
            if name in existing and (name not in manifest or existing[name]["sha"] != manifest[name]):
                raise HTTPException(409, "분석에서 제외된 파일을 변경할 수 없습니다.")
            if name.startswith(".github/workflows/"):
                raise HTTPException(409, "GitHub Actions 워크플로 변경은 현재 지원하지 않습니다.")
        with Workspace(files) as workspace:
            workspace.apply(row.diff)
            changed = workspace.read(paths)
        return [{"path": name, "mode": existing[name]["mode"] if name in existing else "100644",
                 "type": "blob", "content": changed[name]} for name in sorted(paths)]


def lock_publication(session, row, lease_token):
    # A write, rather than just SELECT FOR UPDATE, also serializes SQLite tests.
    # Keep this transaction open across the final GitHub ref update, so expiry,
    # retries and deletion cannot interleave after the ownership check.
    changed = session.execute(update(AIAnalysis).where(AIAnalysis.id == row.id,
        AIAnalysis.status == "publishing", AIAnalysis.publish_token == lease_token,
        AIAnalysis.lease_until > int(time.time())).values(publish_token=lease_token))
    if changed.rowcount != 1:
        raise HTTPException(409, "커밋 저장 시간이 만료되었습니다. 같은 수정안으로 다시 요청해 주세요.")
    session.refresh(row)


def publish(session, github, token, project, row, lease_token):
    repository = project.full_name
    if not row.work_branch or row.work_branch == row.base_branch:
        raise HTTPException(409, "기준 브랜치에는 수정안을 저장할 수 없습니다.")
    head = github.ref(token, repository, row.work_branch)
    if head != row.base_sha and (not row.commit_sha or head != row.commit_sha):
        raise HTTPException(409, "작업 브랜치가 변경되거나 삭제되었습니다. 새 분석을 요청해 주세요.")
    if not row.commit_sha:
        entries = changes_tree(github, token, repository, row)
        tree_sha = github.create_changes_tree(token, repository, row.base_tree, entries)
        if not SHA.fullmatch(tree_sha):
            raise ValueError("invalid_tree_sha")
        commit_sha = github.create_commit(token, repository, row.base_sha, tree_sha,
            f"{'test' if row.provider == 'fake' else 'feat'}: apply AnyShip {row.provider} analysis\n\nAnyShip analysis: {row.id}")
        if not SHA.fullmatch(commit_sha):
            raise ValueError("invalid_commit_sha")
        lock_publication(session, row, lease_token)
        row.commit_sha = commit_sha
        session.commit()  # Persist the recovery checkpoint BEFORE updating a visible branch.
    lock_publication(session, row, lease_token)
    head = github.ref(token, repository, row.work_branch)
    if head != row.commit_sha:
        if head != row.base_sha:
            raise HTTPException(409, "작업 브랜치에 다른 변경이 있습니다. 새 분석을 요청해 주세요.")
        try:
            github.update_ref(token, repository, row.work_branch, row.commit_sha)
        except GitHubFailure:
            if github.ref(token, repository, row.work_branch) != row.commit_sha:
                raise
        if github.ref(token, repository, row.work_branch) != row.commit_sha:
            raise HTTPException(409, "GitHub 커밋 반영을 확인하지 못했습니다. 같은 요청을 다시 시도해 주세요.")
    row.status, row.error, row.active_project_id = "published", "", None
    row.lease_until, row.publish_token, row.finished_at = 0, "", int(time.time())
    logs = json.loads(row.logs_json)
    logs.append({"ts": int(time.time()), "message": "검토한 수정안을 새 작업 브랜치에 커밋했습니다."})
    row.logs_json = json.dumps(logs, ensure_ascii=False)
    session.commit()
