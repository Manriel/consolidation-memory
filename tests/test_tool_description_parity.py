"""Both surfaces must publish the same tool description.

The description is the only thing an agent host reads to decide whether and how
to call a tool. It reaches a host through two different places: the MCP
``tools/list`` entry, and the OpenAI-compatible ``openai_tools`` schema. When
those drift, the richer text is published to one audience and silently withheld
from the other — which is how ``memory_scope_list`` ended up describing itself
as a plain scope listing on MCP while three documents explained that it is a
deployment-wide audit tool that is not filtered by ``read_visibility``.

The contract is single-sourced from ``schemas.openai_tools`` and enforced by
``server._verify_tool_descriptions()`` at import and in the lifespan. These tests
pin the two halves of that: parity today, and a loud failure when it breaks.
"""

from __future__ import annotations

import asyncio
import re

import pytest

from consolidation_memory import mcp_compat, schemas, server


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _mcp_descriptions() -> dict[str, str]:
    return {tool.name: tool.description or "" for tool in asyncio.run(server.mcp.list_tools())}


def _openai_descriptions() -> dict[str, str]:
    return {
        str(tool["function"]["name"]): str(tool["function"]["description"])
        for tool in schemas.openai_tools
    }


def test_every_tool_publishes_one_description_on_both_surfaces() -> None:
    mcp = _mcp_descriptions()
    openai = _openai_descriptions()

    assert set(mcp) == set(openai), (
        "the MCP and OpenAI surfaces must expose the same tool set"
    )
    assert len(openai) == 29

    mismatched = {
        name: (_normalize(mcp[name]), _normalize(openai[name]))
        for name in openai
        if _normalize(mcp[name]) != _normalize(openai[name])
    }
    assert not mismatched, f"tool descriptions diverged between surfaces: {mismatched}"


@pytest.mark.parametrize(
    "name",
    ["memory_scope_list", "memory_policy_list"],
)
def test_unfiltered_listings_say_so_in_the_published_description(name: str) -> None:
    """The discovery tools must carry their visibility semantics where hosts read them.

    Both listings are intentionally outside the ``read_visibility`` filter. That
    is a deliberate design decision with a security consequence, and a host that
    cannot see it in the tool description will route a multi-tenant deployment
    through them without knowing. Asserted on both surfaces because the two
    publish from different places.
    """
    for description in (_mcp_descriptions()[name], _openai_descriptions()[name]):
        assert "not filtered" in description.lower() or "NOT filtered" in description
        assert "read_visibility" in description


def test_verifier_rejects_a_docstring_that_contradicts_the_published_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drift has to fail at import, not reach a client.

    A silent fallback is the failure mode this guard exists to prevent: the
    server would keep serving a stale summary for one tool while everything
    else stayed green.
    """

    class _Stale:
        """Publishes an unrelated summary."""

    monkeypatch.setitem(server.__dict__, "memory_search", _Stale)

    with pytest.raises(mcp_compat.MCPCompatError) as excinfo:
        server._verify_tool_descriptions()

    message = str(excinfo.value)
    assert "memory_search" in message
    assert "docstring" in message and "published" in message


def test_verifier_rejects_a_tool_with_no_docstring(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _bare() -> None:  # pragma: no cover - never called
        return None

    monkeypatch.setitem(server.__dict__, "memory_search", _bare)

    with pytest.raises(mcp_compat.MCPCompatError) as excinfo:
        server._verify_tool_descriptions()

    assert "no docstring" in str(excinfo.value)


def test_verifier_rejects_a_published_tool_with_no_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(server.__dict__, "memory_search", raising=False)

    with pytest.raises(mcp_compat.MCPCompatError) as excinfo:
        server._verify_tool_descriptions()

    assert "no handler is" in str(excinfo.value)


def test_published_descriptions_name_their_own_contract_surface() -> None:
    """Descriptions must not contradict the shared strictness contract.

    Every tool rejects unknown arguments, on every surface. A description that
    invites an agent to pass an undeclared key is a description that will
    generate a rejected call, so the guarantee is checked rather than assumed.
    """
    openai = _openai_descriptions()
    assert "additionalProperties" in str(schemas.openai_tools[0]["function"]["parameters"])
    assert all(_normalize(text) for text in openai.values())

    # No description may claim a parameter the published schema omits.
    for tool in schemas.openai_tools:
        name = str(tool["function"]["name"])
        published = str(tool["function"]["parameters"])
        description = _normalize(str(tool["function"]["description"]))
        for claim in re.findall(r"`([a-z_]+)`", description):
            if claim in {"inputSchema", "outputSchema", "structuredContent"}:
                continue
            assert claim in published, (
                f"{name} mentions {claim!r} but does not publish it"
            )
