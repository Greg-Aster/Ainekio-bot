"""Select the connected body's implemented motions without defining a catalog.

Public command names/descriptions remain owned by environment_adapter.translation.
Legacy eight-servo bodies retain their existing contract. New bodies must declare
their subset; a model name alone never grants the legacy motion set.
"""
from collections.abc import Mapping, Sequence

from protocol.control_v1 import BODY_COMMANDS_FEATURE


def body_commands(
    model: str,
    features: Sequence[str],
    capabilities: Mapping[str, object] | None,
) -> tuple[str, ...] | None:
    """Return ready semantic names, or None for the legacy V1 contract."""
    if capabilities is not None and capabilities.get("motion") is not True:
        return ()
    if BODY_COMMANDS_FEATURE in features:
        names = capabilities.get("commands") if capabilities is not None else None
        return tuple(names) if isinstance(names, list) and all(isinstance(n, str) for n in names) else ()
    return None if model == "v1-8servo" else ()


def body_command_available(name: str, supported: tuple[str, ...] | None) -> bool:
    if supported is not None:
        return name in supported
    # Resolve after gateway/adapter initialization; the adapter package imports
    # the gateway service. Reuse its semantic catalog without a second name list.
    from .environment_adapter.translation import DECLARED_EMOTES, DECLARED_GAITS

    return name not in DECLARED_EMOTES and name not in DECLARED_GAITS


def movement_command(message: Mapping[str, object]) -> str | None:
    """The semantic name of an existing movement envelope; no joint mapping."""
    if message.get("t") != "intent":
        return None
    name = message.get("name")
    if not isinstance(name, str):
        return None
    if name == "walk":
        direction = message.get("dir")
        return {"fwd": "walk", "back": "backward", "turn_l": "left", "turn_r": "right"}.get(
            direction if isinstance(direction, str) else "", "walk"
        )
    if name == "emote":
        asset = message.get("asset")
        return asset if isinstance(asset, str) else "emote"
    return name if name in {"stand", "neutral", "sit", "look"} else None
