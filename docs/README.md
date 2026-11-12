# Ainekio Documentation Authority

## Shared Companion Design

Whole-robot product intent, capability contracts, and qualification scenarios live in **[Ainekio OS](https://github.com/Greg-Aster/ainekio-os)**:

- [Robot Design Core (`ROBOT_BIBLE.md`)](https://github.com/Greg-Aster/ainekio-os/blob/main/docs/robot/ROBOT_BIBLE.md)
- [Robot Software Architecture (`SYSTEM_ARCHITECTURE.md`)](https://github.com/Greg-Aster/ainekio-os/blob/main/docs/robot/SYSTEM_ARCHITECTURE.md)
- [Qualification Scenarios (`QUALIFICATION.md`)](https://github.com/Greg-Aster/ainekio-os/blob/main/docs/robot/QUALIFICATION.md)

When working locally across both repositories, maintain sibling `Ainekio` and `metahuman` (`ainekio-os`) checkouts; do not duplicate cross-repository contracts here.

## Authority by Question

| Question | Canonical Owner |
| --- | --- |
| Whole-robot purpose and companion behavior | [Robot Design Core](https://github.com/Greg-Aster/ainekio-os/blob/main/docs/robot/ROBOT_BIBLE.md) and its linked capability contracts |
| Cross-repository processes, state lifetimes, and execution paths | [Robot Software Architecture](https://github.com/Greg-Aster/ainekio-os/blob/main/docs/robot/SYSTEM_ARCHITECTURE.md) |
| Physical hardware, CAD geometry, and electrical wiring | [V2 Specifications](v2-12servo/SPECIFICATIONS.md) (active) and [V1 Specifications](v1-8servo/SPECIFICATIONS.md) (paused) |
| Wire envelopes, capability flags, joint maps, and binary media frames | [Ainekio Protocol v1](../Slave/software/protocol/README.md) and model/firmware READMEs |
| Repair workflow and end-to-end verification | [Architecture & Repair Design](https://github.com/Greg-Aster/ainekio-os/blob/main/docs/technical/REFACTOR_BLUEPRINT.md#repair-design) and [Maintenance Walkthroughs](https://github.com/Greg-Aster/ainekio-os/blob/main/docs/robot/QUALIFICATION.md#maintenance-walkthroughs) |

Source code establishes software implementation; recorded board markings, saved calibration readbacks, and physical trials establish installed readiness. Update contracts in place at their owning document rather than appending contradictory notes.

## Maintained Repository Documents

| Document | Scope |
| --- | --- |
| [Repository Map](REPOSITORY_MAP.md) | Source ownership across `Master/`, `Slave/`, `experiments/freestyle/`, `tests/`, and `docs/` |
| [Robot Models](ROBOT_MODELS.md) | V1 (`v1-8servo`) and V2 (`v2-12servo`) architectural separation and compatibility rules |
| [Startup Runbook](STARTUP.md) | Starting physical Body Control alongside local or remote Ainekio OS |
| [V2 Specifications](v2-12servo/SPECIFICATIONS.md) | Active 12-servo ESP32-P4 hardware, CAD dimensions, 4th-wire feedback map, power, and network topology |
| [V2 Hardware Overview](v2-12servo/README.md) | V2 component summary, wiring diagram index, CAD assets, and current firmware/locomotion overview |
| [V2 Firmware Design](v2-12servo/FIRMWARE_DESIGN.md) | ESP32-P4/PCA9685 architecture, bus reservations, and staged bring-up design |
| [V2 Walking System](v2-12servo/WALKING_SYSTEM.md) | Locomotion control contracts, IMU balance, recovery, and neural gait boundaries |
| [Gateway & Body Control](../Master/gateway/README.md) | Python `protocol-v1` server, operator dashboard, perception, Microduck neural gait, and `/environment` bridge |
| [ESP32-P4 Firmware](../Slave/firmware/esp32p4-wifi6/README.md) | V2 microcontroller firmware, servo/ADC loop, Microduck execution, camera, audio, LCD face, and CLI |
| [Protocol v1](../Slave/software/protocol/README.md) | JSON control schema, 5-byte binary media framing, capability negotiation, and V1/V2 extensions |
| [V2 Motion Model](../Slave/software/models/v2-12servo/README.md) | Closed 4-bar linkage kinematics, 23 finite postures/gestures, analytic gaits, and compiled Microduck policy |
| [Freestyle Motion](../experiments/freestyle/README.md) | Model-backed 12-joint motion generation, compact wire operations, curriculum, and event recovery |
| [Local Wake Word](LOCAL_WAKE_WORD.md) | On-device microWakeWord training, packaging, and installation |
| [V1 Specifications](v1-8servo/SPECIFICATIONS.md) & [V1 Pinout Diagnostics](v1-8servo/PINOUT_DIAGNOSTICS.md) | Retained 8-servo ESP32-S3 hardware specifications, header map, and electrical checks |

## Consolidated v1.0 Amendments

[System Specification v1.0](Ainekio%20-%20System%20Specification%20v1.0.docx) is retained as historical baseline context; V2 is active development and V1 is paused. The amendments below supersede the corresponding v1.0 clauses within their stated model scope:

1. **V1 pin map (section 6.3)**: Provisional GPIO33/34 servo outputs caused octal-PSRAM corruption on Freenove ESP32-S3 N16R8 boards and are replaced by GPIO47/48 (`R4`/`R3`) per [V1 Pinout Diagnostics](v1-8servo/PINOUT_DIAGNOSTICS.md). Never apply V1 pin maps to ESP32-P4 hardware.
2. **Battery telemetry policy**: Battery states emit telemetry and warnings only; firmware never locks out motion, cancels audio, drops the gateway session, or forces deep sleep from software thresholds. Pack protection hardware owns undervoltage cutoff.
3. **Setup AP provisioning**: Both V1 (`esp32s3`) and V2 (`esp32p4-wifi6`) use a persistent WPA2 setup key and an AP-interface-only provisioning form (`http://192.168.4.1/`) with CSRF validation rather than rotating keys.
4. **Wake-word readiness**: Firmware wake-word support requires an installed, validated wake model in the asset partition; Body Control gates wake activation on advertised model readiness ([LOCAL_WAKE_WORD.md](LOCAL_WAKE_WORD.md)).
5. **Model-specific motion plans**: `motion_plan_v1` (8-joint duration frames) and `motion_plan_v2` (12-joint centidegree/speed targets with 4th-wire arrival verification) are negotiated per model in [Protocol v1](../Slave/software/protocol/README.md).
6. **LAN discovery and gateway switching**: Robots authenticate over `ws://` on trusted private WPA2 LANs (with DNS-SD `_ainekio._tcp.local` fallback when plain WS is configured for that SSID) or `wss://` with verified TLS certificates for remote relays. Control silence (4 s) disarms servo outputs without tearing down healthy media/telemetry sessions.
