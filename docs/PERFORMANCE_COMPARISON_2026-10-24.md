# Manual benchmark comparison — 2026-10-24

Read-only inspection of the operator-supplied `/home/pouya/ai-lab/Benchmarks`.
No benchmark, inference engine, model verification or production data mutation
was performed. Reports are historical observations, not new paired evidence.

The Strata `update-v0441-20261016/REPORT.md` reports the coder IQ1_M model on
Strata 0.1.44.1 with resident experts, automatic expert cache, int8 KV,
15 pool workers, 960 MiB reserve, speculative window 4, minimum probability 0.5,
and optional `--adapt-async 1`. It reports a 66.1 tok/s coding decode median
for the matched update and 68.1 / 69.6 tok/s for two asynchronous runs. Workload,
output length, engine identity and metric basis must match before attributing
any gap to an app regression.

The app's Strata search (`StrataAdapter.search_space`) fixes
`resident_experts=False`, `mmap_experts=True`, `ple_io=direct`; it does not explore
asynchronous adaptation or the manual resident profile. More candidates cannot
search parameters absent from that space. This is a concrete coverage limitation,
now disclosed in Optimize. Changing it requires separate capability, RAM safety,
command translation and matched measurement validation; this UI release does not
expand the execution path or relax qualification.

There is also a metric mismatch: `derive_serving_metrics` computes prompt tokens
per client-observed time to first token, and output tokens after the first token
per remaining client latency. The manual Q2_0 report from October 17 explicitly
uses Strata `prompt_per_second` / `predicted_per_second`. Those rates exclude
different overheads and cannot establish a like-for-like regression. That report
also measures 35-token short prompts with 192 output tokens and 2,106-token long
prompts with only 31–43 outputs, rather than the app's synthetic serving ladder.
Its unchanged baseline prefill moved from 142.0 to 271.6 tok/s, so it explicitly
rejects a causal parameter gain based on later rates alone.

The Q2_0 prefill follow-up documents prompt-prefix reuse dropping first-token
time from 10.663 s to 0.568 s (and 0.085 s on identical repeats), with 2,099+
reused tokens. The app intentionally rejects cached-token reuse for fresh-prompt
qualification. Cached serving latency is useful, but is a different measurement.

The llama.cpp October 20 model comparison uses Qwen3.6 35B, CPU placement for
26 expert layers, a 65,536 context and 39,598-token long prompt. The app's earlier
documented Gemma 12B 4K search is a different model/workload. Their absolute
rates do not measure an app regression either.

Remaining: a fresh matched app/manual comparison with identical model hashes,
engine binary, prompts, token caps, cache state and timing basis. No global
optimum, speed fix or manual-profile recipe qualification is claimed.
