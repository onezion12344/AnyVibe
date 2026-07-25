"""qoder_company/tests/test_observer.py — CompanyObserver tests (fixture-only).

All tests run against the shipped fixture (CV_QODER_FIXTURE).  No StepFun key
is required; the fallback summarizer returns trimmed text.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent.parent  # qoder_company/
_ROOT = _HERE.parent  # coding-vibe-qoder/
_FIXTURE = str(_ROOT / "receptionist" / "adapters" / "fixtures" / "qoder_company_demo.jsonl")

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def force_fixture_mode(monkeypatch):
    monkeypatch.setenv("CV_QODER_FIXTURE", _FIXTURE)
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _run_observer(task=None):
    from receptionist.adapters.qoder import QoderAdapter  # noqa: PLC0415
    from qoder_company.observer import CompanyObserver  # noqa: PLC0415

    adapter = QoderAdapter(fixture_path=_FIXTURE)
    observer = CompanyObserver(adapter=adapter)
    await observer.run(task or "demo task", repo_path="/tmp/cv-demo")
    return observer


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCompanyObserverFixtureRun:
    """Observer driven against the demo fixture — no qodercli needed."""

    async def test_runs_without_error(self):
        from qoder_company.observer import run_company

        observer, handle = await run_company(fixture_path=_FIXTURE)
        assert observer is not None
        assert handle is not None

    async def test_emits_at_least_ten_ops(self):
        """Observer should produce a healthy stream of card-ops."""
        observer = await _run_observer()
        assert len(observer.emitted) >= 10, (
            f"Expected >= 10 card-ops, got {len(observer.emitted)}: "
            + "\n".join(str(op) for op in observer.emitted[:5])
        )

    async def test_ceo_card_created(self):
        """The CEO card must always be the first card created."""
        observer = await _run_observer()
        roles = observer.roles
        assert "ceo" in roles, f"Expected 'ceo' in roles, got: {roles}"

    async def test_at_least_three_sub_role_cards_created(self):
        """The fixture delegates to researcher, full_stack, and qa → 3 sub-role cards."""
        observer = await _run_observer()
        roles = set(observer.roles)
        sub_roles = roles - {"ceo"}
        assert len(sub_roles) >= 3, (
            f"Expected >= 3 sub-role cards, got {sub_roles} (all roles: {roles})"
        )
        expected = {"researcher", "full_stack", "qa"}
        assert expected.issubset(roles), (
            f"Missing expected roles {expected - roles} in {roles}"
        )

    async def test_four_cards_total(self):
        """CEO + researcher + full_stack + qa = 4 cards."""
        observer = await _run_observer()
        assert observer.card_count == 4, (
            f"Expected 4 cards, got {observer.card_count} (roles={observer.roles})"
        )

    async def test_all_cards_end_in_done(self):
        """After the fixture finishes, every card should be in the Done column."""
        observer = await _run_observer()
        for role, card in observer._cards.items():
            assert card["column"] == "done", (
                f"Card for {role!r} still in {card['column']!r}, expected 'done'"
            )

    async def test_ceo_edges_to_all_sub_roles(self):
        """There must be at least one edge from CEO to each sub-role."""
        observer = await _run_observer()
        sub_roles = set(observer.roles) - {"ceo"}
        for role in sub_roles:
            card = observer._cards.get(role, {})
            edges = card.get("edges", [])
            ceo_edges = [e for e in edges if e.get("from") == "ceo"]
            assert len(ceo_edges) >= 1, (
                f"No CEO→{role} edge found. Card edges: {edges}"
            )

    async def test_at_least_three_edges_total(self):
        """CEO→researcher, CEO→full_stack, CEO→qa = >= 3 edges total."""
        observer = await _run_observer()
        all_edges = []
        for card in observer._cards.values():
            all_edges.extend(card.get("edges", []))
        ceo_edges = [e for e in all_edges if e.get("from") == "ceo"]
        assert len(ceo_edges) >= 3, (
            f"Expected >= 3 CEO→sub-role edges, got {len(ceo_edges)}: {ceo_edges}"
        )

    async def test_done_op_present(self):
        """The final emitted op-queue must contain at least one card_done op."""
        observer = await _run_observer()
        done_ops = [op for op in observer.emitted if op.get("op") == "card_done"]
        assert len(done_ops) >= 1, (
            "Expected at least one 'card_done' op in emitted queue: "
            + str([op.get("op") for op in observer.emitted])
        )

    async def test_card_created_ops_count(self):
        """Four card_created ops (CEO + 3 sub-roles) must appear."""
        observer = await _run_observer()
        created_ops = [op for op in observer.emitted if op.get("op") == "card_created"]
        assert len(created_ops) >= 4, (
            f"Expected >= 4 card_created ops, got {len(created_ops)}: {created_ops}"
        )

    async def test_card_ops_have_required_fields(self):
        """Every card-op must have op, card_id, role, column, title."""
        observer = await _run_observer()
        required = {"op", "card_id", "role", "column", "title"}
        for i, op in enumerate(observer.emitted):
            missing = required - op.keys()
            assert not missing, (
                f"Op #{i} ({op.get('op')}) missing fields: {missing}. Op: {op}"
            )

    async def test_op_sequence_ceo_created_first(self):
        """The very first card-op must be card_created for the CEO."""
        observer = await _run_observer()
        assert observer.emitted[0]["op"] == "card_created", (
            f"Expected first op 'card_created', got {observer.emitted[0].get('op')!r}"
        )
        assert observer.emitted[0]["role"] == "ceo"

    async def test_emitted_ops_last_is_done_or_card_done(self):
        """The last card-op should be a terminal operation."""
        observer = await _run_observer()
        last_op = observer.emitted[-1]["op"]
        assert last_op in {"card_done", "done", "card_updated"}, (
            f"Expected terminal op at end, got {last_op!r}"
        )

    async def test_no_crash_on_summarize_no_key(self):
        """With no STEPFUN_API_KEY the observer must still run cleanly."""
        import os
        import qoder_company.summarizer as sm

        old_key = os.environ.pop("STEPFUN_API_KEY", None)
        try:
            observer = await _run_observer()
            assert observer.card_count == 4
        finally:
            if old_key:
                os.environ["STEPFUN_API_KEY"] = old_key

    async def test_custom_board_emit_captures_ops(self):
        """A custom board_emit callable must receive all emitted ops."""
        captured: list[dict] = []
        from receptionist.adapters.qoder import QoderAdapter  # noqa: PLC0415
        from qoder_company.observer import CompanyObserver  # noqa: PLC0415

        adapter = QoderAdapter(fixture_path=_FIXTURE)
        observer = CompanyObserver(adapter=adapter, board_emit=captured.append)
        await observer.run("demo", repo_path="/tmp/cv-demo")

        assert len(captured) == len(observer.emitted)
        assert all(c["op"] == o["op"] for c, o in zip(captured, observer.emitted))

    async def test_monkeypatch_summarize_identity(self):
        """Monkeypatching summarize to identity must not break the observer."""
        import qoder_company.summarizer as sm

        original = sm.summarize

        async def identity(text, role=None):
            return text

        sm.summarize = identity
        try:
            observer = await _run_observer()
            # Observer should still have 4 cards
            assert observer.card_count == 4
        finally:
            sm.summarize = original
