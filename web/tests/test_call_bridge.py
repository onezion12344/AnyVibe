from __future__ import annotations

import asyncio

import pytest

import web.call_bridge as call_bridge
from web.call_bridge import _client_session_update
from web.engineer_dispatch import CallTurn


def test_realtime_session_requests_input_transcription_for_dispatch():
    """The realtime bridge cannot classify a voice request without ASR text."""
    event = _client_session_update("event-123")

    assert event["type"] == "session.update"
    session = event["session"]
    assert session["input_audio_transcription"] == {"model": "step-asr"}
    assert session["turn_detection"]["create_response"] is False
    assert session["turn_detection"]["prefix_padding_ms"] == 600


def test_cs_persona_keeps_status_conversations_open():
    """The live voice prompt must not sound like an eager hang-up bot."""
    instructions = _client_session_update("event-123")["session"]["instructions"]

    assert "进度或报告" in instructions
    assert "不要主动结束通话" in instructions
    assert "不要说“已安排”“马上处理”“忙完回电”" in instructions


class _StepFunTranscript:
    def __init__(self) -> None:
        self._messages = [
            '{"type":"conversation.item.input_audio_transcription.completed",'
            '"transcript":"Build a timer app"}'
        ]

    async def recv(self) -> str:
        if self._messages:
            return self._messages.pop(0)
        # Give the scheduled turn task one loop iteration, as a live socket
        # naturally would before its next event arrives.
        await asyncio.sleep(0)
        raise RuntimeError("end fake realtime stream")


class _BrowserSocket:
    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.audio: list[bytes] = []

    async def send_json(self, payload: dict) -> None:
        self.messages.append(payload)

    async def send_bytes(self, payload: bytes) -> None:
        self.audio.append(payload)


@pytest.mark.asyncio
async def test_transcript_event_is_visible_and_reaches_dispatch(monkeypatch):
    """A completed ASR turn must reach the cascaded decision + reply stage."""
    received: list[str] = []

    async def fake_route(transcript: str, browser_ws) -> None:
        received.append(transcript)

    monkeypatch.setattr(call_bridge, "_route_and_respond", fake_route)
    browser = _BrowserSocket()

    await call_bridge._pump_stepfun_to_browser(_StepFunTranscript(), browser)
    await asyncio.sleep(0)

    assert browser.messages == [{"type": "transcript", "text": "Build a timer app"}]
    assert received == ["Build a timer app"]


class _StepFunSpeechStopped:
    def __init__(self) -> None:
        self._messages = ['{"type":"input_audio_buffer.speech_stopped"}']
        self.sent: list[dict] = []

    async def recv(self) -> str:
        if self._messages:
            return self._messages.pop(0)
        raise RuntimeError("end fake realtime stream")

    async def send(self, payload: str) -> None:
        self.sent.append(__import__("json").loads(payload))


@pytest.mark.asyncio
async def test_asr_only_session_commits_at_the_vad_turn_boundary():
    """With automatic audio responses disabled, ASR still receives a commit."""
    stepfun = _StepFunSpeechStopped()
    browser = _BrowserSocket()

    await call_bridge._pump_stepfun_to_browser(stepfun, browser)

    assert browser.messages == [{"type": "call-state", "state": "speech-stopped"}]
    assert stepfun.sent == [{"type": "input_audio_buffer.commit"}]


@pytest.mark.asyncio
async def test_goodbye_is_voiced_then_ends_the_browser_call(monkeypatch):
    """The backend controls goodbye rather than waiting for a UI button click."""
    spoken: list[str] = []

    async def fake_plan(_transcript: str) -> CallTurn:
        return CallTurn(action="end_call", reply="好，那我先挂了。下次见。")

    async def fake_speak(_browser, text: str) -> float:
        spoken.append(text)
        return 1.25

    monkeypatch.setattr(call_bridge, "plan_call_turn", fake_plan)
    monkeypatch.setattr(call_bridge, "_speak_text", fake_speak)
    browser = _BrowserSocket()

    await call_bridge._route_and_respond("再见", browser)

    assert spoken == ["好，那我先挂了。下次见。"]
    assert browser.messages == [
        {"type": "end-call", "delay_ms": 1430, "reason": "caller-goodbye"}
    ]


@pytest.mark.asyncio
async def test_model_authored_opening_is_the_only_call_opening_audio(monkeypatch):
    """New calls use the LLM's fresh greeting instead of a fixed script."""
    spoken: list[str] = []

    async def fake_opening() -> str:
        return "你好，我是黄羊。你今天最想推进什么？"

    async def fake_speak(_browser, text: str) -> float:
        spoken.append(text)
        return 0.0

    monkeypatch.setattr(call_bridge, "plan_call_opening", fake_opening)
    monkeypatch.setattr(call_bridge, "_speak_text", fake_speak)
    browser = _BrowserSocket()

    await call_bridge._open_call_conversation(browser)

    assert spoken == ["你好，我是黄羊。你今天最想推进什么？"]
