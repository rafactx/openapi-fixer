#!/usr/bin/env python3
"""Step 4 - Generic lint-and-fix pass, then full OpenAPI validation.

Step 3 fixes the problems someone reviewed. This step is the safety net for the
ones nobody listed: it walks *every* operation and applies rules that are always
safe, then validates the result with ``openapi-spec-validator``. It exits non-zero
if anything is still wrong, so it can gate a CI job or a docs deploy.

Rules (all idempotent):
    R1 no-request-body    GET/HEAD/DELETE must not carry a requestBody      -> removed
    R2 phantom-path-param path parameters missing from the URL template      -> removed
    R3 missing-path-param URL template variables with no declared parameter  -> added
                          (a matching components.parameters entry is reused when present)
    R4 path-param-required path parameters must have required: true          -> set
    R5 component-names    component keys must match ^[A-Za-z0-9._-]+$        -> reported
    R6 operation-ids      operationIds must be unique                        -> reported
    R7 summaries          every operation should have a summary              -> warning

Usage:
    python 4_final_verification.py openapi.json [--no-validate]
"""

from __future__ import annotations

import argparse
import re
import sys
from typing import Any

from common import declared_params, iter_operations, load_json, resolve_ref, save_json, template_params

VALID_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
NO_BODY_METHODS = ("get", "head", "delete")


class FinalVerifier:
    def __init__(self, document: dict[str, Any]) -> None:
        self.doc = document
        self.fixes: list[str] = []
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def _component_param(self, name: str) -> dict[str, Any] | None:
        for key, param in self.doc.get("components", {}).get("parameters", {}).items():
            if param.get("name") == name and param.get("in") == "path":
                return {"$ref": f"#/components/parameters/{key}"}
        return None

    def fix_operations(self) -> None:
        for path, method, operation in iter_operations(self.doc):
            label = f"{method.upper()} {path}"
            path_item = self.doc["paths"][path]

            # R1
            if method in NO_BODY_METHODS and "requestBody" in operation:
                del operation["requestBody"]
                self.fixes.append(f"R1 {label}: removed requestBody")

            # R2 (only operation-level params; path-level ones are shared)
            expected = template_params(path)
            params = operation.get("parameters", [])
            kept = []
            for raw in params:
                resolved = resolve_ref(self.doc, raw)
                if resolved.get("in") == "path" and resolved.get("name") not in expected:
                    self.fixes.append(f"R2 {label}: removed path parameter {resolved.get('name')!r}")
                    continue
                kept.append(raw)
            if params:
                operation["parameters"] = kept

            # R3
            declared = {
                resolved.get("name")
                for _raw, resolved in declared_params(self.doc, path_item, operation)
                if resolved.get("in") == "path"
            }
            for name in expected:
                if name in declared:
                    continue
                param = self._component_param(name) or {
                    "name": name,
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
                operation.setdefault("parameters", []).append(param)
                how = "reused " + param["$ref"] if "$ref" in param else "added a stub"
                self.fixes.append(f"R3 {label}: declared {{{name}}} ({how})")

            # R4
            for raw, resolved in declared_params(self.doc, path_item, operation):
                if resolved.get("in") == "path" and resolved.get("required") is not True:
                    resolved["required"] = True
                    self.fixes.append(f"R4 {label}: {resolved.get('name')!r} marked required")

    def check_document(self) -> None:
        # R5
        for section, entries in self.doc.get("components", {}).items():
            for name in entries if isinstance(entries, dict) else {}:
                if not VALID_NAME.match(name):
                    self.errors.append(f"R5 components.{section}: invalid name {name!r}")
        # R6, R7
        seen: dict[str, str] = {}
        for path, method, operation in iter_operations(self.doc):
            label = f"{method.upper()} {path}"
            op_id = operation.get("operationId")
            if op_id in seen:
                self.errors.append(f"R6 {label}: operationId {op_id!r} also used by {seen[op_id]}")
            elif op_id:
                seen[op_id] = label
            if not operation.get("summary"):
                self.warnings.append(f"R7 {label}: no summary")

    def validate(self) -> None:
        try:
            from openapi_spec_validator import validate
        except ImportError:
            self.errors.append("openapi-spec-validator is not installed (pip install -r requirements.txt)")
            return
        try:
            validate(self.doc)
        except Exception as exc:  # the validator raises several exception types
            first_line = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            self.errors.append(f"openapi-spec-validator: {first_line[:300]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Step 4: generic fixes and validation.")
    parser.add_argument("openapi", help="OpenAPI JSON file, rewritten in place when fixed")
    parser.add_argument("--no-validate", action="store_true", help="skip openapi-spec-validator")
    args = parser.parse_args()

    print(f"[4/4] final verification of {args.openapi}")
    verifier = FinalVerifier(load_json(args.openapi))
    verifier.fix_operations()
    verifier.check_document()
    if not args.no_validate and not verifier.errors:
        verifier.validate()

    for line in verifier.fixes:
        print(f"  fixed {line}")
    for line in verifier.warnings:
        print(f"  warn  {line}")
    for line in verifier.errors:
        print(f"  error {line}")
    if verifier.fixes:
        save_json(args.openapi, verifier.doc)

    if verifier.errors:
        print(f"  FAILED: {len(verifier.errors)} error(s)")
        return 1
    validated = "" if args.no_validate else ", valid OpenAPI " + verifier.doc.get("openapi", "?")
    print(f"  ok: {len(verifier.fixes)} fix(es){validated}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
