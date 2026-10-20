"""Phase 1 worker entry point.

Real engine execution is intentionally absent. The daemon shell currently runs
the explicit simulated lane and says so in logs and every observation.
"""

from __future__ import annotations

import logging

from .simulate import main as simulate_main


def main() -> None:
    logging.getLogger(__name__).warning(
        "lab-worker Phase 1 only implements the explicit simulated lane; use lab-worker-sim"
    )
    simulate_main(prog="lab-worker")


if __name__ == "__main__":
    main()
