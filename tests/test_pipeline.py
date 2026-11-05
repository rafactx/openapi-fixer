"""End-to-end checks: the example input is broken, every pipeline output is valid."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from openapi_spec_validator import validate

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "example"
LOCALES = sorted(p.name for p in (EXAMPLE / "locales").iterdir() if p.is_dir())
VALID_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def run(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / script), *args], cwd=ROOT, capture_output=True, text=True
    )


def strings(node: object) -> list[str]:
    if isinstance(node, dict):
        return [s for k, v in node.items() for s in [k, *strings(v)]]
    if isinstance(node, list):
        return [s for item in node for s in strings(item)]
    return [node] if isinstance(node, str) else []


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict]:
    out = tmp_path_factory.mktemp("build")
    result = run("run_pipeline.py", "--out", str(out))
    assert result.returncode == 0, result.stdout + result.stderr
    return {loc: json.loads((out / f"openapi.{loc}.json").read_text("utf-8")) for loc in LOCALES}


def test_example_input_is_really_broken() -> None:
    raw = json.loads((EXAMPLE / "openapi.json").read_text("utf-8"))
    with pytest.raises(Exception):
        validate(raw)
    assert any(" " in name for name in raw["components"]["schemas"])
    assert any(s.startswith("api.doc.") for s in strings(raw))


def test_locales_have_identical_keys() -> None:
    for kind in ("dictionary.json", "summaries.json"):
        reference = json.loads((EXAMPLE / "locales" / "en" / kind).read_text("utf-8")).keys()
        for loc in LOCALES:
            keys = json.loads((EXAMPLE / "locales" / loc / kind).read_text("utf-8")).keys()
            assert keys == reference, f"{loc}/{kind} keys differ from en"


@pytest.mark.parametrize("locale", LOCALES)
def test_output_is_valid_and_complete(built: dict[str, dict], locale: str) -> None:
    spec = built[locale]
    validate(spec)  # raises on any OpenAPI violation

    assert not [s for s in strings(spec) if s.startswith("api.doc.")], "untranslated placeholders"
    for section in spec["components"].values():
        assert all(VALID_NAME.match(name) for name in section)

    for path, item in spec["paths"].items():
        for method, op in item.items():
            assert op.get("summary"), f"{method} {path} has no summary"
            if method == "delete":
                assert "requestBody" not in op

    brands = spec["paths"]["/v3/workspaces/{workspaceId}/brands"]["get"]["parameters"]
    assert {"$ref": "#/components/parameters/BrandName"} in brands
    assert len(spec["tags"]) == 5


def test_locales_are_actually_translated(built: dict[str, dict]) -> None:
    tag_sets = {loc: tuple(t["name"] for t in spec["tags"]) for loc, spec in built.items()}
    assert len(set(tag_sets.values())) == len(LOCALES)


def test_steps_are_idempotent(built: dict[str, dict], tmp_path: Path) -> None:
    target = tmp_path / "openapi.json"
    target.write_text(json.dumps(built["en"], indent=2, ensure_ascii=False) + "\n", "utf-8")
    before = target.read_text("utf-8")
    assert run("2_fix_schema_names_and_refs.py", str(target)).returncode == 0
    assert run("3_fix_semantic_paths.py", str(target), "-c", "example/corrections.yaml").returncode == 0
    assert run("4_final_verification.py", str(target)).returncode == 0
    assert target.read_text("utf-8") == before


def test_step2_refuses_name_collisions(tmp_path: Path) -> None:
    doc = {
        "openapi": "3.0.3",
        "info": {"title": "t", "version": "1"},
        "paths": {},
        "components": {"schemas": {"Store V1": {"type": "object"}, "StoreV1": {"type": "object"}}},
    }
    target = tmp_path / "openapi.json"
    target.write_text(json.dumps(doc), "utf-8")
    result = run("2_fix_schema_names_and_refs.py", str(target))
    assert result.returncode != 0
    assert "collision" in result.stdout + result.stderr


def test_step4_fails_on_invalid_spec(tmp_path: Path) -> None:
    doc = {"openapi": "3.0.3", "info": {"title": "t"}, "paths": {}}  # info.version missing
    target = tmp_path / "openapi.json"
    target.write_text(json.dumps(doc), "utf-8")
    assert run("4_final_verification.py", str(target)).returncode == 1
