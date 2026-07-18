from __future__ import annotations

import asyncio
import json
import logging
import math
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from time import monotonic
from typing import Protocol

from protocol.control_v1 import (
    INTENT_NAMES,
    MAX_SEQUENCE,
    ProtocolValidationError,
    validate_binary_frame,
    validate_control_message,
)
from protocol.binary_helpers import (
    CAMERA_JPEG_FRAME_TYPE,
    HEADER_BYTES,
    MAX_BINARY_COUNTER,
    MIC_PCM_FRAME_TYPE,
    SPEAKER_PCM_FRAME_TYPE,
    encode_binary_frame,
)

from .calibration import CalibrationStore
from .audio import NullSpeakerSink, SpeakerSink
from .assets import AssetStore, IdleBlinkSchedule, MotionAsset
from .battery import BatteryMonitor, BatteryState, BatteryUpdate
from .core import CoreLifecycle, CoreRejection, PortableCore
from .display import DisplayController, DisplaySink
from .media import (
    AUDIO_FRAME_BYTES,
    MAX_JPEG_BYTES,
    CameraSource,
    EnergyVad,
    MediaBudget,
    MicrophoneSource,
    QueueMicrophoneSource,
)
from emulator.faults import EmulatorFaultController


EmitControl = Callable[[dict[str, object]], Awaitable[None]]
EmitBinary = Callable[[bytes], Awaitable[None]]
LOGGER = logging.getLogger(__name__)

_BODY_COMMAND_TYPES = frozenset(
    {
        "intent",
        "stop",
        "motion_plan",
        "tts",
        "cam",
        "snap",
        "mic",
        "wake",
        "profile",
        "state",
        "mode",
        "servo",
        "limits",
        "pose_save",
        "cal_save",
    }
)
_SUPPORTED_MOVEMENT = frozenset({"sit", "stand", "neutral", "walk", "emote"})
_SUPPORTED_CONTROL = frozenset(
    {"cam", "mic", "wake", "profile", "state", "mode", "servo", "limits", "pose_save", "cal_save"}
)
_REJECTION_CODES = {
    CoreRejection.STALE: "stale",
    CoreRejection.MODE: "mode",
    CoreRejection.UNSAFE: "unsafe",
    CoreRejection.LIMIT: "limit",
    CoreRejection.UNKNOWN: "unknown",
    CoreRejection.BUSY: "busy",
    CoreRejection.PROFILE: "profile",
    CoreRejection.ASSET_MISSING: "asset_missing",
    CoreRejection.MALFORMED: "malformed",
}
_STATE_NAMES = ("active", "idle", "dozing", "deep-sleep", "failsafe")
_PROFILE_NAMES = ("home", "tether")
_STOP_BACKEND_WAIT_SECONDS = 0.05
_CALIBRATION_IDLE_SECONDS = 600.0
_CORE_MODE_CALIBRATE = 1
_CORE_STATE_ACTIVE = 0
_CORE_STATE_IDLE = 1
_CORE_STATE_DOZING = 2
_ACTIVE_IDLE_SECONDS = 60.0
_SPEAKER_QUEUE_DEPTH = 25
_CALIBRATION_APPLY_INTERVAL_SECONDS = 0.05
_BATTERY_WAKE_SECONDS = 30 * 60
_MICROPHONE_PRE_ROLL_FRAMES = 5
_MICROPHONE_COOLDOWN_SECONDS = 0.8


class MotionBackend(Protocol):
    async def execute(self, message: Mapping[str, object], *, session_id: str) -> None:
        ...

    async def stop(self, sequence: int, *, session_id: str) -> None:
        ...


