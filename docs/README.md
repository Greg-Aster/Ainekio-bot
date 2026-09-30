# Ainekio Documentation Authority

## Normative set

The normative system set is:

- `Ainekio - System Specification v1.0.docx` - behavior, protocol, software,
  safety, and acceptance authority.
- [Parts Overview](https://docs.google.com/document/d/1wz0kyqttPK3HHL0P0_9lLtRW_B87U5u4kEt-UhttHFA/edit?usp=sharing)
  - externally maintained electrical-parts authority named by the specification.

System Specification v1.0 supersedes the archived v0.6 specification and its
Amendment 1 freeze. The Parts Overview supplies planned electrical facts, but
delivered markings, wiring, measurements, photographs, and H-series results are
required before those values count as installed-hardware evidence.

## Maintained implementation documents

Model-specific hardware records live under `v1-8servo/` and `v2-12servo/`.
Shared system, protocol, and bridge documents remain here. The existing
specification's V1 electrical assumptions do not define the V2 board or wiring;
[Robot Models](ROBOT_MODELS.md) records the approved separation and current
implementation boundary.

| Document | Current purpose |
| --- | --- |
| [ROBOT_MODELS.md](ROBOT_MODELS.md) | V1/V2 model, board, servo-output, and shared-code boundaries |
| [V1 hardware bring-up](v1-8servo/HARDWARE_BRINGUP_CHECKLIST.md) | V1 power topology, staged assembly procedure, open physical gates, and recorded board evidence |
| [V1 pinout diagnostics](v1-8servo/PINOUT_DIAGNOSTICS.md) | V1 Freenove header numbering, the flashed GPIO map, peripheral wiring, and expected diagnostic values |
| [V2 hardware record](v2-12servo/README.md) | Selected ESP32-P4-WIFI6/PCA9685 hardware, design assets, and current implementation limits |
| [V2 firmware design](v2-12servo/FIRMWARE_DESIGN.md) | V1 review, P4/PCA9685 requirements, controller/Q6A boundaries and staged acceptance |
| [Body Control Integration](BODY_CONTROL_INTEGRATION.md) | ROS 2's proposed role alongside Ainekio/MetaHuman, recommended native USB/Wi-Fi layout and operating targets, audit findings and remaining implementation work |
| [Complete robot resource budget](v2-12servo/RESOURCE_BUDGET.md) | Power branches, P4/Q6A memory and processing, all equipment, camera/audio quality, motion timing, pins and wired/Wi-Fi comparisons; reproducible arithmetic and final qualification boundaries |
| [Budget audit evidence](v2-12servo/BUDGET_AUDIT_EVIDENCE.md) | Repository/source identities, manufacturer references, Q6A Wi-Fi capability readback, offline Kokoro timing/RSS and exclusions of stale evidence |
| [V2 Step 1 evidence](v2-12servo/STEP1_EVIDENCE.md) | Build/flash commands, tests, actual board/network results and outstanding electrical proof |
| [SLAVE_BRAIN_PROGRESS.md](SLAVE_BRAIN_PROGRESS.md) | Current robot-body software status, implementation evidence, and deliberately pending work |
| [AINEKIO_METAHUMAN_CLOSED_LOOP_STATUS.md](AINEKIO_METAHUMAN_CLOSED_LOOP_STATUS.md) | Current generic Environment Bridge ownership and closed-loop software status |
| [LOCAL_WAKE_WORD.md](LOCAL_WAKE_WORD.md) | Owner-local microWakeWord training, packaging, installation, and validation workflow |
| [freestyle-movement.md](freestyle-movement.md) | Owner-approved bounded motion-plan extension, emulator evidence, and physical enablement gate |
| [REPOSITORY_MAP.md](REPOSITORY_MAP.md) | Current Master, Slave, Emulator, documentation, and reference ownership map |
| [ROS2_SETUP.md](ROS2_SETUP.md) | Desktop ROS tools, validation, and portability requirements for later Q6A deployment |

These documents describe current implementation and evidence. They do not
silently amend the normative specification. A behavioral conflict requires a
numbered specification erratum or revision; installed electrical facts require
recorded H-series evidence.

## Current v1.0 deltas awaiting specification consolidation

System Specification v1.0 predates several implementation discoveries and
owner-approved extensions. Until they are consolidated by numbered erratum or a
new specification revision, readers must keep these boundaries explicit:

- The delivered N16R8 board cannot use the provisional GPIO33/34 servo map in
  specification section 6.3. Hardware testing proved those pins corrupt octal
  PSRAM. The flashed board profile uses GPIO47/48 for R4/R3 and hands GPIO0/43
  from BOOT/UART to the OLED. `v1-8servo/PINOUT_DIAGNOSTICS.md` is the V1 physical
  wiring reference; the old provisional map must not be wired.
- Owner policy as of 2026-08-03 makes the GPIO3 battery sensor telemetry and
  warning-only. The firmware still classifies low, critical, recovered, and
  disconnected readings, but those readings never lock motion, cancel audio,
  close the gateway, or enter deep sleep. Undervoltage shutdown is owned only
  by the battery pack's hardware protection circuit. The installed pack's
  cutoff behavior is not yet documented, so it must be treated as unverified
  and replaced with a properly protected pack if necessary.
- The checked firmware uses a stable per-device eight-character WPA2 setup key
  instead of generating a new 12-character secret for every entry. Joining
  `Ainekio-Setup` is the only setup authentication step; the portal opens its
  configuration form directly at `http://192.168.4.1/` and rejects requests
  outside the setup AP interface. The OLED reports the setup address/key and
  then the joined SSID, DHCP address, and gateway state. This owner-approved UX and
  security change is flashed and broadcasting its setup AP, but still awaits
  physical form-submission evidence and numbered specification consolidation.
- The local wake-word control plane and inference engine are implemented, but no
  accepted production `Ainekio` model is installed. First boot remains
  `wake_enabled=false` and `wake_ready=false`.
- `motion_plan_v1` is an owner-approved bounded extension implemented in the
  protocol/core, gateway, environment adapter, emulator, and current ESP32-S3
  source. The physical port reuses the existing prepared motion buffer/task and
  post-action camera callback. The matching revision is flashed, digest-verified,
  and connected; physical freestyle remains pending owner-supervised transition,
  stop, completion-image, and memory-headroom validation.
- Local robot transport now defaults to `_ainekio._tcp.local` DNS-SD discovery,
  rejects off-subnet advertised addresses, and caches the last authenticated
  local endpoint as a first-attempt optimization. A stale cached endpoint gets
  one bounded attempt before DNS-SD resumes; it is not a fixed configuration.
  Reconnect backoff resets after authenticated `welcome` and never exceeds 15
  seconds. Local mode never silently falls back to the optional Cloudflare
  relay. The owner selected authenticated `ws://` on the private home WPA2 LAN
  as the intentionally minimal local transport; pinned local WSS is not a
  parallel pending path. The maintained implementation uses one-second control
  pings and a four-second active-motion stale guard without timer-driven session
  teardown. Actual Wi-Fi/WebSocket errors still enter FAILSAFE/offline. The v1.0
  DOCX needs a numbered erratum for this
  local-discovery and liveness contract. The keepalive-free application is
  prepared in source but has not yet been flashed; the dated bridge-liveness
  handoff records the exact source-versus-controller boundary.

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
