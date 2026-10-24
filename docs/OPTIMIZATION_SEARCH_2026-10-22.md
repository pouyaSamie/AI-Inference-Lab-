# Broader settings search — 2026-10-22

Status: both searches complete; Strata has a validated winner. Finalized on 2026-10-23 local time.

The operator requested a broader search after the setup tests found no validated
winner. Studies were submitted through the installed 0.5.0 UI, using the same
existing models/builds, balanced objective and 4K context. No code, model,
engine, driver or safety-setting changes were made.

- Gemma 12B Q4_0 / llama.cpp build 701:
  `exp_a9877d3a-e0ca-5f49-9abd-c703b202f32a`.
- Strata coder IQ1_M / Strata 0.1.44.1:
  `exp_6a10df1b-2db8-5e03-8730-fc87cca7f8f0`.

Each immutable study uses 12 distinct candidates, two finalists, two screening
replications and three final replications, plus its paired baseline. Full-context
proof, quiet-GPU checks, 5% minimum improvement and 95% confidence are retained.
The worker runs one execution command at a time. A finite search identifies the
best tested settings; it does not prove a global optimum or performance at other
contexts. Strata's uncached prompt processing can make this search take hours.

The initial Strata study recorded three EXTERNAL_GPU_CONTENTION failures with
GPU_UTILIZATION_BUSY while both studies were queued. These are rejected attempts,
not performance evidence; this does not establish an unrelated application was
responsible. The Strata study was cancelled through its real UI dialog, and was
recreated only after llama.cpp finished and the GPU was quiet. No safeguard
was weakened. Results and final parameter sets are recorded below.

## Completed llama.cpp search

All 12 alternatives and the paired baseline produced measured observations with
three retained primary samples each. No alternative beat the baseline on the
balanced objective; no recipe qualified. Best tested is the baseline:

- Context: 4096; reasoning off; full GPU offload (`gpu_layers=-1`).
- Threads 8; batch 2048; micro-batch 512; flash attention auto; key cache f16
  (value cache remains the engine default f16).
- 1284.1 client-observed prompt tokens/s, 36.9 generated tokens/s; TTFT 2493.6 ms;
  peak GPU memory 8.20 GiB.

This is the best measured configuration in this finite search, not a proof of a
global optimum. The UI result JSON and screenshots are preserved under
`apps/desktop/release/optimization-search-20261022/`.

The prior accepted setup studies remain preserved and are not modified.

## Fresh sequential Strata search

`exp_be36062f-401a-53dd-a7a8-6b598e8ab649` uses 13 candidates, two finalists,
two screening replications and three final replications; all other model,
context, objective, safety and qualification settings are unchanged. It started
only after the llama study completed. Submission committed, real preflight passed, and all 13 alternatives plus baseline completed with no failed trials.

### Observed repeat-plan defect

Reproduction: cancel a study, then submit an identical plan using the UI. The
fresh 12-candidate Strata submission returned HTTP 500. Its plan ID exactly
matched the cancelled plan (`plan_fdf53d52-1f50-52e5-bf62-941cdd05b596`).
Implementation inspection showed new experiment identity includes the request's
idempotency key, while study identity depends only on spec/plan digests
(`python/lab_api/lab_api/services/experiments.py`, create_experiment). This is the
likely collision; no raw SQL exception was available in the runtime summary log.
A distinct 13-candidate plan committed successfully. This preserves cancelled
work and all safety checks. No code or production state was manually altered.
Expected improvement: scope new study identity to its experiment, retaining
same-key replay semantics, and return a useful UI error instead of an HTTP 500.
The defect remains open; the search continues through the supported UI workaround.

### Interim observations (not final qualification)

The fresh sequential search passed real preflight. Its baseline measured
88.0 prompt tokens/s and 36.9 generated tokens/s. Trial 6 (the fifth alternative)
measured 282.3 prompt tokens/s and 29.8 generated tokens/s with three retained
samples, 11,339.8 ms TTFT and 8.75 GiB peak GPU memory. Its parameters were
`kv=k8v4`, `expert_cache=19`, `prefill=8192`, `spec=2`,
`spec_min_p=0.5410461904005929`, `pool_workers=17`, `kv_resident=32768`,
`kv_grow=false`, `batch=1`, alongside 4096 context, reasoning none, direct
PLE I/O and file-backed expert mappings. These are interim measurements;
formal comparison/qualification remains pending.

## Final Strata result

The installed Compare screen classified this study `VALIDATED_WINNER`. Trial 13
was the qualified 4K winner, with balanced objective ratio **2.0617**
(**+106.17%**) and a 95% paired interval **[1.979, 2.145]**. The paired baseline
and winner each retain three primary samples. All 14 observations were real,
measured server-API observations. Full-context and quiet-GPU requirements were
retained. Five alternatives qualified; the winning trial also had the highest
observed prompt and generation rates in this study.

| Metric | Baseline | Winner #13 |
| --- | ---: | ---: |
| Prompt tokens/s | 88.0 | 323.0 |
| Generated tokens/s | 36.9 | 39.4 |
| Time to first token (ms) | 36,357.0 | 9,910.7 |
| Peak GPU memory (GiB) | 6.25 | 8.77 |

Winning settings, exactly as shown in the installed Live Runs parameter view:

```json
{
  "max_context": 4096,
  "reasoning_effort": "none",
  "ple_io": "direct",
  "resident_experts": false,
  "mmap_experts": true,
  "kv": "k8v4",
  "expert_cache": 15,
  "prefill": "8192",
  "spec": 3,
  "spec_min_p": 0.01078055878321671,
  "pool_workers": 28,
  "kv_resident": 20480,
  "kv_grow": false,
  "batch": 1
}
```

This validates performance for the selected synthetic workload, existing model
and engine hashes, machine and 4K context. It does not prove a global optimum,
answer quality, or performance at larger contexts. The two engines used different
models, so their absolute rates are not an engine-to-engine quality comparison.

UI-derived results, comparison text, screenshots and `best-tested-settings.json`
are preserved in `apps/desktop/release/optimization-search-20261022/`.
The app is left open on the validated comparison. No engine selection, model,
driver or source code was changed during this search.

### Observed recipe timestamp defect

Reproduction: click **Create recipe** on the validated comparison, then open
**Recipes** and retry. The page returns HTTP 500 and remains at “Loading recipes…”.
Screenshot: `lab-recipe-http500.png` in the evidence directory.

A read-only query confirmed a committed validated recipe row:
`recipe_da49af62-4b93-50e7-9c32-e5542f6175bd`, associated with the winning study.
A read-only SQLAlchemy load plus `_recipe_view` reproduced the precise error:
`created_at: timezone_aware — Input should have timezone info`. SQLite returns
`created_at.tzinfo=None`; `_recipe_view` passes it directly to `RecipeView`, which
requires `AwareTimestamp`. The other services already use the repository's
`as_utc` helper. This diagnosis did not alter production state.

Expected improvement: normalize the stored UTC timestamp with `as_utc` when
building recipe responses; cover create, new-session list/get and idempotent
re-creation with SQLite regression tests. The UI should distinguish a saved
recipe from a response/display failure and stop showing a perpetual loading
message after failure. The recipe exists, but UI inspection/verification is
blocked; no recipe verification or promotion is claimed. No duplicate creation
was attempted and no deployment was performed.
