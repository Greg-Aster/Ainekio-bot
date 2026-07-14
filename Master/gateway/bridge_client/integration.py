from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from time import monotonic
from typing import Any, Callable

from gateway.server.service import GatewayError, GatewayService

from .client import BridgeEvent, MetaHumanBridgeClient
from .translation import BridgeAction, translate_environment_action


ENVIRONMENT_BRIDGE_OBSERVATION = "/api/environment-bridge/observation"
ENVIRONMENT_BRIDGE_STREAM = "/api/environment-bridge/stream"
ENVIRONMENT_BRIDGE_ACTION_RESULT = "/api/environment-bridge/action-result"
MAX_ACTIONS_PER_EVENT = 32
MAX_CONTROL_ACTION_AGE_SECONDS = 2.0
MAX_FUTURE_CLOCK_SKEW_SECONDS = 5.0
NON_REPLAYABLE_ACTION_TYPES = frozenset(
    {"move", "look", "jump", "interact", "stop", "robotcommand"}
)


@dataclass(frozen=True)
class GatewayBridgeConfig:
    base_url: str
    service_token: str = ""
    session_id: str = "ainekio-sim-1"
    environment_id: str = "ainekio"
    adapter_id: str = "ainekio-gateway"
    robot_id: str | None = None
    reconnect_seconds: float = 2.0


class GatewayBridge:
    def __init__(
        self,
        gateway: GatewayService,
        config: GatewayBridgeConfig,
        *,
        client: MetaHumanBridgeClient | None = None,
        clock: Callable[[], float] = monotonic,
        utcnow: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.gateway = gateway
        self.config = config
        self.client = client or MetaHumanBridgeClient(config.base_url, config.service_token)
        self.clock = clock
        self.utcnow = utcnow
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self, event_loop: asyncio.AbstractEventLoop) -> None:
        if self._thread is not None:
            raise RuntimeError("MetaHuman bridge is already running")
        self._thread = threading.Thread(
            target=self._stream_loop,
            args=(event_loop,),
            name="ainekio-metahuman-bridge",
            daemon=True,
        )
        self._thread.start()

    def request_stop(self) -> None:
        self._stop.set()

    async def handle_action(
        self,
        action: dict[str, Any],
        *,
        received_at: float | None = None,
    ) -> dict[str, object]:
        action_id = str(action["id"]) if action.get("id") else None
        if self._control_action_is_expired(action):
            return self._result(action_id, "expired", "action_expired_before_dispatch")
        translated = translate_environment_action(action)
        if translated is None:
            return self._result(action_id, "rejected", f"unsupported_action:{action.get('type')}")
        if translated.kind == "text":
            await self.gateway.publish_transcript(
                {
                    "source": "environment_bridge",
                    "session_id": self.config.session_id,
                    **translated.params,
                }
            )
            return self._result(action_id, "completed", "text_received", command="sendText")

        accepted_at = self.clock() if received_at is None else received_at
        try:
            sequence = await self._dispatch(translated, accepted_at)
            terminal = await self.gateway.wait_terminal(
                sequence,
                robot_id=self.config.robot_id,
                timeout=30.0,
            )
        except (GatewayError, TimeoutError) as exc:
            return self._result(action_id, "rejected", str(exc), command=translated.name)

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
        return self._result(
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
        raise GatewayError("unsupported translated bridge action")

    def _control_action_is_expired(self, action: dict[str, Any]) -> bool:
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

    def publish_observation(self) -> dict[str, Any]:
        payload = {
            "environmentId": self.config.environment_id,
            "adapter": self.config.adapter_id,
            "sessionId": self.config.session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "capabilities": {
                "actions": ["robotCommand", "move", "stop", "sendText"],
                "text": True,
                "movement": True,
                "visual": True,
                "map": False,
            },
            "state": {"transport": "protocol-v1", "safety": "body-owned"},
        }
        return self.client.post_json(ENVIRONMENT_BRIDGE_OBSERVATION, payload)

    def _stream_loop(self, event_loop: asyncio.AbstractEventLoop) -> None:
        while not self._stop.is_set():
            try:
                self.publish_observation()
                events = self.client.stream_events(
                    ENVIRONMENT_BRIDGE_STREAM,
                    query={"sessionId": self.config.session_id, "limit": MAX_ACTIONS_PER_EVENT},
                )
                for event in events:
                    if self._stop.is_set():
                        return
                    if event.event in {"connected", "heartbeat", "status"}:
                        self.publish_observation()
                        continue
                    self._submit_event(event_loop, event)
            except Exception:
                self._stop.wait(self.config.reconnect_seconds)

    def _submit_event(
        self,
        event_loop: asyncio.AbstractEventLoop,
        event: BridgeEvent,
    ) -> None:
        if event.event != "actions":
            return
        raw_actions = event.data.get("actions")
        if not isinstance(raw_actions, list):
            return
        actions = [action for action in raw_actions[:MAX_ACTIONS_PER_EVENT] if isinstance(action, dict)]
        received_at = self.clock()
        future = asyncio.run_coroutine_threadsafe(
            self._handle_actions(actions, received_at=received_at),
            event_loop,
        )
        try:
            future.result(timeout=45.0)
        except (concurrent.futures.TimeoutError, concurrent.futures.CancelledError):
            future.cancel()

    async def _handle_actions(
        self,
        actions: list[dict[str, Any]],
        *,
        received_at: float,
    ) -> None:
        for action in actions:
            result = await self.handle_action(action, received_at=received_at)
            await asyncio.to_thread(
                self.client.post_json,
                ENVIRONMENT_BRIDGE_ACTION_RESULT,
                result,
            )

    def _result(
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
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": status,
            "message": message,
            "actionId": action_id,
            "data": {
                "command": command,
                "sequence": sequence,
                "sessionId": self.config.session_id,
            },
        }
