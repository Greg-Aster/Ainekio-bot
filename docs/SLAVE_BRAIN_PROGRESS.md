# Ainekio Slave Brain Progress

This document tracks plans, architecture decisions, and implementation progress
for the Ainekio robot-side controller, also called the slave brain. The slave
brain is the WiFi-connected robot control layer that receives semantic commands
from the remote MetaHuman OS brain, applies robot-side safety and translation,
and drives the ESP32-S3 body hardware or simulator backend.

## Current Phase

Software-only emulator control, protocol transport, safety parity, and
provisioning design while the target hardware is in transit. Hardware flashing
and bring-up remain explicitly pending.

## Current Relevant Documents

- `/home/greggles/Merkin/apps/ainekio/src/content/posts/_remote_doc.md` - remote planning document index for the current robot planning docs.
- Google Doc: `https://docs.google.com/document/d/1AVtNyFN7AG5ymLqshQI-77jO4nfG0yev8FUABZ8YE9E/edit?usp=sharing` - current MetaHuman OS state reference.
- `README.md` - repo overview and current project links.
- `docs/REPOSITORY_MAP.md` - current Master, Slave, Emulator, and docs ownership
  map with the physical robot entry point identified.
- `docs/Ainekio - System Specification v1.0.docx` - current local system specification document.
- `docs/Ainekio - Spec v0.6 Amendment 1 (FINAL) + Freeze.docx` - local freeze/amendment reference.
- `docs/archive/simulator-bridge-progress-scratchpad.md` - historical MetaHuman
  bridge, adapter, and Sesame simulator integration notes; not an architecture
  authority.
- `Emulator/sesame-robot-sim/README.md` - local Sesame browser simulator and
  visual-backend run instructions.
- ESP-IDF v5.5.4 documentation: `https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32s3/` - pinned ESP32-S3 development framework reference.

## Foundation Decisions

- Pin the first ESP32-S3 implementation to ESP-IDF v5.5.4. FreeRTOS is supplied
  by ESP-IDF and will not be installed or maintained separately.
- Keep protocol handling, command lifecycle, robot state, and safety decisions in
  a portable C core with no ESP-IDF, FreeRTOS, socket, GPIO, or filesystem headers.
- Keep FreeRTOS tasks, networking, storage, OTA, and hardware drivers inside the
  ESP32-S3 platform implementation.
- Use semantic robot commands. Remote AI callers never provide raw servo angles.
- Use fixed-size command structures, bounded messages and queues, and explicit
  timeouts. Avoid heap allocation in safety and motion-control paths after startup.
- Treat a future Linux body controller as another platform implementation of the
  same portable core and protocol contract, not as a separate robot brain design.
- Store WiFi credentials, gateway endpoint, robot id, token, calibration, and
  other small configuration values in internal NVS. Credentials never go on SD.
- Keep provisioning separate from the production robot WebSocket. Provisioning
  temporarily allows an inbound setup portal; normal operation only dials the
  configured gateway outward after joining WiFi.
- Use the specification's WPA2 SoftAP provisioning flow for v1. Bluetooth LE is
  technically possible but is deferred unless the owner approves a specification
  change and its additional firmware-memory cost.
- Preserve the board-mounted microSD slot for future removable-storage features.
  GPIO 38 (CMD), GPIO 39 (CLK), and GPIO 40 (DAT0) are reserved exclusively for
  SD_MMC 1-bit mode and must never be assigned to an accessory.

## Current Source Ownership

```text
Master/
  gateway/
    server/

Slave/
  hardware/
    3d-print/
  software/
    core/
    protocol/
    tests/
  firmware/
    esp32s3/
      main/app_main.c

Emulator/
  emulator/
    body/
    backends/
  tests/
  sesame-robot-sim/
  legacy/motion/

docs/
  archive/
  sesame-robot/
```

`Slave/` owns the physical robot. `Slave/firmware/esp32s3/main/app_main.c` is the
ESP32-S3 entry point, `Slave/software/core/` owns portable body behavior and
safety, and `Slave/software/protocol/` owns the wire contract. `Master/gateway/`
owns the brain-side socket. `Emulator/emulator/` owns host body emulation and
renderer transport. `Emulator/legacy/motion/` is superseded Python/SSE code.
`docs/sesame-robot/` is the ignored upstream reference clone, while
`Emulator/sesame-robot-sim/` is the runnable visual simulator.

## Initial Flash and Storage Budget

The current target is the ESP32-S3 N16R8 configuration: 16 MB flash and 8 MB
PSRAM. The normative target below comes from section 6.4 of System Specification
v1.0. PSRAM configuration remains disabled until target hardware bring-up.

