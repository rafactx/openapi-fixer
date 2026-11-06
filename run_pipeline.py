#!/usr/bin/env python3
"""Run steps 1-4 on the example spec for one or more locales.

    python run_pipeline.py                      # every locale in example/locales
    python run_pipeline.py --locale en pt-BR    # just these
    python run_pipeline.py --example my-api --out dist

The input is never modified: each locale gets a fresh copy in <out>/openapi.<locale>.json.
Exits non-zero as soon as a step fails.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run_locale(example: Path, out: Path, locale: str) -> Path:
    target = out / f"openapi.{locale}.json"
    shutil.copyfile(ROOT / example / "openapi.json", ROOT / target)
    locale_dir = example / "locales" / locale
    steps = [
        [
            "1_hydrate_openapi.py",
            str(target),
            str(example / "config.yaml"),
            str(locale_dir / "dictionary.json"),
            str(locale_dir / "summaries.json"),
            "--strict",
        ],
        ["2_fix_schema_names_and_refs.py", str(target)],
        ["3_fix_semantic_paths.py", str(target), "--config", str(example / "corrections.yaml")],
        ["4_final_verification.py", str(target)],
    ]
    for script, *args in steps:
        result = subprocess.run([sys.executable, str(ROOT / script), *args], cwd=ROOT)
        if result.returncode != 0:
            raise SystemExit(f"pipeline failed at {script} for locale {locale}")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the full pipeline on the example spec.")
    parser.add_argument("--example", default=str(ROOT / "example"), help="input folder")
    parser.add_argument("--out", default=str(ROOT / "build"), help="output folder")
    parser.add_argument("--locale", nargs="*", help="locales to build (default: all)")
    args = parser.parse_args()

    example = Path(os.path.relpath(args.example, ROOT))
    out = Path(os.path.relpath(args.out, ROOT))
    (ROOT / out).mkdir(parents=True, exist_ok=True)
    locales = args.locale or sorted(
        p.name for p in (ROOT / example / "locales").iterdir() if p.is_dir()
    )
    for locale in locales:
        print(f"\n=== {locale} ===", flush=True)
        run_locale(example, out, locale)
    print(
        f"\nbuilt {len(locales)} spec(s) in {out}: "
        + ", ".join(f"openapi.{loc}.json" for loc in locales)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