class BodySession:
    def __init__(
        self,
        core: PortableCore,
        motion_backend: MotionBackend,
        calibration_store: CalibrationStore | None = None,
        clock: Callable[[], float] = monotonic,
        speaker_sink: SpeakerSink | None = None,
        asset_store: AssetStore | None = None,
        display_sink: DisplaySink | None = None,
        camera_source: CameraSource | None = None,
        microphone_source: MicrophoneSource | None = None,
        idle_seed: int = 0,
        media_bytes_per_second: int = 512 * 1024,
        faults: EmulatorFaultController | None = None,
    ) -> None:
        self._core = core
        self._motion_backend = motion_backend
        self._calibration_store = calibration_store or CalibrationStore()
        self._clock = clock
        self._speaker_sink = speaker_sink or NullSpeakerSink()
        self._assets = asset_store or AssetStore()
        self._display = DisplayController(self._assets, display_sink)
        self._idle_schedule = IdleBlinkSchedule(idle_seed)
        self._display_state: int | None = None
        self._pre_idle_face = "default"
        self._idle_blink_at: float | None = None
        self._idle_restore_at: float | None = None
        self._idle_extra_blinks = 0
        self._battery = BatteryMonitor()
        self._simulated_vbat = self._battery.volts
        self._pending_battery_events: list[str] = []
        self._camera_source = camera_source
        self._microphone_source = microphone_source or QueueMicrophoneSource()
        self._vad = EnergyVad()
        self._faults = faults
        self._media_budget = MediaBudget(
            media_bytes_per_second,
            clock=self._clock,
        )
        self._epoch = 0
        self._session_id = "disconnected"
        self._started_at = monotonic()
        self._active_sequence: int | None = None
        self._active_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._camera_settings: dict[str, object] = {"on": False, "fps": 0, "res": "QVGA"}
        self._microphone_settings: dict[str, object] = {"on": True, "gate": "vad"}
        self._wake_settings: dict[str, object] = {
            "enabled": False,
            "model": "ainekio",
            "ready": False,
        }
        self._servo_positions: dict[int, float] = {}
        self._sleep_seconds: int | None = None
        self._calibration_last_activity: float | None = None
        self._last_intent_activity = self._clock()
        self._speaker_queue: asyncio.Queue[bytes] = asyncio.Queue(
            maxsize=_SPEAKER_QUEUE_DEPTH
        )
        self._speaker_task: asyncio.Task[None] | None = None
        self._speaker_in_flight = False
        self._tts_start_sequence: int | None = None
        self._tts_open = False
        self._tts_orphan_burst = False
        self._speaker_underruns = 0
        self._say_sequence: int | None = None
        self._say_task: asyncio.Task[None] | None = None
        self._camera_counter = 0
        self._microphone_counter = 0
        self._camera_drops = 0
        self._microphone_drops = 0
        self._next_camera_at = self._clock()
        self._next_microphone_at = self._clock()
        self._microphone_resume_at = self._clock()
        self._microphone_pre_roll: deque[bytes] = deque(
            maxlen=_MICROPHONE_PRE_ROLL_FRAMES
        )
        self._calibration_last_apply: dict[tuple[str, int], float] = {}
        self._calibration_pending: dict[tuple[str, int], dict[str, object]] = {}

    async def begin(self, welcome: Mapping[str, object]) -> None:
        validate_control_message(welcome)
        if welcome.get("t") != "welcome":
            raise RuntimeError("session must begin with a welcome message")

        await self._cancel_active()
        await self._cancel_say(None, code="reconnect")
        await self._reset_speaker(restart=True)
        self._tts_start_sequence = None
        self._tts_open = False
        self._tts_orphan_burst = False
        self._epoch = int(welcome["epoch"])
        self._session_id = f"protocol-v1:{self._epoch}"
        self._core.begin_session(self._epoch, str(welcome["profile"]))
        if self._battery.state == BatteryState.CUTOFF:
            for _ in range(3):
                update = self._battery.observe_constant(self._simulated_vbat)
                self._pending_battery_events.extend(update.events)
        self._core.set_power_guard(self._battery.state.value)
        self._sleep_seconds = (
            _BATTERY_WAKE_SECONDS
            if self._battery.state == BatteryState.CUTOFF
            else None
        )
        self._calibration_last_activity = None
        self._last_intent_activity = self._clock()
        self._next_camera_at = self._clock()
        self._next_microphone_at = self._clock()
        self._microphone_resume_at = self._clock()
        self._microphone_pre_roll.clear()
        self._vad.reset()
        self._calibration_last_apply.clear()
        self._calibration_pending.clear()
        self._display_state = None
        self._idle_blink_at = None
        self._idle_restore_at = None
        self._idle_extra_blinks = 0

    async def handle_raw(
        self,
        raw: str,
        emit: EmitControl,
        emit_binary: EmitBinary | None = None,
    ) -> None:
        try:
            message = json.loads(raw)
        except (json.JSONDecodeError, UnicodeError):
            await emit({"t": "nak", "code": "malformed"})
            return
        await self.handle(message, emit, emit_binary)

    async def handle(
        self,
        message: object,
        emit: EmitControl,
        emit_binary: EmitBinary | None = None,
    ) -> None:
        self._expire_calibration_mode()
        self._expire_active_state()
        try:
            validate_control_message(message)
        except ProtocolValidationError:
            await emit(_validation_nak(message))
            return

        if not isinstance(message, Mapping):
            await emit({"t": "nak", "code": "malformed"})
            return

        message_type = message.get("t")
        if message_type == "ping":
            await emit({"t": "pong"})
            return
        if message_type not in _BODY_COMMAND_TYPES:
            await emit(_validation_nak(message))
            return

        if message_type == "stop":
            await self._handle_stop(message, emit)
            return

        if message_type == "tts":
            await self._handle_tts(message, emit)
            return

        if message_type == "snap":
            await self._handle_snapshot(message, emit, emit_binary)
            return

        if message_type == "motion_plan":
            await self._handle_motion_plan(message, emit)
            return

        if message_type == "intent" and message.get("name") in _SUPPORTED_MOVEMENT:
            await self._handle_movement(message, emit)
            return

        if message_type == "intent" and message.get("name") == "face":
            await self._handle_face(message, emit)
            return

        if message_type == "intent" and message.get("name") == "say":
            await self._handle_say(message, emit)
            return

        if message_type in _SUPPORTED_CONTROL:
            await self._handle_control(message, emit)
            return

        sequence = int(message["seq"])
        rejection = self._core.claim_sequence(sequence)
        if rejection == CoreRejection.NONE:
            await emit(
                {
                    "t": "nak",
                    "seq": sequence,
                    "code": "busy",
                    "msg": "capability mapping is not defined by protocol v1",
                }
            )
        else:
            await emit(_decision_nak(sequence, rejection))

    async def handle_binary(self, raw: bytes, emit: EmitControl) -> None:
        try:
            frame = validate_binary_frame(raw)
        except ProtocolValidationError:
            return
        if not frame.known_type or frame.frame_type != SPEAKER_PCM_FRAME_TYPE:
            return
        if not self._tts_open or self._tts_start_sequence is None:
            if not self._tts_orphan_burst:
                self._tts_orphan_burst = True
                await emit({"t": "event", "name": "tts_orphan"})
            return

        buffered = self._speaker_queue.qsize() + (1 if self._speaker_in_flight else 0)
        if buffered >= _SPEAKER_QUEUE_DEPTH:
            start_sequence = self._tts_start_sequence
            self._tts_open = False
            self._tts_start_sequence = None
            await emit({"t": "event", "name": "tts_overflow"})
            await self._reset_speaker(restart=True)
            self._resume_microphone_after_speaker()
            await emit({"t": "cancelled", "seq": start_sequence, "code": "overflow"})
            return

        self._speaker_queue.put_nowait(raw[HEADER_BYTES:])

    async def _handle_tts(
        self,
        message: Mapping[str, object],
        emit: EmitControl,
    ) -> None:
        sequence = int(message["seq"])
        operation = str(message["op"])
        if operation == "start" and self._say_task is not None:
            rejection = self._core.claim_sequence(sequence)
            if rejection == CoreRejection.NONE:
                await emit({"t": "nak", "seq": sequence, "code": "busy"})
            else:
                await emit(_decision_nak(sequence, rejection))
            return
        if (operation == "start" and self._tts_start_sequence is not None) or (
            operation in {"end", "cancel"} and self._tts_start_sequence is None
        ):
            rejection = self._core.claim_sequence(sequence)
            if rejection == CoreRejection.NONE:
                await emit({"t": "nak", "seq": sequence, "code": "busy"})
            else:
                await emit(_decision_nak(sequence, rejection))
            return

        decision = self._core.accept(message)
        if not decision.accepted:
            await emit(_decision_nak(sequence, decision.rejection))
            return

        if operation == "start":
            self._tts_start_sequence = sequence
            self._tts_open = True
            self._tts_orphan_burst = False
            await self._suspend_microphone_for_speaker(emit)
            await self._display.begin_tts()
            await emit({"t": "ack", "seq": sequence})
            return

        await emit({"t": "ack", "seq": sequence})
        if operation == "cancel":
            await self._cancel_tts(emit, code="stop")
            return

        self._tts_open = False
        await self._speaker_queue.join()
        start_sequence = self._tts_start_sequence
        self._tts_start_sequence = None
        if start_sequence is not None:
            await emit({"t": "done", "seq": start_sequence})
        await self._display.end_tts()
        self._resume_microphone_after_speaker()

    async def _handle_control(
        self,
        message: Mapping[str, object],
        emit: EmitControl,
    ) -> None:
        sequence = int(message["seq"])
        if self._core.mode == _CORE_MODE_CALIBRATE and not self._targets_within_limits(message):
            rejection = self._core.claim_sequence(sequence)
            if rejection == CoreRejection.NONE:
                await emit({"t": "nak", "seq": sequence, "code": "limit"})
            else:
                await emit(_decision_nak(sequence, rejection))
            return
        if (
            message.get("t") == "mic"
            and self.profile == "tether"
            and message.get("gate") == "open"
        ):
            rejection = self._core.claim_sequence(sequence)
            if rejection == CoreRejection.NONE:
                await emit({"t": "nak", "seq": sequence, "code": "profile"})
            else:
                await emit(_decision_nak(sequence, rejection))
            return
        if (
            message.get("t") == "mic"
            and message.get("on") is True
            and message.get("gate") == "wake"
            and (
                not bool(self._wake_settings["enabled"])
                or not bool(self._wake_settings["ready"])
            )
        ):
            rejection = self._core.claim_sequence(sequence)
            if rejection == CoreRejection.NONE:
                await emit(
                    {
                        "t": "nak",
                        "seq": sequence,
                        "code": "busy",
                        "msg": "wake model unavailable",
                    }
                )
            else:
                await emit(_decision_nak(sequence, rejection))
            return
        if message.get("t") == "wake" and (
            message.get("model") != "ainekio"
            or (message.get("enabled") is True and not bool(self._wake_settings["ready"]))
        ):
            rejection = self._core.claim_sequence(sequence)
            if rejection == CoreRejection.NONE:
                await emit(
                    {
                        "t": "nak",
                        "seq": sequence,
                        "code": (
                            "asset_missing"
                            if message.get("model") != "ainekio"
                            else "busy"
                        ),
                        "msg": "wake model unavailable",
                    }
                )
            else:
                await emit(_decision_nak(sequence, rejection))
            return
        if message.get("t") == "cam":
            fps = int(message["fps"])
            resolution = str(message["res"])
            profile_violation = (
                self.profile == "home" and fps > 10
            ) or (
                self.profile == "tether" and fps != 0
            )
            if profile_violation:
                rejection = self._core.claim_sequence(sequence)
                if rejection == CoreRejection.NONE:
                    await emit({"t": "nak", "seq": sequence, "code": "profile"})
                else:
                    await emit(_decision_nak(sequence, rejection))
                return

        if message.get("t") == "mode" and message.get("name") == "normal":
            self._flush_calibration_pending(force=True)
        decision = self._core.accept(message)
        if not decision.accepted:
            await emit(_decision_nak(sequence, decision.rejection))
            return

        try:
            self._apply_control(message)
        except OSError:
            await emit(
                {
                    "t": "nak",
                    "seq": sequence,
                    "code": "busy",
                    "msg": "calibration write failed",
                }
            )
            return

        acknowledgement: dict[str, object] = {"t": "ack", "seq": sequence}
        if message.get("t") == "state" and message.get("name") == "sleep":
            acknowledgement["sleep_s"] = int(message["sleep_s"])
        await emit(acknowledgement)
        if message.get("t") == "cam":
            await emit(
                {
                    "t": "cam_meta",
                    "res": str(message["res"]),
                    "fps": int(message["fps"]),
                    "counter_base": self._camera_counter,
                }
            )

        if decision.lifecycle == CoreLifecycle.ACK_THEN_DONE:
            await emit(self.status())
            await emit({"t": "done", "seq": sequence})

    def _apply_control(self, message: Mapping[str, object]) -> None:
        message_type = message.get("t")
        if message_type == "cam":
            self._camera_settings = {
                "on": bool(message["on"]),
                "fps": int(message["fps"]),
                "res": str(message["res"]),
            }
        elif message_type == "mic":
            self._microphone_settings = {
                "on": bool(message["on"]),
                "gate": str(message["gate"]),
            }
        elif message_type == "wake":
            self._wake_settings = {
                "enabled": bool(message["enabled"]),
                "model": str(message["model"]),
                "ready": bool(self._wake_settings["ready"]),
            }
        elif message_type == "profile" and message.get("name") == "tether":
            if self._microphone_settings["gate"] == "open":
                self._microphone_settings["gate"] = "vad"
        elif message_type == "mode":
            self._calibration_last_activity = (
                self._clock() if message.get("name") == "calibrate" else None
            )
        elif message_type in {"servo", "limits"}:
            self._apply_or_coalesce_calibration(message)
        elif message_type == "pose_save":
            self._calibration_store.stage_pose(message)
        elif message_type == "cal_save":
            self._flush_calibration_pending(force=True)
            self._calibration_store.commit()
        elif message_type == "state" and message.get("name") == "sleep":
            self._sleep_seconds = int(message["sleep_s"])

        if message_type in {"servo", "limits", "pose_save", "cal_save"}:
            self._calibration_last_activity = self._clock()

    def _targets_within_limits(self, message: Mapping[str, object]) -> bool:
        if message.get("t") == "servo":
            return self._calibration_store.target_within_limits(
                int(message["id"]),
                float(message["deg"]),
            )
        if message.get("t") == "pose_save":
            return all(
                self._calibration_store.target_within_limits(
                    int(entry[0]),
                    float(entry[1]),
                )
                for entry in message["servos"]
                if isinstance(entry, list) and len(entry) == 2
            )
        return True

    def _expire_calibration_mode(self) -> None:
        if (
            self._calibration_last_activity is not None
            and self._clock() - self._calibration_last_activity >= _CALIBRATION_IDLE_SECONDS
        ):
            self._flush_calibration_pending(force=True)
            self._core.set_mode("normal")
            self._calibration_last_activity = None

    def _expire_active_state(self) -> None:
        if (
            self._core.state == _CORE_STATE_ACTIVE
            and self._clock() - self._last_intent_activity >= _ACTIVE_IDLE_SECONDS
        ):
            self._core.set_state(_CORE_STATE_IDLE)

    async def _handle_movement(
        self, message: Mapping[str, object], emit: EmitControl
    ) -> None:
        sequence = int(message["seq"])
        asset = self._motion_asset(message)
        if asset is None:
            rejection = self._core.claim_sequence(sequence)
            if rejection == CoreRejection.NONE:
                await emit({"t": "event", "name": "asset_missing"})
                await emit({"t": "nak", "seq": sequence, "code": "asset_missing"})
            else:
                await emit(_decision_nak(sequence, rejection))
            return
        if not self._assets.motion_within_limits(asset, self._calibration_store):
            rejection = self._core.claim_sequence(sequence)
            if rejection == CoreRejection.NONE:
                await emit({"t": "nak", "seq": sequence, "code": "limit"})
            else:
                await emit(_decision_nak(sequence, rejection))
            return
        async with self._lock:
            busy = self._active_task is not None
        if busy:
            rejection = self._core.claim_sequence(sequence)
            if rejection == CoreRejection.NONE:
                await emit({"t": "nak", "seq": sequence, "code": "busy"})
            else:
                await emit(_decision_nak(sequence, rejection))
            return

        decision = self._core.accept(message)
        if not decision.accepted:
            await emit(_decision_nak(sequence, decision.rejection))
            return

        self._last_intent_activity = self._clock()
        await emit({"t": "ack", "seq": sequence})
        if decision.lifecycle != CoreLifecycle.ACK_THEN_DONE:
            return

        async with self._lock:
            self._active_sequence = sequence
            self._active_task = asyncio.create_task(
                self._run_movement(sequence, self._motion_message(message, asset), emit),
                name=f"ainekio-motion-{sequence}",
            )

    async def _handle_motion_plan(
        self, message: Mapping[str, object], emit: EmitControl
    ) -> None:
        sequence = int(message["seq"])
        if not self._motion_plan_within_limits(message):
            rejection = self._core.claim_sequence(sequence)
            if rejection == CoreRejection.NONE:
                await emit({"t": "nak", "seq": sequence, "code": "limit"})
            else:
                await emit(_decision_nak(sequence, rejection))
            return

        async with self._lock:
            busy = self._active_task is not None
        if busy:
            rejection = self._core.claim_sequence(sequence)
            if rejection == CoreRejection.NONE:
                await emit({"t": "nak", "seq": sequence, "code": "busy"})
            else:
                await emit(_decision_nak(sequence, rejection))
            return

        decision = self._core.accept(message)
        if not decision.accepted:
            await emit(_decision_nak(sequence, decision.rejection))
            return

        self._last_intent_activity = self._clock()
        await emit({"t": "ack", "seq": sequence})
        if decision.lifecycle != CoreLifecycle.ACK_THEN_DONE:
            return

        prepared = self._motion_plan_message(message)
        async with self._lock:
            self._active_sequence = sequence
            self._active_task = asyncio.create_task(
                self._run_movement(sequence, prepared, emit),
                name=f"ainekio-motion-plan-{sequence}",
            )

    async def _handle_stop(
        self, message: Mapping[str, object], emit: EmitControl
    ) -> None:
        sequence = int(message["seq"])
        decision = self._core.accept(message)
        cancelled_sequence = await self._cancel_active()
        cancelled_say = await self._cancel_say(None, code="stop")
        if not decision.accepted:
            await emit(_decision_nak(sequence, decision.rejection))
            return

        stop_task = asyncio.create_task(
            self._motion_backend.stop(sequence, session_id=self._session_id),
            name=f"ainekio-stop-{sequence}",
        )
        await emit({"t": "ack", "seq": sequence})
        if cancelled_sequence is not None:
            await emit({"t": "cancelled", "seq": cancelled_sequence, "code": "stop"})
        if cancelled_say is not None:
            await emit({"t": "cancelled", "seq": cancelled_say, "code": "stop"})
        await self._cancel_tts(emit, code="stop")
        try:
            await asyncio.wait_for(stop_task, timeout=_STOP_BACKEND_WAIT_SECONDS)
        except Exception:
            # The portable core has already detached motion. Renderer transport
            # must never delay or invalidate the stop path.
            pass

    async def _run_movement(
        self,
        sequence: int,
        message: Mapping[str, object],
        emit: EmitControl,
    ) -> None:
        try:
            cues = message.get("_motion_face_cues", [])
            if isinstance(cues, list) and cues:
                first = cues[0]
                if isinstance(first, dict):
                    await self._display.set_face(str(first["name"]), str(first["mode"]))
            await self._motion_backend.execute(message, session_id=self._session_id)
        except asyncio.CancelledError:
            return
        except Exception as error:
            LOGGER.error("motion backend failed for sequence %s: %s", sequence, error)
            async with self._lock:
                if self._active_sequence == sequence:
                    self._active_sequence = None
                    self._active_task = None
            await emit({"t": "cancelled", "seq": sequence, "code": "overflow"})
            return

        async with self._lock:
            if self._active_sequence != sequence:
                return
            self._active_sequence = None
            self._active_task = None
        await emit({"t": "done", "seq": sequence})
        cues = message.get("_motion_face_cues", [])
        if isinstance(cues, list) and len(cues) > 1:
            final = cues[-1]
            if isinstance(final, dict):
                await self._display.set_face(str(final["name"]), str(final["mode"]))

    async def _handle_face(
        self,
        message: Mapping[str, object],
        emit: EmitControl,
    ) -> None:
        sequence = int(message["seq"])
        expression = str(message["expr"])
        if self._assets.face(expression) is None:
            rejection = self._core.claim_sequence(sequence)
            if rejection == CoreRejection.NONE:
                await emit({"t": "event", "name": "asset_missing"})
                await emit({"t": "nak", "seq": sequence, "code": "asset_missing"})
            else:
                await emit(_decision_nak(sequence, rejection))
            return
        decision = self._core.accept(message)
        if not decision.accepted:
            await emit(_decision_nak(sequence, decision.rejection))
            return
        self._last_intent_activity = self._clock()
        await emit({"t": "ack", "seq": sequence})
        await self._display.set_face(expression)
        await emit({"t": "done", "seq": sequence})

    async def _handle_snapshot(
        self,
        message: Mapping[str, object],
        emit: EmitControl,
        emit_binary: EmitBinary | None,
    ) -> None:
        sequence = int(message["seq"])
        if self._camera_source is None:
            rejection = self._core.claim_sequence(sequence)
            if rejection == CoreRejection.NONE:
                await emit(
                    {
                        "t": "nak",
                        "seq": sequence,
                        "code": "busy",
                        "msg": "camera unavailable",
                    }
                )
            else:
                await emit(_decision_nak(sequence, rejection))
            return
        decision = self._core.accept(message)
        if not decision.accepted:
            await emit(_decision_nak(sequence, decision.rejection))
            return
        self._last_intent_activity = self._clock()
        await emit({"t": "ack", "seq": sequence})
        if emit_binary is None:
            await emit({"t": "cancelled", "seq": sequence, "code": "overflow"})
            return
        resolution = str(self._camera_settings["res"])
        try:
            payload = await self._camera_source.capture_jpeg(resolution)
        except Exception:
            self._camera_drops += 1
            await emit({"t": "cancelled", "seq": sequence, "code": "overflow"})
            return
        if not 1 <= len(payload) <= MAX_JPEG_BYTES:
            self._camera_drops += 1
            await emit({"t": "cancelled", "seq": sequence, "code": "overflow"})
            return
        await emit(
            {
                "t": "cam_meta",
                "res": resolution,
                "fps": 0,
                "counter_base": self._camera_counter,
            }
        )
        await emit_binary(encode_binary_frame(CAMERA_JPEG_FRAME_TYPE, self._camera_counter, payload))
        self._camera_counter = (self._camera_counter + 1) & MAX_BINARY_COUNTER
        await emit({"t": "done", "seq": sequence})

    async def service_media(
        self,
        emit: EmitControl,
        emit_binary: EmitBinary,
    ) -> None:
        self._expire_active_state()
        if self._faults is not None:
            self.set_simulated_battery(self._faults.snapshot().battery_volts)
        if self._pending_battery_events:
            for event in self._pending_battery_events:
                await emit({"t": "event", "name": event})
            self._pending_battery_events.clear()
        await self._apply_battery_update(
            self._battery.observe_constant(self._simulated_vbat), emit
        )
        self._flush_calibration_pending(force=False)
        await self._service_display()
        if self._core.state not in {_CORE_STATE_ACTIVE, _CORE_STATE_DOZING}:
            return
        now = self._clock()
        microphone_allowed = self._core.state == _CORE_STATE_ACTIVE or (
            self._core.state == _CORE_STATE_DOZING
            and self._microphone_settings["gate"] in {"vad", "wake"}
        )
        if (
            microphone_allowed
            and bool(self._microphone_settings["on"])
            and self._tts_start_sequence is None
            and self._say_task is None
            and now >= self._microphone_resume_at
            and now >= self._next_microphone_at
        ):
            self._next_microphone_at = now + 0.020
            await self._stream_microphone_frame(emit, emit_binary)
        fps = int(self._camera_settings["fps"])
        if (
            self._core.state == _CORE_STATE_ACTIVE
            and self._camera_source is not None
            and bool(self._camera_settings["on"])
            and fps > 0
            and now >= self._next_camera_at
        ):
            self._next_camera_at = now + (1.0 / fps)
            await self._stream_camera_frame(emit_binary)

    async def _service_display(self) -> None:
        now = self._clock()
        state = self._core.state
        if state != self._display_state:
            leaving_idle = self._display_state == _CORE_STATE_IDLE
            self._display_state = state
            self._idle_blink_at = None
            self._idle_restore_at = None
            self._idle_extra_blinks = 0
            if state == _CORE_STATE_IDLE:
                self._pre_idle_face = self._display.current_name
                if not await self._display.set_face("idle", "boomerang", remember=False):
                    await self._display.set_face("default", remember=False)
                self._idle_blink_at = now + self._idle_schedule.next_delay_seconds()
            elif leaving_idle:
                if not await self._display.set_face(self._pre_idle_face):
                    await self._display.set_face("default")

        if state == _CORE_STATE_IDLE:
            if self._idle_restore_at is not None and now >= self._idle_restore_at:
                if not await self._display.set_face("idle", "boomerang", remember=False):
                    await self._display.set_face("default", remember=False)
                self._idle_restore_at = None
                if self._idle_extra_blinks:
                    self._idle_blink_at = (
                        now + self._idle_schedule.next_double_delay_seconds()
                    )
                else:
                    self._idle_blink_at = now + self._idle_schedule.next_delay_seconds()

            if self._idle_blink_at is not None and now >= self._idle_blink_at:
                if self._idle_extra_blinks:
                    self._idle_extra_blinks -= 1
                else:
                    self._idle_extra_blinks = (
                        self._idle_schedule.next_blink_count() - 1
                    )
                if await self._display.set_face("idle_blink", "once", remember=False):
                    duration = self._display.face_duration_seconds("idle_blink") or 0.2
                    self._idle_restore_at = now + duration
                else:
                    self._idle_restore_at = now
                self._idle_blink_at = None

        await self._display.service(now)

    async def _stream_camera_frame(self, emit_binary: EmitBinary) -> None:
        if self._camera_source is None:
            return
        try:
            if self._faults is not None and self._faults.take_oversize_camera():
                payload = bytes(MAX_JPEG_BYTES + 1)
            else:
                payload = await self._camera_source.capture_jpeg(
                    str(self._camera_settings["res"])
                )
            if not 1 <= len(payload) <= MAX_JPEG_BYTES:
                raise ValueError("camera frame is oversized")
            if not self._media_budget.allow_camera(len(payload)):
                self._camera_drops += 1
                return
            await emit_binary(
                encode_binary_frame(CAMERA_JPEG_FRAME_TYPE, self._camera_counter, payload)
            )
            self._camera_counter = (self._camera_counter + 1) & MAX_BINARY_COUNTER
        except Exception:
            self._camera_drops += 1

    async def _stream_microphone_frame(
        self,
        emit: EmitControl,
        emit_binary: EmitBinary,
    ) -> None:
        try:
            payload = await self._microphone_source.read_pcm()
            if payload is None:
                return
            if len(payload) != AUDIO_FRAME_BYTES:
                raise ValueError("microphone frame has invalid length")
            gate = str(self._microphone_settings["gate"])
            event = self._vad.process(payload)
            if event is not None:
                await emit({"t": "event", "name": event})
            outgoing: list[bytes] = []
            if gate == "open":
                outgoing.append(payload)
            elif gate == "vad" and self._vad.is_open:
                if event == "vad_open":
                    outgoing.extend(self._microphone_pre_roll)
                    self._microphone_pre_roll.clear()
                outgoing.append(payload)
            else:
                self._microphone_pre_roll.append(payload)
            for outgoing_payload in outgoing:
                self._media_budget.consume_audio(len(outgoing_payload))
                await emit_binary(
                    encode_binary_frame(
                        MIC_PCM_FRAME_TYPE,
                        self._microphone_counter,
                        outgoing_payload,
                    )
                )
                self._microphone_counter = (
                    self._microphone_counter + 1
                ) & MAX_BINARY_COUNTER
        except Exception:
            self._microphone_drops += 1

    async def _apply_battery_update(
        self,
        update: BatteryUpdate,
        emit: EmitControl,
    ) -> None:
        cutoff = "battery_cutoff" in update.events
        cancelled: list[int] = []
        if cutoff:
            active_sequence = await self._cancel_active()
            say_sequence = await self._cancel_say(None, code="stop")
            tts_sequence = self._tts_start_sequence
            await self._cancel_tts(None, code="stop")
            cancelled.extend(
                sequence
                for sequence in (active_sequence, say_sequence, tts_sequence)
                if sequence is not None
            )
            self._core.set_power_guard(BatteryState.CUTOFF.value)
            if active_sequence is not None:
                try:
                    await asyncio.wait_for(
                        self._motion_backend.stop(
                            active_sequence,
                            session_id=self._session_id,
                        ),
                        timeout=_STOP_BACKEND_WAIT_SECONDS,
                    )
                except Exception:
                    pass
            self._sleep_seconds = _BATTERY_WAKE_SECONDS
        else:
            self._core.set_power_guard(update.state.value)
            if update.state == BatteryState.NORMAL:
                self._sleep_seconds = None

        for event in update.events:
            await emit({"t": "event", "name": event})
        for sequence in cancelled:
            await emit({"t": "cancelled", "seq": sequence, "code": "stop"})
        if cutoff:
            await self._play_low_battery_asset()

    async def _play_low_battery_asset(self) -> None:
        asset = self._assets.audio("low_battery")
        if asset is None:
            return
        try:
            payload = self._assets.audio_pcm(asset)
            for offset in range(0, len(payload), 640):
                await self._play_speaker_pcm(payload[offset : offset + 640])
        except Exception:
            self._speaker_underruns += 1

    async def _handle_say(
        self,
        message: Mapping[str, object],
        emit: EmitControl,
    ) -> None:
        sequence = int(message["seq"])
        asset = self._assets.audio(str(message["asset"]))
        if self._tts_start_sequence is not None or self._say_task is not None:
            rejection = self._core.claim_sequence(sequence)
            if rejection == CoreRejection.NONE:
                await emit({"t": "nak", "seq": sequence, "code": "busy"})
            else:
                await emit(_decision_nak(sequence, rejection))
            return
        if asset is None:
            rejection = self._core.claim_sequence(sequence)
            if rejection == CoreRejection.NONE:
                await emit({"t": "event", "name": "asset_missing"})
                await emit({"t": "nak", "seq": sequence, "code": "asset_missing"})
            else:
                await emit(_decision_nak(sequence, rejection))
            return
        decision = self._core.accept(message)
        if not decision.accepted:
            await emit(_decision_nak(sequence, decision.rejection))
            return
        self._last_intent_activity = self._clock()
        await self._suspend_microphone_for_speaker(emit)
        await emit({"t": "ack", "seq": sequence})
        self._say_sequence = sequence
        self._say_task = asyncio.create_task(
            self._run_say(sequence, self._assets.audio_pcm(asset), emit),
            name=f"ainekio-say-{sequence}",
        )

    async def _run_say(
        self,
        sequence: int,
        payload: bytes,
        emit: EmitControl,
    ) -> None:
        try:
            for offset in range(0, len(payload), 640):
                await self._play_speaker_pcm(payload[offset : offset + 640])
        except asyncio.CancelledError:
            return
        except Exception:
            self._speaker_underruns += 1
            await emit({"t": "cancelled", "seq": sequence, "code": "overflow"})
        else:
            await emit({"t": "done", "seq": sequence})
        finally:
            if self._say_sequence == sequence:
                self._say_sequence = None
                self._say_task = None
                self._resume_microphone_after_speaker()

    def _motion_asset(self, message: Mapping[str, object]) -> MotionAsset | None:
        name = str(message["name"])
        if name == "emote":
            asset_name = str(message["asset"])
        elif name == "walk":
            asset_name = {
                "fwd": "walk_forward",
                "back": "walk_backward",
                "turn_l": "turn_left",
                "turn_r": "turn_right",
            }[str(message["dir"])]
        elif name == "sit":
            asset_name = "rest"
        else:
            asset_name = "stand"
        return self._assets.motion(asset_name)

    @staticmethod
    def _motion_message(
        message: Mapping[str, object],
        asset: MotionAsset,
    ) -> dict[str, object]:
        prepared = dict(message)
        prepared["_motion_asset_frames"] = asset.renderer_frames()
        prepared["_motion_face_cues"] = [
            {"frame": cue.frame, "name": cue.name, "mode": cue.mode}
            for cue in asset.face_cues
        ]
        prepared["_joint_map_version"] = asset.joint_map_version
        return prepared

    def _motion_plan_within_limits(self, message: Mapping[str, object]) -> bool:
        frames = message.get("frames")
        if not isinstance(frames, list):
            return False
        for frame in frames:
            if not isinstance(frame, list) or len(frame) != 2:
                return False
            targets = frame[1]
            if not isinstance(targets, list) or len(targets) != 8:
                return False
            for joint_id, centidegrees in enumerate(targets):
                if type(centidegrees) is not int or not self._calibration_store.logical_target_within_limits(
                    joint_id,
                    centidegrees / 100.0,
                ):
                    return False
        return True

    def _motion_plan_message(
        self, message: Mapping[str, object]
    ) -> dict[str, object]:
        prepared = dict(message)
        raw_frames = message["frames"]
        assert isinstance(raw_frames, list)
        prepared["_motion_plan_frames"] = [
            {
                "duration_ms": int(frame[0]),
                "targets": [
                    [joint_id, int(centidegrees) / 100.0]
                    for joint_id, centidegrees in enumerate(frame[1])
                ],
            }
            for frame in raw_frames
            if isinstance(frame, list)
            and len(frame) == 2
            and isinstance(frame[1], list)
        ]
        prepared["_joint_map_version"] = int(message["map"])
        return prepared

    async def enter_failsafe(self) -> None:
        self._core.enter_failsafe()
        await self._cancel_active()
        await self._cancel_say(None, code="disconnect")
        await self._cancel_tts(None, code="disconnect")

    async def close(self) -> None:
        await self._cancel_active()
        await self._cancel_say(None, code="disconnect")
        await self._reset_speaker(restart=False)
        await _close_optional(self._camera_source)
        await _close_optional(self._microphone_source)

    async def _cancel_tts(self, emit: EmitControl | None, *, code: str) -> None:
        start_sequence = self._tts_start_sequence
        self._tts_start_sequence = None
        self._tts_open = False
        await self._reset_speaker(restart=True)
        await self._display.end_tts()
        if start_sequence is not None:
            self._resume_microphone_after_speaker()
        if start_sequence is not None and emit is not None:
            await emit({"t": "cancelled", "seq": start_sequence, "code": code})

    async def _reset_speaker(self, *, restart: bool) -> None:
        task = self._speaker_task
        self._speaker_task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self._speaker_sink.stop()
        while True:
            try:
                self._speaker_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            else:
                self._speaker_queue.task_done()
        self._speaker_in_flight = False
        if restart:
            self._speaker_task = asyncio.create_task(
                self._speaker_loop(),
                name="ainekio-speaker",
            )

    async def _speaker_loop(self) -> None:
        while True:
            payload = await self._speaker_queue.get()
            self._speaker_in_flight = True
            try:
                await self._play_speaker_pcm(payload)
            except asyncio.CancelledError:
                raise
            except Exception:
                self._speaker_underruns += 1
            finally:
                self._speaker_in_flight = False
                self._speaker_queue.task_done()

    async def _play_speaker_pcm(self, payload: bytes) -> None:
        if self._faults is not None:
            delay = self._faults.snapshot().speaker_delay_ms / 1000.0
            if delay:
                await asyncio.sleep(delay)
        await self._speaker_sink.play_pcm(payload)

    async def wait_until_idle(self) -> None:
        async with self._lock:
            task = self._active_task
        tasks = [candidate for candidate in (task, self._say_task) if candidate is not None]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def status(self, *, rssi: int = -40) -> dict[str, object]:
        self._expire_calibration_mode()
        self._expire_active_state()
        state_index = self._core.state
        state = _STATE_NAMES[state_index] if 0 <= state_index < len(_STATE_NAMES) else "failsafe"
        return {
            "t": "status",
            "vbat": round(self._battery.volts, 3),
            "rssi": rssi,
            "state": state,
            "uptime": int(monotonic() - self._started_at),
            "heap": 0,
            "sd": False,
            "cam_drops": self._camera_drops,
            "spk_underruns": self._speaker_underruns,
            "mic_drops": self._microphone_drops,
            "camera_ready": self._camera_source is not None,
            "wake_enabled": bool(self._wake_settings["enabled"]),
            "wake_model": str(self._wake_settings["model"]),
            "wake_ready": bool(self._wake_settings["ready"]),
            "display_failures": self._display.failure_count,
            "face": self._display.current_name,
        }

    @property
    def profile(self) -> str:
        profile_index = self._core.profile
        if 0 <= profile_index < len(_PROFILE_NAMES):
            return _PROFILE_NAMES[profile_index]
        return "home"

    @property
    def active_sequence(self) -> int | None:
        return self._active_sequence

    @property
    def sleep_seconds(self) -> int | None:
        return self._sleep_seconds

    def take_sleep_request(self) -> int | None:
        sleep_seconds = self._sleep_seconds
        self._sleep_seconds = None
        return sleep_seconds

    def set_simulated_battery(self, volts: float) -> None:
        value = float(volts)
        if not math.isfinite(value) or not 0.0 <= value <= 20.0:
            raise ValueError("simulated battery must be finite and between 0 and 20 V")
        self._simulated_vbat = value

    @property
    def battery_state(self) -> str:
        return self._battery.state.value

    @property
    def camera_settings(self) -> dict[str, object]:
        return dict(self._camera_settings)

    @property
    def microphone_settings(self) -> dict[str, object]:
        return dict(self._microphone_settings)

    @property
    def wake_settings(self) -> dict[str, object]:
        return dict(self._wake_settings)

    @property
    def calibration(self) -> dict[str, object]:
        return self._calibration_store.snapshot()

    @property
    def servo_positions(self) -> dict[int, float]:
        return dict(self._servo_positions)

    def _apply_or_coalesce_calibration(self, message: Mapping[str, object]) -> None:
        key = (str(message["t"]), int(message["id"]))
        now = self._clock()
        last_applied = self._calibration_last_apply.get(key)
        if (
            last_applied is None
            or now - last_applied >= _CALIBRATION_APPLY_INTERVAL_SECONDS
        ):
            self._apply_calibration_message(message)
            self._calibration_last_apply[key] = now
            self._calibration_pending.pop(key, None)
            return
        self._calibration_pending[key] = dict(message)

    def _flush_calibration_pending(self, *, force: bool) -> None:
        now = self._clock()
        for key, message in tuple(self._calibration_pending.items()):
            last_applied = self._calibration_last_apply.get(key, float("-inf"))
            if not force and now - last_applied < _CALIBRATION_APPLY_INTERVAL_SECONDS:
                continue
            self._apply_calibration_message(message)
            self._calibration_last_apply[key] = now
            del self._calibration_pending[key]

    def _apply_calibration_message(self, message: Mapping[str, object]) -> None:
        if message.get("t") == "servo":
            self._servo_positions[int(message["id"])] = float(message["deg"])
        else:
            self._calibration_store.stage_limits(message)

    async def _cancel_active(self) -> int | None:
        async with self._lock:
            sequence = self._active_sequence
            task = self._active_task
            self._active_sequence = None
            self._active_task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return sequence

    async def _cancel_say(
        self,
        emit: EmitControl | None,
        *,
        code: str,
    ) -> int | None:
        sequence = self._say_sequence
        task = self._say_task
        self._say_sequence = None
        self._say_task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await self._speaker_sink.stop()
            self._resume_microphone_after_speaker()
        if sequence is not None and emit is not None:
            await emit({"t": "cancelled", "seq": sequence, "code": code})
        return sequence

    async def _suspend_microphone_for_speaker(self, emit: EmitControl) -> None:
        self._microphone_resume_at = float("inf")
        self._microphone_pre_roll.clear()
        if self._vad.reset():
            await emit({"t": "event", "name": "vad_close"})

    def _resume_microphone_after_speaker(self) -> None:
        self._microphone_resume_at = self._clock() + _MICROPHONE_COOLDOWN_SECONDS
        self._next_microphone_at = self._microphone_resume_at
        self._microphone_pre_roll.clear()


def _decision_nak(sequence: int, rejection: CoreRejection) -> dict[str, object]:
    return {
        "t": "nak",
        "seq": sequence,
        "code": _REJECTION_CODES.get(rejection, "malformed"),
    }


def _validation_nak(message: object) -> dict[str, object]:
    if isinstance(message, Mapping):
        sequence = message.get("seq")
        if (
            message.get("t") == "intent"
            and isinstance(message.get("name"), str)
            and message.get("name") not in INTENT_NAMES
            and type(sequence) is int
            and 1 <= sequence <= MAX_SEQUENCE
        ):
            return {"t": "nak", "seq": sequence, "code": "unknown"}
        if type(sequence) is int and 1 <= sequence <= MAX_SEQUENCE:
            return {"t": "nak", "seq": sequence, "code": "malformed"}
    return {"t": "nak", "code": "malformed"}


async def _close_optional(value: object) -> None:
    close = getattr(value, "close", None)
    if close is None:
        return
    result = close()
    if isinstance(result, Awaitable):
        await result
