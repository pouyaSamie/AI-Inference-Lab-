"""Offline tests for tokenizer-backed workload planning and measurement."""

from __future__ import annotations

import json

import httpx
import pytest
from lab_worker.bench import (
    ServingRun,
    ServingSuite,
    count_prompt_tokens,
    derive_suite_metrics,
    prepare_prompt,
    token_load_mismatch,
    validate_context_measurement,
)

from lab_bench import (
    CORPUS_SHA256,
    ContextMeasurement,
    CorpusMismatch,
    ProtocolViolation,
    corpus_unit,
    fit_prompt_to_tokens,
    near_capacity_case,
    plan_workload_suite,
    primary_case,
    render_corpus,
    verify_corpus,
)
from lab_core import ContextLength, WorkloadSuite


def test_frozen_corpus_identity_and_rendering() -> None:
    assert corpus_unit() == render_corpus(len(corpus_unit()))
    assert CORPUS_SHA256.startswith("11360040") and len(CORPUS_SHA256) == 64
    verify_corpus("lab-synthetic-v1", CORPUS_SHA256)
    with pytest.raises(CorpusMismatch):
        verify_corpus("other", CORPUS_SHA256)
    with pytest.raises(CorpusMismatch):
        verify_corpus("lab-synthetic-v1", "0" * 64)


def test_fit_prompt_is_iterative_and_never_claims_characters() -> None:
    def count(text: str) -> int:
        return max(1, len(text) // 4)

    fit = fit_prompt_to_tokens(1000, count)
    assert fit.token_count == 1000
    assert fit.within_tolerance is True
    assert fit.iterations >= 1


def test_workload_suite_planning_preserves_fractions_and_output_cap() -> None:
    suite = WorkloadSuite(
        prompt_levels=(0.20, 0.55, 0.90),
        output_tokens=128,
        repetitions=2,
        dataset_sha256=CORPUS_SHA256,
    )
    cases = plan_workload_suite(ContextLength.K4, suite)
    assert [case.prompt_fraction for case in cases] == [0.20, 0.55, 0.90]
    assert all(case.output_tokens == 128 for case in cases)
    assert all(case.target_input_tokens + case.output_tokens <= int(ContextLength.K4) for case in cases)
    assert primary_case(cases).prompt_fraction == 0.90
    assert near_capacity_case(cases).prompt_fraction == 0.90
    with pytest.raises(ProtocolViolation):
        plan_workload_suite(
            ContextLength.K4, WorkloadSuite(prompt_levels=(0.5, 0.6, 1.0), output_tokens=4096)
        )


def _mock_client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler, base_url="http://127.0.0.1:8080", trust_env=False)


