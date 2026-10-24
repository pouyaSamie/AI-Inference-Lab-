"""Golden-file conformance checks for the two production adapters.

These tests are offline: they parse captured help/version/evidence fixtures and
assert that plans only emit flags present in the corresponding installed help.
No engine, GPU, network or model file is required.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lab_adapters.base.parsing import observed_flags
from lab_core.ids import sha256_text
from lab_core.search import DimensionKind

from lab_adapters import registry
from lab_core import (
    Backend,
    BinaryKind,
    CandidateSpec,
    CapabilityKind,
    ContextLength,
    EngineId,
    ModelArtifact,
    ProcessOutput,
    RawEvidence,
    RegisteredBinary,
    SandboxPaths,
    SearchSpaceRequest,
    UnsupportedCapabilityError,
)

ROOT = Path(__file__).resolve().parents[1]
LLAMA = ROOT / "fixtures" / "engines" / "llamacpp-0.7.0-dev-build701"
STRATA = ROOT / "fixtures" / "engines" / "strata-0.1.44.1"


def _sandbox() -> SandboxPaths:
    return SandboxPaths(
        root="/tmp/lab-conformance",
        work_dir="/tmp/lab-conformance/work",
        log_dir="/tmp/lab-conformance/logs",
        artifact_dir="/tmp/lab-conformance/artifacts",
        temp_home="/tmp/lab-conformance/home",
    )


def _binary(engine: EngineId, kind: BinaryKind, executable_id: str) -> RegisteredBinary:
    return RegisteredBinary(
        executable_id=executable_id,
        engine_id=engine,
        kind=kind,
        path=f"/sim/{executable_id}",
        sha256="a" * 64,
        build="fixture",
        backend=Backend.CUDA,
    )


def _candidate(
    engine: EngineId,
    parameters: dict[str, object],
    *,
    context: ContextLength = ContextLength.K32,
) -> CandidateSpec:
    return CandidateSpec(
        study_id="study-conformance",
        experiment_id="exp-conformance",
        trial_number=0,
        engine_id=engine.value,
        engine_sha256="a" * 64,
        model_digest="b" * 64,
        worker_id="worker-conformance",
        context=context,
        parameters=parameters,
        workload_digest="c" * 64,
    )


def _llamacpp_manifest():
    adapter = registry().get(EngineId.LLAMACPP)
    binary = _binary(EngineId.LLAMACPP, BinaryKind.SERVER, "llama-server")
    outputs = (
        ProcessOutput(
            command_id="probe-llama-server-version",
            exit_code=0,
            stdout=(LLAMA / "server-version.txt").read_text(encoding="utf-8"),
        ),
        ProcessOutput(
            command_id="probe-llama-server-help",
            exit_code=0,
            stdout=(LLAMA / "server-help.txt").read_text(encoding="utf-8"),
        ),
        ProcessOutput(
            command_id="probe-llama-bench-version",
            exit_code=0,
            stdout=(LLAMA / "version.txt").read_text(encoding="utf-8"),
        ),
        ProcessOutput(
            command_id="probe-llama-bench-help",
            exit_code=0,
            stdout=(LLAMA / "bench-help.txt").read_text(encoding="utf-8"),
        ),
    )
    return adapter, binary, adapter.parse_probe_output(outputs, binary)


def _llamacpp_model() -> ModelArtifact:
    return ModelArtifact(
        model_id="tiny-qwen",
        display_name="Tiny Qwen fixture",
        architecture="qwen2",
        quantization="Q4_K_M",
        path_map=("/models/Tiny-Q4_K_M.gguf",),
        files=(),
        metadata_context_tokens=32768,
        compatible_engines=(EngineId.LLAMACPP,),
    )


def test_llamacpp_fixture_manifest_and_plan_flags_are_scoped_to_help() -> None:
    adapter, server_binary, manifest = _llamacpp_manifest()
    assert manifest.engine.version == "0.7.0-dev"
    assert manifest.engine.build == "701"
    assert manifest.engine.source_commit == "dd002b91f"
    assert {"--model", "--ctx-size", "--host", "--port", "--n-prompt", "--output"} <= manifest.flags
    assert any("server_help_sha256=" in note for note in manifest.notes)
    assert any("bench_help_sha256=" in note for note in manifest.notes)

    candidate = _candidate(
        EngineId.LLAMACPP,
        {
            "gpu_layers": 99,
            "threads": 8,
            "batch": 1024,
            "ubatch": 256,
            "n_cpu_moe": 12,
            "flash_attn": "auto",
            "cache_type_k": "q8_0",
            "cache_type_v": "q8_0",
            "prompt_tokens": 512,
            "n_gen": 128,
            "n_depth": 0,
            "repetitions": 3,
        },
    )
    assert adapter.validate_candidate(candidate, manifest) == ()

    server_flags = observed_flags((LLAMA / "server-help.txt").read_text(encoding="utf-8"))
    server_plan = adapter.build_server_plan(
        candidate,
        _sandbox(),
        binary=server_binary,
        model=_llamacpp_model(),
        port=18080,
    )
    assert server_plan.start.command.executable_sha256 == server_binary.sha256
    for argument in server_plan.start.command.argv:
        if argument.startswith("--"):
            assert argument in server_flags, argument
    assert "--ctx-size" in server_plan.start.command.argv
    assert "32768" in server_plan.start.command.argv
    assert server_plan.bind_host == "127.0.0.1"
    assert server_plan.metrics_path is None

    bench_binary = _binary(EngineId.LLAMACPP, BinaryKind.MICROBENCH, "llama-bench")
    bench_plan = adapter.build_microbench_plan(
        candidate,
        _sandbox(),
        binary=bench_binary,
        model=_llamacpp_model(),
        repetitions=3,
    )
    bench_help = (LLAMA / "bench-help.txt").read_text(encoding="utf-8")
    for argument in bench_plan.stages[0].command.argv:
        if argument.startswith("-") and not argument.lstrip("-").isdigit():
            assert argument in bench_help, argument
    assert bench_plan.stages[0].command.executable_sha256 == bench_binary.sha256


def test_llamacpp_candidate_validation_rejects_wrong_types_and_unknown_flags() -> None:
    adapter, _binary_value, manifest = _llamacpp_manifest()
    for name, value in (
        ("gpu_layers", True),
        ("threads", 1.5),
        ("repetitions", "3"),
        ("flash_attn", "maybe"),
        ("metrics", "yes"),
    ):
        errors = adapter.validate_candidate(_candidate(EngineId.LLAMACPP, {name: value}), manifest)
        assert errors, name
    missing_metrics = manifest.model_copy(
        update={"descriptors": tuple(item for item in manifest.descriptors if item.key != "--metrics")}
    )
    errors = adapter.validate_candidate(_candidate(EngineId.LLAMACPP, {"metrics": True}), missing_metrics)
    assert any("--metrics" in error for error in errors)


def test_llamacpp_parses_native_and_server_fixtures_without_inventing_metrics() -> None:
    adapter, _binary_value, _manifest = _llamacpp_manifest()
    candidate = _candidate(EngineId.LLAMACPP, {})
    native_text = (LLAMA / "bench-output.json").read_text(encoding="utf-8")
    native = adapter.parse_microbench_evidence(
        RawEvidence(
            evidence_id="fixture-native",
            path="fixtures/bench-output.json",
            content_type="application/json",
            text=native_text,
        ),
        candidate,
    )
    assert native.build_commit == "dd002b91f"
    assert native.prefill_row() is not None
    assert native.prefill_row().avg_ts == pytest.approx(1200.5)  # type: ignore[union-attr]
    assert native.decode_row() is not None
    assert native.decode_row().avg_ts == pytest.approx(81.25)  # type: ignore[union-attr]

    props_text = (LLAMA / "server-props.json").read_text(encoding="utf-8")
    serving = adapter.parse_server_evidence(
        RawEvidence(
            evidence_id="fixture-props",
            path="fixtures/server-props.json",
            content_type="application/json",
            text=props_text,
        ),
        None,
        candidate,
    )
    assert serving.context_configured == 32768
    assert serving.context_effective == 32768
    assert serving.time_to_first_token_ms is None
    assert "time_to_first_token_ms" in serving.unavailable_reasons


def test_llamacpp_quantized_value_search_requires_explicit_flash_attention() -> None:
    adapter = registry().get(EngineId.LLAMACPP)
    space = adapter.search_space(
        SearchSpaceRequest(
            engine_id=EngineId.LLAMACPP,
            model_architecture="gemma",
            context_tokens=4096,
            objective="balanced",
        )
    )
    value = space.dimension("cache_type_v")
    assert value is not None
    assert not space.is_active(value, {"flash_attn": "off"})
    assert not space.is_active(value, {"flash_attn": "auto"})
    assert space.is_active(value, {"flash_attn": "on"})


def test_strata_fixture_manifest_numeric_types_and_search_space() -> None:
    adapter = registry().get(EngineId.STRATA)
    binary = _binary(EngineId.STRATA, BinaryKind.CLI, "strata")
    outputs = (
        ProcessOutput(
            command_id="probe-strata-version",
            exit_code=0,
            stderr=(STRATA / "version.txt").read_text(encoding="utf-8"),
        ),
        ProcessOutput(
            command_id="probe-strata-help",
            exit_code=0,
            stderr=(STRATA / "generate-help.txt").read_text(encoding="utf-8"),
        ),
    )
    manifest = adapter.parse_probe_output(outputs, binary)
    assert manifest.engine.version == "0.1.44.1"
    expert_cache = manifest.descriptor("--expert-cache")
    assert expert_cache is not None
    assert expert_cache.kind is CapabilityKind.INT
    assert expert_cache.default == 0
    pool_workers = manifest.descriptor("--pool-workers")
    assert pool_workers is not None
    assert pool_workers.minimum == 0
    assert pool_workers.default == 0

    space = adapter.search_space(
        SearchSpaceRequest(
            engine_id=EngineId.STRATA,
            model_architecture="strata-pack",
            context_tokens=32768,
            objective="balanced",
        )
    )
    assert space.dimension("expert_cache").kind is DimensionKind.INT  # type: ignore[union-attr]
    assert space.dimension("pool_workers").minimum == 0  # type: ignore[union-attr]
    assert space.dimension("batch").choices == (1, 2, 4)  # type: ignore[union-attr]
    iq_space = adapter.search_space(
        SearchSpaceRequest(
            engine_id=EngineId.STRATA,
            model_architecture="strata-pack",
            model_quantization="IQ1_M",
            context_tokens=4096,
            objective="balanced",
        )
    )
    assert iq_space.dimension("spec").minimum == 2  # type: ignore[union-attr]
    assert iq_space.dimension("prefill").default == "auto"  # type: ignore[union-attr]


def test_strata_candidate_validation_rejects_auto_expert_cache_and_bad_numbers() -> None:
    adapter = registry().get(EngineId.STRATA)
    manifest = adapter.parse_probe_output(
        (
            ProcessOutput(
                command_id="probe-strata-version",
                exit_code=0,
                stderr=(STRATA / "version.txt").read_text(encoding="utf-8"),
            ),
            ProcessOutput(
                command_id="probe-strata-help",
                exit_code=0,
                stderr=(STRATA / "generate-help.txt").read_text(encoding="utf-8"),
            ),
        ),
        _binary(EngineId.STRATA, BinaryKind.CLI, "strata"),
    )
    assert adapter.validate_candidate(_candidate(EngineId.STRATA, {"expert_cache": 64}), manifest) == ()
    for parameters in (
        {"expert_cache": "auto"},
        {"spec_min_p": 1.5},
        {"batch": 0},
        {"kv_resident": 1024},
        {"pool_workers": -1},
        {"kv": "fp8"},
    ):
        assert adapter.validate_candidate(_candidate(EngineId.STRATA, parameters), manifest), parameters


def test_strata_profile_emits_observed_flags_and_never_stringifies_native_marker() -> None:
    adapter = registry().get(EngineId.STRATA)
    binary = _binary(EngineId.STRATA, BinaryKind.SERVER_SCRIPT, "strata-server")
    model = ModelArtifact(
        model_id="strata-fixture",
        display_name="Strata fixture",
        architecture="strata-pack",
        quantization="q2_0",
        path_map=("/models/Strata/packs/q2_0",),
        files=(),
        compatible_engines=(EngineId.STRATA,),
        metadata={
            "pack_path": "/models/Strata/packs/q2_0",
            "engine_executable": "/sim/strata",
            "server_script": "/sim/serve/server.py",
            "tokenizer_path": "/models/Strata/packs/q2_0/tokenizer",
            "native": True,
            "native_shard": "/models/Strata/models/Q2_0/shard-00001-of-00002.gguf",
            "base_args": [
                "--pack",
                "/models/old-pack",
                "--max-context",
                "4096",
                "--kv",
                "fp16",
                "--expert-cache",
                "7",
                "--batch",
                "2",
                "--custom-flag",
                "x",
            ],
        },
    )
    candidate = _candidate(
        EngineId.STRATA,
        {
            "kv": "k8v4",
            "expert_cache": 64,
            "prefill": "auto:16384",
            "spec": 4,
            "spec_min_p": 0.65,
            "pool_workers": 0,
            "kv_resident": 20480,
            "kv_grow": True,
            "batch": 2,
            "ple_io": "mmap",
            "resident_experts": True,
            "mmap_experts": True,
            "gpu": "0,1",
        },
    )
    assert (
        adapter.validate_candidate(
            candidate,
            adapter.parse_probe_output(
                (
                    ProcessOutput(
                        command_id="probe-strata-version",
                        exit_code=0,
                        stderr=(STRATA / "version.txt").read_text(encoding="utf-8"),
                    ),
                    ProcessOutput(
                        command_id="probe-strata-help",
                        exit_code=0,
                        stderr=(STRATA / "generate-help.txt").read_text(encoding="utf-8"),
                    ),
                ),
                _binary(EngineId.STRATA, BinaryKind.CLI, "strata"),
            ),
        )
        == ()
    )
    plan = adapter.build_server_plan(
        candidate,
        _sandbox(),
        binary=binary,
        model=model,
        port=18081,
    )
    assert plan.generated_files
    generated = plan.generated_files[0]
    assert generated.relative_path == "strata-profile.json"
    document = json.loads(generated.content)
    assert document["log"] == "/tmp/lab-conformance/logs/strata-engine.log"
    assert document["gpu"] == [0, 1]
    assert document["tokenizer"] == "/models/Strata/packs/q2_0/tokenizer"
    args = document["args"]
    assert args.count("--max-context") == 1
    assert args[args.index("--max-context") + 1] == "32768"
    assert args.count("--kv") == 1
    assert args[args.index("--kv") + 1] == "k8v4"
    assert args.count("--expert-cache") == 1
    assert args[args.index("--expert-cache") + 1] == "64"
    assert "--batch" in args
    assert args[args.index("--batch") + 1] == "2"
    assert "--kv-resident" in args
    assert "--kv-grow" in args
    assert "--ple-io" in args
    assert args[args.index("--ple-io") + 1] == "mmap"
    assert "--spec-min-p" in args
    assert "--custom-flag" in args
    assert "--native" in args
    assert args[args.index("--native") + 1].endswith("shard-00001-of-00002.gguf")
    assert "True" not in args
    assert generated.sha256 == sha256_text(generated.content)
    assert plan.start.command.executable_id == "strata-server"
    assert plan.start.command.argv[0] == "/sim/serve/server.py"
    assert str(plan.start.command.argv[-1]) == "18081"
    assert plan.metrics_path == "/metrics"


def test_strata_refuses_native_benchmark_and_parses_serving_status() -> None:
    adapter = registry().get(EngineId.STRATA)
    with pytest.raises(UnsupportedCapabilityError):
        adapter.build_microbench_plan(
            _candidate(EngineId.STRATA, {}),
            _sandbox(),
            binary=_binary(EngineId.STRATA, BinaryKind.CLI, "strata"),
            model=ModelArtifact(
                model_id="strata-fixture",
                display_name="Strata fixture",
                architecture="strata-pack",
                path_map=("/models/Strata/packs/q2_0",),
            ),
        )
    status_text = (STRATA / "status.json").read_text(encoding="utf-8")
    serving = adapter.parse_server_evidence(
        RawEvidence(
            evidence_id="fixture-status",
            path="fixtures/status.json",
            content_type="application/json",
            text=status_text,
        ),
        None,
        _candidate(EngineId.STRATA, {}),
    )
    assert serving.context_effective == 32768
    assert serving.prefill_tokens_per_sec == pytest.approx(3630.1)
    assert serving.decode_tokens_per_sec == pytest.approx(80.0)
    assert serving.total_latency_ms == pytest.approx(2412.5)
    assert serving.time_to_first_token_ms is None
    assert serving.gpu_vram_used_bytes == int(10123.5 * 1024 * 1024)


def test_observed_flags_ignores_prose_only_mentions() -> None:
    text = "  --spec N\n  --spec-min-p P\n  use --calibrate for more\n  use --max-context <=256\n"
    assert observed_flags(text) == frozenset({"--spec", "--spec-min-p"})


def test_llamacpp_native_rows_use_observed_token_counts_when_test_label_is_absent():
    import json

    adapter, _, _ = _llamacpp_manifest()
    document = [
        {"n_prompt": 1024, "n_gen": 0, "avg_ts": 1438.0},
        {"n_prompt": 0, "n_gen": 256, "avg_ts": 41.6},
    ]
    evidence = RawEvidence(
        evidence_id="token-count-schema",
        path="fixture.json",
        content_type="application/json",
        text=json.dumps(document),
    )
    parsed = adapter.parse_microbench_evidence(evidence, _candidate(EngineId.LLAMACPP, {}))
    assert parsed.prefill_row().avg_ts == 1438.0
    assert parsed.decode_row().avg_ts == 41.6
    document[0]["n_gen"] = 256
    with pytest.raises(ValueError, match="unambiguous"):
        adapter.parse_microbench_evidence(
            evidence.model_copy(update={"text": json.dumps(document)}), _candidate(EngineId.LLAMACPP, {})
        )


def test_llamacpp_answer_benchmark_policy_is_explicit_and_capability_checked():
    adapter, binary, manifest = _llamacpp_manifest()
    space = adapter.search_space(
        SearchSpaceRequest(
            engine_id=EngineId.LLAMACPP,
            model_architecture="gemma4",
            context_tokens=4096,
            objective="balanced",
        )
    )
    assert space.fixed_parameters["reasoning"] == "off"
    candidate = _candidate(EngineId.LLAMACPP, {"reasoning": "off"})
    assert adapter.validate_candidate(candidate, manifest) == ()
    plan = adapter.build_server_plan(
        candidate, _sandbox(), binary=binary, model=_llamacpp_model(), port=18080
    )
    args = plan.start.command.argv
    assert args[args.index("--reasoning") + 1] == "off"
    missing = manifest.model_copy(
        update={"descriptors": tuple(d for d in manifest.descriptors if d.key != "--reasoning")}
    )
    assert adapter.validate_candidate(candidate, missing)


def test_strata_answer_policy_is_a_wrapper_key_not_an_unobserved_native_flag():
    adapter = registry().get(EngineId.STRATA)
    from lab_adapters.strata.adapter import StrataAdapter

    space = StrataAdapter().search_space(
        SearchSpaceRequest(
            engine_id=EngineId.STRATA,
            model_architecture="strata",
            context_tokens=4096,
            objective="balanced",
        )
    )
    assert space.fixed_parameters["reasoning_effort"] == "none"
    candidate = _candidate(EngineId.STRATA, {"reasoning_effort": "none"})
    # The serving key is validated independently from the native CLI surface.
    binary = _binary(EngineId.STRATA, BinaryKind.CLI, "strata")
    manifest = adapter.parse_probe_output(
        (
            ProcessOutput(
                command_id="strata-version", exit_code=0, stderr=(STRATA / "version.txt").read_text()
            ),
            ProcessOutput(
                command_id="strata-help", exit_code=0, stderr=(STRATA / "generate-help.txt").read_text()
            ),
        ),
        binary,
    )
    assert adapter.validate_candidate(candidate, manifest) == ()
    invalid = _candidate(EngineId.STRATA, {"reasoning_effort": "invalid"})
    assert adapter.validate_candidate(invalid, manifest)
