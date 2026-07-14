"""Table-driven validation for the Ainekio v1 wire protocol."""

from __future__ import annotations

import math
import re
from typing import Callable, Mapping

from protocol.binary_helpers import (
    MAX_BINARY_COUNTER,
    BinaryFrame,
    BinaryFrameError,
    decode_binary_frame,
)


PROTOCOL_VERSION = 1
MAX_SEQUENCE = (1 << 31) - 1
MAX_AUTH_CHARS = 128

ASSET_NAME = re.compile(r"[a-z0-9_]{1,32}\Z")

INTENT_NAMES = frozenset(
    {"sit", "stand", "neutral", "look", "walk", "emote", "face", "say"}
)
WALK_DIRECTIONS = frozenset({"fwd", "back", "turn_l", "turn_r"})
PROFILES = frozenset({"home", "tether"})
CAMERA_RESOLUTIONS = frozenset({"QVGA", "VGA"})
MIC_GATES = frozenset({"open", "vad", "wake"})
BODY_STATES = frozenset({"active", "idle", "dozing", "deep-sleep", "failsafe"})
EVENT_NAMES = frozenset(
    {
        "vad_open",
        "vad_close",
        "wake_word",
        "battery_warn",
        "battery_cutoff",
        "brownout_recovered",
        "boot",
        "sd_fail",
        "sd_corrupt",
        "littlefs_fail",
        "asset_missing",
        "tts_orphan",
        "tts_overflow",
    }
)
NAK_CODES = frozenset(
    {"stale", "mode", "unsafe", "limit", "unknown", "busy", "profile", "malformed", "asset_missing"}
)
CANCEL_CODES = frozenset({"stop", "disconnect", "reconnect", "overflow"})


class ProtocolValidationError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _fail(reason: str) -> None:
    raise ProtocolValidationError(reason)


def _required(message: Mapping[str, object], name: str) -> object:
    if name not in message:
        _fail(f"missing:{name}")
    return message[name]


def _string(
    message: Mapping[str, object],
    name: str,
    *,
    allowed: frozenset[str] | None = None,
    min_length: int = 1,
    max_length: int | None = None,
) -> str:
    value = _required(message, name)
    if not isinstance(value, str):
        _fail(f"type:{name}")
    if len(value) < min_length or (max_length is not None and len(value) > max_length):
        _fail(f"range:{name}")
    if allowed is not None and value not in allowed:
        _fail(f"value:{name}")
    return value


def _optional_string(
    message: Mapping[str, object],
    name: str,
    *,
    max_length: int,
) -> str | None:
    if name not in message:
        return None
    return _string(message, name, max_length=max_length)