| Storage | Initial budget | Intended use |
| --- | ---: | --- |
| System NVS | 64 KB | Namespaced WiFi, identity, endpoint, token, calibration, profile, and boot settings |
| NVS keys | 4 KB | Reserved but unused in v1 |
| OTA metadata | 8 KB | Active and rollback OTA selection |
| OTA application slot 0 | 3 MB | Running or previous firmware image |
| OTA application slot 1 | 3 MB | Update firmware image |
| LittleFS | 9.875 MiB (10,112 KiB) | Versioned poses, display assets, and small sounds |

Large recordings, captured media, and continuous logs do not belong in internal
flash. They must be streamed, stored on the board-mounted microSD card, or
discarded according to an explicit retention policy. Internal LittleFS and the
removable microSD card are separate storage systems.

The checked-in layout now matches the normative allocation: one 64 KiB NVS
partition, a reserved-unencrypted 4 KiB `nvs_keys` partition, 8 KiB OTA metadata,
two 3 MiB OTA slots, and all remaining aligned flash assigned to LittleFS. Flash
core dumps are disabled so they do not require an undocumented partition.

## Memory and Growth Rules

- Record application flash, DRAM, IRAM, and per-component size after every build.
- Warn when an application image reaches 60 percent of one OTA slot and fail the
  project memory budget at 70 percent until the owner approves a new budget.
- Keep control-message sizes, queue depths, task stacks, and media buffers bounded.
- Reject oversized or malformed network messages before command execution.
- Keep safety-critical state and DMA requirements in internal RAM. Use PSRAM for
  large camera, audio, and temporary network buffers where hardware rules allow.
- Add optional features as separately owned components with explicit dependencies
  and compile-time configuration.
- Pin third-party component versions and commit dependency lock information.

## Implementation Plan

- [x] Inventory the existing Python motion controller, safety code, adapters, and simulator bridges.
- [x] Select the portable-core and platform-port architecture.
- [x] Install and verify ESP-IDF v5.5.4 and the ESP-IDF VS Code extension.
- [x] Define the v1 protocol validator and golden valid/invalid fixtures.
- [x] Add host-side protocol fixture validation.
- [x] Create the portable C command, state, lifecycle, and safety boundaries.
- [x] Create the minimal ESP32-S3 project and `app_main` composition root.
- [x] Add and validate a provisional 16 MB scaffold partition table.
- [x] Build the empty firmware and record the initial flash, DRAM, and IRAM baseline.
- [x] Reconcile the provisional partition table with normative specification section 6.4.
- [x] Add the language-neutral protocol schemas and binary helpers required by the normative repo layout.
- [x] Consolidate the existing simulator stack behind protocol-v1 transport and
  the portable C safety core as described below.
- [x] Implement and host-test the provisioning state machine before hardware arrives.
- [ ] Boot the target board and emit one structured boot-status message after it arrives.
- [ ] Begin production firmware features only after the specification's firmware start gates pass.

## Existing Sesame Emulator Finding

The repo already contains the original Sesame browser simulator under
`Emulator/sesame-robot-sim`. It is worth retaining and using, with a strict
boundary:

- The simulator is a prebuilt browser/WASM environment based on the original
  Arduino Sesame firmware and robot model.
- The existing Ainekio shim receives local motion events and sends named commands
  such as `run walk` into the simulator's UART/runtime interface.
- It is useful for visible movement, sequence inspection, joint mapping, and
  operator feedback while hardware is unavailable.
- It is not the body protocol or safety acceptance stand-in. The host body
  emulator must own protocol v1, state, lifecycle, and safety before anything is
  sent to Sesame.
- Arduino-specific simulator internals must not leak into the portable C core or
  determine the ESP-IDF firmware architecture.

## Upgraded Body Capability Boundary

Ainekio is an upgraded Sesame-derived robot running native ESP-IDF C, not the
original Arduino firmware. The Sesame browser simulator remains useful, but only
as the first visual motion backend. It does not define or emulate the complete
Ainekio body.

- Motion commands accepted by the portable C core may be rendered through the
  existing Sesame UART shim.
- Sight is a camera capability that emits protocol-v1 JPEG frames and camera
  status. Host tests may use bounded fixture images without emulating computer
  vision; interpretation remains in the remote brain.
- Listening is a microphone capability that emits bounded PCM frames and
  VAD/wake events. Host tests may use prerecorded or generated fixture audio.
- Talking is a speaker capability that consumes bounded protocol-v1 PCM frames
  and reports playback completion, cancellation, overflow, and underrun state.
