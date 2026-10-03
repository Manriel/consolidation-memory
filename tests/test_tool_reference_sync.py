"""docs/TOOLS.md must stay in sync with the published tool schemas."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "generate_tool_reference.py"
    spec = importlib.util.spec_from_file_location("generate_tool_reference_script", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_tool_reference_is_up_to_date() -> None:
    module = _load_module()
    rendered = module.render()
    committed_path = Path(__file__).resolve().parents[1] / "docs" / "TOOLS.md"
    committed = committed_path.read_text(encoding="utf-8")
    assert rendered == committed, (
        "docs/TOOLS.md does not match the published tool schemas; "
        "run scripts/generate_tool_reference.py and commit the result"
    )
