"""Consolidation package.

Public API: ``run_consolidation`` only.
Internal functions should be imported from their submodules directly.

``engine`` (and its SciPy dependency) is loaded lazily so interactive MCP tools
like ``memory_recall`` do not block on native SciPy/DLL imports from worker
threads on Windows.
"""

from __future__ import annotations

from typing import Any

__all__ = ["run_consolidation"]


def __getattr__(name: str) -> Any:
    if name == "run_consolidation":
        from consolidation_memory.consolidation.engine import run_consolidation

        return run_consolidation
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