- The display is a separate local output capability for faces and status. It is
  not coupled to the Sesame simulator's OLED implementation.
- Future sensors publish typed state or events through their own platform ports.
  They do not bypass protocol validation or the portable safety core.
- A missing simulated capability must report unsupported or unavailable. It must
  never claim success or silently route through an unrelated Arduino feature.

The control schema and fixtures already cover camera, snapshot, microphone,
speaker audio, TTS lifecycle, status counters, and media frame types. Emulator
work should implement those contracts incrementally after the motion/control
path is authoritative; it should not create a second all-in-one robot simulator.

## Emulator Transport and Safety Plan

- [x] Inspect the existing Sesame emulator, local shim, Python adapter, virtual
  backend, and current safety controller.
- [x] Establish that the existing Sesame runtime is the motion renderer and that
  upgraded Ainekio capabilities use separate protocol-backed host adapters.
- [x] Keep Sesame as an optional renderer, isolate the old motion/SSE package
  under `Emulator/legacy/motion/`, place normative body behavior in
  `Emulator/emulator/`, and brain-side protocol behavior in `Master/gateway/`.
- [x] Reconcile the normative partition layout before additional firmware storage
  code is built on the provisional layout.
- [x] Add a local gateway/brain stub that serves the exact protocol v1 WebSocket
  and can replay all golden fixtures without MetaHuman OS running.
- [x] Add a host body emulator that initiates the WebSocket and implements
  `hello`, `welcome`, auth/version failures, epoch reset, sequence handling,
  reconnect backoff, ping/pong, and status reporting.
- [x] Compile the portable C core for the host and make it the authoritative
  command, lifecycle, state, and safety gate for the emulator.
- [x] Start with only `stand`, `neutral`, `walk`, and `stop`; unsupported commands
  must reject explicitly rather than partially execute.
- [x] Route accepted semantic commands to a simulator backend behind a narrow
  interface. Keep the existing Sesame UART path as the first visual backend.
- [x] Replace unbounded simulator subscriber queues with bounded delivery, never
  replay stale movement to a newly connected subscriber, and give `stop` a direct
  preemption path.
- [ ] Add a simulator execution result path so publication is not reported as
  `done` until the visual backend acknowledges execution or cancellation.
- [ ] Test malformed and oversized input, stale and duplicate sequences,
  disconnect/reconnect, unavailable simulator, queue saturation, and stop
  preemption within the specification's 100 ms limit.
- [x] Keep the old MetaHuman SSE adapter simulator-only. Later gateway bridge code
  may translate MetaHuman actions into protocol v1, but the firmware must not
  implement both the legacy SSE contract and the production WebSocket contract.

## WiFi Provisioning Decision

The specified board has internal SPI flash and an SD_MMC/microSD subsystem; the
SD card is not an SSD and is not the credential store. WiFi credentials are small
configuration values and belong in internal NVS, where they survive normal power
cycles and firmware restarts. System Specification v1.0 explicitly prohibits
putting credentials on SD. Version 1 keeps exactly one active WiFi configuration;
a successfully validated replacement overwrites the active SSID and password
instead of accumulating network records. This consumes only a small fraction of
the 64 KB NVS partition.

The setup connection is not the production robot WebSocket. In provisioning mode
the robot temporarily broadcasts a WPA2 WiFi access point named
`Ainekio-Setup` and serves a local HTTP setup portal. A phone or computer joins
that temporary network, enters the target WiFi name and password plus gateway
identity settings, and presses save. ESP-IDF supports this SoftAP-to-station
provisioning flow using one radio in AP+STA mode. After successful validation and
an atomic NVS commit, the setup service stops and the robot opens its normal
outbound WebSocket to the configured gateway.

Normative v1 provisioning behavior from specification section 6.7, including
applied Erratum E1:

- Enter provisioning when no valid NVS exists, NVS recovery fails, an
  authenticated dashboard action requests it, BOOT is held for 5 seconds after
  normal boot, or saved WiFi fails to produce a station IP within 60 seconds.
- On boot with saved credentials, show `Connecting to WiFi` and retry association
  and DHCP with bounded backoff for 60 seconds. Apply the same window after a
  connected robot loses WiFi/IP. A gateway or WebSocket failure alone does not
  trigger WiFi provisioning.
- Generate a new 12-character base32 setup secret for every provisioning entry.
  Use it as both the SoftAP WPA2 password and portal login, and display it on the
  OLED for that session with a one-time UART fallback.
- Accept `wifi_ssid`, `wifi_psk`, `endpoint_url`, `robot_id`, and `robot_token`.
- Stage the complete replacement, require association and a station IP within 60
  seconds, and only then atomically replace the active configuration. Invalid
  credentials, connection timeout, or failed commit preserve the previous working
  configuration and leave the portal available for correction.
