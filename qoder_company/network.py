"""Agent-network state for the company dashboard.

The role Kanban is intentionally kept as a separate projection.  This module
maintains the complementary conversation graph: user -> CS -> CEO -> agents,
plus communication edges and a short, board-friendly log for every node/edge.
It is deterministic without an API key because :func:`summarize` has a local
fallback.
"""

from __future__ import annotations

import time
from typing import Any

from qoder_company.summarizer import summarize

DEFAULT_AVATAR = "/static/assets/yellow-sheep-meditating.png"
MAX_LOGS = 24


def _role_from_text(text: str) -> tuple[str | None, str]:
    """Parse adapter's ``role: message`` convention without trusting input."""
    if ": " not in text:
        return None, text.strip()
    maybe, rest = text.split(": ", 1)
    if maybe and " " not in maybe and "(" not in maybe and len(maybe) <= 64:
        return maybe.lower(), rest.strip()
    return None, text.strip()


class NetworkGraph:
    """Mutable graph that can be serialized for the browser and replayed."""

    def __init__(self, user_avatar: str = DEFAULT_AVATAR) -> None:
        self.user_avatar = user_avatar or DEFAULT_AVATAR
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[str, dict[str, Any]] = {}
        self.activity: list[dict[str, Any]] = []
        self.active_role = "ceo"
        self._ensure_node("user", "You", "user", "idle", self.user_avatar)
        self._ensure_node("cs", "CS · Yellow Sheep", "cs")
        self._ensure_node("ceo", "CEO", "ceo")
        self._ensure_edge("user", "cs", "handoff")
        self._ensure_edge("cs", "ceo", "handoff")

    def _ensure_node(
        self,
        node_id: str,
        label: str,
        kind: str,
        status: str = "idle",
        avatar: str = "",
    ) -> dict[str, Any]:
        node = self.nodes.get(node_id)
        if node is None:
            node = {
                "id": node_id,
                "label": label,
                "kind": kind,
                "status": status,
                "column": "backlog",
                "avatar": avatar or "",
                "summary": "",
                "logs": [],
            }
            self.nodes[node_id] = node
        elif avatar:
            node["avatar"] = avatar
        return node

    def _ensure_edge(self, source: str, target: str, kind: str = "message") -> dict[str, Any]:
        edge_id = f"{source}->{target}:{kind}"
        edge = self.edges.get(edge_id)
        if edge is None:
            edge = {
                "id": edge_id,
                "from": source,
                "to": target,
                "kind": kind,
                "status": "idle",
                "summary": "",
                "logs": [],
                "messages": 0,
            }
            self.edges[edge_id] = edge
        return edge

    @staticmethod
    def _append(target: dict[str, Any], summary: str, raw: str, ts: float) -> None:
        if not summary and not raw:
            return
        target["summary"] = summary or raw
        target.setdefault("logs", []).append({"ts": ts, "text": summary or raw})
        del target["logs"][:-MAX_LOGS]

    def set_user_avatar(self, avatar_url: str) -> None:
        """Set a validated local/data URL and keep the graph serializable."""
        if not avatar_url or len(avatar_url) > 2_000_000:
            raise ValueError("avatar URL is empty or too large")
        self.user_avatar = avatar_url
        self.nodes["user"]["avatar"] = avatar_url

    async def apply_event(self, kind: str, text: str) -> dict[str, Any]:
        """Apply one streamed status event and return its latest activity."""
        raw = (text or "").strip()
        role, message = _role_from_text(raw)
        now = time.time()

        # Tool events are CEO delegations in the adapter contract.
        if kind == "tool" and role:
            self._ensure_node(role, role.replace("_", " ").title(), "agent", "running")
            self.nodes["ceo"]["status"] = "running"
            self.nodes["ceo"]["column"] = "running"
            self.nodes["cs"]["status"] = "connected"
            self.nodes["cs"]["column"] = "running"
            self.active_role = role
            self.nodes[role]["column"] = "running"
            edge = self._ensure_edge("ceo", role, "delegation")
            edge["status"] = "active"
            summary = await summarize(message, role="ceo")
            self._append(edge, summary, message, now)
            edge["messages"] += 1
            self._append(self.nodes[role], summary, message, now)
            activity = {"from": "ceo", "to": role, "kind": kind, "text": summary, "ts": now}
        else:
            source = self.active_role if self.active_role in self.nodes else "ceo"
            target = "ceo" if source == "ceo" else source
            if kind in {"message", "progress", "tool"}:
                summary = await summarize(raw, role=source)
                node = self._ensure_node(target, target.replace("_", " ").title(), "agent", "running")
                node["status"] = "running"
                node["column"] = "running"
                self._append(node, summary, raw, now)
                if source != "ceo":
                    edge = self._ensure_edge(source, "ceo", "message")
                    edge["status"] = "active"
                    self._append(edge, summary, raw, now)
                    edge["messages"] += 1
                    activity = {"from": source, "to": "ceo", "kind": kind, "text": summary, "ts": now}
                else:
                    edge = self._ensure_edge("cs", "ceo", "message")
                    edge["status"] = "active"
                    self._append(edge, summary, raw, now)
                    edge["messages"] += 1
                    activity = {"from": "cs", "to": "ceo", "kind": kind, "text": summary, "ts": now}
            elif kind == "done":
                for node in self.nodes.values():
                    if node["kind"] in {"cs", "ceo", "agent"}:
                        node["status"] = "done"
                        node["column"] = "done"
                for edge in self.edges.values():
                    if edge["status"] == "active":
                        edge["status"] = "done"
                activity = {"from": "ceo", "to": "user", "kind": kind, "text": raw or "Task complete", "ts": now}
            elif kind == "error":
                self.nodes["ceo"]["status"] = "error"
                self.nodes["ceo"]["column"] = "needs_approval"
                self._append(self.nodes["ceo"], raw, raw, now)
                activity = {"from": "ceo", "to": "user", "kind": kind, "text": raw, "ts": now}
            else:
                activity = {"from": "cs", "to": "ceo", "kind": kind, "text": raw, "ts": now}

        self.activity.append(activity)
        del self.activity[:-MAX_LOGS]
        return activity

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-safe copy suitable for API/WS payloads."""
        return {
            "version": 1,
            "user_avatar": self.user_avatar,
            "nodes": list(self.nodes.values()),
            "edges": list(self.edges.values()),
            "activity": list(self.activity),
        }


async def summarize_network(messages: list[str]) -> str:
    """Side-LLM hook for a compact internal-communication digest."""
    clean = [m.strip() for m in messages if m and m.strip()]
    if not clean:
        return ""
    return await summarize("；".join(clean), role="network")
