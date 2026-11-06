#!/usr/bin/env python3
"""Step 2 - Fix component names and every $ref that points at them.

Code generators happily emit component names such as ``"Store V1"`` (taken from
``@Schema(name = "Store V1")``). OpenAPI requires component keys to match
``^[a-zA-Z0-9._-]+$``, and many tools break on them: some refs come out raw
(``#/components/schemas/Store V1``), others URL-encoded (``Store%20V1``).

Two phases:
    1. rename every invalid key in components.* (``Store V1`` -> ``StoreV1``),
       refusing to continue if two names would collide
    2. rewrite every $ref in the document (raw or percent-encoded) to the new name,
       then verify that no local $ref is left dangling

Usage:
    python 2_fix_schema_names_and_refs.py openapi.json [--verbose] [--camel-case]
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable
from typing import Any
from urllib.parse import unquote

from common import VALID_COMPONENT_NAME, load_json, save_json

COMPONENT_SECTIONS = (
    "schemas",
    "responses",
    "parameters",
    "examples",
    "requestBodies",
    "headers",
    "securitySchemes",
    "links",
    "callbacks",
)


def strip_invalid(name: str) -> str:
    """Default normaliser: drop every character OpenAPI does not allow."""
    return re.sub(r"[^A-Za-z0-9._-]", "", name)


def camel_case(name: str) -> str:
    """Alternative normaliser: 'store patch v3' -> 'StorePatchV3'."""
    return strip_invalid("".join(word[:1].upper() + word[1:] for word in name.split()))


class ComponentRenamer:
    def __init__(self, document: dict[str, Any], normalise: Callable[[str], str], verbose: bool):
        self.doc = document
        self.normalise = normalise
        self.verbose = verbose
        self.renames: dict[str, dict[str, str]] = {}  # section -> {old: new}
        self.refs_updated = 0

    def rename_components(self) -> None:
        components = self.doc.get("components", {})
        for section in COMPONENT_SECTIONS:
            entries = components.get(section)
            if not isinstance(entries, dict):
                continue
            plan = {
                old: self.normalise(old) for old in entries if not VALID_COMPONENT_NAME.match(old)
            }
            if not plan:
                continue
            self._check_collisions(section, entries, plan)
            # Rebuild the mapping so renamed entries keep their original position.
            components[section] = {plan.get(key, key): value for key, value in entries.items()}
            self.renames[section] = plan
            for old, new in plan.items():
                print(f"  renamed components.{section}: {old!r} -> {new!r}")

    @staticmethod
    def _check_collisions(section: str, entries: dict[str, Any], plan: dict[str, str]) -> None:
        untouched = set(entries) - set(plan)
        seen: dict[str, str] = {}
        for old, new in plan.items():
            if not new:
                raise SystemExit(f"error: {section}/{old!r} normalises to an empty name")
            if new in untouched or new in seen:
                other = seen.get(new, new)
                raise SystemExit(
                    f"error: name collision in components.{section}: {old!r} and {other!r} "
                    f"would both become {new!r}. Rename one of them by hand first."
                )
            seen[new] = old

    def _rewrite_ref(self, ref: str) -> str:
        if not ref.startswith("#/components/"):
            return ref
        parts = ref.split("/", 3)  # ['#', 'components', section, name]
        if len(parts) != 4:
            return ref
        section, name = parts[2], unquote(parts[3])
        plan = self.renames.get(section, {})
        if name in plan:
            return f"#/components/{section}/{plan[name]}"
        return ref

    def update_refs(self, node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "$ref" and isinstance(value, str):
                    new = self._rewrite_ref(value)
                    if new != value:
                        node[key] = new
                        self.refs_updated += 1
                        if self.verbose:
                            print(f"    $ref {value!r} -> {new!r}")
                else:
                    self.update_refs(value)
        elif isinstance(node, list):
            for item in node:
                self.update_refs(item)

    def dangling_refs(self) -> list[str]:
        missing: list[str] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                ref = node.get("$ref")
                parts = ref.split("/", 3) if isinstance(ref, str) else []
                if len(parts) == 4 and parts[:2] == ["#", "components"]:
                    section, name = parts[2], unquote(parts[3])
                    if name not in self.doc.get("components", {}).get(section, {}):
                        missing.append(ref)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(self.doc)
        return sorted(set(missing))


def main() -> int:
    parser = argparse.ArgumentParser(description="Step 2: fix component names and $refs.")
    parser.add_argument("openapi", help="OpenAPI JSON file, rewritten in place")
    parser.add_argument("--verbose", "-v", action="store_true", help="print every rewritten $ref")
    parser.add_argument(
        "--camel-case", action="store_true", help="'store v1' -> 'StoreV1' instead of 'storev1'"
    )
    args = parser.parse_args()

    print(f"[2/4] fix component names and refs in {args.openapi}")
    renamer = ComponentRenamer(
        load_json(args.openapi), camel_case if args.camel_case else strip_invalid, args.verbose
    )
    renamer.rename_components()
    renamer.update_refs(renamer.doc)
    total = sum(len(plan) for plan in renamer.renames.values())
    print(f"  components renamed: {total}, $refs rewritten: {renamer.refs_updated}")

    dangling = renamer.dangling_refs()
    if dangling:
        for ref in dangling:
            print(f"  error: $ref points to nothing: {ref}")
        print("  FAILED: document not saved")
        return 1
    save_json(args.openapi, renamer.doc)
    print("  ok: every local $ref resolves")
    return 0


if __name__ == "__main__":
    sys.exit(main())
