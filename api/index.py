"""Vercel serverless entry point for the FastAPI backend.

Vercel's ``@vercel/python`` runtime serves the module-level ASGI ``app`` exported
here. Every ``/api/*`` request is rewritten to this single function (see
``vercel.json``), and FastAPI's own ``/api/...`` routes match the original path.

Locally you still run the app the normal way::

    pip install -r requirements-dev.txt
    uvicorn backend.main:app --reload --port 8000

This file only matters in the Vercel deployment.
"""
import sys
from pathlib import Path

# Make the repository root importable so ``backend`` resolves once bundled.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.main import app  # noqa: E402

__all__ = ["app"]
