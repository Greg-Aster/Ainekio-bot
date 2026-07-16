from __future__ import annotations

import asyncio
import base64
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from typing import Any, Callable, Mapping

from gateway.server.service import GatewayError, GatewayService
from protocol.binary_helpers import CAMERA_JPEG_FRAME_TYPE
from websockets.exceptions import ConnectionClosed

from .translation import (
    SUPPORTED_ROBOT_COMMANDS,
    BridgeAction,
    translate_environment_action,
)


ADAPTER_PROTOCOL_VERSION = 1
MAX_ADAPTER_MESSAGE_BYTES = 256 * 1024
MAX_CONTROL_ACTION_AGE_SECONDS = 2.0
MAX_FUTURE_CLOCK_SKEW_SECONDS = 5.0
NON_REPLAYABLE_ACTION_TYPES = frozenset(
    {"move", "look", "jump", "interact", "stop", "robotcommand"}
)


@dataclass(frozen=True)
class EnvironmentAdapterConfig:
    token: str
    session_id: str = "ainekio-sim-1"
    environment_id: str = "ainekio"
    adapter_id: str = "ainekio-gateway"
    robot_id: str | None = None
    snapshot_after_action: bool = True

    def __post_init__(self) -> None:
        if not self.token.strip() or len(self.token) > 512:
            raise ValueError("a bounded environment adapter token is required")


