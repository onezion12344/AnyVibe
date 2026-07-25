"""qoder_company/observer.py — CompanyObserver: inter-agent comms → kanban cards.

Consumes QoderAdapter StatusEvents, maintains per-role card state, LLM-summarizes
messages, and pushes card-op dicts over the existing signaling WS broadcast.

Board columns: Backlog → Running → Needs-Approval → Done.

Fixture-first: no StepFun key needed; fallback summarizer returns trimmed text.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, AsyncIterator, Callable

from receptionist.adapters.base import StatusEvent
from qoder_company.network import NetworkGraph
from qoder_company.summarizer import summarize

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CEO_ROLE: str = "ceo"

_COLUMNS = ["backlog", "running", "needs_approval", "done"]

# Column order for transitions
_COLUMN_ORDER: dict[str, int] = {c: i for i, c in enumerate(_COLUMNS)}


# ---------------------------------------------------------------------------
# Card-op helpers
# ---------------------------------------------------------------------------


def _card_op(
    op: str,
    card_id: str,
    role: str,
    column: str,
    title: str,
    subtitle: str = "",
    edges: list[dict] | None = None,
) -> dict[str, Any]:
    """Build a normalised card-op dict for the board client."""
    return {
        "op": op,
        "card_id": card_id,
        "role": role,
        "column": column,
        "title": title,
        "subtitle": subtitle,
        "edges": edges or [],
    }


# ---------------------------------------------------------------------------
# Observer
# ---------------------------------------------------------------------------


class CompanyObserver:
    """Drive a QoderAdapter run and emit board card-ops.

    Parameters
    ----------
    adapter:
        A ``QoderAdapter`` instance.
    board_emit:
        Callable ``(card_op: dict) -> None``.  Called synchronously for each
        card-op produced.  The default broadcasts over ``web.signaling``'s
        ``_clients.broadcast``.  Tests should monkeypatch this to a list-
        appending callable.
    """

    def __init__(
        self,
        adapter: Any,
        board_emit: Callable[[dict[str, Any]], None] | None = None,
        network_emit: Callable[[dict[str, Any]], None] | None = None,
        network: NetworkGraph | None = None,
    ) -> None:
        self._adapter = adapter
        # card state: role -> {"column": str, "title": str, "subtitle": str, "edges": [...]}
        self._cards: dict[str, dict[str, Any]] = {}

        # Ordered queue of emitted card-ops (for tests / replay)
        self.emitted: list[dict[str, Any]] = []
        self.network = network or NetworkGraph()
        self.network_emitted: list[dict[str, Any]] = []

        # Resolve board_emit
        if board_emit is not None:
            self._emit = board_emit
        else:
            self._emit = self._default_emit
        self._network_emit = network_emit or self._default_network_emit

    # ── Internal emit ────────────────────────────────────────────────────────

    def _default_emit(self, card_op: dict[str, Any]) -> None:
        """Broadcast over signaling WS (production path)."""
        try:
            from web.signaling import _clients  # noqa: PLC0415

            payload = {
                "type": "board_update",
                "board": card_op,
            }
            # Schedule the broadcast as a background task
            asyncio.create_task(_clients.broadcast(payload))
        except Exception as exc:
            logger.debug("[observer] signaling broadcast failed: %s", exc)

    def _push(self, card_op: dict[str, Any]) -> None:
        """Record + emit one card-op."""
        self.emitted.append(card_op)
        self._emit(card_op)

    def _default_network_emit(self, payload: dict[str, Any]) -> None:
        """Broadcast a network snapshot over the same live events socket."""
        try:
            from web.signaling import _clients  # noqa: PLC0415

            asyncio.create_task(_clients.broadcast({"type": "network_update", **payload}))
        except Exception as exc:
            logger.debug("[observer] network broadcast failed: %s", exc)

    async def _push_network(self, event: StatusEvent) -> None:
        activity = await self.network.apply_event(event.kind, event.text, actor=event.actor)
        payload = {"snapshot": self.network.snapshot(), "activity": activity}
        self.network_emitted.append(payload)
        del self.network_emitted[:-24]
        self._network_emit(payload)

    def set_user_avatar(self, avatar_url: str) -> None:
        self.network.set_user_avatar(avatar_url)
        payload = {"snapshot": self.network.snapshot(), "activity": None}
        self.network_emitted.append(payload)
        del self.network_emitted[:-24]
        self._network_emit(payload)

    @property
    def network_snapshot(self) -> dict[str, Any]:
        return self.network.snapshot()

    # ── Card management ───────────────────────────────────────────────────────

    def _ensure_card(self, role: str, title: str | None = None) -> dict[str, Any]:
        """Return the card state for *role*, creating it in Backlog if absent."""
        if role not in self._cards:
            self._cards[role] = {
                "column": "backlog",
                "title": title or role.capitalize(),
                "subtitle": "",
                "edges": [],
            }
            self._push(
                _card_op(
                    op="card_created",
                    card_id=role,
                    role=role,
                    column="backlog",
                    title=self._cards[role]["title"],
                )
            )
        return self._cards[role]

    def _set_column(self, role: str, column: str) -> None:
        """Move a card to *column* if it isn't there already."""
        card = self._cards.get(role)
        if card is None:
            return  # card not created yet; will be created on first event
        if card["column"] == column:
            return
        card["column"] = column
        self._push(
            _card_op(
                op="card_moved",
                card_id=role,
                role=role,
                column=column,
                title=card["title"],
                subtitle=card["subtitle"],
                edges=card.get("edges", []),
            )
        )

    def _mark_done(self, role: str) -> None:
        """Advance a card to Done."""
        card = self._ensure_card(role)
        card["column"] = "done"
        self._push(
            _card_op(
                op="card_done",
                card_id=role,
                role=role,
                column="done",
                title=card["title"],
                subtitle=card["subtitle"],
                edges=card.get("edges", []),
            )
        )

    def _update_subtitle(self, role: str, subtitle: str) -> None:
        """Update a card's subtitle and emit a card_updated op."""
        card = self._ensure_card(role)
        card["subtitle"] = subtitle
        self._push(
            _card_op(
                op="card_updated",
                card_id=role,
                role=role,
                column=card["column"],
                title=card["title"],
                subtitle=subtitle,
                edges=card.get("edges", []),
            )
        )

    def _add_edge(self, from_role: str, to_role: str) -> None:
        """Record an org edge from *from_role* → *to_role* (idempotent)."""
        card = self._ensure_card(to_role)
        edge = {"from": from_role, "to": to_role}
        if edge not in card.get("edges", []):
            card.setdefault("edges", []).append(edge)
            self._push(
                _card_op(
                    op="edge_added",
                    card_id=to_role,
                    role=to_role,
                    column=card["column"],
                    title=card["title"],
                    subtitle=card["subtitle"],
                    edges=card["edges"],
                )
            )

    # ── Event dispatch ────────────────────────────────────────────────────────

    async def _on_tool(self, event: StatusEvent) -> None:
        """Handle a ``tool`` event: ``"<role>: <summary>"``."""
        text: str = event.text

        # Parse the ``"<role>: <summary>"`` pattern emitted by the fixture /
        # qoder.py fixture replay.
        role = CEO_ROLE  # default fallback
        subtitle = text

        if ": " in text:
            maybe_role, rest = text.split(": ", 1)
            # Accept only simple role names (no spaces, no brackets)
            if maybe_role and " " not in maybe_role and "(" not in maybe_role:
                role = maybe_role.lower()
                subtitle = rest

        # Seed CEO card on first interaction
        self._ensure_card(CEO_ROLE, "CEO")

        if role == CEO_ROLE:
            # CEO delegating → the subtitle is the delegation itself
            self._update_subtitle(CEO_ROLE, subtitle)
            # CEO moves to Running if still in Backlog
            self._set_column(CEO_ROLE, "running")
        else:
            # A sub-role was created/updated
            self._ensure_card(role, title=role.capitalize())
            self._update_subtitle(role, subtitle)
            # Edge: CEO → this role
            self._add_edge(CEO_ROLE, role)
            # Move sub-role to Running
            self._set_column(role, "running")
            # Also ensure CEO is Running
            self._set_column(CEO_ROLE, "running")

    async def _on_message(self, event: StatusEvent) -> None:
        """Handle a ``message`` event: an agent's output."""
        text: str = event.text
        role = CEO_ROLE  # fixture doesn't tag role in message events directly
        subtitle = await summarize(text, role=role)
        self._ensure_card(role, "CEO")
        self._update_subtitle(role, subtitle)
        self._set_column(role, "running")

    async def _on_progress(self, event: StatusEvent) -> None:
        """Handle a ``progress`` event: tick / subtitle update."""
        text: str = event.text
        role = CEO_ROLE
        subtitle = await summarize(text, role=role)
        self._ensure_card(role, "CEO")
        self._update_subtitle(role, subtitle)

    async def _on_done(self, _event: StatusEvent) -> None:
        """Handle a ``done`` event: mark ALL cards as Done."""
        for role in list(self._cards.keys()):
            self._mark_done(role)

    async def _on_error(self, event: StatusEvent) -> None:
        """Handle an ``error`` event: move CEO to Done with error subtitle."""
        self._ensure_card(CEO_ROLE, "CEO")
        self._update_subtitle(CEO_ROLE, f"Error: {event.text[:80]}")
        self._mark_done(CEO_ROLE)

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self, task: str, *, repo_path: str, context: dict | None = None) -> str:
        """Spawn the adapter, consume all events, return the handle.

        Each StatusEvent drives the card state machine and emits card-ops.
        """
        handle = await self._adapter.spawn(task, repo_path=repo_path, context=context)

        # Seed CEO card (Backlog → Running at first signal)
        self._ensure_card(CEO_ROLE, "CEO")

        async for event in self._adapter.stream_status(handle):
            try:
                # Keep the graph in lockstep with the card stream.  A failure
                # in the optional side summarizer must never stop the run.
                await self._push_network(event)
                if event.kind == "tool":
                    await self._on_tool(event)
                elif event.kind == "message":
                    await self._on_message(event)
                elif event.kind == "progress":
                    await self._on_progress(event)
                elif event.kind == "done":
                    await self._on_done(event)
                elif event.kind == "error":
                    await self._on_error(event)
            except Exception as exc:
                logger.error("[observer] error processing %r event: %s", event.kind, exc)

        return handle

    # ── Utility ───────────────────────────────────────────────────────────────

    @property
    def card_count(self) -> int:
        """Number of cards created so far."""
        return len(self._cards)

    @property
    def roles(self) -> list[str]:
        """All roles that have appeared so far."""
        return list(self._cards.keys())


# ---------------------------------------------------------------------------
# Convenience: run observer against fixture adapter (for scripts / tests)
# ---------------------------------------------------------------------------


async def run_company(
    task: str = "Write a quick_sort function in Python",
    *,
    repo_path: str = "/tmp/cv-demo",
    fixture_path: str | None = None,
    context: dict | None = None,
    board_emit: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[CompanyObserver, str]:
    """Quick-start helper: build a fixture adapter, run observer, return both.

    When *fixture_path* is ``None`` the environment variable ``CV_QODER_FIXTURE``
    is checked.  If neither is set the adapter falls back to live mode (which
    requires ``qodercli login``).

    Returns ``(observer, handle)``.
    """
    from receptionist.adapters.qoder import QoderAdapter  # noqa: PLC0415

    ctx: dict = context or {}
    if fixture_path:
        ctx["_fixture_path"] = fixture_path

    adapter = QoderAdapter(
        fixture_path=fixture_path or ctx.pop("_fixture_path", ""),
    )
    observer = CompanyObserver(adapter=adapter, board_emit=board_emit)
    handle = await observer.run(task, repo_path=repo_path, context=ctx)
    return observer, handle
