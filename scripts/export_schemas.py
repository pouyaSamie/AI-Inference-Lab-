#!/usr/bin/env python
"""Export durable protocol JSON Schemas and a content manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from lab_core.ids import sha256_text
from lab_core.version import (
    API_VERSION,
    CONTRACT_VERSION,
    OPTIMIZER_PROTOCOL_VERSION,
    SCHEMA_VERSION,
    WORKER_PROTOCOL_VERSION,
)

from lab_core import (
    BenchmarkObservation,
    CandidateSpec,
    CommandAck,
    CommandCompletion,
    DeploymentRecipe,
    ExperimentPlan,
    ExperimentSnapshot,
    ExperimentSpec,
    ExperimentStatusView,
    JobEvent,
    OptimizerCompletion,
    OptimizerHeartbeat,
    OptimizerPollResponse,
    OptimizerRequest,
    SearchSpaceSpec,
    WorkerCommand,
    WorkerRegistration,
    WorkerSnapshot,
)
from lab_updates import (
    ComparisonEvidence,
    ComparisonPlan,
    ComparisonResult,
    ImpactAssessment,
    ReleaseMetadata,
)

MODELS: dict[str, type] = {
    "BenchmarkObservation": BenchmarkObservation,
    "CandidateSpec": CandidateSpec,
    "CommandAck": CommandAck,
    "CommandCompletion": CommandCompletion,
    "ComparisonEvidence": ComparisonEvidence,
    "ComparisonPlan": ComparisonPlan,
    "ComparisonResult": ComparisonResult,
    "DeploymentRecipe": DeploymentRecipe,
    "ExperimentPlan": ExperimentPlan,
    "ExperimentSnapshot": ExperimentSnapshot,
    "ExperimentSpec": ExperimentSpec,
    "ExperimentStatusView": ExperimentStatusView,
    "ImpactAssessment": ImpactAssessment,
    "JobEvent": JobEvent,
    "OptimizerCompletion": OptimizerCompletion,
    "OptimizerHeartbeat": OptimizerHeartbeat,
    "OptimizerPollResponse": OptimizerPollResponse,
    "OptimizerRequest": OptimizerRequest,
    "ReleaseMetadata": ReleaseMetadata,
    "SearchSpaceSpec": SearchSpaceSpec,
    "WorkerCommand": WorkerCommand,
    "WorkerRegistration": WorkerRegistration,
    "WorkerSnapshot": WorkerSnapshot,
}


def build_schema() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "api_version": API_VERSION,
        "contract_version": CONTRACT_VERSION,
        "worker_protocol_version": WORKER_PROTOCOL_VERSION,
        "optimizer_protocol_version": OPTIMIZER_PROTOCOL_VERSION,
        "models": {name: model.model_json_schema() for name, model in sorted(MODELS.items())},
    }


def render(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schemas", default="contracts/contracts.schema.json")
    parser.add_argument("--openapi", default="contracts/openapi.json")
    parser.add_argument("--manifest", default="contracts/manifest.json")
    args = parser.parse_args()
    schemas_path = Path(args.schemas)
    openapi_path = Path(args.openapi)
    manifest_path = Path(args.manifest)
    schemas_path.parent.mkdir(parents=True, exist_ok=True)
    schemas_path.write_text(render(build_schema()), encoding="utf-8")
    if not openapi_path.exists():
        raise SystemExit(f"missing {openapi_path}; run scripts/export_openapi.py first")
    manifest = {
        "openapi_sha256": sha256_text(openapi_path.read_text(encoding="utf-8")),
        "schemas_sha256": sha256_text(schemas_path.read_text(encoding="utf-8")),
        "schema_version": SCHEMA_VERSION,
    }
    manifest_path.write_text(render(manifest), encoding="utf-8")
    print(f"wrote {schemas_path} and {manifest_path}")


if __name__ == "__main__":
    main()