class EnvironmentAdapter:
    def __init__(
        self,
        gateway: GatewayService,
        config: EnvironmentAdapterConfig,
        *,
        clock: Callable[[], float] = monotonic,
        utcnow: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.gateway = gateway
        self.config = config
        self.clock = clock
        self.utcnow = utcnow
        self._websocket: Any | None = None
        self._send_lock = asyncio.Lock()
        self._camera_observation_count = 0
        gateway.subscribe_events(self._handle_gateway_event)
        gateway.subscribe_frames(self._handle_gateway_frame)
        gateway.subscribe_transcripts(self._handle_gateway_transcript)

    async def handler(self, websocket: Any) -> None:
        try:
            raw = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            hello = self._decode_message(raw)
        except Exception:
            await websocket.close(code=4002, reason="malformed environment handshake")
            return

        supplied = hello.get("token")
        if (
            hello.get("type") != "bridge.connect"
            or hello.get("version") != ADAPTER_PROTOCOL_VERSION
            or not isinstance(supplied, str)
            or not hmac.compare_digest(self.config.token, supplied)
        ):
            await websocket.close(code=4001, reason="environment authentication failed")
            return

        previous = self._websocket
        self._websocket = websocket
        if previous is not None and previous is not websocket:
            await previous.close(code=4000, reason="new authenticated environment connection")

        await self._send(
            {
                "type": "bridge.ready",
                "version": ADAPTER_PROTOCOL_VERSION,
                "sessionId": self.config.session_id,
                "observation": self._observation(),
            }
        )
        try:
            async for raw in websocket:
                message = self._decode_message(raw)
                if message.get("type") != "environment.action":
                    continue
                action = message.get("action")
                if not isinstance(action, dict):
                    continue
                feedback = await self.handle_action(action)
                await self._send(
                    {
                        "type": "environment.feedback",
                        "version": ADAPTER_PROTOCOL_VERSION,
                        "sessionId": self.config.session_id,
                        "feedback": feedback,
                    }
                )
                observation_sent = False
                if feedback["type"] == "completed" and self.config.snapshot_after_action:
                    previous_camera_count = self._camera_observation_count
                    await self._request_post_action_snapshot()
                    observation_sent = self._camera_observation_count > previous_camera_count
                if not observation_sent:
                    await self._send_observation()
        except ConnectionClosed:
            pass
        finally:
            if self._websocket is websocket:
                self._websocket = None

    async def handle_action(
        self,
        action: dict[str, Any],
        *,
        received_at: float | None = None,
    ) -> dict[str, object]:
        action_id = str(action["id"]) if action.get("id") else None
        if self._control_action_is_expired(action):
            return self._feedback(action_id, "expired", "action_expired_before_dispatch")
        translated = translate_environment_action(action)
        if translated is None:
            return self._feedback(
                action_id,
                "rejected",
                f"unsupported_action:{action.get('type')}",
            )
        if translated.kind == "text":
            await self.gateway.publish_transcript(
                {
                    "source": "environment_adapter",
                    "session_id": self.config.session_id,
                    **translated.params,
                }
            )
            return self._feedback(action_id, "completed", "text_received", command="sendText")

        accepted_at = self.clock() if received_at is None else received_at
        try:
            sequence = await self._dispatch(translated, accepted_at)
            terminal = await self.gateway.wait_terminal(
                sequence,
                robot_id=self.config.robot_id,
                timeout=30.0,
            )
        except (GatewayError, TimeoutError) as exc:
            return self._feedback(action_id, "rejected", str(exc), command=translated.name)

        terminal_type = str(terminal.get("t"))
        if terminal_type in {"ack", "done"}:
            status = "completed"
            message = terminal_type
        elif terminal_type == "cancelled":
            status = "cancelled"
            message = str(terminal.get("code", "cancelled"))
        else:
            status = "rejected"
            message = str(terminal.get("code", "rejected"))
        return self._feedback(
            action_id,
            status,
            message,
            command=translated.name or translated.kind,
            sequence=sequence,
        )

    async def _dispatch(self, action: BridgeAction, received_at: float) -> int:
        if action.kind == "stop":
            return await self.gateway.estop(
                robot_id=self.config.robot_id,
                received_at=received_at,
            )
        if action.kind == "intent" and action.name is not None:
            return await self.gateway.queue_intent(
                action.name,
                action.params,
                robot_id=self.config.robot_id,
                received_at=received_at,
            )
        raise GatewayError("unsupported translated environment action")

    async def _request_post_action_snapshot(self) -> None:
        try:
            sequence = await self.gateway.request_snap(robot_id=self.config.robot_id)
            await self.gateway.wait_terminal(
                sequence,
                robot_id=self.config.robot_id,
                timeout=10.0,
            )
        except (GatewayError, TimeoutError):
            return

    async def _handle_gateway_event(self, event: dict[str, object]) -> None:
        if event.get("t") not in {"connection", "event"}:
            return
        await self._send_observation()

    async def _handle_gateway_transcript(self, transcript: dict[str, object]) -> None:
        if transcript.get("source") == "environment_adapter":
            return
        text = transcript.get("text")
        if not isinstance(text, str) or not text.strip():
            return
        text_event = {
            "id": f"ainekio-text-{int(self.clock() * 1000)}",
            "source": "environment",
            "text": text[:4096],
            "timestamp": self.utcnow().isoformat(),
        }
        await self._send_observation(text=[text_event])

    async def _handle_gateway_frame(self, frame: dict[str, object]) -> None:
        if frame.get("frame_type") != CAMERA_JPEG_FRAME_TYPE:
            return
        payload = frame.get("payload")
        if not isinstance(payload, bytes):
            return
        visual = {
            "id": f"ainekio-camera-{frame.get('counter', int(self.clock() * 1000))}",
            "timestamp": self.utcnow().isoformat(),
            "mimeType": "image/jpeg",
            "dataUrl": f"data:image/jpeg;base64,{base64.b64encode(payload).decode('ascii')}",
            "source": "robot-camera",
            "metadata": {
                "robotId": frame.get("robot_id"),
                "counter": frame.get("counter"),
            },
        }
        await self._send_observation(visual=visual)
        self._camera_observation_count += 1

    async def _send_observation(
        self,
        *,
        text: list[dict[str, object]] | None = None,
        visual: dict[str, object] | None = None,
    ) -> None:
        await self._send(
            {
                "type": "environment.observation",
                "version": ADAPTER_PROTOCOL_VERSION,
                "sessionId": self.config.session_id,
                "observation": self._observation(text=text, visual=visual),
            }
        )

    def _observation(
        self,
        *,
        text: list[dict[str, object]] | None = None,
        visual: dict[str, object] | None = None,
    ) -> dict[str, object]:
        observation: dict[str, object] = {
            "environmentId": self.config.environment_id,
            "adapter": self.config.adapter_id,
            "sessionId": self.config.session_id,
            "timestamp": self.utcnow().isoformat(),
            "capabilities": {
                "actions": ["robotCommand", "move", "stop", "sendText"],
                "robotCommands": list(SUPPORTED_ROBOT_COMMANDS),
                "text": True,
                "movement": True,
                "visual": True,
                "map": False,
            },
            "state": {
                "transport": "protocol-v1",
                "safety": "body-owned",
                "gateway": self.gateway.status(),
            },
        }
        if text:
            observation["text"] = text
        if visual:
            observation["visual"] = visual
            observation["visuals"] = [visual]
        return observation

    async def _send(self, message: Mapping[str, object]) -> None:
        websocket = self._websocket
        if websocket is None or websocket.closed:
            return
        encoded = json.dumps(message, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > MAX_ADAPTER_MESSAGE_BYTES:
            raise GatewayError("environment adapter message exceeds its size limit")
        async with self._send_lock:
            await websocket.send(encoded)

    def _decode_message(self, raw: object) -> dict[str, Any]:
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_ADAPTER_MESSAGE_BYTES:
            raise ValueError("invalid environment adapter message")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("environment adapter message must be an object")
        return value

    def _control_action_is_expired(self, action: Mapping[str, object]) -> bool:
        action_type = str(action.get("type", "")).strip().lower().replace("_", "")
        if action_type not in NON_REPLAYABLE_ACTION_TYPES:
            return False
        created_at = action.get("createdAt")
        if not isinstance(created_at, str):
            return True
        try:
            parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            return True
        if parsed.tzinfo is None:
            return True
        age = (self.utcnow() - parsed.astimezone(timezone.utc)).total_seconds()
        return age > MAX_CONTROL_ACTION_AGE_SECONDS or age < -MAX_FUTURE_CLOCK_SKEW_SECONDS

    def _feedback(
        self,
        action_id: str | None,
        status: str,
        message: str,
        *,
        command: str | None = None,
        sequence: int | None = None,
    ) -> dict[str, object]:
        return {
            "id": f"ainekio-result-{action_id or int(self.clock() * 1000)}",
            "timestamp": self.utcnow().isoformat(),
            "type": status,
            "message": message,
            "actionId": action_id,
            "data": {"command": command, "sequence": sequence},
        }
