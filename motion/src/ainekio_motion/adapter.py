from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Protocol

from .backend import VirtualBackend
from .commands import translate_environment_action
from .metahuman import BridgeEvent, MetaHumanBridgeClient
from .safety import SafetyController
from .simulator_shim import SimulatorShimClient, build_motion_payload
from .types import MotionCommand, ServoFrame, now_ms


ENVIRONMENT_BRIDGE_OBSERVATION = "/api/environment-bridge/observation"
ENVIRONMENT_BRIDGE_STREAM = "/api/environment-bridge/stream"
ENVIRONMENT_BRIDGE_ACTION_RESULT = "/api/environment-bridge/action-result"


class BridgeClient(Protocol):
    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        ...

    def stream_events(self, path: str, *, query: dict[str, Any] | None = None) -> Iterable[BridgeEvent]:
        ...


class MotionBackend(Protocol):
    def apply(self, command: MotionCommand, *, start_ms: int = 0) -> list[ServoFrame]:
        ...


class SimulatorPublisher(Protocol):
    def publish_motion(self, payload: dict[str, Any]) -> None:
        ...


@dataclass(frozen=True)
class ActionResult:
    action_id: str | None
    status: str
    message: str
    command: str | None = None
    frames: int = 0


@dataclass
class AinekioEnvironmentAdapter:
    client: BridgeClient
    session_id: str = "ainekio-sim-1"
    environment_id: str = "ainekio"
    adapter_id: str = "ainekio-sesame"
    backend: MotionBackend = field(default_factory=VirtualBackend)
    simulator: SimulatorPublisher | None = None
    safety: SafetyController = field(default_factory=SafetyController)
    default_ttl_ms: int = 1200
    max_action_age_ms: int = 5000

    def publish_observation(self, *, at: datetime | None = None) -> dict[str, Any]:
        timestamp = (at or datetime.now(timezone.utc)).isoformat()
        payload = {
            "environmentId": self.environment_id,
            "adapter": self.adapter_id,
            "sessionId": self.session_id,
            "timestamp": timestamp,
            "capabilities": {
                "actions": ["robotCommand", "move", "stop", "sendText"],
                "text": True,
                "movement": True,
                "visual": False,
                "map": False,
            },
            "state": {
                "backend": type(self.backend).__name__,
                "safety": "ready",
            },
        }
        return self.client.post_json(ENVIRONMENT_BRIDGE_OBSERVATION, payload)

    def handle_action(self, action: dict[str, Any], *, at_ms: int | None = None) -> ActionResult:
        current_ms = at_ms if at_ms is not None else _epoch_ms()
        action_id = str(action["id"]) if action.get("id") else None
        created_at = _parse_iso_ms(action.get("createdAt"))
        if created_at is not None and current_ms - created_at > self.max_action_age_ms:
            return ActionResult(action_id, "rejected", "action_expired")
        if action.get("type") == "sendText":
            return ActionResult(action_id, "completed", "text_received", command="sendText")

        command = translate_environment_action(
            action,
            issued_at_ms=current_ms,
            default_ttl_ms=self.default_ttl_ms,
        )
        if command is None:
            return ActionResult(action_id, "rejected", f"unsupported_action:{action.get('type')}")

        decision = self.safety.accept(command, at_ms=current_ms)
        if not decision.accepted:
            return ActionResult(action_id, "rejected", decision.reason, command=decision.command.command.value)

        frames = self.backend.apply(decision.command, start_ms=0)
        simulator_message = ""
        if self.simulator is not None:
            try:
                self.simulator.publish_motion(
                    build_motion_payload(
                        action_id=action_id,
                        session_id=self.session_id,
                        command=decision.command,
                        frames=frames,
                    )
                )
            except RuntimeError as exc:
                simulator_message = f"; simulator_publish_failed:{exc}"
        return ActionResult(
            action_id,
            "completed",
            f"completed{simulator_message}",
            command=decision.command.command.value,
            frames=len(frames),
        )

    def report_result(self, result: ActionResult, *, at: datetime | None = None) -> dict[str, Any]:
        payload = {
            "id": f"ainekio-result-{result.action_id or now_ms()}",
            "timestamp": (at or datetime.now(timezone.utc)).isoformat(),
            "type": result.status,
            "message": result.message,
            "actionId": result.action_id,
            "data": {
                "command": result.command,
                "frames": result.frames,
                "sessionId": self.session_id,
            },
        }
        return self.client.post_json(ENVIRONMENT_BRIDGE_ACTION_RESULT, payload)

    def handle_stream_event(self, event: BridgeEvent) -> list[ActionResult]:
        if event.event in {"connected", "heartbeat", "status"}:
            self.publish_observation()
            return []

        if event.event != "actions":
            return []

        actions = event.data.get("actions", [])
        if not isinstance(actions, list):
            return []

        results = [self.handle_action(action) for action in actions if isinstance(action, dict)]
        for result in results:
            self.report_result(result)
        return results

    def stream_results(self, *, limit: int = 10) -> Iterable[ActionResult]:
        self.publish_observation()
        for event in self.client.stream_events(
            ENVIRONMENT_BRIDGE_STREAM,
            query={"sessionId": self.session_id, "limit": limit},
        ):
            yield from self.handle_stream_event(event)


def create_adapter(
    *,
    base_url: str,
    session_id: str = "ainekio-sim-1",
    backend: MotionBackend | None = None,
    simulator_shim_url: str | None = None,
) -> AinekioEnvironmentAdapter:
    return AinekioEnvironmentAdapter(
        client=MetaHumanBridgeClient(base_url),
        session_id=session_id,
        backend=backend or VirtualBackend(),
        simulator=SimulatorShimClient(simulator_shim_url) if simulator_shim_url else None,
    )


def _parse_iso_ms(value: object) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def _epoch_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)
