"""Resolve static Python import aliases without importing the inspected application."""

import ast


def aliases(tree: ast.AST) -> dict[str, str]:
    result = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                result[item.asname or item.name.split(".")[0]] = (
                    item.name if item.asname else item.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            for item in node.names:
                result[item.asname or item.name] = f"{node.module}.{item.name}"
    return result


def qualified(node: ast.AST, imports: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return imports.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        return qualified(node.value, imports) + "." + node.attr
    return ""
