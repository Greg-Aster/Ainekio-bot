from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Mapping


class CoreRejection(IntEnum):
    NONE = 0
    STALE = 1
    MODE = 2
    UNSAFE = 3
    LIMIT = 4
    UNKNOWN = 5
    BUSY = 6
    PROFILE = 7
    ASSET_MISSING = 8
    MALFORMED = 9


class CoreLifecycle(IntEnum):
    ACK_ONLY = 0
    ACK_THEN_DONE = 1


class _CommandKind(IntEnum):
    INTENT = 0
    STOP = 1
    MOTION_PLAN = 2
    TTS = 3
    CAMERA = 4
    SNAPSHOT = 5
    MICROPHONE = 6
    WAKE_CONFIG = 7
    PROFILE = 8
    STATE = 9
    MODE = 10
    SERVO = 11
    LIMITS = 12
    POSE_SAVE = 13
    CALIBRATION_SAVE = 14


@dataclass(frozen=True)
class CoreDecision:
    accepted: bool
    rejection: CoreRejection
    lifecycle: CoreLifecycle


_INTENTS = {
    "sit": 0,
    "stand": 1,
    "neutral": 2,
    "look": 3,
    "walk": 4,
    "emote": 5,
    "face": 6,
    "say": 7,
}
_TTS_OPERATIONS = {"start": 0, "end": 1, "cancel": 2}
_PROFILES = {"home": 0, "tether": 1}
_STATE_REQUESTS = {"idle": 0, "doze": 1, "sleep": 2}
_MODES = {"normal": 0, "calibrate": 1}
_POWER_GUARDS = {"normal": 0, "move_locked": 1, "cutoff": 2}
_POWER_GUARD_NAMES = ("normal", "move_locked", "cutoff")


def _default_library_path() -> Path:
    root = Path(__file__).resolve().parents[3]
    return root / "build" / "emulator" / "libainekio_emulator_core.so"