@pytest.mark.parametrize("engine_id,cached", [("llamacpp", 0), ("strata", 0), ("strata", 99)])
def test_serving_requests_stream_usage_and_recomputes_prompts(monkeypatch, engine_id, cached):
    import os

    from lab_worker.config import WorkerSettings

    from lab_worker import bench

    original_client = httpx.Client
    requests = []
    resets = []

    def handler(request):
        if request.url.path in ("/v1/unload", "/v1/load"):
            resets.append(request.url.path)
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/props":
            return httpx.Response(200, json={"n_ctx": 4096})
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        requests.append(body)
        events = [{"choices": [{"delta": {"content": "ok"}}]}]
        if body.get("stream_options", {}).get("include_usage"):
            events.append(
                {
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 2,
                        "prompt_tokens_details": {"cached_tokens": cached},
                    }
                }
            )
        content = "".join("data: " + json.dumps(event) + "\n\n" for event in events)
        return httpx.Response(200, content=content + "data: [DONE]\n\n")

    monkeypatch.setattr(
        bench.httpx,
        "Client",
        lambda **_: original_client(transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8080"),
    )
    monkeypatch.setattr(
        bench,
        "prepare_prompt",
        lambda *_, **__: bench.PreparedPrompt(
            text="synthetic fixture",
            target_tokens=100,
            measured_tokens=100,
            method="test-tokenizer",
            includes_template=True,
        ),
    )
    result = bench.run_serving_workload(
        WorkerSettings(),
        port=8080,
        model_name="fixture",
        context_tokens=4096,
        output_tokens=2,
        target_input_tokens=100,
        engine_id=engine_id,
        gpu_uuid=None,
        pid=os.getpid(),
    )
    assert result.prompt_tokens == 100
    assert result.output_tokens == 2
    if engine_id == "llamacpp":
        assert requests[0]["cache_prompt"] is False
        assert not resets
    else:
        assert resets == ["/v1/unload", "/v1/load"]
    assert result.completed is (cached == 0)
    if cached:
        assert "cached prompt tokens" in result.error


def test_llamacpp_tokenizer_uses_template_and_tokenize() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/apply-template":
            return httpx.Response(200, json={"prompt": "rendered prompt"})
        if request.url.path == "/tokenize":
            body = json.loads(request.content)
            assert body["content"] == "rendered prompt"
            assert body["add_special"] is True
            return httpx.Response(200, json={"tokens": [1, 2, 3, 4]})
        return httpx.Response(404)

    with _mock_client(httpx.MockTransport(handler)) as client:
        counted = count_prompt_tokens(
            client,
            engine_id="llamacpp",
            model_name="tiny",
            text="hello",
            output_tokens=16,
        )
    assert counted is not None
    assert counted.tokens == 4
    assert counted.includes_template is True
    assert counted.method == "llamacpp-apply-template+tokenize"


def test_strata_tokenizer_uses_anthropic_count_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/messages/count_tokens":
            body = json.loads(request.content)
            assert body["messages"][0]["content"] == "hello"
            assert body["max_tokens"] == 16
            return httpx.Response(200, json={"input_tokens": 123})
        return httpx.Response(404)

    with _mock_client(httpx.MockTransport(handler)) as client:
        counted = count_prompt_tokens(
            client,
            engine_id="strata",
            model_name="tiny",
            text="hello",
            output_tokens=16,
        )
    assert counted is not None
    assert counted.tokens == 123
    assert counted.includes_template is True
    assert counted.method == "strata-count_tokens"


def test_missing_tokenizer_is_a_labelled_character_fallback() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with _mock_client(httpx.MockTransport(handler)) as client:
        prepared = prepare_prompt(
            client,
            engine_id="llamacpp",
            model_name="tiny",
            context_tokens=4096,
            target_input_tokens=3000,
            output_tokens=256,
        )
    assert prepared.method == "character-fallback"
    assert prepared.measured_tokens is None
    assert prepared.includes_template is False


def test_suite_metrics_use_primary_median_and_context_validation() -> None:
    suite = WorkloadSuite(prompt_levels=(0.25, 0.6, 0.9, 0.98), output_tokens=16)
    cases = plan_workload_suite(ContextLength.K4, suite)
    primary = primary_case(cases)
    near = near_capacity_case(cases)

    def run(case, *, ttft: float, prompt_tokens: int, measured: int) -> ServingRun:
        return ServingRun(
            http_status=200,
            ttft_ms=ttft,
            total_latency_ms=ttft + 100.0,
            prompt_tokens=prompt_tokens,
            output_tokens=16,
            text_preview="ok",
            effective_context=4096,
            case_id=case.case_id,
            prompt_fraction=case.prompt_fraction,
            target_input_tokens=case.target_input_tokens,
            measured_prompt_tokens=measured,
            token_count_method="test-tokenizer",
            token_count_includes_template=True,
        )

    runs = (
        run(
            primary,
            ttft=100.0,
            prompt_tokens=primary.target_input_tokens,
            measured=primary.target_input_tokens,
        ),
        run(
            primary,
            ttft=120.0,
            prompt_tokens=primary.target_input_tokens,
            measured=primary.target_input_tokens,
        ),
        run(near, ttft=140.0, prompt_tokens=near.target_input_tokens, measured=near.target_input_tokens),
    )
    result = ServingSuite(
        cases=cases,
        runs=runs,
        primary_case_id=primary.case_id,
        near_case_id=near.case_id,
    )
    metrics = derive_suite_metrics(result)
    assert metrics["time_to_first_token_ms"] == pytest.approx(110.0)
    assert metrics["sample_count"] == 2
    measurement = validate_context_measurement(result, context_tokens=4096)
    assert measurement is not None
    measurement.validate_measurement()
    assert token_load_mismatch(result.near_run()) is None


def test_context_measurement_rejects_overflow_and_truncation() -> None:
    with pytest.raises(ProtocolViolation):
        ContextMeasurement(
            context=ContextLength.K4,
            configured_context=4096,
            effective_context=4096,
            input_tokens=4000,
            output_tokens=256,
        ).validate_measurement()
    with pytest.raises(ProtocolViolation):
        ContextMeasurement(
            context=ContextLength.K4,
            configured_context=4096,
            effective_context=4096,
            input_tokens=100,
            output_tokens=16,
            truncated=True,
        ).validate_measurement()
