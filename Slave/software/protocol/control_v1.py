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
MAX_FEATURES = 16
MAX_FEATURE_CHARS = 32
MOTION_PLAN_FEATURE = "motion_plan_v1"
COMMAND_DEADLINE_FEATURE = "command_deadline_v1"
CAMERA_PROFILES_FEATURE = "camera_profiles_v1"
BODY_CALIBRATION_FEATURE = "body_calibration_v2"
MAX_CALIBRATION_PULSE_US = (1 << 16) - 1  # Wire representation, not a servo travel limit.
ROBOT_SETTINGS_FEATURE = "robot_settings_v1"
STORAGE_CONTROL_FEATURE = "storage_control_v1"
MOTION_SPEED_FEATURE = "motion_speed_v1"
JOINT_SPEED_LIMIT_FEATURE = "joint_speed_limit_v1"
BODY_CAPABILITIES_FEATURE = "body_capabilities_v1"
BODY_COMMANDS_FEATURE = "body_commands_v1"
WALK_CONTROLS_FEATURE = "walk_controls_v1"
LOCOMOTION_FEATURE = "walk_controls_v2"
WALK_STEERING_FEATURE = "walk_steering_v1"
RUN_GAIT_FEATURE = "run_gait_v1"
CRAB_GAIT_FEATURE = "crab_gait_v1"
MAX_MONOTONIC_MS = (1 << 53) - 1
MOTION_PLAN_JOINT_MAP = 1
MOTION_PLAN_JOINTS = 8
MOTION_PLAN_MAX_FRAMES = 32
MOTION_PLAN_MIN_FRAME_MS = 100
MOTION_PLAN_MAX_FRAME_MS = 5000
MOTION_PLAN_MAX_TOTAL_MS = 10000
MOTION_PLAN_MAX_CENTIDEGREES = 18000

ASSET_NAME = re.compile(r"[a-z0-9_]{1,32}\Z")
FEATURE_NAME = re.compile(r"[a-z0-9_]{1,32}\Z")

INTENT_NAMES = frozenset(
    {"sit", "stand", "neutral", "look", "walk", "emote", "face", "say"}
)
WALK_DIRECTIONS = frozenset({"fwd", "back", "turn_l", "turn_r", "side_l", "side_r"})
PROFILES = frozenset({"home", "tether"})
CAMERA_RESOLUTIONS = frozenset({"QVGA", "VGA", "XGA"})
CAMERA_STREAM_RESOLUTIONS = frozenset({"QVGA", "VGA"})
CAMERA_ORIGINS = frozenset({"request", "action", "audio"})
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


def _validate_capabilities(caps: object) -> None:
    if not isinstance(caps, Mapping):
        _fail("type:capabilities")
    for name in ("motion", "speaker", "microphone", "camera"):
        _boolean(caps, name)
    for name in ("profile", "power", "storage", "display", "wake", "calibration"):
        if name in caps:
            _boolean(caps, name)
    if "reasons" in caps:
        reasons = caps["reasons"]
        if not isinstance(reasons, Mapping) or len(reasons) > 16:
            _fail("type:capabilities.reasons")
        for name, reason in reasons.items():
            if not isinstance(name, str) or len(name) > 32 or not isinstance(reason, str) or len(reason) > 160:
                _fail("value:capabilities.reasons")
    if "commands" in caps:
        _validate_body_commands(caps["commands"])


def _validate_body_commands(commands: object) -> None:
    if not isinstance(commands, list) or len(commands) > 64:
        _fail("type:capabilities.commands")
    if any(not isinstance(name, str) or not name or len(name) > 32 for name in commands):
        _fail("value:capabilities.commands")
    if len(set(commands)) != len(commands):
        _fail("value:capabilities.commands.duplicate")


def _validate_hello(message: Mapping[str, object]) -> None:
    if "seq" in message:
        _fail("unexpected:seq")
    if _integer(message, "ver", minimum=PROTOCOL_VERSION, maximum=PROTOCOL_VERSION) != PROTOCOL_VERSION:
        _fail("value:ver")
    _string(message, "fw", max_length=32)
    _string(message, "id", max_length=64)
    _string(message, "auth", max_length=MAX_AUTH_CHARS)
    if "features" in message:
        features = message["features"]
        if not isinstance(features, list):
            _fail("type:features")
        if len(features) > MAX_FEATURES:
            _fail("range:features")
        seen: set[str] = set()
        for feature in features:
            if not isinstance(feature, str):
                _fail("type:features")
            if len(feature) > MAX_FEATURE_CHARS or FEATURE_NAME.fullmatch(feature) is None:
                _fail("value:features")
            if feature in seen:
                _fail("value:features.duplicate")
            seen.add(feature)
    if COMMAND_DEADLINE_FEATURE in message.get("features", []):
        _integer(message, "clock_ms", minimum=0, maximum=MAX_MONOTONIC_MS)
    if BODY_CAPABILITIES_FEATURE in message.get("features", []):
        _string(message, "model", max_length=32)
        _validate_capabilities(_required(message, "capabilities"))
    if BODY_COMMANDS_FEATURE in message.get("features", []):
        if BODY_CAPABILITIES_FEATURE not in message.get("features", []):
            _fail("missing:body_capabilities_v1")
        _validate_body_commands(message["capabilities"].get("commands"))


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
    if COMMAND_DEADLINE_FEATURE in message:
        _boolean(message, COMMAND_DEADLINE_FEATURE)


