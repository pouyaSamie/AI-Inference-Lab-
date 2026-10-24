"""Isolated entry point for the bundled relocatable CPython distribution."""

import sys
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path[:0] = [str(root / "site-packages"), str(root / "packages")]
if len(sys.argv) == 2 and sys.argv[1] == "desktop-hardware":
    from lab_worker.desktop_hardware import main

    main()
elif len(sys.argv) == 4 and sys.argv[1] == "engine-archive":
    from lab_worker.engine_archive import main

    main(sys.argv[2], sys.argv[3])
else:
    from lab_api.desktop_runtime import main

    main()