def _integer(
    message: Mapping[str, object],
    name: str,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    value = _required(message, name)
    if type(value) is not int:
        _fail(f"type:{name}")
    if minimum is not None and value < minimum:
        _fail(f"range:{name}")
    if maximum is not None and value > maximum:
        _fail(f"range:{name}")
    return value


def _optional_integer(
    message: Mapping[str, object],
    name: str,
    *,
    minimum: int,
    maximum: int,
    default: int | None = None,
) -> int | None:
    if name not in message:
        return default
    return _integer(message, name, minimum=minimum, maximum=maximum)


def _number(message: Mapping[str, object], name: str) -> float:
    value = _required(message, name)
    if type(value) not in {int, float} or not math.isfinite(value):
        _fail(f"type:{name}")
    return float(value)


def _boolean(message: Mapping[str, object], name: str) -> bool:
    value = _required(message, name)
    if type(value) is not bool:
        _fail(f"type:{name}")
    return value


def _seq(message: Mapping[str, object]) -> int:
    return _integer(message, "seq", minimum=1, maximum=MAX_SEQUENCE)


def _asset(message: Mapping[str, object], name: str) -> str:
    value = _string(message, name, max_length=32)
    if ASSET_NAME.fullmatch(value) is None:
        _fail(f"value:{name}")
    return value


def _validate_hello(message: Mapping[str, object]) -> None:
    if "seq" in message:
        _fail("unexpected:seq")
    if _integer(message, "ver", minimum=PROTOCOL_VERSION, maximum=PROTOCOL_VERSION) != PROTOCOL_VERSION:
        _fail("value:ver")
    _string(message, "fw", max_length=32)
    _string(message, "id", max_length=64)
    _string(message, "auth", max_length=MAX_AUTH_CHARS)


def _validate_err(message: Mapping[str, object]) -> None:
    if "seq" in message:
        _fail("unexpected:seq")
    _string(message, "code", allowed=frozenset({"auth", "ver"}))


def _validate_welcome(message: Mapping[str, object]) -> None:
    if "seq" in message:
        _fail("unexpected:seq")
    _integer(message, "ver", minimum=PROTOCOL_VERSION, maximum=PROTOCOL_VERSION)
    _integer(message, "epoch", minimum=0, maximum=MAX_BINARY_COUNTER)
    _string(message, "profile", allowed=PROFILES)


def _validate_intent(message: Mapping[str, object]) -> None:
    _seq(message)
    name = _string(message, "name", allowed=INTENT_NAMES)
    if name == "look":
        _integer(message, "yaw", minimum=-90, maximum=90)
        _integer(message, "pitch", minimum=-45, maximum=45)
        _optional_integer(message, "ms", minimum=100, maximum=5000, default=400)
    elif name == "walk":
        _string(message, "dir", allowed=WALK_DIRECTIONS)
        _integer(message, "steps", minimum=1, maximum=10)
    elif name == "emote":
        _asset(message, "asset")
    elif name == "face":
        _asset(message, "expr")
    elif name == "say":
        _asset(message, "asset")


def _validate_stop(message: Mapping[str, object]) -> None:
    _seq(message)


def _validate_tts(message: Mapping[str, object]) -> None:
    _seq(message)
    _string(message, "op", allowed=frozenset({"start", "end", "cancel"}))


def _validate_cam(message: Mapping[str, object]) -> None:
    _seq(message)
    _boolean(message, "on")
    _integer(message, "fps", minimum=0, maximum=15)
    _string(message, "res", allowed=CAMERA_RESOLUTIONS)


def _validate_snap(message: Mapping[str, object]) -> None:
    _seq(message)


def _validate_mic(message: Mapping[str, object]) -> None:
    _seq(message)
    _boolean(message, "on")
    _string(message, "gate", allowed=MIC_GATES)


def _validate_profile(message: Mapping[str, object]) -> None:
    _seq(message)
    _string(message, "name", allowed=PROFILES)


def _validate_state(message: Mapping[str, object]) -> None:
    _seq(message)
    name = _string(message, "name", allowed=frozenset({"idle", "doze", "sleep"}))
    if name == "sleep":
        _integer(message, "sleep_s", minimum=60, maximum=86400)


def _validate_ping_or_pong(message: Mapping[str, object]) -> None:
    if "seq" in message:
        _fail("unexpected:seq")


def _validate_mode(message: Mapping[str, object]) -> None:
    _seq(message)
    _string(message, "name", allowed=frozenset({"calibrate", "normal"}))


def _validate_servo(message: Mapping[str, object]) -> None:
    _seq(message)
    _integer(message, "id", minimum=0, maximum=7)
    _number(message, "deg")
    _integer(message, "ms", minimum=0, maximum=5000)


def _validate_limits(message: Mapping[str, object]) -> None:
    _seq(message)
    _integer(message, "id", minimum=0, maximum=7)
    minimum = _number(message, "min")
    maximum = _number(message, "max")
    center = _number(message, "center")
    _boolean(message, "invert")
    if minimum > maximum or center < minimum or center > maximum:
        _fail("range:limits")


def _validate_pose_save(message: Mapping[str, object]) -> None:
    _seq(message)
    _asset(message, "name")
    servos = _required(message, "servos")
    if not isinstance(servos, list) or not 1 <= len(servos) <= 8:
        _fail("type:servos")
    seen: set[int] = set()
    for entry in servos:
        if not isinstance(entry, list) or len(entry) != 2:
            _fail("type:servos")
        servo_id, degrees = entry
        if type(servo_id) is not int or not 0 <= servo_id <= 7:
            _fail("range:servos.id")
        if type(degrees) not in {int, float} or not math.isfinite(degrees):
            _fail("type:servos.deg")
        if servo_id in seen:
            _fail("value:servos.duplicate")
        seen.add(servo_id)


def _validate_cal_save(message: Mapping[str, object]) -> None:
    _seq(message)


def _validate_ack(message: Mapping[str, object]) -> None:
    _seq(message)
    _optional_integer(message, "sleep_s", minimum=60, maximum=86400)


def _validate_nak(message: Mapping[str, object]) -> None:
    code = _string(message, "code", allowed=NAK_CODES)
    if "seq" in message:
        _seq(message)
    elif code != "malformed":
        _fail("missing:seq")
    _optional_string(message, "msg", max_length=160)


def _validate_done(message: Mapping[str, object]) -> None:
    _seq(message)


def _validate_cancelled(message: Mapping[str, object]) -> None:
    _seq(message)
    _string(message, "code", allowed=CANCEL_CODES)


def _validate_status(message: Mapping[str, object]) -> None:
    _number(message, "vbat")
    _integer(message, "rssi", minimum=-127, maximum=0)
    _string(message, "state", allowed=BODY_STATES)
    _integer(message, "uptime", minimum=0)
    _integer(message, "heap", minimum=0)
    _boolean(message, "sd")
    _integer(message, "cam_drops", minimum=0)
    _integer(message, "spk_underruns", minimum=0)
    _integer(message, "mic_drops", minimum=0)


def _validate_event(message: Mapping[str, object]) -> None:
    _string(message, "name", allowed=EVENT_NAMES)


def _validate_cam_meta(message: Mapping[str, object]) -> None:
    _string(message, "res", allowed=CAMERA_RESOLUTIONS)
    _integer(message, "fps", minimum=0, maximum=15)
    _integer(message, "counter_base", minimum=0, maximum=MAX_BINARY_COUNTER)


VALIDATORS: dict[str, Callable[[Mapping[str, object]], None]] = {
    "hello": _validate_hello,
    "err": _validate_err,
    "welcome": _validate_welcome,
    "intent": _validate_intent,
    "stop": _validate_stop,
    "tts": _validate_tts,
    "cam": _validate_cam,
    "snap": _validate_snap,
    "mic": _validate_mic,
    "profile": _validate_profile,
    "state": _validate_state,
    "ping": _validate_ping_or_pong,
    "mode": _validate_mode,
    "servo": _validate_servo,
    "limits": _validate_limits,
    "pose_save": _validate_pose_save,
    "cal_save": _validate_cal_save,
    "ack": _validate_ack,
    "nak": _validate_nak,
    "done": _validate_done,
    "cancelled": _validate_cancelled,
    "status": _validate_status,
    "event": _validate_event,
    "cam_meta": _validate_cam_meta,
    "pong": _validate_ping_or_pong,
}


def validate_control_message(message: object) -> None:
    if not isinstance(message, Mapping):
        _fail("type:message")
    message_type = _string(message, "t", max_length=24)
    validator = VALIDATORS.get(message_type)
    if validator is None:
        _fail("value:t")
    validator(message)


def validate_binary_frame(frame: bytes) -> BinaryFrame:
    try:
        return decode_binary_frame(frame)
    except BinaryFrameError as error:
        _fail(error.reason)