def validate_walk_controls(message: Mapping[str, object]) -> None:
    """A negotiated extension: speed percent OR stride percent and rate multiplier."""
    auto = "speed" in message
    manual = "stride" in message or "rate" in message
    if auto and manual:
        _fail("value:walk.controls.mixed")
    if manual and not ("stride" in message and "rate" in message):
        _fail("value:walk.controls.incomplete")
    if any(k in message for k in ("speed_percent", "stride_percent", "motion_rate")):
        _fail("value:walk.controls.use_speed_stride_rate")
    for name, lo, hi in (("speed", 0, 100 if message.get("gait") in {"crawl", "crab"} else 200), ("stride", 1, 100), ("rate", .25, 3)):
        if name in message:
            value = message[name]
            if type(value) not in (int, float) or not math.isfinite(value):
                _fail("type:walk." + name)
            if not lo <= value <= hi:
                _fail("range:walk." + name)
    if "forward" in message or "turn" in message:
        for name in ("forward", "turn"):
            value = message.get(name)
            if type(value) not in (int, float) or not math.isfinite(value):
                _fail("type:walk." + name)
            if not -100 <= value <= 100:
                _fail("range:walk." + name)
    if "gait" in message:
        _string(message, "gait", allowed=frozenset({"walk", "crawl", "run", "crab"}))
    if message.get("dir") in {"side_l", "side_r"} and message.get("gait") != "crab":
        _fail("value:walk.direction.gait")
    if "update" in message:
        _integer(message, "update", minimum=1, maximum=MAX_SEQUENCE)
        if not (auto or manual):
            _fail("value:walk.update.controls_required")


def _validate_intent(message: Mapping[str, object]) -> None:
    _seq(message)
    name = _string(message, "name", allowed=INTENT_NAMES)
    if "playback_rate" in message:
        if name not in {"sit", "stand", "emote"}:
            _fail("value:playback_rate.named_motion_required")
        _motion_rate(message, "playback_rate")
    if name == "look":
        _integer(message, "yaw", minimum=-90, maximum=90)
        _integer(message, "pitch", minimum=-45, maximum=45)
        _optional_integer(message, "ms", minimum=100, maximum=5000, default=400)
    elif name == "walk":
        _string(message, "dir", allowed=WALK_DIRECTIONS)
        _integer(message, "steps", minimum=0, maximum=10)
        validate_walk_controls(message)
    elif name == "emote":
        _asset(message, "asset")
    elif name == "face":
        _asset(message, "expr")
    elif name == "say":
        _asset(message, "asset")


def _validate_stop(message: Mapping[str, object]) -> None:
    _seq(message)
    if "detach" in message:
        _boolean(message, "detach")


def _validate_motion_plan(message: Mapping[str, object]) -> None:
    _seq(message)
    _integer(
        message,
        "map",
        minimum=MOTION_PLAN_JOINT_MAP,
        maximum=MOTION_PLAN_JOINT_MAP,
    )
    frames = _required(message, "frames")
    if not isinstance(frames, list):
        _fail("type:frames")
    if not 1 <= len(frames) <= MOTION_PLAN_MAX_FRAMES:
        _fail("range:frames")
    total_duration_ms = 0
    for frame in frames:
        if not isinstance(frame, list) or len(frame) != 2:
            _fail("type:frames.frame")
        duration_ms, targets = frame
        if type(duration_ms) is not int:
            _fail("type:frames.duration")
        if not MOTION_PLAN_MIN_FRAME_MS <= duration_ms <= MOTION_PLAN_MAX_FRAME_MS:
            _fail("range:frames.duration")
        total_duration_ms += duration_ms
        if total_duration_ms > MOTION_PLAN_MAX_TOTAL_MS:
            _fail("range:frames.total_duration")
        if not isinstance(targets, list) or len(targets) != MOTION_PLAN_JOINTS:
            _fail("range:frames.targets")
        for target in targets:
            if type(target) is not int:
                _fail("type:frames.target")
            if not 0 <= target <= MOTION_PLAN_MAX_CENTIDEGREES:
                _fail("range:frames.target")
    _string(message, "end", allowed=frozenset({"hold", "stand", "neutral"}))


