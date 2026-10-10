"""배포할 소스를 가져오는 부품. 지금은 서비스 서버의 폴더에 이미 받아 둔 소스만 쓴다(`LocalFolderSource`).

나중에 GitHub tarball을 받아 푸는 구현이 같은 `SourceProvider` 자리에 들어온다. 소스 루트에 `Dockerfile`과 `deploy-spec.yaml`이
있다고 가정한다(AI가 서비스에 연결되기 전의 시험용 가정). 소스 폴더는 읽기만 하고 수정하지 않는다. 빌더가 임시 복사본에서 빌드한다.

커밋 SHA는 파일 내용으로 정한다. 폴더에서 `git`을 실행하지 않는다(사용자가 둔 `.git/config`가 명령을 실행하게 만들 수 있고,
커밋하지 않은 수정이 있으면 HEAD가 실제 내용을 말해 주지 못한다). 이미지 빌더가 복사하지 않는 파일(`.git`, `.env*`)은 해시에도 넣지 않는다.
"""
import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

import yaml

_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,99}$")
MAX_BYTES = 200 * 1024 * 1024  # 이미지 빌더의 소스 한도와 같다
MAX_ENTRIES = 20000
MAX_SPEC_BYTES = 64 * 1024
_SKIP_DIRS = {".git", "__pycache__"}


class SourceError(Exception):
    """소스를 쓸 수 없을 때. 문구에는 서버의 경로를 싣지 않는다."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass(frozen=True)
class SourceResult:
    path: Path  # 소스 폴더(읽기 전용으로 취급한다)
    commit_sha: str  # 7~40자리 16진수. 이미지 태그가 된다
    spec: Mapping[str, Any]  # deploy-spec.yaml의 내용(형식 검증은 Deployer가 한다)


class SourceProvider(Protocol):
    def fetch(self, full_name: str) -> SourceResult: ...


class LocalFolderSource:
    def __init__(self, root: Path):
        self._root = Path(root)

    def fetch(self, full_name: str) -> SourceResult:
        name = full_name.rsplit("/", 1)[-1]
        if not _NAME.match(name) or name in (".", ".."):
            raise SourceError("source_not_found", "이 저장소의 소스 폴더를 찾을 수 없습니다.")
        root = self._root.resolve()
        folder = root / name
        if folder.is_symlink() or not folder.is_dir() or folder.resolve().parent != root:
            raise SourceError("source_not_found", "이 저장소의 소스 폴더를 찾을 수 없습니다.")
        for required in ("Dockerfile", "deploy-spec.yaml"):
            entry = folder / required
            if entry.is_symlink() or not entry.is_file():
                raise SourceError("source_incomplete", f"소스 폴더의 루트에 {required} 파일이 필요합니다.")
        return SourceResult(folder, _fingerprint(folder), _read_spec(folder / "deploy-spec.yaml"))


def _read_spec(path: Path) -> Mapping[str, Any]:
    if path.stat().st_size > MAX_SPEC_BYTES:
        raise SourceError("source_incomplete", "deploy-spec.yaml이 너무 큽니다.")
    try:
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError):
        raise SourceError("source_incomplete", "deploy-spec.yaml을 읽을 수 없습니다.") from None
    if not isinstance(spec, dict):
        raise SourceError("source_incomplete", "deploy-spec.yaml은 항목들의 목록이 아니라 매핑이어야 합니다.")
    return spec


def _fingerprint(folder: Path) -> str:
    """경로 순서가 정해진 해시. 내용, 실행 권한, 링크 대상이 바뀌면 달라진다. 링크는 따라가지 않는다."""
    digest, total, count = hashlib.sha256(), 0, 0
    for directory, dirs, files in os.walk(folder, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".env"))
        for entry in sorted(files + [d for d in dirs if os.path.islink(os.path.join(directory, d))]):
            if entry.startswith(".env"):
                continue
            path = os.path.join(directory, entry)
            relative = os.path.relpath(path, folder).replace(os.sep, "/")
            count += 1
            if count > MAX_ENTRIES:
                raise SourceError("source_too_large", "소스의 파일이 너무 많습니다.")
            if os.path.islink(path):
                digest.update(b"L\0" + relative.encode() + b"\0" + os.readlink(path).encode() + b"\0")
                continue
            info = os.stat(path)
            total += info.st_size
            if total > MAX_BYTES:
                raise SourceError("source_too_large", "소스가 너무 큽니다.")
            digest.update(b"F\0" + relative.encode() + b"\0" + (b"x" if info.st_mode & 0o111 else b"-"))
            with open(path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(chunk)
            digest.update(b"\0")
    return digest.hexdigest()[:12]
