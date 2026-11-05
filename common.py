"""Small helpers shared by the four pipeline scripts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterator

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
PATH_TEMPLATE_PARAM = re.compile(r"\{([^}/]+)\}")


def load_json(path: str | Path) -> dict[str, Any]:
    """Read a JSON document, failing with a readable message."""
    path = Path(path)
    if not path.exists():
        raise SystemExit(f"error: file not found: {path}")
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"error: {path} is not valid JSON ({exc.msg}, line {exc.lineno})")


def save_json(path: str | Path, document: dict[str, Any]) -> None:
    """Write a JSON document with stable formatting (UTF-8, 2-space indent)."""
    with Path(path).open("w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def iter_operations(document: dict[str, Any]) -> Iterator[tuple[str, str, dict[str, Any]]]:
    """Yield (path, method, operation) for every operation in the document."""
    for path, path_item in document.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() in HTTP_METHODS and isinstance(operation, dict):
                yield path, method.lower(), operation


def template_params(path: str) -> list[str]:
    """Return the parameter names used in a path template, e.g. /a/{id} -> ['id']."""
    return PATH_TEMPLATE_PARAM.findall(path)


def resolve_ref(document: dict[str, Any], node: Any) -> Any:
    """Resolve a local '#/...' $ref (one level at a time, until a non-ref node)."""
    seen: set[str] = set()
    while isinstance(node, dict) and isinstance(node.get("$ref"), str):
        ref = node["$ref"]
        if not ref.startswith("#/") or ref in seen:
            return node
        seen.add(ref)
        target: Any = document
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            if not isinstance(target, dict) or part not in target:
                return node
            target = target[part]
        node = target
    return node


def declared_params(
    document: dict[str, Any], path_item: dict[str, Any], operation: dict[str, Any]
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Return (raw, resolved) pairs for path-level and operation-level parameters."""
    pairs = []
    for raw in list(path_item.get("parameters", [])) + list(operation.get("parameters", [])):
        pairs.append((raw, resolve_ref(document, raw)))
    return pairs
