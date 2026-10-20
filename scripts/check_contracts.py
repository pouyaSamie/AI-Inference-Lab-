#!/usr/bin/env python
"""Fail when committed contracts or generated TypeScript are stale."""

from __future__ import annotations

import argparse
from pathlib import Path

from export_openapi import build_document
from export_openapi import render as render_openapi
from export_schemas import build_schema
from export_schemas import render as render_json
from export_ts import render as render_ts


def compare(path: Path, expected: str) -> list[str]:
    if not path.exists():
        return [f"missing {path}"]
    actual = path.read_text(encoding="utf-8")
    if actual != expected:
        return [f"stale {path}"]
    return []


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    root = Path(args.root)
    failures: list[str] = []
    openapi_path = root / "contracts/openapi.json"
    schemas_path = root / "contracts/contracts.schema.json"
    manifest_path = root / "contracts/manifest.json"
    ts_path = root / "packages/client-contracts/src/openapi-types.ts"
    index_path = root / "packages/client-contracts/src/index.ts"

    document = build_document()
    openapi_text = render_openapi(document)
    failures.extend(compare(openapi_path, openapi_text))
    schemas = build_schema()
    schemas_text = render_json(schemas)
    failures.extend(compare(schemas_path, schemas_text))
    if openapi_path.exists():
        from lab_core.ids import sha256_text

        manifest = {
            "openapi_sha256": sha256_text(openapi_text),
            "schemas_sha256": sha256_text(schemas_text),
            "schema_version": schemas["schema_version"],
        }
        failures.extend(compare(manifest_path, render_json(manifest)))
    failures.extend(compare(ts_path, render_ts(document)))
    expected_index = (
        "// Generated contract entry point. Do not edit by hand.\n"
        'export type { components, operations, paths } from "./openapi-types";\n'
    )
    failures.extend(compare(index_path, expected_index))
    if failures:
        for failure in failures:
            print(f"CONTRACT CHECK: {failure}")
        print(
            "Regenerate with: uv run python scripts/export_openapi.py && "
            "uv run python scripts/export_schemas.py && uv run python scripts/export_ts.py"
        )
        raise SystemExit(1)
    print("contracts are current")


if __name__ == "__main__":
    main()