- Never echo stored secrets and never write them to logs or SD.
- In automatic fallback, cycle the setup AP for 10 minutes on and 60 seconds off
  while retrying the saved network. If it returns before replacement, close setup
  and resume normal operation. Manual provisioning with valid credentials times
  out after 10 minutes and resumes the old configuration; with no valid
  credentials, continue the AP cycle until setup succeeds.
- Use the OLED as the primary status channel: `Connecting to WiFi`, `WiFi
  unavailable`, setup network/secret screens, and a brief `WiFi connected` notice.
  Emit one short non-repeating audio cue when setup is required and a distinct cue
  on connection success; audio failure never blocks provisioning.
- BOOT entry does not erase configuration. An authenticated network-only reset
  clears only SSID/password and enters provisioning while preserving endpoint,
  identity/token, calibration, poses, profile, and ADC settings. Full NVS erase is
  a separate service procedure and is never automatic.
- Keep Bluetooth LE provisioning as a possible later alternative, not a v1
  requirement. SoftAP is more universal and avoids carrying a Bluetooth stack in
  normal firmware.

### Provisioning Implementation Plan

- [x] Define the versioned NVS namespaces and keys for WiFi, endpoint, robot
  identity/token, calibration, profile, ADC factor, and setup-secret hash.
- [x] Add a platform-neutral provisioning state machine with host tests for valid,
  missing, corrupt, staged, committed, and rolled-back configuration, plus the
  60-second connection window and automatic fallback cycle.
- [ ] Add the ESP32-S3 NVS adapter with specified recovery behavior and atomic
  staging-to-active commit.
- [ ] Add the ESP32-S3 WPA2 SoftAP and authenticated HTTP setup portal using
  bounded request bodies and rate limits.
- [ ] Add WiFi scanning, credential validation, connection progress, and clear
  failure reporting without exposing the submitted password.
- [ ] Keep exactly one active WiFi configuration and verify that a replacement is
  committed only after association and DHCP succeed; connection failure must
  leave the prior active namespace unchanged.
- [ ] Treat SoftAP channel changes or a temporary setup-client disconnect as an
  expected transition; determine success from ESP-IDF station/IP events rather
  than assuming the browser remains connected throughout the handoff.
- [ ] Add authenticated network-only reset and post-boot BOOT-button entry paths
  without confusing provisioning with ROM download mode or erasing robot
  identity, calibration, poses, profile, or ADC settings.
- [ ] Add bounded OLED status transitions and one-shot setup/success audio cues;
  neither display nor audio failure may block networking or safety tasks.
- [ ] Add emulator acceptance coverage for credential replacement and failed
  commit preservation, transient network recovery, automatic fallback, setup
  timeout/cycling, and network-only reset; run the complete hardware provisioning
  matrix when the board arrives.
- [ ] Treat NVS encryption as a future security migration. Specification v1.0
  currently reserves `nvs_keys` but leaves it unused; enabling encryption requires
  an approved specification errata and migration test.

## Provisioning Core Progress - 2026-07-13

- Added a versioned NVS contract in
  `Slave/software/core/include/ainekio/config_schema.h`. Configuration uses two
  bounded A/B slots and one metadata commit that bumps `schema_ver` and switches
  `active_slot`, so a staged replacement is validated before activation.
  Calibration, named poses, profile, and ADC settings remain in separate
  namespaces.
- Added the platform-neutral state machine in
  `Slave/software/core/src/provisioning.c`. It has no ESP-IDF, FreeRTOS, socket,
  GPIO, filesystem, or heap dependency.
- Implemented valid/migrated/missing/corrupt boot handling, the 60-second station
  connection window, WiFi-loss recovery, manual setup timeout, automatic setup
  AP cycling, staged validation, commit, rollback, network-only reset, saved
  network return, and gateway-failure separation.
- Setup-secret generation, display states, and one-shot audio cues are emitted as
  bounded platform actions. The state machine does not log or retain credentials.
- Added a dedicated host C test target covering the NVS contract and provisioning
  transitions. Both portable C CTest targets pass under C11 with warnings as
  errors.
- ESP-IDF v5.5.4 cross-build passed with `provisioning.c` compiled into the core
  component. The current boot-shell image remains `0x299c0` bytes with 95 percent
  of the 3 MiB OTA slot free because `app_main` does not call provisioning yet.

The next provisioning item is the ESP32-S3 NVS adapter and its recovery and
staging-to-active commit behavior. SoftAP and portal code remain later steps and
must not be added before the storage adapter is host-tested at its boundary.

