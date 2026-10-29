# Ainekio Documentation Authority

## Shared companion design

Start robot work with the canonical
[robot design core](../../metahuman/docs/robot/ROBOT_BIBLE.md) in the sibling
MetaHuman checkout. It explains the intended companion, system boundaries
and maintenance approach, with links to capability contracts and
[qualification scenarios](../../metahuman/docs/robot/QUALIFICATION.md).
Both repositories use that entry point; do not maintain another copy here.

Source links across repositories assume sibling `Ainekio` and `metahuman`
checkouts. Locate the paired checkout before tracing a cross-repository change;
an absent checkout is not evidence that a responsibility has no implementation.

## Which source answers which question

| Question | Authority |
| --- | --- |
| What is the whole robot intended to do? | Shared [Robot Bible](../../metahuman/docs/robot/ROBOT_BIBLE.md) and its capability contracts |
| How do processes, responsibilities and state connect? | Shared [software architecture](../../metahuman/docs/robot/SYSTEM_ARCHITECTURE.md); implementation contracts remain with the linked owners |
| What hardware, dimensions and wiring apply? | Selected [V2 specification](v2-12servo/SPECIFICATIONS.md) or retained [V1 specification](v1-8servo/SPECIFICATIONS.md), with their source and physical evidence |
| What wire messages, units and execution behavior apply? | Maintained [protocol](../Slave/software/protocol/README.md), selected firmware/model contracts and approved amendments below |
| How is a change maintained and demonstrated? | Shared [repair method](../../metahuman/docs/technical/REFACTOR_BLUEPRINT.md#repair-design) and [qualification walkthroughs](../../metahuman/docs/robot/QUALIFICATION.md#maintenance-walkthroughs) |

The [System Specification v1.0](<Ainekio - System Specification v1.0.docx>) is the
retained baseline. **The numbered amendments below replace its corresponding
clauses.** Unchanged clauses remain applicable within their original scope; V1
board assumptions do not define V2 hardware. V2 is active development; V1 is paused.
This consolidates already-approved changes rather than introducing new behavior.

The externally maintained [Parts Overview](https://docs.google.com/document/d/1wz0kyqttPK3HHL0P0_9lLtRW_B87U5u4kEt-UhttHFA/edit?usp=sharing)
named by v1.0 supplies planning inputs;
the model-specific records identify installed components and evidence. It is not
authority to restore superseded V2 parts such as the SHARGE power system.
Source shows implementation; recorded markings, wiring and measurements establish
installed facts. A compilation or an older successful flash establishes neither
today's installed version nor loaded physical performance.

When an approved change alters a contract, replace that statement at its existing
owner and update its consumers, tests and incoming references together. Record the
reason beside the contract. Do not append a contradictory instruction to this
index. Escalate an unresolved intent conflict precisely; historical evidence and
code alone do not settle it. Private agent instructions point to these shared
documents; public contributors can follow the procedure without those local files.

## Maintained implementation documents

Model-specific hardware records live under `v1-8servo/` and `v2-12servo/`.
Shared system, protocol, and bridge documents remain here. The existing
specification's V1 electrical assumptions do not define the V2 board or wiring;
[Robot Models](ROBOT_MODELS.md) records the approved separation and current
implementation boundary.

| Document | Current purpose |
| --- | --- |
| [Robot software architecture](../../metahuman/docs/robot/SYSTEM_ARCHITECTURE.md) | Cross-repository processes, interfaces, source owners, execution paths and state lifetimes |
| [V1 specifications](v1-8servo/SPECIFICATIONS.md) | Eight-servo body hardware, dimensions/unknowns, pin mapping, power and Body Control/MetaHuman connections |
| [V2 specifications](v2-12servo/SPECIFICATIONS.md) | Twelve-servo body hardware, current geometry, calibration/feedback mapping, power and local/remote connections |
| [Restarting Body Control and remote MetaHuman OS](STARTUP.md) | Restart an existing two-computer installation, check its VPN and bridge, and stop its foreground launchers |
| [ROBOT_MODELS.md](ROBOT_MODELS.md) | V1/V2 model, board, servo-output, and shared-code boundaries |
| [V1 hardware bring-up](v1-8servo/HARDWARE_BRINGUP_CHECKLIST.md) | V1 power topology, staged assembly procedure, open physical gates, and recorded board evidence |
| [V1 pinout diagnostics](v1-8servo/PINOUT_DIAGNOSTICS.md) | V1 Freenove header numbering, the flashed GPIO map, peripheral wiring, and expected diagnostic values |
| [V2 hardware record](v2-12servo/README.md) | Selected ESP32-P4-WIFI6/PCA9685 hardware, design assets, and current implementation limits |
| [V2 firmware design](v2-12servo/FIRMWARE_DESIGN.md) | V1 review, P4/PCA9685 requirements, controller/Q6A boundaries and staged acceptance |
| [Body Control Integration](BODY_CONTROL_INTEGRATION.md) | Selected wireless/offboard Q6A direction, USB comparison, ROS 2 role, operating targets and audit findings |
| [Vision and target tracking audit](audits/VISION_TRACKING_INTEGRATION.md) | Current camera/YOLO/MetaHuman ownership, verified gaps and tests, and a staged integration plan using existing execution owners |
| [Distributed robot foundation](DISTRIBUTED_ROBOT_FOUNDATION.md) | Universal P4 control, Q6A/remote/manual takeover, shared status/routing/queues, ROS comparison and migration gates before feature coding |
| [Resource budget](v2-12servo/RESOURCE_BUDGET.md) | Dated capacity analysis; its retired SHARGE topology and runtime calculations do not describe the current V2 assembly |
| [Budget audit evidence](v2-12servo/BUDGET_AUDIT_EVIDENCE.md) | Repository/source identities, manufacturer references, Q6A Wi-Fi capability readback, offline Kokoro timing/RSS and exclusions of stale evidence |
| [V2 Step 1 evidence](v2-12servo/STEP1_EVIDENCE.md) | Build/flash commands, tests, actual board/network results and outstanding electrical proof |
| [SLAVE_BRAIN_PROGRESS.md](SLAVE_BRAIN_PROGRESS.md) | Dated implementation/bring-up evidence; refresh deployment claims before reuse |
| [LOCAL_WAKE_WORD.md](LOCAL_WAKE_WORD.md) | Owner-local microWakeWord training, packaging, installation, and validation workflow |
| [freestyle-movement.md](freestyle-movement.md) | Owner-approved bounded motion-plan extension, emulator evidence, and physical enablement gate |
| [REPOSITORY_MAP.md](REPOSITORY_MAP.md) | Current Master, Slave, Emulator, documentation, and reference ownership map |
| [ROS2_SETUP.md](ROS2_SETUP.md) | Desktop ROS tools, validation, and portability requirements for later Q6A deployment |

## Consolidated v1.0 amendments

These are the approved replacements previously listed here as awaiting
consolidation. They retain their original model scope and do not reopen paused V1
development. Detailed values remain in the linked owners; deployment claims stay
with dated evidence.

1. **V1 pin map (section 6.3).** The provisional GPIO33/34 servo map is superseded:
   testing found octal-PSRAM corruption. The delivered board uses GPIO47/48 for
   R4/R3 and the recorded BOOT/UART-to-OLED handoff. [V1 pinout](v1-8servo/PINOUT_DIAGNOSTICS.md)
   owns that wiring; never apply it to the P4 body.
2. **Battery response (owner decision 2026-08-03).** Battery classifications are
   telemetry/warnings; they do not lock motion, cancel audio, close the gateway or
   enter deep sleep. Hardware pack protection owns undervoltage shutdown. Use the
   selected model's power record; no unmeasured cutoff performance is implied.
3. **V1 setup authentication.** The approved setup uses a stable per-device
   eight-character WPA2 key and a form restricted to the setup AP interface.
   The OLED reports setup and connection information. This replaces the original
   rotating-key requirement; [S3 firmware](../Slave/firmware/esp32s3/README.md)
   owns implementation and recorded validation.
4. **Wake-word capability.** Implemented control/inference support does not imply
   an installed accepted model. Read advertised readiness and configuration;
   [the wake-word owner](LOCAL_WAKE_WORD.md) owns training and installation.
5. **Motion-plan extension.** `motion_plan_v1` is an approved protocol extension;
   use the maintained [protocol](../Slave/software/protocol/README.md) and
   [model boundaries](ROBOT_MODELS.md). The older [V1 extension evidence](freestyle-movement.md)
   does not qualify current V2 Freestyle or its twelve-joint execution.
6. **V1 local discovery and liveness.** The approved local path uses DNS-SD with
   an authenticated endpoint cache (one cached attempt before rediscovery),
   reconnect backoff capped at 15 seconds and authenticated `ws://`
   on the owner's private WPA2 LAN. It does not silently fall back to Cloudflare
   or require a parallel local-WSS implementation. The recorded source contract
   uses one-second control pings and a four-second active-motion stale guard, without timer-driven
   session teardown; actual transport errors still enter the existing offline
   path. The [S3 network owner](../Slave/firmware/esp32s3/README.md) and dated
   bridge-liveness evidence retain exact settings and flash status. This amendment
   does not assert that a particular board currently runs that revision.

## Reference inputs

- `Freenove_ESP32_S3_WROOM_Board-main/` contains the vendor board pinout,
  tutorial, driver, and datasheet bundle used to identify physical headers and
  fixed onboard buses. It is reference material, not Ainekio behavior authority.
- `sesame-robot/` is the upstream Sesame source reference used by deterministic
  asset conversion and parity inspection. It is not linked into the runtime and
  does not own Ainekio protocol or safety behavior.

## Archive

`archive/` contains superseded specifications and historical progress material.
Archived files preserve lineage and evidence only; they must not be cited as the
current design. See [archive/README.md](archive/README.md).
