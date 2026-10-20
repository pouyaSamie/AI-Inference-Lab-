# Phase 3 report — adapter productionization and conformance

Date: 2026-10-21

Status: **implemented, verified offline and committed locally. No real
preflight, trial or benchmark campaign was run.**

This report records only work actually performed. Adapter conformance is not
performance evidence.

## 1. Delivered

### Shared parsing and validation

- `observed_flags` and `flag_aliases` now read only help lines that begin a
  command-line option. A flag mentioned in prose is not a capability.
- Added strict `validate_capability_value` for enum, integer, float, boolean and
  string descriptors. Booleans are not accepted as integers, numeric strings are
  not accepted as numbers, floats must be finite, and bounds are enforced.
- llama.cpp help is read from stdout and stderr; Strata already required stderr
  support because its installed help prints there.

### llama.cpp adapter

- Server and `llama-bench` probe output are separated by command ID and checked
  separately:
  - server requires `--model`, `--ctx-size`, `--host`, `--port`;
  - native bench requires `--model`, `--n-prompt`, `--n-gen`, `--n-depth`,
    `--repetitions`, `--output`.
- The combined manifest records `server_help_sha256` and `bench_help_sha256`.
- Added the missing `--model` descriptor so `require_supported(("--model",
  "--ctx-size"))` no longer reports a false missing flag.
- Candidate validation now covers workload parameters (`prompt_tokens`,
  `n_gen`, `n_depth`, `repetitions`) and strict types for all descriptors.
- Native plans accept a candidate-level repetition override while retaining the
  explicit plan argument as a default.
- Deployment launch arguments now reproduce candidate server options including
  load mode, split mode, `--kv-unified`, `--kv-unified-per-slot` and `--metrics`.
- `/props` parsing now reads `n_ctx` and `default_generation_settings.n_ctx`;
  missing per-request timings are recorded as unavailable, including TTFT.

### Strata adapter

- Encodes the installed `0.1.44.1` surface only. No `models list`,
  `models inspect`, `doctor`, `engine calibrate` or `bench run` command is
  synthesized.
- `--expert-cache` is an integer descriptor with default `0`.
- `--pool-workers` accepts `0` (all physical cores) with default `0`.
- `--kv-resident` accepts `0` or at least `20480`; the adapter enforces the
  non-zero lower bound separately from the descriptor maximum.
- Added observed search dimensions: numeric `expert_cache`, string `prefill`,
  `spec_min_p`, `kv_resident`, `kv_grow`, opt-in `batch` and `ple_io`.
- Search defaults no longer claim a non-zero worker count or a string
  `expert_cache`.
- Profile generation strips adapter-managed flags from operator base args before
  re-emitting typed values, preventing duplicate or conflicting arguments.
- `native: true` is treated as a discovery marker, not a path. Only an explicit
  `native_shard` emits `--native SHARD1`; `--native True` is impossible.
- The unobserved `--mtp` form is not emitted.
- GPU profile values support an integer or comma-separated index list.
- `/v1/status` parsing accepts `last_timings` or `timings` and `n_ctx`.

### Worker integration

- Real trial observations pass server `/props` or `/v1/status` documents through
  the engine adapter for context identity. Client-observed TTFT, latency and
  usage keep precedence; a status document is not used to invent peak VRAM or
  throughput.
- Adapter parse failures are recorded as notes rather than fabricated values.

### Fixtures and tests

New sanitized fixtures:

- `fixtures/engines/llamacpp-0.7.0-dev-build701/bench-output.json`
- `fixtures/engines/llamacpp-0.7.0-dev-build701/server-props.json`
- `fixtures/engines/strata-0.1.44.1/status.json`

New `tests/test_adapter_conformance.py` covers:

- fixture manifest identity and separate server/bench help digests;
- every emitted server flag exists in server help and every emitted native flag
  exists in bench help;
