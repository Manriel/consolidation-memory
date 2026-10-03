"""MCP tool timeout resolution and SciPy preload helpers."""

from __future__ import annotations

from consolidation_memory import server


def test_tool_timeout_defaults_status_and_consolidate():
    assert server._tool_timeout_seconds("memory_status") == 30.0
    assert server._tool_timeout_seconds("memory_consolidate") == 600.0
    assert server._tool_timeout_seconds("memory_store") == 30.0


def test_tool_timeout_env_override(monkeypatch):
    monkeypatch.setenv("CONSOLIDATION_MEMORY_TIMEOUT_MEMORY_STATUS", "12")
    assert server._tool_timeout_seconds("memory_status") == 12.0


def test_call_tool_result_applies_default_timeout(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_run_blocking(func, *args, timeout=None, **kwargs):
        captured["timeout"] = timeout
        captured["name"] = args[0] if args else None
        return {"ok": True}

    monkeypatch.setattr(server, "_run_blocking", fake_run_blocking)
    monkeypatch.setattr(server, "tool_requires_client", lambda name: False)

    import asyncio

    payload = asyncio.run(server._call_tool_result("memory_policy_list", {}))
    assert payload == {"ok": True}
    assert captured["timeout"] == server._tool_timeout_seconds("memory_policy_list")
    assert captured["name"] == "memory_policy_list"


def test_call_tool_result_timeout_returns_error_result(monkeypatch):
    async def fake_run_blocking(func, *args, timeout=None, **kwargs):
        raise TimeoutError()

    monkeypatch.setattr(server, "_run_blocking", fake_run_blocking)
    monkeypatch.setattr(server, "tool_requires_client", lambda name: False)

    import asyncio

    result = asyncio.run(server._call_tool_result("memory_status", {}))
    assert result.is_error is True
    assert "timed out" in result.content[0].text.lower()
    payload = result.structured_content
    assert "error" in payload
    assert "timed out" in payload["error"].lower()


def test_preload_scipy_is_idempotent(monkeypatch):
    monkeypatch.setattr(server, "_PRELOAD_SCIPY_ON_START", True)
    server._preload_scipy_clustering()
    server._preload_scipy_clustering()
    import sys

    assert "scipy.cluster.hierarchy" in sys.modules
