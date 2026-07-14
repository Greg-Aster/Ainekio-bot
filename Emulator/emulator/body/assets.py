from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path

from protocol.joints_v1 import JOINT_COUNT, JOINT_MAP_VERSION, validate_joint_contract

from .calibration import CalibrationStore


MAX_MANIFEST_BYTES = 512 * 1024
MAX_MOTION_FRAMES = 256
MAX_FACE_FRAMES = 6
FACE_FRAME_BYTES = 128 * 64 // 8


class AssetError(RuntimeError):
    pass


@dataclass(frozen=True)
class MotionFrame:
    duration_ms: int
    targets: tuple[tuple[int, float], ...]


@dataclass(frozen=True)
class FaceCue:
    frame: int
    name: str
    mode: str


@dataclass(frozen=True)
class MotionAsset:
    name: str
    joint_map_version: int
    repeat_count: int
    return_pose: str | None
    face_cues: tuple[FaceCue, ...]
    frames: tuple[MotionFrame, ...]

    def renderer_frames(self) -> list[dict[str, object]]:
        return [
            {
                "duration_ms": frame.duration_ms,
                "targets": [[joint_id, degrees] for joint_id, degrees in frame.targets],
            }
            for frame in self.frames
        ]


@dataclass(frozen=True)
class FaceAsset:
    name: str
    fps: int
    mode: str
    frame_paths: tuple[Path, ...]


@dataclass(frozen=True)
class AudioAsset:
    name: str
    path: Path
    samples: int


class AssetStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else _default_asset_root()
        self._motions = self._load_motions()
        self._faces = self._load_faces()
        self._audio = self._load_audio()

    def motion(self, name: str) -> MotionAsset | None:
        return self._motions.get(name)

    def face(self, name: str) -> FaceAsset | None:
        return self._faces.get(name)

    def face_frame(self, asset: FaceAsset, index: int) -> bytes:
        if not 0 <= index < len(asset.frame_paths):
            raise AssetError("face frame index is out of range")
        payload = asset.frame_paths[index].read_bytes()
        if len(payload) != FACE_FRAME_BYTES:
            raise AssetError("face frame has an invalid size")
        return payload

    def audio(self, name: str) -> AudioAsset | None:
        return self._audio.get(name)

    def audio_pcm(self, asset: AudioAsset) -> bytes:
        payload = asset.path.read_bytes()
        if len(payload) != asset.samples * 2 or len(payload) > 2 * 16000 * 30:
            raise AssetError("audio asset has an invalid size")
        return payload

    def motion_within_limits(
        self,
        asset: MotionAsset,
        calibration: CalibrationStore,
    ) -> bool:
        return all(
            calibration.logical_target_within_limits(joint_id, degrees)
            for frame in asset.frames
            for joint_id, degrees in frame.targets
        )

    @property
    def motion_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._motions))

    @property
    def face_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._faces))

    def _load_motions(self) -> dict[str, MotionAsset]:
        value = _read_manifest(self.root / "motions-v1.json")
        if value.get("schema_version") != 1:
            raise AssetError("motion manifest schema mismatch")
        try:
            validate_joint_contract(value.get("joint_map"))
        except ValueError as exc:
            raise AssetError(str(exc)) from exc
        raw_assets = value.get("assets")
        if not isinstance(raw_assets, list) or not raw_assets:
            raise AssetError("motion manifest has no assets")
        result: dict[str, MotionAsset] = {}
        for raw_asset in raw_assets:
            asset = _parse_motion(raw_asset)
            if asset.name in result:
                raise AssetError(f"duplicate motion asset {asset.name!r}")
            result[asset.name] = asset
        return result

    def _load_faces(self) -> dict[str, FaceAsset]:
        value = _read_manifest(self.root / "faces-v1.json")
        if value.get("schema_version") != 1:
            raise AssetError("face manifest schema mismatch")
        raw_faces = value.get("faces")
        if not isinstance(raw_faces, list) or not raw_faces:
            raise AssetError("face manifest has no assets")
        result: dict[str, FaceAsset] = {}
        for raw_face in raw_faces:
            face = self._parse_face(raw_face)
            if face.name in result:
                raise AssetError(f"duplicate face asset {face.name!r}")
            result[face.name] = face
        return result

    def _load_audio(self) -> dict[str, AudioAsset]:
        value = _read_manifest(self.root / "audio-v1.json")
        if (
            value.get("schema_version") != 1
            or value.get("sample_rate") != 16000
            or value.get("format") != "s16le-mono"
        ):
            raise AssetError("audio manifest schema mismatch")
        raw_assets = value.get("assets")
        if not isinstance(raw_assets, list):
            raise AssetError("audio manifest assets are invalid")
        result: dict[str, AudioAsset] = {}
        resolved_root = self.root.resolve()
        for value in raw_assets:
            if not isinstance(value, dict):
                raise AssetError("audio entry must be an object")
            name = _asset_name(value.get("name"))
            samples = value.get("samples")
            raw_path = value.get("path")
            if type(samples) is not int or not 1 <= samples <= 16000 * 30:
                raise AssetError(f"audio {name!r} sample count is invalid")
            if not isinstance(raw_path, str):
                raise AssetError(f"audio {name!r} path is invalid")
            path = (self.root / raw_path).resolve()
            if not path.is_relative_to(resolved_root) or not path.is_file():
                raise AssetError(f"audio {name!r} escapes or is missing")
            if path.stat().st_size != samples * 2:
                raise AssetError(f"audio {name!r} size is invalid")
            if name in result:
                raise AssetError(f"duplicate audio asset {name!r}")
            result[name] = AudioAsset(name, path, samples)
        return result

    def _parse_face(self, value: object) -> FaceAsset:
        if not isinstance(value, dict):
            raise AssetError("face entry must be an object")
        name = _asset_name(value.get("name"))
        fps = value.get("fps")
        mode = value.get("mode")
        frames = value.get("frames")
        if type(fps) is not int or not 1 <= fps <= 30:
            raise AssetError(f"face {name!r} has invalid fps")
        if mode not in {"loop", "once", "boomerang"}:
            raise AssetError(f"face {name!r} has invalid mode")
        if not isinstance(frames, list) or not 1 <= len(frames) <= MAX_FACE_FRAMES:
            raise AssetError(f"face {name!r} has invalid frame count")
        paths = []
        resolved_root = self.root.resolve()
        for raw_path in frames:
            if not isinstance(raw_path, str) or not raw_path:
                raise AssetError(f"face {name!r} has invalid frame path")
            path = (self.root / raw_path).resolve()
            if not path.is_relative_to(resolved_root) or not path.is_file():
                raise AssetError(f"face {name!r} frame escapes or is missing")
            if path.stat().st_size != FACE_FRAME_BYTES:
                raise AssetError(f"face {name!r} frame has invalid size")
            paths.append(path)
        return FaceAsset(name, fps, str(mode), tuple(paths))


class FaceAnimator:
    def __init__(self, asset: FaceAsset) -> None:
        self.asset = asset

    def frame_index(self, tick: int) -> int:
        count = len(self.asset.frame_paths)
        if tick < 0:
            raise ValueError("animation tick cannot be negative")
        if self.asset.mode == "once":
            return min(tick, count - 1)
        if self.asset.mode == "loop" or count <= 1:
            return tick % count
        period = (count * 2) - 2
        position = tick % period
        return position if position < count else period - position


class IdleBlinkSchedule:
    def __init__(self, seed: int) -> None:
        self._random = random.Random(seed)

    def next_delay_seconds(self) -> float:
        return self._random.uniform(3.0, 7.0)

    def next_blink_count(self) -> int:
        return 2 if self._random.random() < 0.30 else 1

    def next_double_delay_seconds(self) -> float:
        return self._random.uniform(0.120, 0.220)


