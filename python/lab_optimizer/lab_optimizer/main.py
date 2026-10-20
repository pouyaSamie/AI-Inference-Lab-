"""CLI for the supervised optimizer process."""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
from threading import Event

from .config import OptimizerSettings
from .worker import OptimizerWorker


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lab-optimizer", description="Supervised Optuna process")
    parser.add_argument("command", nargs="?", default="run", choices=("run", "once", "health"))
    parser.add_argument("--controller-url", default=None)
    parser.add_argument("--token", default=None)
    parser.add_argument("--db-url", default=None)
    parser.add_argument("--optimizer-id", default=None)
    parser.add_argument("--heartbeat-seconds", type=float, default=None)
    parser.add_argument("--poll-seconds", type=float, default=None)
    parser.add_argument("--max-iterations", type=int, default=None)
    parser.add_argument("--log-level", default=None)
    return parser


def _settings(args: argparse.Namespace) -> OptimizerSettings:
    values: dict[str, object] = {}
    if args.controller_url:
        values["controller_url"] = args.controller_url
    if args.token:
        values["token"] = args.token
    if args.db_url:
        values["db_url"] = args.db_url
    if args.optimizer_id:
        values["optimizer_id"] = args.optimizer_id
    if args.heartbeat_seconds is not None:
        values["heartbeat_seconds"] = args.heartbeat_seconds
    if args.poll_seconds is not None:
        values["poll_seconds"] = args.poll_seconds
    if args.max_iterations is not None:
        values["max_iterations"] = args.max_iterations
    if args.log_level:
        values["log_level"] = args.log_level
    return OptimizerSettings.model_validate(values)


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    settings = _settings(args)
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        settings.validate_runtime()
    except ValueError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    worker = OptimizerWorker(settings)
    if args.command == "health":
        print(json.dumps(worker.health(), indent=2, sort_keys=True))
        worker.client.close()
        return
    if args.command == "once":
        count = worker.run_once()
        print(json.dumps({"processed": count, **worker.health()}, indent=2, sort_keys=True))
        worker.client.close()
        return

    stop_event = Event()

    def _stop(signum: int, frame: object) -> None:
        logging.getLogger(__name__).info("received signal %s; stopping optimizer", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    logging.getLogger(__name__).info(
        "optimizer starting",
        extra={"optimizer_id": worker.optimizer_id, "controller": settings.controller_url},
    )
    processed = worker.run(stop_event, max_iterations=settings.max_iterations)
    logging.getLogger(__name__).info("optimizer stopped after %s requests", processed)
    worker.client.close()
