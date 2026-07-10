"""Import isolation: interactive recall paths must not pull SciPy."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"


def _run_isolated(code: str) -> subprocess.CompletedProcess[str]:
    import os

    env = os.environ.copy()
    env["PYTHONPATH"] = str(_SRC) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUNBUFFERED"] = "1"
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )


def test_episode_embedding_import_does_not_load_scipy():
    code = """
import sys
from consolidation_memory.episode_embedding import distinctive_token_set
assert distinctive_token_set is not None
assert "scipy" not in sys.modules, sorted(m for m in sys.modules if m.startswith("scipy"))
assert "consolidation_memory.consolidation.engine" not in sys.modules
print("ok")
"""
    result = _run_isolated(code)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok" in result.stdout


def test_consolidation_package_import_is_lazy_for_engine():
    code = """
import sys
import consolidation_memory.consolidation as pkg
assert "consolidation_memory.consolidation.engine" not in sys.modules
assert "scipy" not in sys.modules
from consolidation_memory.consolidation import fast_path
assert fast_path is not None
assert "scipy" not in sys.modules
assert "consolidation_memory.consolidation.engine" not in sys.modules
print("ok")
"""
    result = _run_isolated(code)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok" in result.stdout


def test_run_consolidation_getattr_loads_engine():
    code = """
import sys
import consolidation_memory.consolidation as pkg
fn = pkg.run_consolidation
assert callable(fn)
assert "consolidation_memory.consolidation.engine" in sys.modules
print("ok")
"""
    result = _run_isolated(code)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok" in result.stdout


def test_context_assembler_import_does_not_load_scipy():
    code = """
import sys
from consolidation_memory.context_assembler import recall
assert callable(recall)
assert "scipy" not in sys.modules, sorted(m for m in sys.modules if m.startswith("scipy"))
assert "consolidation_memory.consolidation.engine" not in sys.modules
print("ok")
"""
    result = _run_isolated(code)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok" in result.stdout