def _validate_tts(message: Mapping[str, object]) -> None:
    _seq(message)
    _string(message, "op", allowed=frozenset({"start", "end", "cancel"}))


def _validate_cam(message: Mapping[str, object]) -> None:
    _seq(message)
    _boolean(message, "on")
    _integer(message, "fps", minimum=0, maximum=15)
    _string(message, "res", allowed=CAMERA_STREAM_RESOLUTIONS)
    if "snapshot_res" in message:
        _string(message, "snapshot_res", allowed=CAMERA_RESOLUTIONS)


def _validate_snap(message: Mapping[str, object]) -> None:
    _seq(message)


def _validate_mic(message: Mapping[str, object]) -> None:
    _seq(message)
    _boolean(message, "on")
    _string(message, "gate", allowed=MIC_GATES)


def _validate_wake(message: Mapping[str, object]) -> None:
    _seq(message)
    _boolean(message, "enabled")
    _asset(message, "model")


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
    _optional_integer(message, "clock_ms", minimum=0, maximum=MAX_MONOTONIC_MS)


def _calibration_joint(message: Mapping[str, object]) -> None:
    _integer(message, "id", minimum=0, maximum=11)
    _integer(message, "channel", minimum=-1, maximum=11)
    _integer(message, "home_us", minimum=1, maximum=MAX_CALIBRATION_PULSE_US)
    _boolean(message, "invert")
    if ("home_cd" in message) != ("us_per_degree" in message):
        _fail("missing:us_per_degree" if "home_cd" in message else "missing:home_cd")
    if "home_cd" in message:
        _integer(message, "home_cd", minimum=-36000, maximum=36000)
        scale = _number(message, "us_per_degree")
        if not 0 < scale <= 100:
            _fail("range:us_per_degree")


def _validate_calibration(message: Mapping[str, object]) -> None:
    _seq(message)
    operation = _string(message, "op", allowed=frozenset({"get", "set", "move", "home", "save"}))
    if operation != "set" and ("home_cd" in message or "us_per_degree" in message):
        _fail("unexpected:calibration.mapping")
    if operation == "set":
        _calibration_joint(message)
    elif operation == "move":
        _integer(message, "id", minimum=0, maximum=11)
        _integer(message, "pulse_us", minimum=1, maximum=MAX_CALIBRATION_PULSE_US)
    elif operation == "home":
        _optional_integer(message, "id", minimum=0, maximum=11)
    elif "id" in message:
        _fail("unexpected:id")


def _validate_calibration_status(message: Mapping[str, object]) -> None:
    _seq(message)
    dirty, saved = _boolean(message, "dirty"), _boolean(message, "saved")
    if dirty and saved:
        _fail("value:calibration.saved")
    _boolean(message, "ready")
    _optional_string(message, "reason", max_length=160)
    if ("pulse_min_us" in message) != ("pulse_max_us" in message):
        _fail("missing:pulse_max_us" if "pulse_min_us" in message else "missing:pulse_min_us")
    if "pulse_min_us" in message:
        minimum = _integer(message, "pulse_min_us", minimum=1, maximum=MAX_CALIBRATION_PULSE_US)
        maximum = _integer(message, "pulse_max_us", minimum=1, maximum=MAX_CALIBRATION_PULSE_US)
        if minimum > maximum:
            _fail("range:calibration.pulse_bounds")
    for flag in ("profile_confirmed", "shaft_travel_measured"):
        if flag in message:
            _boolean(message, flag)
    _optional_string(message, "servo_profile_id", max_length=96)
    _optional_integer(message, "recommended_reference_us", minimum=1, maximum=MAX_CALIBRATION_PULSE_US)
    if "provisional_us_per_degree" in message:
        value = _number(message, "provisional_us_per_degree")
        if not 0 < value <= 100:
            _fail("range:provisional_us_per_degree")
    joints = _required(message, "joints")
    if not isinstance(joints, list) or len(joints) != 12:
        _fail("range:calibration.joints")
    seen_ids: set[int] = set()
    channels: set[int] = set()
    for joint in joints:
        if not isinstance(joint, Mapping):
            _fail("type:calibration.joint")
        _calibration_joint(joint)
        if "recommended_home_cd" in joint:
            _integer(joint, "recommended_home_cd", minimum=-36000, maximum=36000)
        _integer(joint, "pulse_us", minimum=0, maximum=MAX_CALIBRATION_PULSE_US)
        if joint["id"] in seen_ids or (joint["channel"] >= 0 and joint["channel"] in channels):
            _fail("value:calibration.duplicate")
        seen_ids.add(joint["id"])
        channels.add(joint["channel"])


