import ast
from pathlib import PurePosixPath

from ai.detectors.repo import RepoView, aliases, qualified
from ai.models import FrameworkDetection


def detect_framework(repo: RepoView) -> FrameworkDetection:
    frameworks = set()
    entrypoints = []
    for file, tree in repo.modules():
        if "tests" in PurePosixPath(file).parts or PurePosixPath(file).name.startswith("test_"):
            continue
        imports = aliases(tree)
        frameworks.update(
            value.split(".")[0]
            for value in imports.values()
            if value.split(".")[0] in {"fastapi", "flask", "django", "starlette"}
        )
        for node in tree.body:
            value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
            if isinstance(value, ast.Call) and qualified(value.func, imports) == "fastapi.FastAPI":
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        module = str(PurePosixPath(file).with_suffix("")).replace("/", ".")
                        if all(part.isidentifier() for part in module.split(".")):
                            entrypoints.append(f"{module}:{target.id}")
    if frameworks == {"fastapi"} and entrypoints:
        return FrameworkDetection(
            support_grade="supported",
            framework="fastapi",
            entrypoint=sorted(entrypoints)[0],
            reason="FastAPI 전역 앱 진입점을 정적으로 확인했습니다.",
        )
    if frameworks:
        return FrameworkDetection(
            support_grade="partial",
            framework=",".join(sorted(frameworks)),
            reason="다른 프레임워크·혼합 앱·미확인 진입점입니다. 변환 지원은 미확정입니다.",
        )
    return FrameworkDetection(
        support_grade="unsupported", reason="지원 가능한 FastAPI 앱 진입점을 찾지 못했습니다."
    )