- strict rejection of wrong candidate types and absent descriptors;
- native `llama-bench` and `/props` parsing without invented metrics;
- Strata stderr help/version, integer capability types and search-space shape;
- Strata rejection of string `expert_cache`, oversized `spec_min_p`, zero
  `batch`, undersized `kv_resident`, negative workers and invalid `kv`;
- profile de-duplication, preservation of custom operator args, `native_shard`
  emission, generated-file digest and metrics path;
- refusal of a Strata native microbenchmark;
- prose-only help mentions not becoming capabilities.

## 2. Safety boundaries

- No adapter imports subprocess, sockets, HTTP clients, `pathlib`, `os` process
  APIs or hardware probes. The existing purity test still passes.
- No engine, model, GPU or network resource was launched or modified for these
  tests.
- The real lane remains `simulated=false`; the simulated lane is unchanged.
- Missing metrics remain missing. Strata full-context proof remains
  `INCONCLUSIVE`.
- No installed binary or weight was replaced, and no process was terminated.

## 3. Commands actually run

Final static gate in this tree:

```bash
uv run ruff check
# All checks passed!

uv run ruff format --check
# 106 files already formatted

uv run mypy python
# Success: no issues found in 90 source files

uv run pytest -q
# 33 passed in 7.59s

uv run python scripts/check_contracts.py
# contracts are current

pnpm typecheck
# tsc --noEmit -p tsconfig.json: passed

systemd-analyze verify packaging/systemd/lab-controller.service \
  packaging/systemd/lab-optimizer.service packaging/systemd/lab-worker.service
# Only the expected missing /opt/ai-inference-lab/.venv/bin/lab-* paths.
# No unit was installed, enabled or started.
```

No core contract or generated-contract change was required in Phase 3.

### Live discovery conformance

The installed engines were probed through the real worker discovery code with
hashing disabled for models. The later model scan was not part of this run.

```text
warnings ()
llamacpp 0.7.0-dev 701 dd002b91f 26 descriptors
  server_help_sha256=e163fc12b945ea0d86100d66757db1e96028339a7ea565d0ad481dd67ea4fabb
  bench_help_sha256=491f2896f82166a5e287bdcee90101865ca45ba8691e707731fa5409f7279ccf
strata   0.1.44.1  0.1.44.1 None 19 descriptors
```

The live manifests include the required server and bench flags. Strata help and
version were parsed from stderr. No warning was emitted by engine discovery.

## 4. Not performed

- No full SHA-256 scan of the model root.
- No real `PREFLIGHT`, `CLAIM_TRIAL` or serving measurement.
- No real Strata full-context proof.
- No 4K/32K/128K evidence and no second-GPU comparison.
- No systemd installation or enablement.
- No download, engine replacement, weight mutation or unowned-process
  termination.

## 5. Known limitations

- Strata model discovery records the pack and `native: true` but does not yet
  resolve the source GGUF shard path. The adapter therefore emits no `--native`
  argument until an explicit `native_shard` is available; Phase 4 must resolve
  and record it read-only.
- The installed Strata build exposes no native microbenchmark or calibration
  command. That boundary is intentionally preserved.
- `--mtp` is mentioned in help prose but is not an observed option definition,
  so it is not emitted.
- The adapter conformance tests use captured fixtures. They prove translation
  and refusal behavior, not GPU performance or recipe quality.

## 6. Exit criteria met

- [x] Help-line capabilities are observed option definitions only.
- [x] llama.cpp server and bench requirements are checked separately.
- [x] Candidate types and bounds are strict.
- [x] Strata installed-build numeric and profile behavior is encoded.
- [x] Profiles do not duplicate managed args or stringify `native: true`.
- [x] Worker uses adapter status parsing without overriding client metrics.
- [x] Offline golden fixtures cover plans, evidence and generated digests.
- [x] Full static/test/contract/typecheck gate passed.
- [x] No contract drift and no forbidden adapter I/O.

## 7. Next

Phase 4 adds tokenizer-backed benchmark corpora, the real serving/full-context
harness, Strata native-shard resolution and operator-approved real evidence
collection. See `docs/NEXT_STEPS.md`.