class PortableCore:
    def __init__(self, library_path: str | os.PathLike[str] | None = None) -> None:
        path = Path(
            library_path
            or os.environ.get("AINEKIO_EMULATOR_CORE_LIBRARY", "")
            or _default_library_path()
        )
        if not path.is_file():
            raise RuntimeError(
                f"portable core library not found at {path}; "
                "run: cmake -S Emulator/emulator -B build/emulator "
                "&& cmake --build build/emulator"
            )

        self._library = ctypes.CDLL(str(path))
        self._configure_abi()
        self._handle = self._library.ainekio_emulator_core_create()
        if not self._handle:
            raise RuntimeError("portable core allocation failed")

    def _configure_abi(self) -> None:
        library = self._library
        library.ainekio_emulator_core_create.argtypes = []
        library.ainekio_emulator_core_create.restype = ctypes.c_void_p
        library.ainekio_emulator_core_destroy.argtypes = [ctypes.c_void_p]
        library.ainekio_emulator_core_destroy.restype = None
        library.ainekio_emulator_core_begin_session.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_int,
        ]
        library.ainekio_emulator_core_begin_session.restype = None
        library.ainekio_emulator_core_enter_failsafe.argtypes = [ctypes.c_void_p]
        library.ainekio_emulator_core_enter_failsafe.restype = None
        library.ainekio_emulator_core_set_mode.argtypes = [ctypes.c_void_p, ctypes.c_int]
        library.ainekio_emulator_core_set_mode.restype = None
        library.ainekio_emulator_core_set_state.argtypes = [ctypes.c_void_p, ctypes.c_int]
        library.ainekio_emulator_core_set_state.restype = None
        library.ainekio_emulator_core_set_power_guard.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        library.ainekio_emulator_core_set_power_guard.restype = None
        library.ainekio_emulator_core_claim_sequence.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        library.ainekio_emulator_core_claim_sequence.restype = ctypes.c_int
        library.ainekio_emulator_core_accept.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
        ]
        library.ainekio_emulator_core_accept.restype = ctypes.c_int
        library.ainekio_emulator_core_state.argtypes = [ctypes.c_void_p]
        library.ainekio_emulator_core_state.restype = ctypes.c_int
        library.ainekio_emulator_core_profile.argtypes = [ctypes.c_void_p]
        library.ainekio_emulator_core_profile.restype = ctypes.c_int
        library.ainekio_emulator_core_mode.argtypes = [ctypes.c_void_p]
        library.ainekio_emulator_core_mode.restype = ctypes.c_int
        library.ainekio_emulator_core_servos_attached.argtypes = [ctypes.c_void_p]
        library.ainekio_emulator_core_servos_attached.restype = ctypes.c_int
        library.ainekio_emulator_core_power_guard.argtypes = [ctypes.c_void_p]
        library.ainekio_emulator_core_power_guard.restype = ctypes.c_int

    def close(self) -> None:
        if self._handle:
            self._library.ainekio_emulator_core_destroy(self._handle)
            self._handle = None

    def __enter__(self) -> "PortableCore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def begin_session(self, epoch: int, profile: str = "home") -> None:
        self._library.ainekio_emulator_core_begin_session(
            self._require_handle(), epoch, _PROFILES[profile]
        )

    def enter_failsafe(self) -> None:
        self._library.ainekio_emulator_core_enter_failsafe(self._require_handle())

    def set_mode(self, mode: str) -> None:
        self._library.ainekio_emulator_core_set_mode(
            self._require_handle(),
            _MODES[mode],
        )

    def set_state(self, state: int) -> None:
        self._library.ainekio_emulator_core_set_state(self._require_handle(), state)

    def set_power_guard(self, guard: str) -> None:
        self._library.ainekio_emulator_core_set_power_guard(
            self._require_handle(), _POWER_GUARDS[guard]
        )

    def claim_sequence(self, sequence: int) -> CoreRejection:
        rejection = self._library.ainekio_emulator_core_claim_sequence(
            self._require_handle(), sequence
        )
        return CoreRejection(rejection)

    def accept(self, message: Mapping[str, object]) -> CoreDecision:
        sequence = message.get("seq")
        if type(sequence) is not int:
            return CoreDecision(False, CoreRejection.MALFORMED, CoreLifecycle.ACK_ONLY)

        command_kind, command_value = _normalize_command(message)
        rejection = ctypes.c_int(CoreRejection.NONE)
        lifecycle = ctypes.c_int(CoreLifecycle.ACK_ONLY)
        accepted = self._library.ainekio_emulator_core_accept(
            self._require_handle(),
            sequence,
            int(command_kind),
            command_value,
            ctypes.byref(rejection),
            ctypes.byref(lifecycle),
        )
        return CoreDecision(
            bool(accepted),
            CoreRejection(rejection.value),
            CoreLifecycle(lifecycle.value),
        )

    @property
    def state(self) -> int:
        return int(self._library.ainekio_emulator_core_state(self._require_handle()))

    @property
    def profile(self) -> int:
        return int(self._library.ainekio_emulator_core_profile(self._require_handle()))

    @property
    def mode(self) -> int:
        return int(self._library.ainekio_emulator_core_mode(self._require_handle()))

    @property
    def servos_attached(self) -> bool:
        return bool(
            self._library.ainekio_emulator_core_servos_attached(self._require_handle())
        )

    @property
    def power_guard(self) -> str:
        index = int(
            self._library.ainekio_emulator_core_power_guard(self._require_handle())
        )
        return _POWER_GUARD_NAMES[index]

    def _require_handle(self) -> ctypes.c_void_p:
        if not self._handle:
            raise RuntimeError("portable core is closed")
        return self._handle


def _normalize_command(message: Mapping[str, object]) -> tuple[_CommandKind, int]:
    message_type = message.get("t")
    if message_type == "intent":
        return _CommandKind.INTENT, _INTENTS[str(message["name"])]
    if message_type == "stop":
        return _CommandKind.STOP, 0
    if message_type == "motion_plan":
        return _CommandKind.MOTION_PLAN, 0
    if message_type == "tts":
        return _CommandKind.TTS, _TTS_OPERATIONS[str(message["op"])]
    if message_type == "cam":
        return _CommandKind.CAMERA, 0
    if message_type == "snap":
        return _CommandKind.SNAPSHOT, 0
    if message_type == "mic":
        return _CommandKind.MICROPHONE, 0
    if message_type == "wake":
        return _CommandKind.WAKE_CONFIG, 0
    if message_type == "profile":
        return _CommandKind.PROFILE, _PROFILES[str(message["name"])]
    if message_type == "state":
        return _CommandKind.STATE, _STATE_REQUESTS[str(message["name"])]
    if message_type == "mode":
        return _CommandKind.MODE, _MODES[str(message["name"])]
    if message_type == "servo":
        return _CommandKind.SERVO, 0
    if message_type == "limits":
        return _CommandKind.LIMITS, 0
    if message_type == "pose_save":
        return _CommandKind.POSE_SAVE, 0
    if message_type == "cal_save":
        return _CommandKind.CALIBRATION_SAVE, 0
    raise ValueError(f"message type {message_type!r} is not a body command")
