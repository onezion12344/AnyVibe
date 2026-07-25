"""Focused contract tests for the network projection."""

from __future__ import annotations

import asyncio

from qoder_company.network import DEFAULT_AVATAR, NetworkGraph, summarize_network


def test_network_has_root_chain_and_json_contract():
    graph = NetworkGraph()
    snapshot = graph.snapshot()
    assert {node["id"] for node in snapshot["nodes"]} == {"user", "cs", "ceo"}
    assert {edge["from"] + "->" + edge["to"] for edge in snapshot["edges"]} == {"user->cs", "cs->ceo"}
    assert snapshot["user_avatar"] == DEFAULT_AVATAR
    assert {"version", "nodes", "edges", "activity"} <= snapshot.keys()


def test_tool_and_message_events_create_internal_edges_and_logs():
    async def run():
        graph = NetworkGraph()
        await graph.apply_event("tool", "researcher: investigate edge cases")
        await graph.apply_event("message", "empty input is supported")
        return graph.snapshot()

    snapshot = asyncio.run(run())
    researcher = next(node for node in snapshot["nodes"] if node["id"] == "researcher")
    assert researcher["status"] == "running"
    assert researcher["logs"]
    assert any(edge["id"] == "ceo->researcher:delegation" for edge in snapshot["edges"])
    assert any(edge["id"] == "researcher->ceo:message" for edge in snapshot["edges"])
    assert snapshot["activity"][-1]["to"] == "ceo"


def test_ceo_completion_flows_through_cs_to_user_and_direct_tools_are_not_cs_messages():
    async def run():
        graph = NetworkGraph()
        direct_tool = await graph.apply_event("tool", "Write({'file_path': 'demo.py'})", actor="ceo")
        ceo_update = await graph.apply_event("message", "Implementation and tests passed", actor="ceo")
        completion = await graph.apply_event("done", "Qoder task complete", actor="ceo")
        return graph.snapshot(), direct_tool, ceo_update, completion

    snapshot, direct_tool, ceo_update, completion = asyncio.run(run())
    assert direct_tool["from"] == direct_tool["to"] == "ceo"
    assert ceo_update["from"] == "ceo"
    assert ceo_update["to"] == "cs"
    assert completion["from"] == "cs"
    assert completion["to"] == "user"
    assert completion["kind"] == "done"
    assert completion["text"] == "Qoder task complete"
    assert [(item["from"], item["to"]) for item in snapshot["activity"][-2:]] == [
        ("ceo", "cs"),
        ("cs", "user"),
    ]


def test_done_and_error_map_to_network_columns():
    async def run():
        graph = NetworkGraph()
        await graph.apply_event("tool", "qa: run tests")
        await graph.apply_event("error", "approval required")
        error_snapshot = graph.snapshot()
        graph2 = NetworkGraph()
        await graph2.apply_event("tool", "qa: run tests")
        await graph2.apply_event("done", "complete")
        return error_snapshot, graph2.snapshot()

    error_snapshot, done_snapshot = asyncio.run(run())
    assert next(n for n in error_snapshot["nodes"] if n["id"] == "ceo")["column"] == "needs_approval"
    assert all(n["column"] == "done" for n in done_snapshot["nodes"] if n["kind"] in {"cs", "ceo", "agent"})


def test_side_summary_hook_is_deterministic_without_key(monkeypatch):
    import qoder_company.summarizer as summarizer
    monkeypatch.setattr(summarizer, "_STEPFUN_KEY", "")
    result = asyncio.run(summarize_network(["alpha", "beta"]))
    assert result == "alpha；beta"