def _motion_rate(message: Mapping[str, object], key: str = "rate") -> None:
    if _number(message, key) <= 0:
        _fail("range:" + key)


def _validate_motion_speed(message: Mapping[str, object]) -> None:
    _seq(message)
    operation = _string(message, "op", allowed=frozenset({"get", "save"}))
    fields = {"rate", "joint_speed_limit_deg_s"}.intersection(message)
    if operation == "save":
        if len(fields) != 1:
            _fail("save requires one speed setting")
        _motion_rate(message, next(iter(fields)))
    elif fields:
        _fail("unexpected speed setting")


def _validate_motion_speed_status(message: Mapping[str, object]) -> None:
    _seq(message)
    _motion_rate(message)
    _boolean(message, "saved")
    if "joint_speed_limit_deg_s" in message:
        _motion_rate(message, "joint_speed_limit_deg_s")
        _boolean(message, "joint_speed_limit_saved")


def _settings_text(message: Mapping[str, object], name: str, maximum: int, minimum: int = 0) -> str:
    value = _string(message, name, min_length=minimum, max_length=maximum)
    if "\x00" in value or len(value.encode("utf-8")) > maximum:
        _fail(f"range:{name}")
    return value


def _wifi_password(value: str, *, raw_key: bool = False) -> None:
    if not value:
        return
    if raw_key and len(value) == 64 and all(c in "0123456789abcdefABCDEF" for c in value):
        return
    if not (8 <= len(value) <= 63 and all(32 <= ord(c) <= 126 for c in value)):
        _fail("Wi-Fi requires 8–63 ASCII characters, a 64-digit hex key, or an empty password for an open network")


def _settings_endpoint(message: Mapping[str, object]) -> None:
    endpoint = _settings_text(message, "endpoint", 255, 1)
    if not re.fullmatch(r"wss?://[^/@?#\s]+/robot", endpoint):
        _fail("endpoint must be ws://host:port/robot or wss://host/robot")


def _validate_robot_settings(message: Mapping[str, object]) -> None:
    _seq(message)
    op = _string(message, "op", allowed=frozenset({"get", "network", "remove", "security", "apply"}))
    allowed = {"t", "seq", "epoch", "deadline_ms", "op"}
    if op != "get":
        allowed.add("revision")
        _integer(message, "revision", minimum=0, maximum=2**32-1)
    if op in {"network", "remove"}:
        allowed.add("index")
        _integer(message, "index", minimum=0, maximum=3)
    if op == "network":
        allowed.update({"ssid", "endpoint", "wifi_password"})
        _settings_text(message, "ssid", 32, 1)
        _settings_endpoint(message)
        if "wifi_password" in message:
            _wifi_password(_settings_text(message, "wifi_password", 64), raw_key=True)
    if op == "security":
        allowed.update({"robot_token", "setup_password"})
        if not {"robot_token", "setup_password"} & message.keys():
            _fail("select a credential to change")
        if "robot_token" in message:
            _settings_text(message, "robot_token", 128, 1)
        if "setup_password" in message:
            _wifi_password(_settings_text(message, "setup_password", 63))
    if set(message) - allowed:
        _fail("unexpected robot settings fields")


def _validate_robot_settings_status(message: Mapping[str, object]) -> None:
    _seq(message)
    _integer(message, "revision", minimum=0, maximum=2**32-1)
    _integer(message, "active_index", minimum=-1, maximum=3)
    _boolean(message, "pending_restart")
    _boolean(message, "setup_open")
    networks = message.get("networks")
    if not isinstance(networks, list) or len(networks) > 4:
        _fail("invalid networks")
    indices = set()
    for profile in networks:
        if not isinstance(profile, dict) or set(profile) != {"index", "ssid", "endpoint", "open"}:
            _fail("invalid network profile")
        index = _integer(profile, "index", minimum=0, maximum=3)
        if index in indices:
            _fail("duplicate network slot")
        indices.add(index)
        _settings_text(profile, "ssid", 32, 1)
        _settings_endpoint(profile)
        _boolean(profile, "open")
    if set(message) != {"t", "seq", "revision", "active_index", "pending_restart", "setup_open", "networks"}:
        _fail("unexpected settings readback fields")


def _validate_storage(message: Mapping[str, object]) -> None:
    _seq(message)
    _string(message, "op", allowed=frozenset({"get", "retry", "clear"}))


