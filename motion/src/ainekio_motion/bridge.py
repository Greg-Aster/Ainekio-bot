from __future__ import annotations

from collections.abc import Iterable
from typing import Mapping

from .commands import translate_environment_action
from .types import MotionCommand, now_ms


def filter_reconnect_actions(
    actions: Iterable[Mapping[str, object]],
    *,
    at_ms: int | None = None,
    default_ttl_ms: int = 1200,
) -> list[MotionCommand]:
    """One-shot reconnect catch-up that drops expired actions.

    This is deliberately not a polling loop. A bridge client should call this
    once after reconnecting, then return to its push/event subscription.
    """

    current_ms = at_ms if at_ms is not None else now_ms()
    commands: list[MotionCommand] = []
    for action in actions:
        issued_at = action.get("issued_at_ms") or action.get("issuedAtMs")
        command = translate_environment_action(
            action,
            issued_at_ms=int(issued_at) if issued_at is not None else current_ms,
            default_ttl_ms=default_ttl_ms,
        )
        if command is not None and not command.is_expired(current_ms):
            commands.append(command)
    return commands
