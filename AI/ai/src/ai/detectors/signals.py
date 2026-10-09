import ast

from ai.detectors.repo import RepoView, aliases, qualified
from ai.models import Signal
from ai.spec.tfvars_schema import MVP_REQUEST_LIMIT_SECONDS

LONG_REQUEST_THRESHOLD = MVP_REQUEST_LIMIT_SECONDS


def detect_signals(repo: RepoView) -> list[Signal]:
    found = {}
    for file, tree in repo.modules():
        imports = aliases(tree)
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            kind = None
            evidence = ""
            if any(name.split(".")[0] in {"apscheduler", "celery", "schedule"} for name in names):
                kind, evidence = (
                    "scheduler",
                    "스케줄러/작업 라이브러리 import. 실제 실행 위치는 검토가 필요합니다.",
                )
            elif any(name.split(".")[0] == "websockets" for name in names):
                kind, evidence = "websocket", "WebSocket 라이브러리 import 신호입니다."
            if isinstance(node, ast.Call):
                name = qualified(node.func, imports)
                if name.endswith(".websocket"):
                    kind, evidence = "websocket", "WebSocket 엔드포인트 선언 신호입니다."
                elif (
                    name in {"time.sleep", "asyncio.sleep"}
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, (int, float))
                    and node.args[0].value > LONG_REQUEST_THRESHOLD
                ):
                    kind, evidence = (
                        "long_request",
                        "긴 sleep 리터럴 신호. 요청 시간을 측정한 값이 아닙니다.",
                    )
                elif name.endswith(".StreamingResponse") or any(
                    k.arg in {"timeout", "timeout_seconds"}
                    and isinstance(k.value, ast.Constant)
                    and isinstance(k.value.value, (int, float))
                    and k.value.value > LONG_REQUEST_THRESHOLD
                    for k in node.keywords
                ):
                    kind, evidence = (
                        "long_request",
                        "스트리밍/긴 timeout 신호. 실제 요청 시간은 미확인입니다.",
                    )
            if kind:
                key = kind, file
                signal = Signal(name=kind, file=file, line=node.lineno, evidence=evidence)
                if key not in found or signal.line < found[key].line:
                    found[key] = signal
    return sorted(found.values(), key=lambda s: (s.name, s.file, s.line))
