from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class MotionServerConfig:
    host: str = "127.0.0.1"
    port: int = 8787


@dataclass(frozen=True)
class BridgeConfig:
    url: str
    catch_up_url: str | None
    adapter_id: str


@dataclass(frozen=True)
class BackendConfig:
    active: str = "virtual"
    hardware_enabled: bool = False
    pca9685_address: str = "0x40"
    servo_frequency_hz: int = 50


@dataclass(frozen=True)
class TelemetryConfig:
    interval_ms: int = 100


@dataclass(frozen=True)
class SafetyConfig:
    default_ttl_ms: int = 1200
    lease_ttl_ms: int = 1500
    stale_stop_ms: int = 600
    motor_stagger_ms: int = 20
    low_battery_mv: int = 6500


@dataclass(frozen=True)
class MotionConfig:
    motion: MotionServerConfig
    bridge: BridgeConfig
    backend: BackendConfig
    telemetry: TelemetryConfig
    safety: SafetyConfig


def _section(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, Mapping):
        raise ValueError(f"Config section {key!r} must be an object")
    return value


def load_config(path: str | os.PathLike[str] | None = None) -> MotionConfig:
    config_path = Path(path or os.environ.get("AINEKIO_MOTION_CONFIG", "motion/config.json"))
    with config_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, Mapping):
        raise ValueError("Motion config must be a JSON object")

    motion = _section(data, "motion")
    bridge = _section(data, "bridge")
    backend = _section(data, "backend")
    telemetry = _section(data, "telemetry")
    safety = _section(data, "safety")

    bridge_url = bridge.get("url")
    if not isinstance(bridge_url, str) or not bridge_url:
        raise ValueError("bridge.url is required")

    return MotionConfig(
        motion=MotionServerConfig(
            host=str(motion.get("host", "127.0.0.1")),
            port=int(motion.get("port", 8787)),
        ),
        bridge=BridgeConfig(
            url=bridge_url,
            catch_up_url=str(bridge["catch_up_url"]) if bridge.get("catch_up_url") else None,
            adapter_id=str(bridge.get("adapter_id", "ainekio-motion-local")),
        ),
        backend=BackendConfig(
            active=str(backend.get("active", "virtual")),
            hardware_enabled=bool(backend.get("hardware_enabled", False)),
            pca9685_address=str(backend.get("pca9685_address", "0x40")),
            servo_frequency_hz=int(backend.get("servo_frequency_hz", 50)),
        ),
        telemetry=TelemetryConfig(interval_ms=int(telemetry.get("interval_ms", 100))),
        safety=SafetyConfig(
            default_ttl_ms=int(safety.get("default_ttl_ms", 1200)),
            lease_ttl_ms=int(safety.get("lease_ttl_ms", 1500)),
            stale_stop_ms=int(safety.get("stale_stop_ms", 600)),
            motor_stagger_ms=int(safety.get("motor_stagger_ms", 20)),
            low_battery_mv=int(safety.get("low_battery_mv", 6500)),
        ),
    )
