#!/usr/bin/env python
"""Export the controller OpenAPI document deterministically, without a server."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lab_api.app import create_app
from lab_api.config import Settings


def contract_settings() -> Settings:
    return Settings(
        environment="test",
        controller_db_url="sqlite:////tmp/lab-openapi-controller.sqlite3",
        optimizer_db_url="sqlite:////tmp/lab-openapi-optimizer.sqlite3",
        artifact_root="/tmp/lab-openapi-artifacts",
        operator_token="contract-operator-token-000000000000",
        enrollment_token="contract-enrollment-token-0000000000",
        optimizer_token="contract-optimizer-token-0000000000",
        worker_token_pepper="contract-worker-pepper-000000000000",
        scheduler_enabled=False,
        document_openapi=True,
        log_level="WARNING",
    )


def build_document() -> dict:
    app = create_app(contract_settings())
    return app.openapi()


def render(document: dict) -> str:
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="contracts/openapi.json")
    args = parser.parse_args()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(build_document()), encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
