#!/usr/bin/env python3
"""Step 1 - Hydrate: enrich a generated OpenAPI spec with everything the generator left out.

Backend frameworks export specs that are structurally complete but unreadable:
descriptions are i18n keys (``api.doc.v3.store.id.description``), operations have
no summaries, error responses are missing and there is no info, server or auth
metadata. This step fills all of that from three sources of truth:

* ``config.yaml``      locale-independent metadata, components, error rules, tag order
* ``dictionary.json``  i18n key -> text, one file per locale
* ``summaries.json``   operationId -> short human title, one file per locale

Transformations, in order:
    1. info and servers
    2. security schemes and global security
    3. reusable components (schemas, responses, parameters)
    4. operation summaries
    5. default error responses, chosen by path prefix (v3 vs legacy)
    6. global header parameters
    7. ordered tag list for the sidebar
    8. recursive translation of every placeholder (runs last, so config text is translated too)

Usage:
    python 1_hydrate_openapi.py openapi.json config.yaml dictionary.json summaries.json [--strict]
"""

from __future__ import annotations

import argparse
import copy
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from common import iter_operations, load_json, save_json


class OpenAPIHydrator:
    """Applies config, dictionary and summaries to an OpenAPI document."""

    def __init__(
        self,
        document: dict[str, Any],
        config: dict[str, Any],
        dictionary: dict[str, str],
        summaries: dict[str, str],
    ) -> None:
        self.doc = document
        self.config = config
        self.dictionary = dictionary
        self.summaries = summaries
        self.placeholder = re.compile(config.get("placeholder_pattern", r"^api\.doc\."))
        self.translated = 0
        self.missing_summaries: list[str] = []

    def inject_metadata(self) -> None:
        if "info" in self.config:
            self.doc["info"] = copy.deepcopy(self.config["info"])
        if "servers" in self.config:
            self.doc["servers"] = copy.deepcopy(self.config["servers"])
        print(f"  info and {len(self.doc.get('servers', []))} server(s) injected")

    def inject_security(self) -> None:
        schemes = self.config.get("security_schemes", {})
        if not schemes:
            return
        components = self.doc.setdefault("components", {})
        components.setdefault("securitySchemes", {}).update(copy.deepcopy(schemes))
        self.doc["security"] = copy.deepcopy(
            self.config.get("security", [{name: []} for name in schemes])
        )
        print(f"  security schemes: {', '.join(schemes)}")

    def inject_components(self) -> None:
        components = self.doc.setdefault("components", {})
        for section in ("schemas", "responses", "parameters"):
            entries = self.config.get("components", {}).get(section, {})
            if entries:
                components.setdefault(section, {}).update(copy.deepcopy(entries))
                print(f"  components.{section}: +{len(entries)}")

    def inject_summaries(self) -> None:
        injected = 0
        for path, method, operation in iter_operations(self.doc):
            summary = self.summaries.get(operation.get("operationId", ""))
            if summary:
                operation["summary"] = summary
                injected += 1
            elif not operation.get("summary"):
                op_id = operation.get("operationId", "no operationId")
                self.missing_summaries.append(f"{method.upper()} {path} ({op_id})")
        print(f"  summaries injected: {injected}")
        for item in self.missing_summaries:
            print(f"  warn: no summary for {item}")

    def inject_error_responses(self) -> None:
        rules = self.config.get("error_responses", [])
        added = 0
        for path, _method, operation in iter_operations(self.doc):
            rule = next((r for r in rules if path.startswith(r.get("path_prefix", ""))), None)
            if rule is None:
                continue
            responses = operation.setdefault("responses", {})
            for status, response_name in rule["responses"].items():
                if str(status) not in responses:
                    responses[str(status)] = {"$ref": f"#/components/responses/{response_name}"}
                    added += 1
        print(f"  error responses added: {added}")

    def inject_global_parameters(self) -> None:
        added = 0
        for entry in self.config.get("global_parameters", []):
            ref = {"$ref": f"#/components/parameters/{entry['name']}"}
            prefixes = entry.get("path_prefixes")
            for path, _method, operation in iter_operations(self.doc):
                if prefixes and not any(path.startswith(p) for p in prefixes):
                    continue
                params = operation.setdefault("parameters", [])
                if ref not in params:
                    params.append(copy.deepcopy(ref))
                    added += 1
        print(f"  global header references added: {added}")

    def order_tags(self) -> None:
        configured = copy.deepcopy(self.config.get("tags", []))
        known = {tag["name"] for tag in configured}
        used: list[str] = []
        for _path, _method, operation in iter_operations(self.doc):
            for tag in operation.get("tags", []):
                if tag not in used:
                    used.append(tag)
        extra = [{"name": tag} for tag in used if tag not in known]
        for tag in extra:
            print(f"  warn: tag {tag['name']!r} is used but not listed in config.tags")
        self.doc["tags"] = [tag for tag in configured if tag["name"] in used] + extra
        print(f"  tags ordered: {len(self.doc['tags'])}")

    def _translate(self, node: Any) -> Any:
        if isinstance(node, dict):
            # Keys are translated too (some generators emit i18n keys as map keys),
            # but $ref targets never are.
            return {
                key if key == "$ref" else self._translate_str(key): (
                    value if key == "$ref" else self._translate(value)
                )
                for key, value in node.items()
            }
        if isinstance(node, list):
            return [self._translate(item) for item in node]
        if isinstance(node, str):
            return self._translate_str(node)
        return node

    def _translate_str(self, value: str) -> str:
        if value in self.dictionary:
            self.translated += 1
            return self.dictionary[value]
        return value

    def translate(self) -> None:
        self.doc = self._translate(self.doc)
        print(f"  placeholders translated: {self.translated}")

    def untranslated(self) -> list[str]:
        """Collect every string that still looks like a placeholder."""
        found: list[str] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    walk(key)
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)
            elif isinstance(node, str) and self.placeholder.search(node) and node not in found:
                found.append(node)

        walk(self.doc)
        return found

    def run(self) -> dict[str, Any]:
        self.inject_metadata()
        self.inject_security()
        self.inject_components()
        self.inject_summaries()
        self.inject_error_responses()
        self.inject_global_parameters()
        self.order_tags()
        self.translate()
        return self.doc


def main() -> int:
    parser = argparse.ArgumentParser(description="Step 1: hydrate a generated OpenAPI spec.")
    parser.add_argument("openapi", help="OpenAPI JSON file, rewritten in place")
    parser.add_argument("config", help="config.yaml")
    parser.add_argument("dictionary", help="dictionary.json for the target locale")
    parser.add_argument("summaries", help="summaries.json for the target locale")
    parser.add_argument(
        "--strict", action="store_true", help="exit 1 if any translation or summary is missing"
    )
    args = parser.parse_args()

    print(f"[1/4] hydrate {args.openapi} (locale: {Path(args.dictionary).parent.name})")
    with open(args.config, encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    hydrator = OpenAPIHydrator(
        load_json(args.openapi), config, load_json(args.dictionary), load_json(args.summaries)
    )
    document = hydrator.run()

    leftovers = hydrator.untranslated()
    for value in leftovers:
        print(f"  warn: missing translation for {value!r}")
    save_json(args.openapi, document)

    problems = len(leftovers) + len(hydrator.missing_summaries)
    if args.strict and problems:
        print(f"  FAILED: {problems} missing translation(s) or summary(ies) in --strict mode")
        return 1
    print("  ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