## Foundation Baseline - 2026-07-13

Toolchain and editor setup:

- ESP-IDF v5.5.4 installed at `/home/greggles/esp/esp-idf-v5.5.4`.
- ESP32-S3 compiler: `xtensa-esp-elf-gcc 14.2.0_20260121`.
- VS Code extension: `espressif.esp-idf-extension` v2.1.0.
- FreeRTOS comes from the pinned ESP-IDF checkout.

Validation completed:

- Protocol host tests: 12 passed. These cover valid and invalid control messages,
  exact schema/validator message-type coverage, semantic schema rules, binary
  encode/decode round trips, audio/camera frames, counter wrap, truncation,
  unknown frame types, and fixture secret redaction.
- Portable core: clean host build with C11, `-Wall`, `-Wextra`, `-Werror`, and
  `-Wpedantic`; command/safety and provisioning CTest targets passed.
- ESP32-S3 cross-build: passed with the portable core linked as an ESP-IDF
  component.
- Normative partition table: passed the ESP-IDF v5.5.4 partition validator and a
  clean cross-build for 16 MB flash. LittleFS begins at `0x620000`, is 10,112 KiB,
  and ends exactly at `0x1000000`.
- SD_MMC preservation: GPIO 38/39/40 are reserved in the normative pin map and
  current software plan. Electrical pull-up and concurrent camera/PSRAM/SD/PWM
  behavior remain hardware gate H2 after the board arrives.

Reconciled size-optimized ESP32-S3 shell baseline:

| Measurement | Used | Available or note |
| --- | ---: | --- |
| Application image | 170,311 bytes | 3 MiB OTA slot; approximately 95 percent free |
| Padded application binary | 170,432 bytes | `0x299c0` |
| Flash code | 69,524 bytes | `.text` |
| Flash data | 37,824 bytes | `.rodata` plus app descriptor |
| Internal data RAM | 13,804 bytes | `.data` plus `.bss` |
| Executable internal RAM | 51,391 bytes | DIRAM text plus IRAM text and vectors |

The build shell currently initializes only the portable core and emits a
structured boot record. It does not initialize WiFi, servos, audio, display,
camera, sensors, LittleFS, or PSRAM. The board boot record remains unverified
until target hardware is connected and flashed.

## Simulator Consolidation Progress - 2026-07-13

- Reconciled ownership with System Specification v1.0:
  `Emulator/emulator/` owns body emulation and host renderer transport,
  `Master/gateway/` owns the brain-side protocol,
  `Emulator/legacy/motion/` contains the superseded Python/SSE path, and
  `Emulator/sesame-robot-sim/` is optional visual runtime code.
- Defined the Sesame browser runtime as the visual motion backend only. Camera,
  microphone, speaker, display, and future sensors remain separate protocol-backed
  capabilities of the upgraded native-C Ainekio body.
- Replaced each unbounded simulator subscriber queue with a one-slot,
  latest-command-wins queue.
- Removed cached command replay when a browser connects. A command issued with no
  connected subscriber is not retained for later execution.
- Verified that a queued movement is replaced immediately by `stop`.
- Added the protocol-v1 body emulator and local gateway stub, including
  body-initiated authentication, version rejection, fixture consumption,
  sequence/lifecycle handling, portable-core safety decisions, and the initial
  `stand`, `neutral`, `walk`, and `stop` renderer path.
- Refactored repository ownership so active emulator code no longer imports the
  old Python motion package. The renderer shim lives under
  `Emulator/emulator/backends/`; the old package and scratchpad live under
  `Emulator/legacy/` and `docs/archive/` respectively.
- Four-folder layout validation: 17 active emulator/gateway tests, 19 legacy
  adapter tests, 12 protocol tests, 4 retained Megameal bridge tests, the
  portable C CTest target, and the full ESP-IDF v5.5.4 cross-build passed from
  their new paths. Python compilation and startup-script syntax checks also
  passed.

The next open simulator item is a visual-backend execution acknowledgement path;
the HTTP shim currently confirms publication, not completion inside the browser
runtime. Broader malformed-input, reconnect, saturation, and 100 ms stop-latency
coverage also remains open. Media capability adapters follow after those control
path gaps are resolved.

## First-Pass Stop Condition

The initial technical scaffold met its build, host-test, normative
partition-validation, protocol-layout, and size-report conditions. The partition
and language-neutral protocol layouts are reconciled, and the emulator consumes
the protocol fixture set through the portable core. This first-pass foundation
stop condition is complete. No robot feature drivers are part of this pass.
