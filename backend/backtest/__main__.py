"""Enable ``python -m backend.backtest``."""
from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    # The report prints Unicode (→, ×). Windows' default cp1252 console encoding
    # can't encode those, so force UTF-8 output where supported.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
