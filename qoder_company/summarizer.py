"""qoder_company/summarizer.py — LLM summarizer for inter-agent messages.

Uses StepFun step-3.7-flash via the OpenAI-compatible endpoint
(STEPFUN_API_KEY / STEPFUN_BASE_URL from .env).

If STEPFUN_API_KEY is not set the summarizer is a pass-through that returns a
lightly trimmed version of *text* (so the board still shows something).

Both the real and fallback paths are easily monkeypatchable in tests.
"""

from __future__ import annotations

import os
from typing import Optional

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

_STEPFUN_KEY: str = os.environ.get("STEPFUN_API_KEY", "")
_STEPFUN_BASE: str = os.environ.get("STEPFUN_BASE_URL", "https://api.stepfun.com/v1")
_MODEL: str = "step-3.7-flash"

# Max chars we keep from the original text as fallback / for truncation.
_MAX_TEXT: int = 120


async def summarize(text: str, role: Optional[str] = None) -> str:
    """Return a short board-friendly one-liner summary of *text*.

    Parameters
    ----------
    text:
        Raw message text from an agent.
    role:
        Optional role name (e.g. "ceo", "researcher"). Prepended to the
        prompt so the model can tailor the summary style.

    Returns
    -------
    str
        A concise one-liner, <= ~120 chars.  Falls back to a trimmed
        version of *text* when no API key is available.
    """
    # ── Fast-path: empty / trivial ──────────────────────────────────────────
    if not text or not text.strip():
        return ""

    stripped = text.strip()

    # ── No API key → deterministic pass-through ────────────────────────────
    if not _STEPFUN_KEY:
        return _trim(stripped)

    # ── Live summarization ─────────────────────────────────────────────────
    import httpx  # lazy import — only needed when key is present

    role_hint = f" [{role}]" if role else ""
    prompt = (
        f"Summarise the following agent message{role_hint} in ONE short Chinese "
        f"sentence (<= 60 chars).  Keep it factual and board-friendly. "
        f"Output ONLY the summary, no extra text.\n\n"
        f"{stripped}"
    )

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{_STEPFUN_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {_STEPFUN_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": _MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 80,
                    "temperature": 0.2,
                },
            )
            if resp.status_code != 200:
                # Non-200 → fall back silently (board must never break)
                return _trim(stripped)

            data = resp.json()
            content: str = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            return content.strip() or _trim(stripped)

    except Exception:
        # Network error, timeout, etc. — never crash the observer
        return _trim(stripped)


# ── Internal helpers ────────────────────────────────────────────────────────────

def _trim(text: str) -> str:
    """Hard-cap text at _MAX_TEXT chars, ellipsising if necessary."""
    if len(text) <= _MAX_TEXT:
        return text
    return text[:_MAX_TEXT - 1].rstrip() + "…"
