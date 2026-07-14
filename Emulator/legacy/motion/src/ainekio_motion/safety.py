from __future__ import annotations

from dataclasses import dataclass

from .types import MotionCommand, RobotCommand, now_ms


@dataclass(frozen=True)
class SafetyDecision:
    accepted: bool
    command: MotionCommand
    reason: str


class SafetyController:
    def __init__(
        self,
        *,
        stale_stop_ms: int = 600,
        offline_fallback_ms: int = 1500,
    ) -> None:
        self.stale_stop_ms = stale_stop_ms
        self.offline_fallback_ms = offline_fallback_ms
        self._estop_latched = False
        self._low_battery_locked = False
        self._leases: dict[str, int] = {}
        self._last_command_ms: int | None = None
        self._last_connected_ms: int | None = None

    def grant_lease(self, lease_id: str, *, ttl_ms: int, at_ms: int | None = None) -> None:
        current_ms = at_ms if at_ms is not None else now_ms()
        self._leases[lease_id] = current_ms + ttl_ms

    def latch_estop(self) -> None:
        self._estop_latched = True

    def clear_estop(self) -> None:
        self._estop_latched = False

    def set_low_battery_locked(self, locked: bool) -> None:
        self._low_battery_locked = locked

    def mark_connected(self, at_ms: int | None = None) -> None:
        self._last_connected_ms = at_ms if at_ms is not None else now_ms()

    def accept(self, command: MotionCommand, *, at_ms: int | None = None) -> SafetyDecision:
        current_ms = at_ms if at_ms is not None else now_ms()
        if self._estop_latched:
            return SafetyDecision(False, self._stop(current_ms), "estop_latched")
        if self._low_battery_locked:
            return SafetyDecision(False, self._stop(current_ms), "low_battery_locked")
        if command.is_expired(current_ms):
            return SafetyDecision(False, self._stop(current_ms), "command_expired")
        if command.lease_id is not None and self._leases.get(command.lease_id, -1) < current_ms:
            return SafetyDecision(False, self._stop(current_ms), "lease_expired")

        self._last_command_ms = current_ms
        return SafetyDecision(True, command, "accepted")

    def heartbeat_command(self, *, at_ms: int | None = None) -> MotionCommand | None:
        current_ms = at_ms if at_ms is not None else now_ms()
        if self._estop_latched or self._low_battery_locked:
            return self._stop(current_ms)
        if self._last_command_ms is not None and current_ms - self._last_command_ms > self.stale_stop_ms:
            return self._stop(current_ms)
        return None

    def offline_fallback_command(self, *, at_ms: int | None = None) -> MotionCommand | None:
        current_ms = at_ms if at_ms is not None else now_ms()
        if self._estop_latched or self._low_battery_locked:
            return self._stop(current_ms)
        if self._last_connected_ms is None:
            return MotionCommand(RobotCommand.IDLE, issued_at_ms=current_ms, source="offline-fallback")
        if current_ms - self._last_connected_ms >= self.offline_fallback_ms:
            return MotionCommand(RobotCommand.IDLE, issued_at_ms=current_ms, source="offline-fallback")
        return None

    @staticmethod
    def _stop(at_ms: int) -> MotionCommand:
        return MotionCommand(RobotCommand.STOP, issued_at_ms=at_ms, ttl_ms=100, source="safety")