def _validate_storage_status(message: Mapping[str, object]) -> None:
    _seq(message)
    _boolean(message, "available")
    _boolean(message, "mounted")
    _boolean(message, "busy")
    total = _integer(message, "total_bytes", minimum=0, maximum=MAX_MONOTONIC_MS)
    _integer(message, "free_bytes", minimum=0, maximum=total)
    _integer(message, "dropped_records", minimum=0, maximum=MAX_MONOTONIC_MS)
    _string(message, "error", min_length=0, max_length=160)


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
    if "capabilities" in message:
        _validate_capabilities(message["capabilities"])
    _number(message, "vbat")
    _integer(message, "rssi", minimum=-127, maximum=0)
    _string(message, "state", allowed=BODY_STATES)
    _integer(message, "uptime", minimum=0)
    _integer(message, "heap", minimum=0)
    _boolean(message, "sd")
    if "camera_ready" in message:
        _boolean(message, "camera_ready")
    _integer(message, "cam_drops", minimum=0)
    _integer(message, "spk_underruns", minimum=0)
    _integer(message, "mic_drops", minimum=0)
    if "wake_enabled" in message:
        _boolean(message, "wake_enabled")
    if "wake_model" in message:
        _asset(message, "wake_model")
    if "wake_ready" in message:
        _boolean(message, "wake_ready")
    if "mode" in message:
        _string(message, "mode", allowed=frozenset({"normal", "calibrate"}))
    for field in ("output_ready", "output_armed", "calibration_dirty", "calibration_saved",
                  "power_monitor_ready", "microphone_ready", "speaker_ready", "display_ready"):
        if field in message:
            _boolean(message, field)
    _optional_integer(message, "output_fault", minimum=0, maximum=255)


def _validate_event(message: Mapping[str, object]) -> None:
    name = _string(message, "name", allowed=EVENT_NAMES)
    if "origin_id" in message:
        if name not in {"vad_open", "vad_close"}:
            _fail("unexpected:origin_id")
        _integer(message, "origin_id", minimum=0, maximum=MAX_BINARY_COUNTER)


def _validate_cam_meta(message: Mapping[str, object]) -> None:
    _string(message, "res", allowed=CAMERA_RESOLUTIONS)
    _integer(message, "fps", minimum=0, maximum=15)
    _integer(message, "counter_base", minimum=0, maximum=MAX_BINARY_COUNTER)
    has_origin = "origin" in message
    has_origin_id = "origin_id" in message
    if has_origin != has_origin_id:
        _fail("missing:camera_origin_pair")
    if has_origin:
        origin = _string(message, "origin", allowed=CAMERA_ORIGINS)
        minimum = 0 if origin == "audio" else 1
        maximum = MAX_BINARY_COUNTER if origin == "audio" else MAX_SEQUENCE
        _integer(message, "origin_id", minimum=minimum, maximum=maximum)


VALIDATORS: dict[str, Callable[[Mapping[str, object]], None]] = {
    "hello": _validate_hello,
    "err": _validate_err,
    "welcome": _validate_welcome,
    "intent": _validate_intent,
    "stop": _validate_stop,
    "motion_plan": _validate_motion_plan,
    "tts": _validate_tts,
    "cam": _validate_cam,
    "snap": _validate_snap,
    "mic": _validate_mic,
    "wake": _validate_wake,
    "profile": _validate_profile,
    "state": _validate_state,
    "ping": _validate_ping_or_pong,
    "mode": _validate_mode,
    "servo": _validate_servo,
    "limits": _validate_limits,
    "pose_save": _validate_pose_save,
    "cal_save": _validate_cal_save,
    "calibration": _validate_calibration,
    "calibration_status": _validate_calibration_status,
    "motion_speed": _validate_motion_speed,
    "motion_speed_status": _validate_motion_speed_status,
    "robot_settings": _validate_robot_settings,
    "robot_settings_status": _validate_robot_settings_status,
    "storage": _validate_storage,
    "storage_status": _validate_storage_status,
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
    if "playback_rate" in message and message_type != "intent":
        _fail("value:playback_rate.named_motion_required")
    validator(message)
    # Negotiated extensions are also typed when present on an older message.
    _optional_integer(message, "epoch", minimum=0, maximum=MAX_BINARY_COUNTER)
    _optional_integer(message, "deadline_ms", minimum=0, maximum=MAX_MONOTONIC_MS)


def validate_binary_frame(frame: bytes) -> BinaryFrame:
    try:
        return decode_binary_frame(frame)
    except BinaryFrameError as error:
        _fail(error.reason)
