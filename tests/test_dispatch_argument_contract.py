"""Contract enforcement and MCP/dispatch parity for tool arguments.

Every published ``inputSchema`` declares ``additionalProperties: false``, so an
argument the contract does not name must be rejected on every surface — never
silently dropped. MCP rejects it at registration time (pydantic ``extra="forbid"``
on ``ArgModelBase``); ``tool_dispatch.reject_unknown_arguments`` is the same
check for the dispatch seam shared by the OpenAI, REST and desktop surfaces,
reading the allowed names straight from ``schemas.openai_tools`` so enforcement
cannot drift from the published contract.

Cross-surface tests live here (not in ``test_schemas.py``) because they need the
MCP server registry as well as the dispatch entry point.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from consolidation_memory import server
from consolidation_memory.schemas import openai_tools
from consolidation_memory.tool_dispatch import (
    ToolContractError,
    accepted_argument_names,
    dispatch_tool_call,
    execute_tool_call,
)
from consolidation_memory.types import RecallResult, StatusResult

try:
    from fastapi.testclient import TestClient

    HAS_FASTAPI = True
except ImportError:  # pragma: no cover - exercised only without the rest extra
    HAS_FASTAPI = False

try:
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # pragma: no cover - depends on the installed mcp layout
    from mcp.server.fastmcp.exceptions import ToolError

PUBLISHED_TOOL_NAMES = [tool["function"]["name"] for tool in openai_tools]

# A no-argument tool (the audit repro), a tool with many optional parameters, a
# tool with a nested/dict parameter, and a tool whose name collides with a
# parameter that only other tools declare.
PARITY_SAMPLES: list[tuple[str, dict[str, Any], list[str]]] = [
    ("memory_policy_list", {}, ["dry_run", "junk"]),
    (
        "memory_recall",
        {"query": "deploy", "n_results": 5, "scope": {"project": {"slug": "repo-a"}}},
        ["junk"],
    ),
    (
        "memory_status",
        {"lightweight": True, "scope": {"namespace": {"slug": "team-a"}}},
        ["dry_run", "junk"],
    ),
    ("memory_hygiene_apply", {"dry_run": True}, ["junk"]),
]


def _published_parameters(name: str) -> dict[str, Any]:
    tool = next(t for t in openai_tools if t["function"]["name"] == name)
    return tool["function"]["parameters"]


def _mcp_input_schema(name: str) -> dict[str, Any]:
    published = {tool.name: tool for tool in asyncio.run(server.mcp.list_tools())}
    return dict(published[name].input_schema or {})


def _mcp_reject_message(name: str, arguments: dict[str, Any]) -> str:
    with pytest.raises(ToolError) as excinfo:
        asyncio.run(server.mcp.call_tool(name, arguments))
    return str(excinfo.value)


class TestEnforcedContractMatchesPublishedSchemas:
    def test_every_published_tool_is_enforced(self):
        """A new published tool is enforced the day it is published, not later."""
        enforced = {
            name
            for name in PUBLISHED_TOOL_NAMES
            if accepted_argument_names(name) is not None
        }
        assert enforced == set(PUBLISHED_TOOL_NAMES)

    def test_enforced_argument_set_is_the_published_property_set(self):
        """No hand-maintained table: the enforced set *is* the published contract."""
        for name in PUBLISHED_TOOL_NAMES:
            parameters = _published_parameters(name)
            assert parameters["additionalProperties"] is False, name
            assert accepted_argument_names(name) == frozenset(parameters["properties"]), name

    def test_mcp_publishes_the_same_argument_set_it_enforces(self):
        """MCP and dispatch enforce one contract, not two that look alike."""
        for name in PUBLISHED_TOOL_NAMES:
            input_schema = _mcp_input_schema(name)
            assert input_schema["additionalProperties"] is False, name
            assert frozenset(input_schema["properties"]) == accepted_argument_names(name), name

    @pytest.mark.parametrize("name", PUBLISHED_TOOL_NAMES)
    def test_undeclared_argument_is_rejected_for_every_tool(self, name: str):
        with pytest.raises(ToolContractError) as excinfo:
            execute_tool_call(name, {"undeclared_probe": 1})

        message = str(excinfo.value)
        assert "undeclared_probe" in message
        assert name in message
        assert "Extra inputs are not permitted" in message
        assert "inputSchema" in message

    def test_unknown_tools_keep_their_own_error(self):
        with pytest.raises(ValueError, match="Unknown tool: nonexistent_tool"):
            execute_tool_call("nonexistent_tool", {"junk": 1})


class TestMcpDispatchParity:
    @pytest.mark.parametrize(
        ("name", "declared", "unknown"),
        PARITY_SAMPLES,
        ids=[sample[0] for sample in PARITY_SAMPLES],
    )
    def test_both_surfaces_reject_the_same_unknown_keys(
        self,
        name: str,
        declared: dict[str, Any],
        unknown: list[str],
    ):
        mcp_arguments = {**declared, **{key: 1 for key in unknown}}
        mcp_message = _mcp_reject_message(name, mcp_arguments)

        with pytest.raises(ToolContractError) as excinfo:
            execute_tool_call(name, mcp_arguments, client=MagicMock())
        dispatch_message = str(excinfo.value)

        for key in unknown:
            assert key in mcp_message, f"MCP must name {key} for {name}"
            assert key in dispatch_message, f"dispatch must name {key} for {name}"
        for key in declared:
            assert key not in dispatch_message, f"{name}: {key} is declared, not unknown"
        assert "Extra inputs are not permitted" in mcp_message
        assert "Extra inputs are not permitted" in dispatch_message

    def test_declared_arguments_reach_the_dispatch_seam_from_mcp(self):
        """Parity is not only about rejection: valid arguments keep working."""
        declared = {"dry_run": True}
        canned = {
            "status": "dry_run",
            "episode_targets": 0,
            "episode_ids": [],
            "expire_orphans": False,
            "orphan_repair": None,
        }

        with patch(
            "consolidation_memory.server.execute_tool_call",
            return_value=canned,
        ) as mock_execute:
            result = asyncio.run(server.mcp.call_tool("memory_hygiene_apply", declared))

        assert result.is_error is not True
        assert mock_execute.call_args.args[1]["dry_run"] is True

    def test_nested_scope_argument_is_a_value_not_an_unknown_key(self):
        """Dict-shaped parameters reach the client untouched on both surfaces."""
        scope = {"namespace": {"slug": "team-a"}, "policy": {"write_mode": "deny"}}

        with patch(
            "consolidation_memory.server.execute_tool_call",
            return_value={"status": "forgotten", "id": "ep-1", "message": None},
        ) as mock_execute:
            forget_args = {"episode_id": "ep-1", "scope": scope}
            asyncio.run(server.mcp.call_tool("memory_forget", forget_args))
        assert mock_execute.call_args.args[1]["scope"] == scope

        client = MagicMock()
        client.status.return_value = StatusResult(
            version="0.1.0",
            embedding_backend="fastembed",
            fast_path_hits=0,
            llm_fallbacks=0,
        )
        dispatch_tool_call(client, "memory_status", {"scope": scope})
        assert client.status.call_args.kwargs["scope"] == scope


class TestErrorSurface:
    def test_mcp_dispatch_path_reports_a_contract_violation_as_is_error(self):
        """The same rejection MCP produces for bad input, via the dispatch seam."""
        result = asyncio.run(server._call_tool_result("memory_policy_list", {"junk": 1}))

        assert result.is_error is True
        text = result.content[0].text
        assert "junk" in text
        assert "Extra inputs are not permitted" in text

    def test_contract_error_is_a_value_error(self):
        """REST maps ValueError to HTTP 422, so the REST path rejects too."""
        assert issubclass(ToolContractError, ValueError)

    def test_dispatch_raises_instead_of_returning_a_soft_error_payload(self):
        with pytest.raises(ToolContractError):
            dispatch_tool_call(MagicMock(), "memory_policy_list", {"junk": 1, "dry_run": True})

    def test_other_failures_keep_the_soft_error_payload_convention(self):
        """Only contract violations raise; runtime failures still return ``error``."""
        result = dispatch_tool_call(MagicMock(), "nonexistent_tool", {})
        assert result == {"error": "Unknown tool: nonexistent_tool"}


class TestInternalArgumentPassthrough:
    def test_recall_deadline_argument_is_accepted_but_never_published(self):
        client = MagicMock()
        client.query_recall.return_value = RecallResult(episodes=[], knowledge=[])

        execute_tool_call(
            "memory_recall",
            {"query": "deploy", "_recall_deadline_monotonic": 123.5},
            client=client,
        )

        assert "_recall_deadline_monotonic" not in (accepted_argument_names("memory_recall") or ())
        assert client.query_recall.call_args.kwargs["recall_deadline_monotonic"] == 123.5

    def test_undeclared_internal_looking_key_is_still_rejected(self):
        with pytest.raises(ToolContractError, match="_junk"):
            execute_tool_call("memory_recall", {"query": "deploy", "_junk": 1})

    def test_simple_surface_re_translation_stays_inside_the_contract(self):
        client = MagicMock()
        client.query_recall.return_value = RecallResult(episodes=[], knowledge=[])

        result = dispatch_tool_call(
            client,
            "memory_ask",
            {"query": "deploy", "_recall_deadline_monotonic": 7.5},
        )

        assert result["query"] == "deploy"
        assert client.query_recall.call_args.kwargs["recall_deadline_monotonic"] == 7.5


@pytest.mark.skipif(not HAS_FASTAPI, reason="fastapi not installed")
class TestRestSurface:
    @patch("consolidation_memory.backends.encode_documents")
    def test_rest_recall_path_survives_the_internal_deadline_key(self, mock_embed):
        """REST injects the deadline key; enforcement must not reject the hop."""
        from tests.helpers import make_normalized_vec

        mock_embed.return_value = make_normalized_vec(seed=11).reshape(1, -1)

        from consolidation_memory.rest import create_app

        with TestClient(create_app()) as client:
            response = client.post("/memory/ask", json={"query": "rest contract test"})

        assert response.status_code == 200, response.text
        assert response.json()["query"] == "rest contract test"

    def test_rest_rejects_a_badly_typed_argument_with_an_error_status(self):
        """A rejected argument is an error status, never a soft ``error`` body."""
        from consolidation_memory.rest import create_app

        with TestClient(create_app()) as client:
            response = client.post("/memory/hygiene/apply", json={"dry_run": "not-a-bool"})

        assert response.status_code == 422
        assert "error" not in response.json()

    def test_known_gap_rest_request_models_drop_unknown_keys_before_dispatch(self):
        """Residual in rest.py (not the dispatch contract): FastAPI models ignore extras.

        The unknown key is dropped by the request model, so it never reaches the
        dispatch seam over HTTP. ``rest.py`` should set ``extra="forbid"`` on its
        request models; the seam below them already rejects the same key.
        """
        from consolidation_memory.rest import create_app

        with TestClient(create_app()) as client:
            response = client.post("/memory/hygiene/apply", json={"dry_run": True, "junk": 1})

        assert response.status_code == 200
        with pytest.raises(ToolContractError, match="junk"):
            execute_tool_call("memory_hygiene_apply", {"dry_run": True, "junk": 1})
