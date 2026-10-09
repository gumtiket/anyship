"""여러 테스트가 같이 쓰는 가짜 서버와 가짜 프로세스. 실제 SSH나 Docker는 쓰지 않는다."""
import io
import shlex
import subprocess
from pathlib import Path


class FakeServer:
    """가짜 SSH 실행기: 서버의 파일을 딕셔너리로 흉내 내고, 받은 명령을 기록한다.

    responses  {명령의 앞부분(튜플): (종료 코드, stdout, stderr)}. 앞부분이 맞는 명령은 이 값으로 답한다.
    """

    def __init__(self, fail_path_suffix=None, responses=None):
        self.files: dict[str, bytes] = {}
        self.commands: list[list[str]] = []
        self.kwargs: list[dict] = []
        self.responses: dict[tuple, tuple] = dict(responses or {})
        self._fail_suffix = fail_path_suffix

    def __call__(self, cmd, **kwargs):
        remote = shlex.split(cmd[-1])
        self.commands.append(remote)
        self.kwargs.append(kwargs)
        for prefix, (code, out, err) in self.responses.items():
            if tuple(remote[:len(prefix)]) == prefix:
                return subprocess.CompletedProcess(cmd, code, stdout=out, stderr=err)
        if remote[0] == "cat":
            found = remote[1] in self.files
            return subprocess.CompletedProcess(cmd, 0 if found else 1,
                                               stdout=self.files.get(remote[1], b""), stderr=b"")
        if remote[:2] == ["sh", "-c"]:  # SshRunner.put이 만든 파일 쓰기 명령
            path = remote[4]
            if self._fail_suffix and path.endswith(self._fail_suffix):
                return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"disk full")
            self.files[path] = kwargs["input"]
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    def written(self):
        return [Path(p).name for p in self.files]

    def last(self):
        return self.commands[-1]


class FakePopen:
    """로컬 `docker save`를 흉내 낸다."""

    def __init__(self, cmd, *, code=0, image=b"IMAGE-BYTES", errors=b"", **kwargs):
        self.cmd, self.kwargs, self.code, self.killed = cmd, kwargs, code, False
        self.stdout, self.stderr = io.BytesIO(image), io.BytesIO(errors)

    def kill(self):
        self.killed = True

    def wait(self):
        return self.code
