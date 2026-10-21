"""Benchmark workload execution over the installed OpenAI-compatible server.

This is a Lab Custom Protocol measurement. It never treats a server's own
timings block as a native benchmark score and never substitutes an estimate
for a missing metric.

Prompt sizes are measured with the target engine's tokenizer endpoint when the
installed server exposes one. Character estimates are retained only as an
explicit, labelled fallback and can never qualify a measured observation.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Event
from typing import Any

import httpx

from lab_bench import (
    ContextMeasurement,
    ProtocolViolation,
    WorkloadCase,
    fit_prompt_to_tokens,
    near_capacity_case,
    plan_workload_suite,
    primary_case,
    render_corpus,
    verify_corpus,
)
from lab_core import ContextLength, WorkloadSuite

from .config import WorkerSettings
from .hardware import TelemetrySample, TelemetrySummary, sample_gpu

CHARACTER_FALLBACK = "character-fallback"


@dataclass(frozen=True)
class TokenCount:
    tokens: int
    method: str
    includes_template: bool


@dataclass(frozen=True)
class PreparedPrompt:
    text: str
    target_tokens: int
    measured_tokens: int | None
    method: str
    includes_template: bool
    iterations: int = 0


@dataclass
class ServingRun:
    ttft_ms: float | None
    total_latency_ms: float
    prompt_tokens: int | None
    output_tokens: int | None
    text_preview: str
    effective_context: int | None
    status_document: dict[str, Any] = field(default_factory=dict)
    unavailable: dict[str, str] = field(default_factory=dict)
    telemetry: TelemetrySummary = field(default_factory=TelemetrySummary)
    error: str | None = None
    http_status: int | None = None
    case_id: str | None = None
    prompt_fraction: float | None = None
    target_input_tokens: int | None = None
    token_count_method: str | None = None
    token_count_includes_template: bool = False
    measured_prompt_tokens: int | None = None
    truncated: bool = False
    finish_reason: str | None = None

    @property
    def completed(self) -> bool:
        return self.error is None and self.http_status is not None and self.http_status < 400


@dataclass(frozen=True)
class ServingSuite:
    cases: tuple[WorkloadCase, ...]
    runs: tuple[ServingRun, ...]
    primary_case_id: str
    near_case_id: str
    error: str | None = None

    def primary_runs(self) -> tuple[ServingRun, ...]:
        return tuple(run for run in self.runs if run.case_id == self.primary_case_id)

    def near_run(self) -> ServingRun | None:
        return next((run for run in self.runs if run.case_id == self.near_case_id), None)

    @property
    def completed(self) -> bool:
        return bool(self.runs) and self.error is None and all(run.completed for run in self.runs)


def _props(client: httpx.Client) -> dict[str, Any]:
    for path in ("/props", "/v1/status"):
        try:
            response = client.get(path)
        except httpx.HTTPError:
            continue
        if response.status_code != 200:
            continue
        try:
            document = response.json()
        except ValueError:
            continue
        if isinstance(document, dict):
            return document
    return {}


def _effective_context(document: dict[str, Any]) -> int | None:
    for value in (
        document.get("n_ctx"),
        (document.get("default_generation_settings") or {}).get("n_ctx")
        if isinstance(document.get("default_generation_settings"), dict)
        else None,
        (document.get("context") or {}).get("native") if isinstance(document.get("context"), dict) else None,
        (document.get("context") or {}).get("max_positions")
        if isinstance(document.get("context"), dict)
        else None,
    ):
        if isinstance(value, (int, float)) and value > 0:
            return int(value)
    return None


def build_prompt(context_tokens: int, output_tokens: int, *, fraction: float = 0.90) -> tuple[str, int]:
    """Build a deterministic character-based fallback prompt.

    This is used only when the installed server exposes no tokenizer endpoint.
    It never claims a token count; the response usage remains authoritative.
    """
    usable = max(1, int(context_tokens * fraction) - output_tokens)
    target_chars = max(256, usable * 4)
    sentence = (
        "The laboratory measures deterministic inference throughput using repeated, "
        "neutral text with no private data. "
    )
    repeats = max(1, math.ceil(target_chars / len(sentence)))
    prompt = (sentence * repeats)[:target_chars]
    return prompt, usable


def _json_post(client: httpx.Client, path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    try:
        response = client.post(path, json=payload)
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    try:
        document = response.json()
    except ValueError:
        return None
    return document if isinstance(document, dict) else None


def count_prompt_tokens(
    client: httpx.Client,
    *,
    engine_id: str,
    model_name: str,
    text: str,
    output_tokens: int,
) -> TokenCount | None:
    """Ask the target server for the token count it would actually read.

    llama.cpp exposes ``/apply-template`` + ``/tokenize``; Strata exposes the
    Anthropic-compatible ``/v1/messages/count_tokens``. Any missing or failed
    endpoint returns ``None`` and the caller must label the prompt as
    character-estimated rather than tokenized.
    """

    messages = [{"role": "user", "content": text}]
    if engine_id == "strata":
        document = _json_post(
            client,
            "/v1/messages/count_tokens",
            {
                "model": model_name,
                "messages": messages,
                "max_tokens": output_tokens,
            },
        )
        if document is not None:
            value = document.get("input_tokens")
            if isinstance(value, (int, float)) and value >= 0:
                return TokenCount(int(value), "strata-count_tokens", True)
        return None

    if engine_id != "llamacpp":
        return None

    prompt = text
    method = "llamacpp-tokenize-content"
    includes_template = False
    template = _json_post(client, "/apply-template", {"messages": messages})
    if template is not None and isinstance(template.get("prompt"), str):
        prompt = template["prompt"]
        method = "llamacpp-apply-template+tokenize"
        includes_template = True
    document = _json_post(
        client,
        "/tokenize",
        {"content": prompt, "add_special": includes_template},
    )
    if document is None:
        return None
    tokens = document.get("tokens")
    if not isinstance(tokens, list):
        return None
    return TokenCount(len(tokens), method, includes_template)


def prepare_prompt(
    client: httpx.Client,
    *,
    engine_id: str,
    model_name: str,
    context_tokens: int,
    target_input_tokens: int,
    output_tokens: int,
) -> PreparedPrompt:
    """Fit the frozen corpus against the target tokenizer, or fall back openly."""

    if target_input_tokens <= 0:
        raise ValueError("target_input_tokens must be positive")
    reserve = max(64, math.ceil(context_tokens * 0.01))
    initial_text = render_corpus(max(256, target_input_tokens * 4))
    initial = count_prompt_tokens(
        client,
        engine_id=engine_id,
        model_name=model_name,
        text=initial_text,
        output_tokens=output_tokens,
    )
    if initial is None:
        prompt, _approx = build_prompt(context_tokens, output_tokens)
        return PreparedPrompt(
            text=prompt,
            target_tokens=target_input_tokens,
            measured_tokens=None,
            method=CHARACTER_FALLBACK,
            includes_template=False,
        )

    target = target_input_tokens if initial.includes_template else max(1, target_input_tokens - reserve)

    def count(text: str) -> int:
        counted = count_prompt_tokens(
            client,
            engine_id=engine_id,
            model_name=model_name,
            text=text,
            output_tokens=output_tokens,
        )
        if counted is None:
            raise ValueError("tokenizer endpoint stopped responding")
        return counted.tokens

    try:
        fit = fit_prompt_to_tokens(target, count, tolerance=0.005)
    except ValueError:
        prompt, _approx = build_prompt(context_tokens, output_tokens)
        return PreparedPrompt(
            text=prompt,
            target_tokens=target_input_tokens,
            measured_tokens=None,
            method=CHARACTER_FALLBACK,
            includes_template=False,
        )
    return PreparedPrompt(
        text=fit.text,
        target_tokens=target_input_tokens,
        measured_tokens=fit.token_count,
        method=initial.method,
        includes_template=initial.includes_template,
        iterations=fit.iterations,
    )


def _parse_sse(
    response: httpx.Response,
    *,
    started: float,
    model_name: str,
    gpu_uuid: str | None,
    pid: int,
    on_tick: Callable[[], None] | None = None,
    cancel_event: Event | None = None,
) -> ServingRun:
    first_content_at: float | None = None
    text_parts: list[str] = []
    usage: dict[str, Any] = {}
    timings: dict[str, Any] = {}
    events = 0
    cancel_error: str | None = None
    truncated = False
    finish_reason: str | None = None
    last_tick = time.monotonic()
    for line in response.iter_lines():
        if cancel_event is not None and cancel_event.is_set():
            cancel_error = "cancelled by operator"
            break
        now = time.monotonic()
        if on_tick is not None and now - last_tick >= 20.0:
            last_tick = now
            on_tick()
        if not line:
            continue
        if line.startswith("data:"):
            payload = line[5:].strip()
        elif line.startswith("{"):
            payload = line.strip()
        else:
            continue
        if payload == "[DONE]":
            break
        try:
            document = json.loads(payload)
        except ValueError:
            continue
        events += 1
        if not isinstance(document, dict):
            continue
        if isinstance(document.get("usage"), dict):
            usage.update(document["usage"])
        if isinstance(document.get("timings"), dict):
            timings.update(document["timings"])
        if document.get("truncated") is True:
            truncated = True
        for choice in document.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            reason = choice.get("finish_reason")
            if isinstance(reason, str):
                finish_reason = reason
            delta = choice.get("delta")
            content = None
            if isinstance(delta, dict):
                content = delta.get("content")
            if content is None:
                message = choice.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
            if isinstance(content, str) and content:
                if first_content_at is None:
                    first_content_at = time.perf_counter()
                text_parts.append(content)
    finished = time.perf_counter()
    prompt_tokens = usage.get("prompt_tokens")
    output_tokens = usage.get("completion_tokens")
    ttft = (first_content_at - started) * 1000.0 if first_content_at is not None else None
    total = (finished - started) * 1000.0
    if ttft is None:
        unavailable = {"time_to_first_token_ms": "stream produced no content event; TTFT was not invented"}
    else:
        unavailable = {}
    telemetry = TelemetrySummary(samples=[sample_gpu(gpu_uuid, pid)])
    if finish_reason == "length":
        unavailable["complete_output"] = "generation stopped at the requested token cap"
    return ServingRun(
        ttft_ms=ttft,
        total_latency_ms=total,
        prompt_tokens=int(prompt_tokens) if isinstance(prompt_tokens, (int, float)) else None,
        output_tokens=int(output_tokens) if isinstance(output_tokens, (int, float)) else None,
        text_preview="".join(text_parts)[:2000],
        effective_context=None,
        unavailable=unavailable,
        telemetry=telemetry,
        error=cancel_error,
        http_status=response.status_code,
        truncated=truncated,
        finish_reason=finish_reason,
    )


def run_serving_workload(
    settings: WorkerSettings,
    *,
    port: int,
    model_name: str,
    context_tokens: int,
    output_tokens: int,
    gpu_uuid: str | None,
    pid: int,
    engine_id: str = "llamacpp",
    target_input_tokens: int | None = None,
    case_id: str | None = None,
    prompt_fraction: float | None = None,
    seed: int = 42,
    temperature: float = 0.0,
    top_p: float = 1.0,
    timeout_seconds: float | None = None,
    on_tick: Callable[[], None] | None = None,
    cancel_event: Event | None = None,
) -> ServingRun:
    if cancel_event is not None and cancel_event.is_set():
        return ServingRun(
            ttft_ms=None,
            total_latency_ms=0.0,
            prompt_tokens=None,
            output_tokens=None,
            text_preview="",
            effective_context=None,
            error="cancelled by operator",
            case_id=case_id,
            prompt_fraction=prompt_fraction,
            target_input_tokens=target_input_tokens,
        )
    client = httpx.Client(
        base_url=f"http://127.0.0.1:{port}",
        timeout=httpx.Timeout(timeout_seconds or max(60.0, context_tokens / 64.0)),
        trust_env=False,
    )
    try:
        document = _props(client)
        effective = _effective_context(document)
        target = target_input_tokens
        if target is None:
            target = max(1, int(context_tokens * 0.90) - output_tokens)
        if effective is not None and target + output_tokens > effective:
            return ServingRun(
                ttft_ms=None,
                total_latency_ms=0.0,
                prompt_tokens=None,
                output_tokens=None,
                text_preview="",
                effective_context=effective,
                status_document=document,
                error=(
                    f"planned prompt {target} + output {output_tokens} exceeds "
                    f"server effective context {effective}"
                ),
                case_id=case_id,
                prompt_fraction=prompt_fraction,
                target_input_tokens=target,
            )
        prepared = prepare_prompt(
            client,
            engine_id=engine_id,
            model_name=model_name,
            context_tokens=context_tokens,
            target_input_tokens=target,
            output_tokens=output_tokens,
        )
        payload: dict[str, Any] = {
            "model": model_name,
            "messages": [{"role": "user", "content": prepared.text}],
            "max_tokens": output_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "seed": seed,
            "stream": True,
        }
        started = time.perf_counter()
        with client.stream("POST", "/v1/chat/completions", json=payload) as response:
            if response.status_code >= 400:
                body = response.read().decode("utf-8", "replace")[:1000]
                return ServingRun(
                    ttft_ms=None,
                    total_latency_ms=(time.perf_counter() - started) * 1000.0,
                    prompt_tokens=None,
                    output_tokens=None,
                    text_preview="",
                    effective_context=effective,
                    status_document=document,
                    telemetry=TelemetrySummary(samples=[sample_gpu(gpu_uuid, pid)]),
                    error=f"HTTP {response.status_code}: {body}",
                    http_status=response.status_code,
                    case_id=case_id,
                    prompt_fraction=prompt_fraction,
                    target_input_tokens=target,
                    token_count_method=prepared.method,
                    token_count_includes_template=prepared.includes_template,
                    measured_prompt_tokens=prepared.measured_tokens,
                )
            result = _parse_sse(
                response,
                started=started,
                model_name=model_name,
                gpu_uuid=gpu_uuid,
                pid=pid,
                on_tick=on_tick,
                cancel_event=cancel_event,
            )
            result.effective_context = effective
            result.status_document = document
            result.case_id = case_id
            result.prompt_fraction = prompt_fraction
            result.target_input_tokens = target
            result.token_count_method = prepared.method
            result.token_count_includes_template = prepared.includes_template
            result.measured_prompt_tokens = prepared.measured_tokens
            if prepared.measured_tokens is None:
                result.unavailable["prompt_size"] = (
                    "server exposed no usable tokenizer endpoint; prompt size is a character estimate"
                )
            if effective is None:
                result.unavailable["effective_context"] = "server did not report an effective context"
            return result
    except httpx.HTTPError as exc:
        return ServingRun(
            ttft_ms=None,
            total_latency_ms=0.0,
            prompt_tokens=None,
            output_tokens=None,
            text_preview="",
            effective_context=None,
            telemetry=TelemetrySummary(samples=[sample_gpu(gpu_uuid, pid)]),
            error=f"{type(exc).__name__}: {exc}",
            case_id=case_id,
            prompt_fraction=prompt_fraction,
            target_input_tokens=target_input_tokens,
        )
    finally:
        client.close()


def run_serving_suite(
    settings: WorkerSettings,
    *,
    port: int,
    model_name: str,
    engine_id: str,
    context_tokens: int,
    workload: WorkloadSuite,
    gpu_uuid: str | None,
    pid: int,
    tokenizer_id: str | None = None,
    timeout_seconds: float | None = None,
    on_tick: Callable[[], None] | None = None,
    cancel_event: Event | None = None,
) -> ServingSuite:
    """Execute the tokenizer-backed prompt ladder for one candidate context.

    Every selected level runs once. The primary comparable level is repeated
    according to the workload suite; the near-capacity level is a single stress
    probe. A failure stops the ladder so a smaller level can never be presented
    as if full context passed.
    """

    try:
        verify_corpus(workload.dataset_id, workload.dataset_sha256)
        cases = plan_workload_suite(
            ContextLength(int(context_tokens)),
            workload,
            tokenizer_id=tokenizer_id or model_name,
        )
    except (ProtocolViolation, ValueError) as exc:
        return ServingSuite(cases=(), runs=(), primary_case_id="", near_case_id="", error=str(exc))
    primary = primary_case(cases)
    near = near_capacity_case(cases)
    runs: list[ServingRun] = []
    for case in cases:
        repetitions = max(1, workload.repetitions) if case.case_id == primary.case_id else 1
        for index in range(repetitions):
            if cancel_event is not None and cancel_event.is_set():
                break
            run = run_serving_workload(
                settings,
                port=port,
                model_name=model_name,
                context_tokens=context_tokens,
                output_tokens=case.output_tokens,
                gpu_uuid=gpu_uuid,
                pid=pid,
                engine_id=engine_id,
                target_input_tokens=case.target_input_tokens,
                case_id=case.case_id,
                prompt_fraction=case.prompt_fraction,
                seed=case.seed + index,
                temperature=workload.temperature,
                top_p=workload.top_p,
                timeout_seconds=timeout_seconds,
                on_tick=on_tick,
                cancel_event=cancel_event,
            )
            runs.append(run)
            if run.error is not None:
                break
        if runs and runs[-1].error is not None:
            break
    error = next((run.error for run in runs if run.error), None)
    return ServingSuite(
        cases=cases,
        runs=tuple(runs),
        primary_case_id=primary.case_id,
        near_case_id=near.case_id,
        error=error,
    )


def effective_context(port: int, timeout: float = 5.0) -> tuple[int | None, dict[str, Any]]:
    client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=timeout, trust_env=False)
    try:
        document = _props(client)
        return _effective_context(document), document
    finally:
        client.close()


def derive_serving_metrics(run: ServingRun) -> dict[str, float | int | None]:
    """Derive only client-observed values; missing usage is left missing."""
    prefill = None
    decode = None
    if run.prompt_tokens and run.ttft_ms and run.ttft_ms > 0:
        prefill = run.prompt_tokens / (run.ttft_ms / 1000.0)
    if (
        run.output_tokens
        and run.output_tokens > 1
        and run.ttft_ms is not None
        and run.total_latency_ms > run.ttft_ms
    ):
        decode = (run.output_tokens - 1) / ((run.total_latency_ms - run.ttft_ms) / 1000.0)
    return {
        "prefill_tokens_per_sec": prefill,
        "decode_tokens_per_sec": decode,
        "time_to_first_token_ms": run.ttft_ms,
        "total_latency_ms": run.total_latency_ms,
        "prompt_tokens": run.prompt_tokens,
        "output_tokens": run.output_tokens,
    }


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def derive_suite_metrics(suite: ServingSuite) -> dict[str, float | int | None]:
    """Median the repeated primary level; never merge different prompt loads."""

    primary = [run for run in suite.primary_runs() if run.completed]
    if not primary:
        return {
            "prefill_tokens_per_sec": None,
            "decode_tokens_per_sec": None,
            "time_to_first_token_ms": None,
            "total_latency_ms": None,
            "prompt_tokens": None,
            "output_tokens": None,
            "sample_count": 0,
        }
    derived = [derive_serving_metrics(run) for run in primary]

    def median_metric(key: str) -> float | None:
        values: list[float] = []
        for item in derived:
            value = item[key]
            if not isinstance(value, (int, float)):
                return None
            values.append(float(value))
        return _median(values)

    prompt_tokens = median_metric("prompt_tokens")
    output_tokens = median_metric("output_tokens")
    return {
        "prefill_tokens_per_sec": median_metric("prefill_tokens_per_sec"),
        "decode_tokens_per_sec": median_metric("decode_tokens_per_sec"),
        "time_to_first_token_ms": median_metric("time_to_first_token_ms"),
        "total_latency_ms": median_metric("total_latency_ms"),
        "prompt_tokens": int(prompt_tokens) if prompt_tokens is not None else None,
        "output_tokens": int(output_tokens) if output_tokens is not None else None,
        "sample_count": len(primary),
    }


def validate_context_measurement(
    suite: ServingSuite,
    *,
    context_tokens: int,
) -> ContextMeasurement | None:
    """Reject silent truncation or a prompt that missed its planned token load."""

    near = suite.near_run()
    if near is None or not near.completed or near.prompt_tokens is None or near.output_tokens is None:
        return None
    effective = near.effective_context or int(context_tokens)
    return ContextMeasurement(
        context=ContextLength(int(context_tokens)),
        configured_context=int(context_tokens),
        effective_context=effective,
        input_tokens=near.prompt_tokens,
        output_tokens=near.output_tokens,
        truncated=near.truncated,
        # ``input_tokens`` is the server-reported prompt usage, which already
        # includes the chat template. Adding an inferred template overhead here
        # would double-count it.
        template_overhead_tokens=0,
    )


def token_load_mismatch(run: ServingRun | None, *, tolerance: float = 0.05) -> str | None:
    """Return a reason when the measured request missed the planned token load."""

    if run is None:
        return "near-capacity case was not executed"
    if run.token_count_method == CHARACTER_FALLBACK:
        # A character-estimated prompt cannot prove a token target. It is
        # already labelled screening-only rather than turned into a false
        # context mismatch.
        return None
    if run.prompt_tokens is None:
        return "server usage did not report prompt tokens"
    target = run.target_input_tokens
    if target is None:
        return "planned prompt token target is missing"
    delta = abs(run.prompt_tokens - target)
    allowed = max(32, int(target * tolerance))
    if delta > allowed:
        return (
            f"measured prompt {run.prompt_tokens} differs from planned {target} by more than {allowed} tokens"
        )
    return None


def telemetry_with_startup(samples: list[TelemetrySample]) -> TelemetrySummary:
    return TelemetrySummary(samples=samples)
