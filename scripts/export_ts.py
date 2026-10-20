#!/usr/bin/env python
"""Generate dependency-free TypeScript contracts from the committed OpenAPI JSON."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

IDENT_RE = re.compile(r"[^A-Za-z0-9_$]")


def ident(value: str) -> str:
    cleaned = IDENT_RE.sub("_", value)
    if cleaned and cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    return cleaned or "_"


def literal(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return str(value)


def ref_name(ref: str) -> str:
    return ident(ref.rsplit("/", 1)[-1])


def ts_type(schema: dict[str, Any] | bool | None, indent: int = 0) -> str:
    if schema is True or schema is None:
        return "unknown"
    if schema is False:
        return "never"
    if "$ref" in schema:
        return f'components["schemas"]["{ref_name(schema["$ref"])}"]'
    if "const" in schema:
        return literal(schema["const"])
    if "enum" in schema:
        return " | ".join(literal(item) for item in schema["enum"])
    variants = schema.get("anyOf") or schema.get("oneOf")
    if variants:
        return " | ".join(dict.fromkeys(ts_type(item, indent) for item in variants))
    all_of = schema.get("allOf")
    if all_of:
        return " & ".join(dict.fromkeys(ts_type(item, indent) for item in all_of))
    kind = schema.get("type")
    if isinstance(kind, list):
        return " | ".join(dict.fromkeys(ts_type({**schema, "type": item}, indent) for item in kind))
    if kind == "object" or "properties" in schema or "additionalProperties" in schema:
        properties = schema.get("properties") or {}
        required = set(schema.get("required") or ())
        pad = "  " * (indent + 1)
        lines: list[str] = []
        for name, child in sorted(properties.items()):
            optional = "" if name in required else "?"
            lines.append(f"{pad}{json.dumps(name)}{optional}: {ts_type(child, indent + 1)};")
        if schema.get("additionalProperties") is True:
            lines.append(f"{pad}[key: string]: unknown;")
        elif isinstance(schema.get("additionalProperties"), dict):
            lines.append(f"{pad}[key: string]: {ts_type(schema['additionalProperties'], indent + 1)};")
        if not lines:
            return "Record<string, unknown>"
        return "{\n" + "\n".join(lines) + "\n" + "  " * indent + "}"
    if kind == "array":
        item = ts_type(schema.get("items"), indent)
        if " | " in item or item.startswith("{"):
            item = f"({item})"
        return f"{item}[]"
    if kind == "string":
        return "string"
    if kind in ("integer", "number"):
        return "number"
    if kind == "boolean":
        return "boolean"
    if kind == "null":
        return "null"
    return "unknown"


def request_body(operation: dict[str, Any]) -> str:
    body = operation.get("requestBody") or {}
    content = body.get("content") or {}
    media = content.get("application/json")
    if not media:
        return "never"
    return ts_type(media.get("schema"))


def responses(operation: dict[str, Any]) -> str:
    lines: list[str] = []
    for status, response in sorted((operation.get("responses") or {}).items()):
        content = (response or {}).get("content") or {}
        media = content.get("application/json")
        if media:
            lines.append(f'    "{status}": {ts_type(media.get("schema"))};')
        else:
            lines.append(f'    "{status}": unknown;')
    if not lines:
        return "Record<string, unknown>"
    return "{\n" + "\n".join(lines) + "\n  }"


def render_operations(document: dict[str, Any]) -> str:
    lines = ["export interface operations {"]
    for path, path_item in sorted((document.get("paths") or {}).items()):
        del path
        for method, operation in sorted(path_item.items()):
            if method not in {"get", "put", "post", "delete", "patch", "head", "options", "trace"}:
                continue
            operation = operation or {}
            op_id = ident(operation.get("operationId") or f"{method}_{len(lines)}")
            lines.append(f"  {json.dumps(op_id)}: {{")
            lines.append(f"    method: {json.dumps(method.upper())};")
            parameters = operation.get("parameters") or []
            if parameters:
                lines.append("    parameters: {")
                for parameter in parameters:
                    name = json.dumps(parameter.get("name", "parameter"))
                    required = "?" if not parameter.get("required", False) else ""
                    lines.append(f"      {name}{required}: {ts_type(parameter.get('schema'))};")
                lines.append("    };")
            else:
                lines.append("    parameters: never;")
            lines.append(f"    requestBody: {request_body(operation)};")
            lines.append(f"    responses: {responses(operation)};")
            lines.append("  };")
    lines.append("}")
    return "\n".join(lines)


def render_paths(document: dict[str, Any]) -> str:
    lines = ["export interface paths {"]
    for path, path_item in sorted((document.get("paths") or {}).items()):
        lines.append(f"  {json.dumps(path)}: {{")
        for method, operation in sorted(path_item.items()):
            if method not in {"get", "put", "post", "delete", "patch", "head", "options", "trace"}:
                continue
            operation = operation or {}
            op_id = ident(operation.get("operationId") or f"{method}_{len(lines)}")
            lines.append(f"    {method}: operations[{json.dumps(op_id)}];")
        lines.append("  };")
    lines.append("}")
    return "\n".join(lines)


def render(document: dict[str, Any]) -> str:
    schemas = (document.get("components") or {}).get("schemas") or {}
    lines = [
        "// Generated by scripts/export_ts.py. Do not edit by hand.",
        "// Source: contracts/openapi.json",
        "",
        "export interface components {",
        "  schemas: {",
    ]
    for name, schema in sorted(schemas.items()):
        lines.append(f"    {json.dumps(ident(name))}: {ts_type(schema, 2)};")
    lines.extend(["  };", "}", "", render_operations(document), "", render_paths(document), ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--openapi", default="contracts/openapi.json")
    parser.add_argument("--output", default="packages/client-contracts/src/openapi-types.ts")
    args = parser.parse_args()
    document = json.loads(Path(args.openapi).read_text(encoding="utf-8"))
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(document), encoding="utf-8")
    index = path.parent / "index.ts"
    index.write_text(
        "// Generated contract entry point. Do not edit by hand.\n"
        'export type { components, operations, paths } from "./openapi-types";\n',
        encoding="utf-8",
    )
    print(f"wrote {path} and {index}")


if __name__ == "__main__":
    main()