def _parse_motion(value: object) -> MotionAsset:
    if not isinstance(value, dict):
        raise AssetError("motion entry must be an object")
    name = _asset_name(value.get("name"))
    version = value.get("joint_map_version")
    repeat_count = value.get("repeat_count")
    return_pose = value.get("return_pose")
    if version != JOINT_MAP_VERSION:
        raise AssetError(f"motion {name!r} joint-map version mismatch")
    if type(repeat_count) is not int or not 1 <= repeat_count <= 16:
        raise AssetError(f"motion {name!r} has invalid repeat count")
    if return_pose is not None:
        return_pose = _asset_name(return_pose)

    raw_frames = value.get("frames")
    if not isinstance(raw_frames, list) or not 1 <= len(raw_frames) <= MAX_MOTION_FRAMES:
        raise AssetError(f"motion {name!r} has invalid frame count")
    frames = tuple(_parse_motion_frame(name, frame) for frame in raw_frames)

    raw_cues = value.get("face_cues", [])
    if not isinstance(raw_cues, list) or len(raw_cues) > MAX_MOTION_FRAMES:
        raise AssetError(f"motion {name!r} has invalid face cues")
    cues = []
    for raw_cue in raw_cues:
        if not isinstance(raw_cue, dict):
            raise AssetError(f"motion {name!r} has invalid face cue")
        frame = raw_cue.get("frame")
        mode = raw_cue.get("mode")
        if type(frame) is not int or not 0 <= frame < len(frames):
            raise AssetError(f"motion {name!r} face cue frame is invalid")
        if mode not in {"loop", "once", "boomerang"}:
            raise AssetError(f"motion {name!r} face cue mode is invalid")
        cues.append(FaceCue(frame, _asset_name(raw_cue.get("name")), str(mode)))
    return MotionAsset(name, int(version), repeat_count, return_pose, tuple(cues), frames)


def _parse_motion_frame(asset_name: str, value: object) -> MotionFrame:
    if not isinstance(value, dict):
        raise AssetError(f"motion {asset_name!r} frame must be an object")
    duration = value.get("duration_ms")
    targets = value.get("targets")
    if type(duration) is not int or not 20 <= duration <= 5000:
        raise AssetError(f"motion {asset_name!r} frame duration is invalid")
    if not isinstance(targets, list) or not 1 <= len(targets) <= JOINT_COUNT:
        raise AssetError(f"motion {asset_name!r} frame targets are invalid")
    parsed = []
    seen = set()
    for target in targets:
        if not isinstance(target, list) or len(target) != 2:
            raise AssetError(f"motion {asset_name!r} target is invalid")
        joint_id, degrees = target
        if type(joint_id) is not int or not 0 <= joint_id < JOINT_COUNT or joint_id in seen:
            raise AssetError(f"motion {asset_name!r} has duplicate or unknown joint")
        if type(degrees) not in {int, float} or not math.isfinite(degrees):
            raise AssetError(f"motion {asset_name!r} has non-finite target")
        seen.add(joint_id)
        parsed.append((joint_id, float(degrees)))
    return MotionFrame(duration, tuple(parsed))


def _asset_name(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 32:
        raise AssetError("asset name is invalid")
    if any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in value):
        raise AssetError(f"asset name {value!r} is invalid")
    return value


def _read_manifest(path: Path) -> dict[str, object]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise AssetError(f"asset manifest {path} is unavailable") from exc
    if len(raw) > MAX_MANIFEST_BYTES:
        raise AssetError(f"asset manifest {path} is oversized")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AssetError(f"asset manifest {path} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise AssetError(f"asset manifest {path} must contain an object")
    return value


def _default_asset_root() -> Path:
    return Path(__file__).resolve().parents[3] / "Slave" / "software" / "assets" / "seed"
