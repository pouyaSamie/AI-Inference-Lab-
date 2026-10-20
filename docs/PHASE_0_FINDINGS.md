# Phase 0 findings — installed reality

Date of reconnaissance: 2026-10-20/21 (local workstation).
Scope: verify the installed executable surface before writing adapters. This is
**evidence inventory, not a benchmark result**.

Fixtures are sanitized copies under `fixtures/engines/`. No model weights,
prompts, tokens or private paths beyond the local lab layout are committed.

## 1. Environment observed

- Linux x86_64 host.
- NVIDIA GeForce RTX 3060, compute capability 8.6, reported total VRAM
  `11908 MiB` in the captured CUDA initialization banner.
- Python toolchain for the lab: CPython 3.13 in the local `uv` environment;
  `requires-python = ">=3.12,<3.15"`.
- Model root: `/home/pouya/ai-lab/models`.
- Engine root: `/home/pouya/ai-lab/Inference`.

## 2. llama.cpp

### Installed binaries

```text
/home/pouya/ai-lab/Inference/llama-cpp/builds/linux/latest-candidate/bin/llama-server
/home/pouya/ai-lab/Inference/llama-cpp/builds/linux/latest-candidate/bin/llama-bench
/home/pouya/ai-lab/Inference/llama-cpp/builds/linux/latest-candidate/bin/llama-cli
```

Important: the directory is `llama-cpp` (with a hyphen). Earlier placeholder
worker defaults used `llamacpp`; the defaults were corrected during Phase 1.

### Version evidence

`fixtures/engines/llamacpp-0.7.0-dev-build701/version.txt` records:

```text
ggml_cuda_init: found 1 CUDA devices (Total VRAM: 11908 MiB):
  Device 0: NVIDIA GeForce RTX 3060, compute capability 8.6, VMM: yes, VRAM: 11908 MiB
version: 0.7.0-dev (build 701, commit dd002b91f)
built with GNU 15.2.0 for Linux x86_64
```

The installed binaries are CUDA builds. The helper libraries are not on the
default loader path; real execution requires:

```bash
export LD_LIBRARY_PATH=/home/pouya/ai-lab/Inference/llama-cpp/builds/linux/latest-candidate/bin
```

### Observed CLI surface (examples, not a complete union)

From the captured `llama-server --help`:

- model/context: `-m/--model`, `-c/--ctx-size`, `-b/--batch-size`,
  `-ub/--ubatch-size`, `-t/--threads`, `--threads-batch`;
- GPU/backend: `-ngl/--n-gpu-layers`, `-fa/--flash-attn [on|off|auto]`,
  `-ctk/--cache-type-k`, `-ctv/--cache-type-v`;
- server: `--host`, `--port`, `--alias`, readiness/API options present in the
  installed help;
- sampling and generation controls are present, but are not automatically valid
  benchmark search dimensions.

From the captured `llama-bench --help`:

- workload shape: `-p/--n-prompt`, `-n/--n-gen`, `-d/--n-depth`,
  `-b`, `-ub`, `-t`, `-ngl`, `-fa`, `-ctk`, `-ctv`, `-r/--repetitions`;
- output formats: `-o/--output <csv|json|jsonl|md|sql>`;
- device/readiness controls: `--list-devices`, `--fit-target`, `--fit-ctx`.

The adapter only exposes flags observed in the installed help. Presence of a
flag does **not** prove that every value is legal or that a short `llama-bench`
run proves full-context capacity. Phase 4 must add the full-context
`llama-server` allocation test described in the PRD.

### Model inventory observed

```text
/home/pouya/ai-lab/models/Qwen3.6-35B-A3B-GGUF/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf   ~21 GiB
/home/pouya/ai-lab/models/Qwen3.6-35B-A3B-GGUF/mmproj-F32.gguf                 ~1.7 GiB
/home/pouya/ai-lab/models/Qwen3.6-35B-A3B-Uncensored/...-Q4_K_M.gguf           ~20 GiB
```

These are **discovered model artifacts**, not validated candidates. A 35B
MoE/quantized model on a 12 GiB GPU may require partial CPU expert offload and
must be empirically qualified; no claim is made here.

## 3. Strata

### Installed build

```text
/home/pouya/ai-lab/Inference/strata/builds/linux/v0.1.44.1-candidate/strata
/home/pouya/ai-lab/Inference/strata/builds/linux/current/strata
```

`fixtures/engines/strata-0.1.44.1/version.txt`:

```text
strata 0.1.44.1
```

`fixtures/engines/strata-0.1.44.1/build.json` records a local CUDA 13.1 source
build, architecture `86`, `src` `7dfd34378bd2d32a`, commit
`296b59d2f73c8f04a805df29c2fa97655adace78`, and binary SHA-256
`fa29349e3eaab141aceab98a91dc999b450a7f6b9c28f323cafc7ec865a2a98d`.
Treat the digest as build evidence, not as a release recipe.

### Observed command surface

The installed executable exposes `strata generate`; the captured help includes
model pack, token, GPU, PLE, KV, context, sampling and diagnostics options. A
Python serving entry point exists at:

```text
/home/pouya/ai-lab/Inference/strata/source/serve/server.py
```

The PRD's illustrative Strata commands (`models list`, `models inspect`,
`doctor`, `serve --plan`, `engine calibrate`, `bench run`) were **not found in
the installed 0.1.44.1 CLI**. They must not be claimed or synthesized.

### Model inventory observed

```text
/home/pouya/ai-lab/models/Strata-Qwen3.8-Flash-Next-Coder/IQ1_M/*.gguf
/home/pouya/ai-lab/models/Strata-Qwen3.8-Flash-Next-Q2_0/mtp/*.gguf
```

These are Strata-specific packs/manifests. They are not generic GGUF inputs and
must be handled through Strata-native profile/pack semantics when real execution
is implemented.

## 4. Adapter consequences

1. **llama.cpp** capability discovery is help/version-driven. The adapter parses
   observed flags and builds version-scoped descriptors; any unobserved flag is
   unsupported. It does not assume a universal flag set.
2. **Strata** capability discovery must be conservative: only `generate` and the
   known Python serving path are evidence. The adapter produces a Lab Custom
   Protocol workload plan and does not pretend there is a native benchmark
   command or a standard Strata score.
3. Both adapters are pure. Probe commands and server/bench plans are typed
   `CommandSpec`/`ExecutionPlan` values; execution belongs to the Phase 2 worker
   runner.
4. Full-context feasibility cannot be inferred from `llama-bench` or a GGUF
   header. The Phase 4 protocol must start the actual server with pinned KV
   settings, run near-capacity token loads, and retain startup/post-prefill
   memory evidence.
5. The RTX 3060 has 11908 MiB reported VRAM. Any 128K or large-MoE result must be
   empirical and may be `INFEASIBLE_128K`; no six-context winner is assumed.

## 5. Phase 0 gaps (explicitly not claimed)

- No live 4K/32K measurement was executed as part of this foundation. The
  evidence above is binary/help/version reconnaissance and sanitized fixtures.
- No second GPU type (L40S or equivalent) was exercised.
- No live llama.cpp server or Strata serving run was performed.
- No model SHA-256 strong hashes were computed for production recipes.
- No quality/correctness dataset was established.

These gaps block later benchmark and recipe claims, not the Phase 1 protocol
foundation. They must be closed before treating any performance or recipe result
as validated.
