"""Benchmark workload execution over the installed OpenAI-compatible server.

This is a Lab Custom Protocol measurement. It never treats a server's own
timings block as a native benchmark score and never substitutes an estimate
for a missing metric.
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

from .config import WorkerSettings
from .hardware import TelemetrySample, TelemetrySummary, sample_gpu


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

    @property
    def completed(self) -> bool:
        return self.error is None and self.http_status is not None and self.http_status < 400


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
    """Build a deterministic near-capacity synthetic prompt.

    The true token count is measured by the server's usage response. Character
    count is deliberately conservative and never presented as a token count.
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
        for choice in document.get("choices") or []:
            if not isinstance(choice, dict):
                continue
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
        )
    prompt, _approx_tokens = build_prompt(context_tokens, output_tokens)
    client = httpx.Client(
        base_url=f"http://127.0.0.1:{port}",
        timeout=httpx.Timeout(timeout_seconds or max(60.0, context_tokens / 64.0)),
        trust_env=False,
    )
    document = _props(client)
    effective = _effective_context(document)
    payload: dict[str, Any] = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": output_tokens,
        "temperature": 0.0,
        "top_p": 1.0,
        "seed": 42,
        "stream": True,
    }
    started = time.perf_counter()
    try:
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
            return result
    except httpx.HTTPError as exc:
        return ServingRun(
            ttft_ms=None,
            total_latency_ms=(time.perf_counter() - started) * 1000.0,
            prompt_tokens=None,
            output_tokens=None,
            text_preview="",
            effective_context=effective,
            status_document=document,
            telemetry=TelemetrySummary(samples=[sample_gpu(gpu_uuid, pid)]),
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        client.close()


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


def telemetry_with_startup(samples: list[TelemetrySample]) -> TelemetrySummary:
    return TelemetrySummary(samples=samples)
