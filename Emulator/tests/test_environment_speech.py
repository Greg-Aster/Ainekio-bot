from __future__ import annotations

import json
import struct
import unittest

from gateway.environment_adapter.server import (
    EnvironmentAdapter,
    EnvironmentAdapterConfig,
)
from gateway.environment_adapter.speech_transport import (
    SPEECH_AUDIO_MAGIC,
    SpeechAudioMessage,
    parse_speech_audio_message,
)


def speech_packet(*, session_id: str = "ainekio-01") -> bytes:
    pcm = bytes(640)
    metadata = json.dumps(
        {
            "type": "audio.speech",
            "version": 1,
            "sessionId": session_id,
            "actionId": "speech-action-1",
            "speechId": "speech-1",
            "format": "pcm_s16le",
            "sampleRateHz": 16000,
            "channels": 1,
            "frameBytes": 640,
            "durationMs": 20,
            "pcmBytes": len(pcm),
        },
        separators=(",", ":"),
    ).encode()
    return SPEECH_AUDIO_MAGIC + struct.pack("<I", len(metadata)) + metadata + pcm


class FakeWebSocket:
    closed = False

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, value: str) -> None:
        self.sent.append(value)


class FakeGateway:
    def __init__(self) -> None:
        self.frames: list[bytes] = []

    def subscribe_events(self, _callback: object) -> None:
        pass

    def subscribe_frames(self, _callback: object) -> None:
        pass

    def subscribe_transcripts(self, _callback: object) -> None:
        pass

    def status(self) -> dict[str, object]:
        return {
            "robots": {
                "ainekio-body": {
                    "connected": True,
                    "status": {},
                }
            }
        }

    async def tts_speak(self, frames: object, **_kwargs: object) -> int:
        self.frames = [frame async for frame in frames]  # type: ignore[union-attr]
        return 7

    async def wait_terminal(self, _sequence: int, **_kwargs: object) -> dict[str, object]:
        return {"t": "done", "seq": 7}


class EnvironmentSpeechTests(unittest.IsolatedAsyncioTestCase):
    def test_binary_contract_is_bounded_and_session_authenticated(self) -> None:
        parsed = parse_speech_audio_message(
            speech_packet(),
            expected_session_id="ainekio-01",
            max_message_bytes=512 * 1024,
        )
        self.assertEqual(parsed.action_id, "speech-action-1")
        self.assertEqual(len(parsed.pcm), 640)
        with self.assertRaises(ValueError):
            parse_speech_audio_message(
                speech_packet(session_id="wrong-session"),
                expected_session_id="ainekio-01",
                max_message_bytes=512 * 1024,
            )

    async def test_adapter_reuses_gateway_speaker_and_reports_completion(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(  # type: ignore[arg-type]
            gateway,
            EnvironmentAdapterConfig(token="adapter-secret"),
        )
        websocket = FakeWebSocket()
        adapter._websocket = websocket
        speech = SpeechAudioMessage(
            session_id="ainekio-01",
            action_id="speech-action-1",
            speech_id="speech-1",
            duration_ms=20,
            pcm=bytes(640),
        )
        await adapter._process_speech_audio(speech)
        self.assertEqual(gateway.frames, [bytes(640)])
        feedback = json.loads(websocket.sent[0])["feedback"]
        self.assertEqual(feedback["actionId"], "speech-action-1")
        self.assertEqual(feedback["type"], "completed")


if __name__ == "__main__":
    unittest.main()
