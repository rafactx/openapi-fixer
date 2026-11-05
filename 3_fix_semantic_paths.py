#!/usr/bin/env python3
"""Step 3 - Apply reviewed, targeted fixes to specific operations.

Some problems cannot be fixed by a generic rule because the right answer depends
on what the endpoint really does: a DELETE that carries a body should probably take
its IDs as a query parameter instead; a ``name`` declared as a *path* parameter on
``/brands`` was meant to be a filter. Those decisions live in a corrections file
(YAML or JSON), so a new fix is a reviewed config change, not new Python.

Supported actions:
    REMOVE_KEY        delete ``key`` from the operation (e.g. requestBody)
    REMOVE_PARAMETER  drop parameters matching ``match`` (name/in, $refs resolved)
    ADD_PARAMETER     append ``parameter`` unless an equivalent one already exists
    SET_KEY           set ``key`` to ``value`` on the operation

Every action is idempotent: running the step twice changes nothing the second time.

Usage:
    python 3_fix_semantic_paths.py openapi.json --config corrections.yaml [--verbose]
    python 3_fix_semantic_paths.py --export-config corrections-template.yaml
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from common import declared_params, iter_operations, load_json, resolve_ref, save_json, template_params

TEMPLATE: dict[str, Any] = {
    "corrections": [
        {
            "id": "delete-without-body",
            "description": "DELETE requests must not carry a body.",
            "path": "/v1/{workspaceId}/things/{thingId}",
            "method": "delete",
            "action": "REMOVE_KEY",
            "key": "requestBody",
        },
        {
            "id": "drop-phantom-param",
            "description": "'name' is declared as a path parameter but is not in the URL.",
            "path": "/v1/{workspaceId}/things",
            "method": "get",
            "action": "REMOVE_PARAMETER",
            "match": {"name": "name", "in": "path"},
        },
        {
            "id": "declare-workspace-id",
            "description": "The URL uses {workspaceId} but the operation never declares it.",
            "path": "/v1/{workspaceId}/things/{thingId}",
            "method": "get",
            "action": "ADD_PARAMETER",
            "parameter": {"$ref": "#/components/parameters/WorkspaceId"},
        },
    ]
}


class SemanticFixer:
    def __init__(self, document: dict[str, Any], corrections: list[dict[str, Any]], verbose: bool):
        self.doc = document
        self.corrections = corrections
        self.verbose = verbose
        self.applied = 0
        self.skipped = 0
        self.not_found = 0

    def _same_param(self, a: Any, b: Any) -> bool:
        ra, rb = resolve_ref(self.doc, a), resolve_ref(self.doc, b)
        return (ra.get("name"), ra.get("in")) == (rb.get("name"), rb.get("in"))

    def _matches(self, param: Any, match: dict[str, Any]) -> bool:
        resolved = resolve_ref(self.doc, param)
        return all(resolved.get(key) == value for key, value in match.items())

    def apply(self, correction: dict[str, Any]) -> None:
        cid = correction.get("id", "?")
        path, method = correction["path"], correction["method"].lower()
        operation = self.doc.get("paths", {}).get(path, {}).get(method)
        if not isinstance(operation, dict):
            print(f"  warn: [{cid}] {method.upper()} {path} not found, skipped")
            self.not_found += 1
            return

        action = correction["action"].upper()
        changed = False
        if action == "REMOVE_KEY":
            changed = operation.pop(correction["key"], None) is not None
        elif action == "SET_KEY":
            if operation.get(correction["key"]) != correction["value"]:
                operation[correction["key"]] = copy.deepcopy(correction["value"])
                changed = True
        elif action == "REMOVE_PARAMETER":
            params = operation.get("parameters", [])
            kept = [p for p in params if not self._matches(p, correction["match"])]
            changed = len(kept) != len(params)
            operation["parameters"] = kept
        elif action == "ADD_PARAMETER":
            new = correction["parameter"]
            params = operation.setdefault("parameters", [])
            if not any(self._same_param(p, new) for p in params):
                params.append(copy.deepcopy(new))
                changed = True
        else:
            raise SystemExit(f"error: [{cid}] unknown action {action!r}")

        if changed:
            self.applied += 1
            print(f"  fixed [{cid}] {action} on {method.upper()} {path}")
        else:
            self.skipped += 1
            if self.verbose:
                print(f"  ok    [{cid}] already applied")

    def remaining_issues(self) -> list[str]:
        """Report (do not fix) generic problems left for step 4."""
        issues = []
        for path, method, operation in iter_operations(self.doc):
            path_item = self.doc["paths"][path]
            declared = {
                resolved.get("name")
                for _raw, resolved in declared_params(self.doc, path_item, operation)
                if resolved.get("in") == "path"
            }
            expected = set(template_params(path))
            for name in sorted(expected - declared):
                issues.append(f"{method.upper()} {path}: path parameter {{{name}}} not declared")
            for name in sorted(declared - expected):
                issues.append(f"{method.upper()} {path}: path parameter {name!r} not in URL")
            if method == "delete" and "requestBody" in operation:
                issues.append(f"DELETE {path}: has a requestBody")
        return issues

    def run(self) -> None:
        for correction in self.corrections:
            self.apply(correction)


def load_corrections(path: str) -> list[dict[str, Any]]:
    text = Path(path).read_text(encoding="utf-8")
    data = json.loads(text) if path.endswith(".json") else yaml.safe_load(text)
    return (data or {}).get("corrections", [])


def main() -> int:
    parser = argparse.ArgumentParser(description="Step 3: apply targeted semantic fixes.")
    parser.add_argument("openapi", nargs="?", help="OpenAPI JSON file, rewritten in place")
    parser.add_argument("--config", "-c", help="corrections file (YAML or JSON)")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--export-config", metavar="FILE", help="write a template corrections file")
    args = parser.parse_args()

    if args.export_config:
        Path(args.export_config).write_text(
            yaml.safe_dump(TEMPLATE, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        print(f"template written to {args.export_config}")
        return 0
    if not args.openapi or not args.config:
        parser.error("openapi and --config are required (or use --export-config)")

    print(f"[3/4] targeted fixes on {args.openapi} ({args.config})")
    fixer = SemanticFixer(load_json(args.openapi), load_corrections(args.config), args.verbose)
    fixer.run()
    save_json(args.openapi, fixer.doc)
    print(
        f"  applied: {fixer.applied}, already applied: {fixer.skipped}, "
        f"target not found: {fixer.not_found}"
    )
    for issue in fixer.remaining_issues():
        print(f"  note: left for step 4: {issue}")
    print("  ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
