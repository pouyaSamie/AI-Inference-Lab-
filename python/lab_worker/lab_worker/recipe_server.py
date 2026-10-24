"""One explicitly requested, worker-owned local server with an exclusive GPU lease."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from lab_core.ids import sha256_text

from lab_core import (
    RecipeChatPayload,
    RecipeChatResult,
    RunRecipePayload,
    RunRecipeResult,
    ServingSession,
    StopRecipePayload,
    StopRecipeResult,
    utcnow,
)

from .bench import effective_context
from .gpu import GpuLease
from .hardware import gpu_preflight
from .runner import ServerProcess, allocate_loopback_port
from .sandbox import create_sandbox

if TYPE_CHECKING:
    from .real_executor import RealExecutor


class RecipeServer:
    def __init__(self, owner: RealExecutor) -> None:
        self.owner = owner
        self.lock = threading.RLock()
        self.session: ServingSession | None = None
        self.server: ServerProcess | None = None
        self.gpu: GpuLease | None = None
        self.cancel = threading.Event()
        self.model_name = ""
        self.engine_id = ""

    def status(self) -> ServingSession | None:
        with self.lock:
            if self.server and self.server._process.poll() is not None:
                self._stop_locked("failed", "The engine exited. Review the recipe and start it again.")
            return self.session

    def _stop_locked(self, state: str = "stopped", message: str = "Engine stopped.") -> None:
        if self.server:
            self.server.stop()
            self.server = None
        if self.gpu:
            self.gpu.release()
            self.gpu = None
        if self.session:
            self.session = self.session.model_copy(update={"state": state, "port": None, "message": message})

    def stop(self, payload: StopRecipePayload | None = None) -> StopRecipeResult:
        with self.lock:
            session_id = (
                payload.session_id if payload else (self.session.session_id if self.session else "shutdown")
            )
            if self.session and self.session.session_id == session_id:
                self.cancel.set()
                if self.session.state == "starting" and self.server is None:
                    # The startup thread owns its lease until the runner stops.
                    return StopRecipeResult(session_id=session_id, stopped=False)
                self._stop_locked()
                return StopRecipeResult(session_id=session_id, stopped=True)
            # A late Stop for an older session cannot stop its replacement.
            return StopRecipeResult(session_id=session_id, stopped=False)

    def _hash(self, path: Path, tick: Callable[[], None], *, progress: bool = False) -> str:
        digest = hashlib.sha256()
        before = path.stat()
        with path.open("rb") as stream:
            while chunk := stream.read(8 * 1024 * 1024):
                if self.cancel.is_set():
                    raise RuntimeError("Recipe startup cancelled.")
                digest.update(chunk)
                if progress:
                    with self.lock:
                        if self.session:
                            self.session = self.session.model_copy(
                                update={"bytes_done": self.session.bytes_done + len(chunk)}
                            )
                tick()
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise RuntimeError("A recipe input changed during verification. Rescan and verify it.")
        return digest.hexdigest()

    def start(self, payload: RunRecipePayload, command_id: str, renew: Callable[[], None]) -> RunRecipeResult:
        from .real_executor import _strata_memory_failure, _write_generated_files

        if payload.issued_at < self.owner.booted_at:
            raise RuntimeError("This launch predates the worker restart. Click Run recipe again.")
        with self.lock:
            current = self.status()
            if current and current.state in {"starting", "ready"}:
                if current.session_id == payload.session_id and current.state == "ready":
                    return RunRecipeResult(session=current)
                raise RuntimeError("A recipe session is already running. Stop it first.")
            self.cancel = threading.Event()
            self.session = ServingSession(
                session_id=payload.session_id,
                recipe_id=payload.recipe_id,
                state="starting",
                context_tokens=int(payload.candidate.context),
                started_at=utcnow(),
                message="Verifying the recipe's files before loading the model.",
            )
        last_renewed = 0.0

        def tick() -> None:
            nonlocal last_renewed
            if time.monotonic() - last_renewed >= 5:
                renew()
                last_renewed = time.monotonic()

        try:
            candidate = payload.candidate
            allowed, _reasons = gpu_preflight(self.owner.settings, payload.gpu_uuid)
            if not allowed:
                raise RuntimeError("The GPU is busy or unavailable. Close GPU workloads and retry.")
            snapshot = self.owner.current_snapshot()
            model = snapshot.model(payload.model.model_id) if snapshot else None
            if (
                model is None
                or not model.hashes_complete()
                or model.artifact_digest != candidate.model_digest
                or candidate.worker_id != self.owner.settings.worker_id
            ):
                raise RuntimeError("Recipe model or worker identity does not match the current inventory.")
            bundle = self.owner._bundle(candidate.engine_id)
            engine = bundle.manifest.engine
            if engine.executable_sha256 != candidate.engine_sha256 or not engine.executable_path:
                raise RuntimeError("The recipe's engine build changed. Benchmark the selected build again.")
            if self._hash(Path(engine.executable_path), tick) != candidate.engine_sha256:
                raise RuntimeError("The engine executable changed. Rescan and verify it.")
            with self.lock:
                assert self.session is not None
                self.session = self.session.model_copy(
                    update={
                        "bytes_total": sum(f.size_bytes for f in model.files),
                        "files_total": len(model.files),
                    }
                )
            for item in model.files:
                if self._hash(Path(item.path), tick, progress=True) != item.sha256:
                    raise RuntimeError("A model file changed. Rescan and verify it.")
                with self.lock:
                    assert self.session is not None
                    self.session = self.session.model_copy(update={"files_done": self.session.files_done + 1})
            if bundle.adapter.validate_candidate(candidate, bundle.manifest):
                raise RuntimeError("The current engine no longer supports this recipe's settings.")
            if candidate.engine_id == "strata":
                script = bundle.server_script
                expected_script = payload.model.metadata.get("server_script_sha256")
                if script is None or self._hash(script, tick) != expected_script:
                    raise RuntimeError("The Strata serving wrapper changed. Revalidate this recipe.")
                failure = _strata_memory_failure(dict(candidate.parameters), model)
                if failure:
                    raise RuntimeError(failure.message)
                profile = bundle.adapter._profile(candidate, model)  # type: ignore[attr-defined]
                expected = sha256_text(
                    json.dumps(profile, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
                )
                if payload.profile_sha256 != expected:
                    raise RuntimeError("The Strata profile no longer matches the validated recipe.")
            allowed, _reasons = gpu_preflight(self.owner.settings, payload.gpu_uuid)
            if not allowed:
                raise RuntimeError("The GPU is busy or unavailable. Close GPU workloads and retry.")
            if snapshot is None or not any(g.uuid == payload.gpu_uuid for g in snapshot.hardware.gpus):
                raise RuntimeError("The recipe GPU is not available on this worker.")
            sandbox = create_sandbox(self.owner.settings, command_id)
            port = allocate_loopback_port()
            if bundle.server_binary is None:
                raise RuntimeError("No verified serving executable is available for this engine.")
            plan = bundle.adapter.build_server_plan(
                candidate, sandbox, binary=bundle.server_binary, model=model, port=port
            )
            _write_generated_files(plan, Path(sandbox.work_dir))
            with self.lock:
                if self.cancel.is_set():
                    raise RuntimeError("Recipe startup cancelled.")
                self.gpu = self.owner.leases.acquire((payload.gpu_uuid,), command_id=command_id)
                assert self.session is not None
                self.session = self.session.model_copy(
                    update={"message": "Files verified. Loading the model and checking readiness."}
                )
            server, _result = self.owner.runner.start_server(
                command_id=command_id,
                stage="recipe-server",
                command=plan.start.command,
                sandbox=sandbox,
                lease=self.gpu,
                port=port,
                cancel_event=self.cancel,
                on_tick=tick,
            )
            with self.lock:
                self.server = server
                if server is None or self.cancel.is_set():
                    raise RuntimeError(
                        "The engine could not start safely. Review the model and engine build."
                    )
                self.model_name = str(model.metadata.get("model_name") or model.model_id)
                self.engine_id = candidate.engine_id
            # Readiness alone does not prove the model loaded. A one-token local
            # smoke request loads it, then the server must report the target cap.
            self._request(port, [{"role": "user", "content": "Reply OK."}], 1, tick)
            cap, _document = effective_context(port)
            if cap is None or cap < int(candidate.context):
                raise RuntimeError("The engine did not confirm the recipe's context capacity.")
            with self.lock:
                if self.cancel.is_set():
                    raise RuntimeError("Recipe startup cancelled.")
                assert self.session is not None
                self.session = self.session.model_copy(
                    update={
                        "state": "ready",
                        "port": port,
                        "message": "Engine ready. Local applications and Lab chat can use this session.",
                    }
                )
                return RunRecipeResult(session=self.session)
        except Exception:
            with self.lock:
                self._stop_locked(
                    "stopped" if self.cancel.is_set() else "failed",
                    "Engine stopped."
                    if self.cancel.is_set()
                    else "Recipe startup failed. Check the reported reason and retry.",
                )
            raise

    def _request(
        self, port: int, messages: list[dict[str, str]], limit: int, tick: Callable[[], None]
    ) -> str:
        def request() -> str:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=180, trust_env=False) as client:
                if self.engine_id == "strata":
                    counted = client.post(
                        "/v1/messages/count_tokens",
                        json={"model": self.model_name, "messages": messages, "max_tokens": limit},
                    )
                    counted.raise_for_status()
                    n = counted.json().get("input_tokens")
                else:
                    template = client.post("/apply-template", json={"messages": messages})
                    template.raise_for_status()
                    counted = client.post("/tokenize", json={"content": template.json()["prompt"]})
                    counted.raise_for_status()
                    n = len(counted.json()["tokens"])
                if not isinstance(n, int) or self.session is None or n + limit > self.session.context_tokens:
                    raise RuntimeError(
                        "This conversation exceeds the recipe context. Start a new chat or shorten it."
                    )
                body: dict[str, Any] = {
                    "model": self.model_name,
                    "messages": messages,
                    "max_tokens": limit,
                    "temperature": 0.2,
                    "stream": False,
                    "cache_prompt": False,
                }
                if self.engine_id == "strata":
                    body["reasoning_effort"] = "none"
                with client.stream("POST", "/v1/chat/completions", json=body) as response:
                    response.raise_for_status()
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > 131072:
                            raise RuntimeError("The engine response exceeded the safe response limit.")
                    document = json.loads(content)
                text = document["choices"][0]["message"]["content"]
                if not isinstance(text, str):
                    raise RuntimeError("The engine returned an unsupported response.")
                return text[:32768]

        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="local-recipe-request")
        future = pool.submit(request)
        try:
            while True:
                try:
                    return future.result(timeout=1)
                except FutureTimeout:
                    tick()
                    if self.cancel.is_set():
                        raise RuntimeError("The engine session was stopped.") from None
        except httpx.HTTPError:
            raise RuntimeError(
                "The local engine request failed. Check context limits and engine status."
            ) from None
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def chat(self, payload: RecipeChatPayload, tick: Callable[[], None]) -> RecipeChatResult:
        with self.lock:
            current = self.status()
            if (
                not current
                or current.session_id != payload.session_id
                or current.state != "ready"
                or not current.port
            ):
                raise RuntimeError("The engine session is no longer ready. Start the recipe again.")
            port = current.port
        text = self._request(port, [m.model_dump() for m in payload.messages], payload.max_tokens, tick)
        return RecipeChatResult(session_id=payload.session_id, content=text)
