"""CLI entry point for the real Linux worker."""

from __future__ import annotations

import argparse
import json
import logging
import signal
from threading import Event

from .config import WorkerSettings
from .real_worker import RealWorker, print_once_summary


def parser(prog: str = "lab-worker") -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=prog, description="Real Linux inference worker")
    p.add_argument("--controller-url", default=None)
    p.add_argument("--enrollment-token", default=None)
    p.add_argument("--worker-token", default=None)
    p.add_argument("--worker-id", default=None)
    p.add_argument("--worker-name", default=None)
    p.add_argument("--state-file", default=None)
    p.add_argument("--state-root", default=None)
    p.add_argument("--model-root", action="append", default=None)
    p.add_argument("--llama-server-path", default=None)
    p.add_argument("--llama-bench-path", default=None)
    p.add_argument("--llama-lib-dir", default=None)
    p.add_argument("--strata-path", default=None)
    p.add_argument("--strata-server-script", default=None)
    p.add_argument("--strata-python", default=None)
    p.add_argument("--gpu-uuid", action="append", default=None)
    p.add_argument("--poll-seconds", type=float, default=None)
    p.add_argument("--heartbeat-seconds", type=float, default=None)
    p.add_argument("--lease-renew-seconds", type=float, default=None)
    p.add_argument("--max-iterations", type=int, default=None)
    p.add_argument("--no-initial-discovery", action="store_true")
    p.add_argument("--scan-only", action="store_true")
    p.add_argument("--hash-models", action="store_true")
    p.add_argument("--once", action="store_true")
    p.add_argument("--log-level", default=None)
    return p


def settings_from_args(args: argparse.Namespace) -> WorkerSettings:
    values: dict[str, object] = {
        "simulated": False,
        "execution_mode": "real",
    }
    for arg, field in (
        ("controller_url", "controller_url"),
        ("enrollment_token", "enrollment_token"),
        ("worker_token", "worker_token"),
        ("worker_id", "worker_id"),
        ("worker_name", "worker_name"),
        ("state_file", "state_file"),
        ("state_root", "state_root"),
        ("llama_server_path", "llama_server_path"),
        ("llama_bench_path", "llama_bench_path"),
        ("llama_lib_dir", "llama_lib_dir"),
        ("strata_path", "strata_path"),
        ("strata_server_script", "strata_server_script"),
        ("strata_python", "strata_python"),
        ("poll_seconds", "poll_seconds"),
        ("heartbeat_seconds", "heartbeat_seconds"),
        ("lease_renew_seconds", "lease_renew_seconds"),
        ("max_iterations", "max_iterations"),
    ):
        value = getattr(args, arg)
        if value is not None:
            values[field] = value
    if args.model_root:
        values["model_roots"] = list(args.model_root)
    if args.gpu_uuid:
        values["gpu_uuids"] = list(args.gpu_uuid)
    return WorkerSettings.model_validate(values)


def main(argv: list[str] | None = None, prog: str = "lab-worker") -> None:
    args = parser(prog).parse_args(argv)
    settings = settings_from_args(args)
    logging.basicConfig(
        level=getattr(logging, (args.log_level or "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logger = logging.getLogger(__name__)
    logger.warning(
        "REAL_EXECUTION: this worker launches observed engines, leases GPU UUIDs and records "
        "measured evidence; simulated evidence is never produced here"
    )
    worker = RealWorker(settings, initial_discovery=not args.no_initial_discovery)
    try:
        worker.ensure_enrolled()
        worker.recover()
        if args.scan_only:
            from .discovery import discover_snapshot

            snapshot = worker.executor.current_snapshot()
            discovery = discover_snapshot(
                settings,
                revision=(snapshot.revision + 1) if snapshot else 1,
                include_models=True,
                include_engines=True,
                include_hardware=True,
                hash_models=args.hash_models,
            )
            worker.executor.discovery = discovery
            worker.executor._last_scan = discovery
            worker.executor._snapshot_revision = discovery.snapshot.revision
            worker.executor._engines = discovery.engines
            worker.executor._reindex()
            worker.sync_snapshot()
            worker.heartbeat()
            print(
                json.dumps(
                    {
                        "worker_id": settings.worker_id,
                        "snapshot": discovery.snapshot.model_dump(mode="json"),
                        "warnings": list(discovery.warnings),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return
        if args.once:
            worker.sync_snapshot()
            worker.heartbeat()
            processed = worker.run_once()
            print_once_summary(worker)
            logger.info("processed %s command(s)", processed)
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
        worker.close()


if __name__ == "__main__":
    main()
