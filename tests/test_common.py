"""Unit tests for the helpers in common.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from common import (
    declared_params,
    iter_operations,
    load_json,
    resolve_ref,
    save_json,
    template_params,
)


def test_template_params() -> None:
    assert template_params("/v1/{workspaceId}/malls/{mallId}") == ["workspaceId", "mallId"]
    assert template_params("/health") == []


def test_iter_operations_skips_non_operations() -> None:
    doc = {
        "paths": {
            "/a": {"GET": {"operationId": "a"}, "parameters": [], "summary": "path-level"},
            "/b": {"post": {"operationId": "b"}, "delete": "not a dict"},
            "/c": "not a path item",
        }
    }
    assert [(p, m, op["operationId"]) for p, m, op in iter_operations(doc)] == [
        ("/a", "get", "a"),
        ("/b", "post", "b"),
    ]


def test_resolve_ref_follows_chains_and_escapes() -> None:
    doc = {
        "components": {
            "parameters": {
                "Alias": {"$ref": "#/components/parameters/Id"},
                "Id": {"name": "id", "in": "path"},
            }
        },
        "paths": {"/a/{id}": {"x": 1}},
    }
    assert resolve_ref(doc, {"$ref": "#/components/parameters/Alias"}) == {
        "name": "id",
        "in": "path",
    }
    assert resolve_ref(doc, {"$ref": "#/paths/~1a~1{id}"}) == {"x": 1}


@pytest.mark.parametrize(
    "node",
    [
        {"$ref": "#/components/parameters/Missing"},
        {"$ref": "other.yaml#/Thing"},
        {"$ref": "#/components/parameters/Loop"},
    ],
)
def test_resolve_ref_returns_node_when_unresolvable(node: dict) -> None:
    doc = {"components": {"parameters": {"Loop": {"$ref": "#/components/parameters/Loop"}}}}
    result = resolve_ref(doc, node)
    assert "$ref" in result


def test_declared_params_merges_path_and_operation_level() -> None:
    doc = {"components": {"parameters": {"Id": {"name": "id", "in": "path"}}}}
    path_item = {"parameters": [{"$ref": "#/components/parameters/Id"}]}
    operation = {"parameters": [{"name": "q", "in": "query"}]}
    resolved = [r for _raw, r in declared_params(doc, path_item, operation)]
    assert resolved == [{"name": "id", "in": "path"}, {"name": "q", "in": "query"}]


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    target = tmp_path / "doc.json"
    save_json(target, {"title": "Café"})
    assert target.read_text("utf-8") == '{\n  "title": "Café"\n}\n'
    assert load_json(target) == {"title": "Café"}


def test_load_json_errors_are_readable(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="file not found"):
        load_json(tmp_path / "missing.json")
    broken = tmp_path / "broken.json"
    broken.write_text("{", "utf-8")
    with pytest.raises(SystemExit, match="not valid JSON"):
        load_json(broken)
