"""CLI for the explicit Phase 1 simulated worker."""

from __future__ import annotations

import argparse
import json
import logging
import signal
from threading import Event

from .config import WorkerSettings
from .worker import SimulatedWorker


def parser(prog: str = "lab-worker-sim") -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=prog, description="Phase 1 simulated worker")
    p.add_argument("--controller-url", default=None)
    p.add_argument("--enrollment-token", default=None)
    p.add_argument("--worker-token", default=None)
    p.add_argument("--worker-id", default=None)
    p.add_argument("--worker-name", default=None)
    p.add_argument("--state-file", default=None)
    p.add_argument("--model-id", default=None)
    p.add_argument("--model-path", default=None)
    p.add_argument("--engine-path", default=None)
    p.add_argument("--llama-bench-path", default=None)
    p.add_argument("--iterations", type=int, default=None)
    p.add_argument("--poll-seconds", type=float, default=None)
    p.add_argument("--heartbeat-seconds", type=float, default=None)
    p.add_argument("--once", action="store_true")
    p.add_argument("--log-level", default=None)
    return p


def settings_from_args(args: argparse.Namespace) -> WorkerSettings:
    values: dict[str, object] = {}
    for arg, field in (
        ("controller_url", "controller_url"),
        ("enrollment_token", "enrollment_token"),
        ("worker_token", "worker_token"),
        ("worker_id", "worker_id"),
        ("worker_name", "worker_name"),
        ("state_file", "state_file"),
        ("model_id", "model_id"),
        ("model_path", "model_path"),
        ("engine_path", "engine_path"),
        ("llama_bench_path", "llama_bench_path"),
        ("iterations", "max_iterations"),
        ("poll_seconds", "poll_seconds"),
        ("heartbeat_seconds", "heartbeat_seconds"),
    ):
        value = getattr(args, arg)
        if value is not None:
            values[field] = value
    values["simulated"] = True
    values["execution_mode"] = "simulated"
    return WorkerSettings.model_validate(values)


def main(argv: list[str] | None = None, prog: str = "lab-worker-sim") -> None:
    args = parser(prog).parse_args(argv)
    settings = settings_from_args(args)
    logging.basicConfig(
        level=getattr(logging, (args.log_level or "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger = logging.getLogger(__name__)
    logger.warning(
        "PHASE_1_SIMULATED_EXECUTION: this worker never launches an engine, allocates a GPU, "
        "or produces validated production evidence"
    )
    worker = SimulatedWorker(settings)
    try:
        if args.once:
            worker.ensure_enrolled()
            worker.sync_snapshot()
            worker.heartbeat()
            processed = worker.run_once()
            print(
                json.dumps(
                    {
                        "worker_id": settings.worker_id,
                        "processed": processed,
                        "snapshot_revision": worker.executor.snapshot.revision,
                        "simulated": True,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return
        stop_event = Event()

        def _stop(signum: int, frame: object) -> None:
            logger.info("received signal %s; stopping worker", signum)
            stop_event.set()

        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)
        worker.run(stop_event)
    except Exception as exc:
        logger.error("worker failed: %s", exc, exc_info=True)
        raise SystemExit(1) from exc
    finally:
        worker.client.close()


if __name__ == "__main__":
    main()
