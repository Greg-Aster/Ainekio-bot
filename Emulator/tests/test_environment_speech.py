from __future__ import annotations

import json
import base64
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


def speech_packet(*, session_id: str = "ainekio-01", duration_ms: int = 20) -> bytes:
    pcm = bytes(duration_ms * 32)
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
            "durationMs": duration_ms,
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
        self.instance_id = "fixture-gateway"
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
                    "epoch": 3,
                    "status": {},
                }
            }
        }

    async def tts_speak(self, frames: object, **_kwargs: object) -> int:
        async with _kwargs["on_sequence"](7):
            pass
        self.frames = [frame async for frame in frames]  # type: ignore[union-attr]
        return 7

    async def wait_terminal(self, _sequence: int, **_kwargs: object) -> dict[str, object]:
        return {"t": "done", "seq": 7}


class EnvironmentSpeechTests(unittest.IsolatedAsyncioTestCase):
    def test_long_reply_keeps_every_audio_frame(self) -> None:
        # Exceeds the former duration, PCM and outer WebSocket cutoffs.
        parsed = parse_speech_audio_message(
            speech_packet(duration_ms=180_000),
            expected_session_id="ainekio-01",
        )
        self.assertEqual(parsed.duration_ms, 180_000)
        self.assertEqual(parsed.pcm, bytes(180_000 * 32))

    def test_binary_contract_is_session_authenticated(self) -> None:
        parsed = parse_speech_audio_message(
            speech_packet(),
            expected_session_id="ainekio-01",
        )
        self.assertEqual(parsed.action_id, "speech-action-1")
        self.assertEqual(len(parsed.pcm), 640)
        with self.assertRaises(ValueError):
            parse_speech_audio_message(
                speech_packet(session_id="wrong-session"),
                expected_session_id="ainekio-01",
            )

    async def test_duplicate_saved_image_does_not_block_the_speech_connection(self) -> None:
        adapter = EnvironmentAdapter(FakeGateway(),
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret"))
        adapter._websocket, adapter._bridge_ready = FakeWebSocket(), True
        visual = {"dataUrl": "data:image/jpeg;base64," + base64.b64encode(bytes(256 * 1024)).decode()}
        observation = adapter._observation(visual=visual)
        self.assertNotIn("visuals", observation)
        # Exercise an already-persisted receipt from before the correction.
        envelope = {"type": "environment.observation", "observation": {
            "id": "saved-camera", "visual": visual, "visuals": [visual],
        }}
        adapter.receipts.queue("saved-camera", None, envelope)
        await adapter._replay_pending_feedback()
        delivered = json.loads(adapter._websocket.sent[0])["observation"]
        self.assertEqual(delivered["visual"], visual)
        self.assertNotIn("visuals", delivered)
        self.assertEqual(envelope["observation"]["visuals"], [visual])

    async def test_adapter_reuses_gateway_speaker_and_reports_completion(self) -> None:
        gateway = FakeGateway()
        adapter = EnvironmentAdapter(  # type: ignore[arg-type]
            gateway,
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret"),
        )
        websocket = FakeWebSocket()
        adapter._websocket = websocket
        adapter._bridge_ready = True
        speech = SpeechAudioMessage(
            session_id="ainekio-01",
            action_id="speech-action-1",
            speech_id="speech-1",
            duration_ms=20,
            pcm=bytes(640),
        )
        adapter.receipts.receive({"id": speech.action_id, "type": "speechAudio", "sessionId": speech.session_id,
            "speechId": speech.speech_id, "durationMs": speech.duration_ms, "pcm": base64.b64encode(speech.pcm).decode("ascii")},
            adapter._feedback(speech.action_id, "accepted", "accepted"))
        await adapter._process_speech_audio(speech)
        self.assertEqual(gateway.frames, [bytes(640)])
        feedback = json.loads(websocket.sent[0])["feedback"]
        self.assertEqual(feedback["actionId"], "speech-action-1")
        self.assertEqual(feedback["type"], "completed")
        wire = json.loads(adapter.receipts.action(speech.action_id)["wire"])
        self.assertEqual(wire, {"robotId": "ainekio-body", "epoch": 3, "sequence": 7,
                                "gatewayInstance": "fixture-gateway", "kind": "speech"})

    async def test_cancel_before_receipt_survives_reconnect_and_blocks_late_speech(self) -> None:
        adapter = EnvironmentAdapter(FakeGateway(),
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret"))
        adapter._websocket, adapter._bridge_ready = FakeWebSocket(), True
        lease = {"bodyId": "ainekio-01", "executionId": "fixture-execution", "generation": 1}
        await adapter._cancel_action({"actionId": "lost-speech", "cancellationId": "cancel-lost", "bodyLease": lease})
        feedback = json.loads(adapter.receipts.action("lost-speech")["result"])
        self.assertEqual(feedback["type"], "cancelled")
        adapter._websocket = FakeWebSocket()
        await adapter._recover_action_receipts()
        await adapter._replay_pending_feedback()
        self.assertTrue(any(json.loads(value).get("feedback", {}).get("id") == feedback["id"]
                            for value in adapter._websocket.sent))
        from gateway.environment_adapter.action_receipts import ActionConflictError
        with self.assertRaises(ActionConflictError):
            adapter.receipts.receive({"id": "lost-speech", "type": "speechAudio"},
                adapter._feedback("lost-speech", "accepted", "accepted"))
        self.assertEqual(adapter.gateway.frames, [])

    async def test_saved_speech_recovers_its_result_without_replaying_audio(self) -> None:
        adapter = EnvironmentAdapter(FakeGateway(),
            EnvironmentAdapterConfig(receipt_path=":memory:", token="adapter-secret"))
        for restarted in (False, True):
            action_id = f"saved-speech-{restarted}"
            adapter.receipts.receive({"id": action_id, "type": "speechAudio"},
                adapter._feedback(action_id, "accepted", "accepted"))
            adapter.receipts.begin(action_id, {"robotId": "ainekio-body", "epoch": 3, "sequence": 7,
                "gatewayInstance": "previous-gateway" if restarted else "fixture-gateway", "kind": "speech"})
            feedback = await adapter._resume_action_receipt(adapter.receipts.action(action_id))
            self.assertEqual(feedback["type"], "cancelled" if restarted else "completed")
            self.assertEqual(adapter.gateway.frames, [])


if __name__ == "__main__":
    unittest.main()
