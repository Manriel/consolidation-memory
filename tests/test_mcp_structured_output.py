"""Regression tests for MCP tool result encoding (issue #5).

Tool handlers must hand FastMCP a JSON-serializable object. Returning JSON text
makes FastMCP wrap the payload as ``{"result": "<json text>"}`` in
``structuredContent``, and ``json.dumps`` defaults to ``ensure_ascii=True``, so
non-ASCII text arrives as ``\\uXXXX`` escapes that the client passes to the model
verbatim.

The same contract has to show up in the published schemas: ``inputSchema`` must
describe the handler parameters, and ``outputSchema`` must describe the payload
the handler actually returns.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any

import jsonschema
import pytest
from mcp.types import Tool as MCPTool

from consolidation_memory import server

_NON_ASCII_PAYLOAD: dict[str, Any] = {
    "episodes": [{"id": "ep-1", "content": "Γειά σου κόσμε — память"}],
    "total_matches": 1,
}

# ASCII, non-ASCII and literal \uXXXX sequences in one stored string.
_BYTE_IDENTITY_CONTENT = (
    "ascii: the quick brown fox jumps over the lazy dog\n"
    "non-ascii: Γειά σου κόσμε — مرحبا 世界 你好\n"
    'literal escape sequence: \\u0393 and \\u043f, quote " and backslash \\'
)


def _published_tools() -> list[MCPTool]:
    return asyncio.run(server.mcp.list_tools())


def _handler_for(tool: MCPTool) -> inspect.Signature:
    return inspect.signature(getattr(server, tool.name))


def _call_status(
    monkeypatch: Any,
    *,
    payload: dict[str, Any] | None = None,
    error: BaseException | None = None,
) -> Any:
    """Run ``memory_status`` through FastMCP with a canned dispatch result."""

    if error is not None:

        async def fake_call_tool_payload(*args: Any, **kwargs: Any) -> dict[str, object]:
            raise error

    else:

        async def fake_call_tool_payload(*args: Any, **kwargs: Any) -> dict[str, object]:
            return dict(payload or {})

    monkeypatch.setattr(server, "_call_tool_payload", fake_call_tool_payload)
    monkeypatch.setattr(server, "tool_requires_client", lambda name: False)
    return asyncio.run(server.mcp.call_tool("memory_status", {"lightweight": True}))


def test_structured_content_is_the_payload_object(monkeypatch: Any) -> None:
    result = _call_status(monkeypatch, payload=_NON_ASCII_PAYLOAD)
    assert isinstance(result, tuple), "expected (content, structured_content) from FastMCP"
    _content, structured = result
    assert structured == _NON_ASCII_PAYLOAD


def test_text_content_is_single_encoded_json_with_unicode(monkeypatch: Any) -> None:
    result = _call_status(monkeypatch, payload=_NON_ASCII_PAYLOAD)
    assert isinstance(result, tuple)
    content, _structured = result
    text = content[0].text
    assert "Γειά" in text, "non-ASCII text must be returned as-is"
    assert "\\u0393" not in text, "Greek characters must not be \\uXXXX-escaped"
    assert "\\u043f" not in text, "Cyrillic characters must not be \\uXXXX-escaped"
    assert json.loads(text) == _NON_ASCII_PAYLOAD


def test_stored_content_round_trips_byte_identically() -> None:
    """Stored text must come back unchanged: nothing re-encoded, nothing decoded."""
    from consolidation_memory.database import ensure_schema, insert_episode

    ensure_schema()
    insert_episode(content=_BYTE_IDENTITY_CONTENT)

    result = asyncio.run(
        server.mcp.call_tool("memory_search", {"query": "quick brown fox", "limit": 5})
    )
    assert isinstance(result, tuple)
    content, structured = result

    assert structured.get("episodes"), "search must return the stored episode"
    from_structured = structured["episodes"][0]["content"]
    from_text = json.loads(content[0].text)["episodes"][0]["content"]

    for returned in (from_structured, from_text):
        assert returned == _BYTE_IDENTITY_CONTENT
        assert returned.encode("utf-8") == _BYTE_IDENTITY_CONTENT.encode("utf-8")


def test_error_result_is_a_structured_object(monkeypatch: Any) -> None:
    result = _call_status(monkeypatch, error=TimeoutError("boom"))
    assert isinstance(result, tuple)
    _content, structured = result
    assert isinstance(structured, dict)
    assert isinstance(structured.get("error"), str)
    assert "timed out" in structured["error"]


def test_handler_returns_object_not_json_text(monkeypatch: Any) -> None:
    async def fake_call_tool_payload(*args: Any, **kwargs: Any) -> dict[str, object]:
        return dict(_NON_ASCII_PAYLOAD)

    monkeypatch.setattr(server, "_call_tool_payload", fake_call_tool_payload)
    result = asyncio.run(server.memory_status(lightweight=True))
    assert isinstance(result, dict)
    assert result == _NON_ASCII_PAYLOAD


def test_input_schemas_are_valid_json_schema() -> None:
    for tool in _published_tools():
        assert tool.inputSchema is not None, tool.name
        jsonschema.Draft202012Validator.check_schema(tool.inputSchema)
        assert tool.inputSchema.get("type") == "object", tool.name


def test_input_schemas_match_handler_signatures() -> None:
    for tool in _published_tools():
        signature = _handler_for(tool)
        expected = set(signature.parameters)
        properties = set((tool.inputSchema or {}).get("properties") or {})
        assert properties == expected, (
            f"{tool.name}: inputSchema properties {sorted(properties)} "
            f"!= handler parameters {sorted(expected)}"
        )
        required = set((tool.inputSchema or {}).get("required") or [])
        expected_required = {
            name
            for name, parameter in signature.parameters.items()
            if parameter.default is inspect.Parameter.empty
        }
        assert required == expected_required, (
            f"{tool.name}: required {sorted(required)} != parameters without defaults "
            f"{sorted(expected_required)}"
        )


def test_output_schemas_are_valid_json_schema() -> None:
    for tool in _published_tools():
        assert tool.outputSchema is not None, tool.name
        jsonschema.Draft202012Validator.check_schema(tool.outputSchema)
        assert tool.outputSchema.get("type") == "object", tool.name


def test_output_schema_describes_the_payload(monkeypatch: Any) -> None:
    result = _call_status(monkeypatch, payload=_NON_ASCII_PAYLOAD)
    assert isinstance(result, tuple)
    _content, structured = result

    tool = next(tool for tool in _published_tools() if tool.name == "memory_status")
    assert tool.outputSchema is not None
    properties = set(tool.outputSchema.get("properties") or {})
    assert "result" not in properties, "payload must not be wrapped in a result key"
    jsonschema.validate(structured, tool.outputSchema)


def test_output_schema_rejects_non_object_payload(monkeypatch: Any) -> None:
    """A str payload is not what the schema promises."""
    tool = next(tool for tool in _published_tools() if tool.name == "memory_status")
    assert tool.outputSchema is not None
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(json.dumps(dict(_NON_ASCII_PAYLOAD)), tool.outputSchema)
