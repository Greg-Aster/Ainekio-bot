# Robot Models and Code Separation

Ainekio maintains two distinct hardware models behind a shared `protocol-v1` transport and Body Control gateway:

- **`v2-12servo` (Active)**: 12-servo quadruped (`ESP32-P4-WIFI6` + `ESP32-C6` companion radio, `PCA9685` PWM, 16-channel muxed 4th-wire analog feedback, `LSM6DS3` IMU, `OV5647` CSI camera, `ES8311` audio, and `ST7789` LCD face).
- **`v1-8servo` (Paused)**: Retained 8-servo quadruped (`Freenove ESP32-S3-WROOM CAM N16R8` with direct MCPWM servo drive and `SSD1306` OLED).

## Model Summary

| Model | Chassis & Kinematics | Controller & Drive | Motion & Locomotion Stack | Specifications |
| --- | --- | --- | --- | --- |
| `v2-12servo` | 4 legs × 3 DOF (shoulder, carrier, crank closed 4-bar linkage) | ESP32-P4-WIFI6 + PCA9685 (`0x40`) + CD74HC4067 ADC feedback | Compiled Microduck neural policy (`v2_microduck`), Pupper MJX host policy, analytic Walk/Run/Crawl/Crab, 23 finite postures/gestures, and model-backed Freestyle trajectories | [V2 Specifications](v2-12servo/SPECIFICATIONS.md) |
| `v1-8servo` | 8-servo quadruped frame | ESP32-S3 direct MCPWM outputs | Portable core keyframe player and 8-joint `motion_plan_v1` | [V1 Specifications](v1-8servo/SPECIFICATIONS.md) |

Hardware specifications reconcile CAD geometry, electrical pinouts, and measured evidence at their model-specific owners; V1 bring-up results never establish V2 wiring, calibration, or physical readiness.

## Ownership Boundaries

| Responsibility | Canonical Owner |
| --- | --- |
| Mechanical CAD and printable STLs | `Slave/hardware/<model>/` |
| Linkage geometry, analytic gaits, finite clips, and firmware Microduck policy | [`Slave/software/models/v2-12servo/`](../Slave/software/models/v2-12servo/README.md) (V2); retained seed assets for V1 |
| Joint ID ordering and wire schemas | [`Slave/software/protocol/`](../Slave/software/protocol/README.md) (`joints_v1.py` map 1, `joints_v2.py` map 2) |
| Board buses, peripheral drivers, and real-time motion execution | [`Slave/firmware/esp32p4-wifi6/`](../Slave/firmware/esp32p4-wifi6/README.md) (V2) and `Slave/firmware/esp32s3/` (V1) |
| Robot sessions, operator dashboard, perception, and neural-gait training/serving | [`Master/gateway/`](../Master/gateway/README.md) |
| Learned 12-joint Freestyle generation, library, and event recovery | [`experiments/freestyle/`](../experiments/freestyle/README.md) |
| Semantic capabilities and observation/receipt bridge to Ainekio OS | `Master/gateway/environment_adapter/` and `Master/gateway/body_capabilities.py` |
| Host integration, protocol, and dashboard regression suites | `tests/` and `Slave/software/tests/protocol/` |
| Pairing secrets, per-device joint/feedback calibration, and runtime logs | Ignored per-device NVS and `build/gateway/` storage |

## Existing V1 Code to Separate

V1 extraction is paused. The paths below hold retained 8-servo assumptions and remain intact for V1 firmware and protocol compatibility:

| Owner | V1-Specific Content |
| --- | --- |
| [`protocol.h`](../Slave/software/core/include/ainekio/protocol.h) | 8-servo joint enum and legacy pose/motion C structs alongside V2 extensions |
| [`joints_v1.py`](../Slave/software/protocol/joints_v1.py) | Frozen 8-joint map-1 order (`control_v1.py` supports both map 1 and V2 map 2) |
| [`assets.c`](../Slave/software/core/src/assets.c) & `Slave/software/assets/seed/` | V1 fallback poses/keyframes alongside shared face and audio seed assets |
| `Slave/firmware/esp32s3/components/ainekio_platform/` | ESP32-S3 GPIO pin map, MCPWM driver, and V1 motion service |

## Compatibility Rules

- **Independent identifiers**: Robot model (`v1-8servo` vs `v2-12servo`), board target, firmware version, wire protocol (`protocol-v1`), and joint-map version (`map: 1` vs `map: 2`) are negotiated separately.
- **No cross-model command leakage**: Advertised commands come from the connected body's negotiated `capabilities.commands` subset and hardware readiness (`Master/gateway/body_capabilities.py`), never by inheriting V1's catalog on authentication.
- **Per-device calibration**: Joint channel assignment, Home pulse/angle, direction, scale, and 4th-wire ADC curves belong to each physical robot's saved configuration (`SERVO_SOCKET_MAP.md`), distinct from `home`/`tether` resource profiles.
