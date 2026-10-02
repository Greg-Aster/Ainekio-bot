# V2 Firmware Review and Implementation Design

This document preserves the earlier implementation plan and deployment checkpoints.
Current firmware, verification counts, application hash and bench limitations are
in [Controller validation](../../Slave/software/models/v2-12servo/CONTROLLER_VALIDATION.md).

Historical calibration update: `0.6.3-p4-calibration` removed the P4 pulse-endpoint subsystem:
Min/Max fields, ordering/Home checks, stored endpoints, old NVS import code,
protocol/schema fields, endpoint UI and draft handling, and unused model endpoint
accessors. Home/channel/inversion/angle/scale are the complete joint mapping.
`body_calibration_v2` and the single compact `joint_mapping` record replace the
old formats. V1 eight-servo calibration remains separate and unchanged.

Manual and generated pulses use actual PCA9685 timer capacity. The motion
model's coupled mechanism geometry remains unchanged. See the
[assembly guide](../../Slave/software/models/v2-12servo/SERVO_ASSEMBLY.md).

At that checkpoint, the source update had not been flashed. The P4 was disconnected when a fresh
calibration export was attempted; its existing NVS remains untouched. Export
and restore the retained mapping fields before relying on automatic Home with
this format. Without saved mapping, startup leaves outputs disabled.

Validation: 25 native checks passed, including the prior motion variant's 30 finite clips, eight
continuous gait/direction combinations, compact calibration save/reload and
failure handling. Protocol/calibration and dashboard tests passed; the ESP-IDF
application rebuilt successfully. These are software checks, not hardware proof.

Restoration/review update: the selected reference is **1300 µs**, with non-inverted CAD offsets shoulder 0°, carrier +1.17° and crank −40.41°. The original motion choreography is restored. Mode handoff preserves a known Home pose; integer-pulse inverse mapping accounts for rounding; delayed dashboard replies are fenced by robot and request identity. The updated mounting references fit the recorded carrier/crank ranges within the observed pulse span at the provisional scale. Shrug and Surprised retain shoulder pulse-span conflicts; existing modeled-collision conflicts remain flagged without reducing movements. Saved device mapping is retained until physical re-indexing and explicit recalibration. See the [range findings](../../Slave/software/models/v2-12servo/mechanics/original-motion-range-audit.md). This historical update did not flash or move the robot.

## Previous deployed application and evidence

Updated: 2026-09-22. The owner authorized completing P4 firmware and Body Control,
including **all currently implemented motion controls**. Display/touch selection
and implementation remain deferred. Source `0.6.1-p4-motion` connects the model
executors to calibrated PCA output and advertises the installed motion catalog.
At this checkpoint, the P4 ran this application and advertised its motion catalog. Physical pose
and peripheral acceptance remain separate from source and transport checks.
The no-output gait calculation completes, but some updates exceed the nominal
20 ms interval. Actual PWM timing and physical pose fit remain unqualified.

This was the work tracker at that checkpoint. The numbered implementation order later in
this document is the original plan, not a claim that every physical acceptance
step has passed. Earlier electrical evidence remains in
[STEP1_EVIDENCE.md](STEP1_EVIDENCE.md); software tests do not establish physical
PWM, pose, camera or audio behavior.

| Area | Current implementation | Remaining acceptance |
| --- | --- | --- |
| Twelve-joint calibration | Live read/stage/move/home/save; versioned NVS migration preserves saved pulses; model Home angle and µs/degree; manual pulses use actual PWM capacity, motion endpoints are owner-controlled | Establish actual electrical positioning range, horn trim, direction and scale; 180° and 270° assumptions are not hardware measurements |
| Gateway and operator panel | Model/feature isolation, V1 controls preserved, actual capability updates, storage actions, paced PCM, obsolete output-test subsystem removed; flashed P4 authenticated with the running updated gateway | Exercise the panel with the physical joints |
| Provisioning | AP-only browser form, CSRF and bounded input, durable AP key, network/controller changes preserve identity | Real AP browser provisioning with the new image |
| Profiles and power | Persistent profiles, idle/doze, preflight-controlled sleep/restart, actual status; no invented voltage/current sensor | Device sleep/wake acceptance; software failure paths reviewed and tested |
| Camera and audio | OV5647 CSI/JPEG; ES8311 16 kHz mono capture/TTS/SAY; VAD and canonical shared wake engine; bounded queues and session cancellation | Physical capture/playback and combined-load acceptance |
| Storage and assets | Bounded SD logs/captures, CRC recovery, actual retry/clear results, read-only voice/wake LittleFS; full layout and asset image deployed | Real card recovery tests; no card detected on deployment |
| Display/touch | Explicitly deferred; no display backend/configuration retained | Owner hardware selection before implementation |
| Body gait/gesture execution | Stand/Neutral, algorithmic walk/crawl and compiled clip catalog connected through the single body task; async completion/cancellation and range checks; catalog visible on the flashed P4 | Nominal 20 ms calculation budget is not consistently met; qualify actual PWM cadence under load, calibrate the mechanism and reconcile motion ranges |
| V1 compatibility | Shared wire remains eight-joint; wake engine extracted once without changing the S3 behavior | Current S3 build and focused regressions passed; physical V1 behavior not exercised |

Three implementation agents worked concurrently, followed by an independent
reviewer and parent integration review. The portable core/gateway/browser tests
exercise software behavior; none count as physical robot proof. See the
[P4 target README](../../Slave/firmware/esp32p4-wifi6/README.md) for current build,
resource, calibration, storage and asset procedures.

## Motion integration verification, 2026-09-22

- `0.6.1-p4-motion` removes the generic 500–2500 µs hard cap from calibration
  across the C/Python protocol, schema, gateway, interface and firmware. Manual
  Move/trim bypass saved motion bounds; normal motion targets retain them. The
  body validates PWM representability before queuing Move or any Home channel.
  Settings remain positive uint16 values with ordered endpoints, and the device
  validates endpoints against its configured timer. Existing saved values and
  the NVS record format are preserved.
- Application `0.6.1-p4-motion` was flashed at `0x20000` with hash verification;
  the image is 4,584,416 bytes, SHA-256
  `1ec19674200fe996b55cfaa4547184b498e2243109474731cef6b44ebdab1f26`.
  Startup reported the matching version, Home ESP_OK and ready/armed with no
  output fault. Gateway readback preserved all twelve saved calibration records
  and reported timer capacity of 3–19986 µs. During the owner's subsequent
  testing, joint 1 read back a commanded 2800 µs despite its saved maximum of
  2500 µs. This confirms command acceptance, not measured shaft travel.
- Range-change checks passed the PCA driver, joint-calibration and body-executor
  native suites, 13 shared-core tests, 14 protocol/schema tests and 12 gateway
  calibration tests. The driver check covers every positive uint16 pulse at nine
  timer configurations, and invalid Move/Home requests cause no output write.
  Browser fixtures passed manual Move/trim beyond the saved maximum, explicit
  endpoint edits, Save acknowledgement handling and unchanged V1 behavior.
- The owner's linked Miuzei MG90S listing advertises 180°, and the owner reports
  unrestricted manual shaft rotation when unpowered. That does not establish
  controlled travel. The motion geometry's 270° entry and firmware's provisional
  180° pulse conversion remain conflicting assumptions; neither is a measurement.
  No angle scale, saved endpoint, or motion source was changed to hide that gap.
  After the cap removal, the owner reported an observed working pulse range of
  300–2900 µs for one servo. Its joint identity and angular travel were not stated;
  this observation does not establish calibration for all twelve servos.
- Shared-core tests: 13 passed. Protocol/schema tests: 14 passed. Focused gateway,
  calibration, storage, dashboard and V2 tests: 77 passed, including the native
  walk integration cases. P4 executor tests include injected calculation/write
  delays, Stop during motion, generation changes and exact clip range preflight.
- Isolated browser checks passed dynamic catalog rendering, crawl/turn/Finish,
  calibration mapping, V1 compatibility and visible firmware rejection details.
- Earlier application `0.6.0-p4-motion` built and flashed with hash verification. The
  image with full-cycle timing diagnostics is 4,583,792 bytes, SHA-256
  `af918b273d52e3610aa5ba3829a3ec6aa6c903980123e8c01c27ad5898ec90e5`.
  Startup Home returned ESP_OK, output ready/armed were true with no fault, and
  the gateway authenticated. Live readback preserved twelve 1500 µs Home values
  and exposed 500–2500 µs bounds plus model mapping fields. The owner has since
  saved calibration; no shaft positions are inferred from pulse readbacks.
- A browser connected to the real gateway displayed enabled poses and
  walk/crawl controls with no JavaScript exceptions. No pose or walking command
  was sent by that browser check.
- The existing no-output gait diagnostic initially measured 71,874 µs for
  begin and 90,563 µs for the first 20 ms tick. Exact support-point bounds now
  avoid exhaustive hull scans; the planner still integrates at its original
  cadence but solves joint angles once per output frame. Native checks compared
  80,000 support searches against exhaustive results and 24,818 before/after
  poses across 96 scenarios; maximum angle change was 0.000039 degrees. These
  checks do not establish physical output timing.
- A complete no-output walk entry/loop/finish on the P4 passed all 383 samples:
  begin 10,371 µs, maximum tick 25,582 µs, 215 ticks above the nominal 20 ms
  interval, completed at 7,660 ms of simulated motion. Maximum ideal completion
  spacing was 25,696 µs. This estimate excludes the output task's polling, I²C
  writes and scheduling, and is not measured PWM timing or proof of 50 Hz
  command updates. The existing 40 ms output-progress guard remains unchanged.
- The P4 sends its monotonic-clock sample every 250 ms. The former 1-second
  interval met the gateway's 1-second freshness limit with no network margin.
  Twenty consecutive live calibration readbacks passed after this change; the
  gateway's expiry check remains in force.
- Body Control Save now stages the displayed edited settings, verifies the
  returned settings, and then persists them. Polling no longer overwrites an
  edited Home when focus leaves the form. A Move target remains separate from
  Home; **Use commanded pulse as home** explicitly copies it.
- Calibration now retains the selected robot/joint, target pulse and per-joint
  drafts in browser storage across reloads and controller epochs. Resume mode
  remains explicit, and restored drafts never replay Move/Set/Save. The slider
  displays a calculated model angle from confirmed calibration and dispatches
  once after release; Stop, later commands, selection changes and page loss
  cancel an unsent slider request. Independent source review found no blocker.
  The live gateway page displayed the slider and hardware bounds with zero
  JavaScript exceptions; visual inspection confirmed full joint names after
  widening the panel. These checks sent no physical movement commands.
  The isolated browser regression passed reload/reconnect recovery with
  300–2900 µs drafts, rejected-target retention, explicit Resume, inverted angle
  mapping, one Move per release, cancellation after Detach, stale replies during
  joint/robot switching and serialized status polling. One concurrent browser
  run exceeded its 3-second wait for a delayed Move response; a sequential run
  passed without source changes, so that timing failure remains undetermined.
  Final evidence: `/tmp/ainekio-calibration-ux-check.log` and
  `/tmp/ainekio-calibration-ui.png`.
- Nominal Rest-at-midpoint calibration does not fit Point, Bow, Pushup, Shrug
  or Surprised; these are rejected before PWM. Forward/backward walking can also
  exceed the current mapping. Some catalog joint spans exceed nominal 180°;
  moving Home alone cannot make every source motion fit. Geometry is not silently
  compressed to hide this incompatibility.
  For example, Bow requests about 3,087 µs from each front carrier under the
  default mapping, exceeding 2,500 µs; a rear-left carrier trim cannot resolve
  that rejection. Disabled channels are excluded from pulse mapping, but merely
  unplugging a servo does not change its configured assignment.

Evidence: `/tmp/ainekio-p4-final-motion-build.log`,
`/tmp/ainekio-p4-final-motion-flash.log`, `/tmp/ainekio-p4-motion-boot.log`,
`/tmp/ainekio-p4-after-motion-calibration.json`, and
`/tmp/ainekio-live-motion-ui.mjs`. The no-output timing recheck is complete;
this section does not claim physical motion acceptance or measured PWM cadence.
The range-change build/flash logs are `/tmp/ainekio-p4-calibration-range-build.log`
and `/tmp/ainekio-p4-calibration-range-flash.log`; before/after settings snapshots
are `/tmp/ainekio-p4-before-range-calibration.json` and
`/tmp/ainekio-p4-after-range-calibration.json`.

## Pre-deployment system-port validation, 2026-09-22

Independent review and parent integration review found no remaining blocking
source issues after corrections to stop/cancellation ordering, power-preflight
failure recovery, driver reinitialization, complete home readback, media readiness,
SD operation completion and wake-engine recovery.

- At source-review time, P4 default and optional full-layout builds passed. The application was
  4,418,640 bytes, leaving 47% of the 8 MiB app partition free.
- Default-layout application SHA-256:
  `13e13d7944833c23138781a079e5851323a92a77c77651b930ca1ff290c62a40`.
- Full-layout application SHA-256:
  `cb4c066a9cafd8974ac38ffc7220e934cd1911c64d08eb8da5c0525449cb11b4`.
- The separate LittleFS image built and was listed: three PCM voice files,
  their audio index, and the validated local wake model/manifest only. No V1
  motions or display assets are included. Local model data remains ignored.
- Fresh S3 build passed after the shared wake extraction and final protocol
  changes: 1,511,456 bytes, 52% app-partition free.
- Shared native tests: 13/13 passed; PCA driver suite: 1/1 passed.
- Focused gateway/protocol/operator/storage/audio/V1 Python suite: 90 tests ran,
  one pre-existing skip, no failures. Asset-policy suite: 7/7 passed.
- Real headless-browser checks against an isolated simulated body passed:
  twelve-joint readback/trim/stage/save/home, upper joint 11, V1 switching,
  storage retry/confirmed clear and dynamic camera readiness; no JS exceptions.
- A disposable harness using the actual power-preflight functions passed seven
  injected failure stages, successful transitions and simultaneous-admission
  rejection. The firmware calibration validator separately passed disabled
  channels, duplicate mapping, bounds and malformed inversion checks.

Build/test logs are workstation artifacts under `/tmp/ainekio-p4-final-build.log`,
`/tmp/ainekio-p4-full-final-build.log`, `/tmp/s3-wake-final-build.log`, and
`/tmp/ainekio-body-control-python-tests.log`. Browser reproduction is
`/tmp/ainekio-body-control-ui-check.mjs`; these temporary paths are evidence for
this run, not versioned project dependencies.

Those checks preceded device deployment. Actual saved horn trim, camera/audio
operation, SD behavior and electrical/mechanical acceptance remain separate work.
At that earlier deployment, display/touch and gait execution were deferred. The
owner subsequently authorized motion integration, reflected in the current
tracker above; display/touch remains deferred.

## Device deployment, 2026-09-22

- Backed up the complete 32 MiB flash outside the repository before migration.
  Installed the full partition layout and voice/wake image with esptool hash
  verification. A readback before first boot confirmed NVS and PHY data were
  byte-for-byte unchanged.
- The first boot exposed a pre-main allocation failure on P4 revision 1.3.
  ESP-Hosted allocates transport pools before IDF makes most internal RAM
  available. Setting the SDIO TX/RX queue depths to eight in `sdkconfig.defaults`
  recovers approximately 38.44 KiB during startup, preserving task stacks and
  driver code. This configuration fix was independently reviewed and rebuilt.
  Peak media throughput with the smaller queues remains unmeasured.
- Corrected full-layout application: 4,513,136 bytes, SHA-256
  `69a6674decc36803b3bd8fbacba98d4ced6d150e3a748a6fbde1c0fb0bbde85b`.
  Application flash hash verification passed.
- Normal boot reported `0.5.0-p4-body`, `home: ESP_OK`, and PCA
  `ready=1 armed=1 fault=0 outstanding=0`. Readback showed twelve valid 1500 µs
  home channels, `saved=0 dirty=0`; joint calibration has not yet been saved in
  the new record format. These are controller reports, not observed pose proof.
- Wi-Fi connected and the selected gateway authenticated. The first connection
  attempt timed out and its retry succeeded. No further reset or panic occurred
  during the 40-second boot/status observation.
- Three voice assets and the wake model loaded. Microphone, speaker and wake
  report ready; audio capture/playback was not physically tested. OV5647 was not
  connected and SD initialization reported no available card. Gait execution and
  display remain deferred.

Workstation evidence: `/tmp/ainekio-p4-boot-fix-build.log`,
`/tmp/ainekio-p4-body-flash.log`, `/tmp/ainekio-p4-boot-fix-flash.log`, and
`/tmp/ainekio-p4-body-boot.log`. The full recovery image is private local state at
`~/.local/state/ainekio/firmware-backups/p4-before-body-0.5.0-20260922.bin`;
it contains device settings and must not be committed.

## Hardware Baseline

The owner selected twelve **MG90** servos, the ESP32-P4-WIFI6 kit, and the
**HUAREW PCA9685** breakout sold under ASIN B0CRV3MK14. The controller listing
advertises an output-enable pin. Its exact revision, pull resistors, and delivered
wiring remain unverified. MG90 is the supplied servo designation; neither an
MG90S variant nor a manufacturer, pulse range, or travel range is established.
See the [hardware record](README.md) and
[selected controller listing](https://www.amazon.com/dp/B0CRV3MK14).

The Waveshare board combines P4 with a C6 wireless coprocessor and provides
MIPI-CSI camera connectivity and onboard audio. Its schematic identifies an
ES8311 codec. These differ from V1's native S3 Wi-Fi, parallel camera, and external
I2S audio devices. The selected kit lists an OV5647 camera and speaker; installed
peripheral evidence is still pending.
[Board documentation](https://docs.waveshare.com/ESP32-P4-WIFI6),
[board schematic](https://files.waveshare.com/wiki/ESP32-P4-WIFI6/ESP32-P4-WIFI6-datasheet.pdf).

## V1 Review: Concrete Separation Work

These are compatibility obstacles to adding V2, not evidence that the existing
eight-servo robot is defective.

| Current owner | Confirmed assumption | Required separation |
| --- | --- | --- |
| [protocol.h](../../Slave/software/core/include/ainekio/protocol.h) | `AINEKIO_SERVO_COUNT` is eight; joint IDs and pose/plan arrays use V1's order. | Separate active model joint count from bounded storage capacity. Keep V1 IDs and formats stable. |
| [motion_service.h](../../Slave/firmware/esp32s3/components/ainekio_platform/include/ainekio/platform/motion_service.h) and [motion_service.c](../../Slave/firmware/esp32s3/components/ainekio_platform/src/motion_service.c) | `calibration_pending_mask`, its local copy, and shifted bits are eight-bit values. Merely raising the servo count would lose calibration requests for joints 8–11. | Use a count-aware pending representation and test the upper four joints explicitly. |
| [servo.h](../../Slave/software/core/include/ainekio/servo.h) and [servo.c](../../Slave/software/core/src/servo.c) | Angle conversion embeds Sesame's effective 732–2500 microsecond pulse range and rounding behavior. | Preserve that conversion for V1; give V2 its own measured servo calibration. |
| [runtime_service.h](../../Slave/firmware/esp32s3/components/ainekio_platform/include/ainekio/platform/runtime_service.h) and motion service | Runtime dependencies contain `ainekio_mcpwm_adapter_t *mcpwm`; motion calls MCPWM directly. | Introduce a small servo-output contract and make both board implementations use it. |
| [nvs_adapter.c](../../Slave/firmware/esp32s3/components/ainekio_platform/src/nvs_adapter.c) | Calibration stores an eight-element C array as a blob; poses use `sizeof(*poses)`. Loading validates schema and blob size. | Preserve V1 decoding. Define an explicit V2 storage format with model/joint-map identity; never reinterpret a V1 blob as twelve joints. |
| [assets.c](../../Slave/software/core/src/assets.c), [seed assets](../../Slave/software/assets/seed/), and `perform_stop()` in motion service | Fallback poses and feedback movements are V1-specific. Ordinary stop transitions to V1 stand and leaves PWM holding; detach or a failed hold disables signals. | Move V1 motion data into its model. Define V2 stop, hold, and detach behavior against its actual geometry. |
| [app_main.c](../../Slave/firmware/esp32s3/main/app_main.c) | Boot constructs the concrete S3 peripherals and can enable calibrated servo centers before networking. | Write a P4 composition root with explicit board readiness and output initialization. |
| [platform CMakeLists.txt](../../Slave/firmware/esp32s3/components/ainekio_platform/CMakeLists.txt) | One component mixes orchestration with MCPWM, camera, audio, networking, display, storage, and inference dependencies. | Extract genuinely reusable services once; keep board dependencies in their own targets. |

The boundary also crosses the shared host code:

- [joints_v1.py](../../Slave/software/protocol/joints_v1.py),
  [control_v1.py](../../Slave/software/protocol/control_v1.py), and
  [schemas](../../Slave/software/protocol/schemas/) freeze eight-joint validation.
- The [gateway service](../../Master/gateway/server/service.py) currently uses
  `motion_plan_v1` and the global joint-map definition. The
  [dashboard](../../Master/gateway/dashboard/server.py) builds calibration-neutral
  commands with `range(8)`.
- The legacy environment adapter path uses the fixed V1 motion catalog. Step 1
  adds negotiated model/readiness fields and suppresses unimplemented P4 motion
  and media capabilities. A complete twelve-joint definition remains Step 2.

A twelve-channel driver alone would therefore leave calibration, validation,
assets, and Body Control behavior incomplete.

## Recommended Code Ownership

| Owner | Responsibility |
| --- | --- |
| `Slave/software/core/` | Portable command admission, sequencing, lifecycle, bounded motion evaluation, and validation against the selected model. No ESP-IDF or FreeRTOS dependencies. |
| `Slave/software/models/v1-8servo/` | V1 joint definitions, motion assets, fallback poses, pulse-conversion compatibility, and supported body motions. |
| `Slave/software/models/v2-12servo/` | Twelve-joint definition, geometry-dependent constraints, poses, motion assets, and supported body motions. Measured device calibration remains in device storage. |
| `Slave/software/protocol/` | Wire schemas, compatibility rules, and validation. Robot model and protocol version remain separate concepts. |
| `Slave/firmware/common/` **(proposed additional owner)** | ESP-IDF orchestration that both targets actually consume: motion task, session/queue lifecycle, and reusable transport services after concrete hardware dependencies are removed. |
| `Slave/firmware/esp32s3/` | V1 startup, board resources, MCPWM, existing camera/audio hardware, and target build configuration. |
| `Slave/firmware/esp32p4-wifi6/` | P4 startup, board resources, PCA9685, C6 host integration, OV5647 capture, ES8311 audio, and target build configuration. |
| `Master/gateway/` and `Emulator/` | One shared Body Control service and host runtime, selecting the connected model's capabilities and the appropriate simulator backend. |

The proposed `firmware/common/` location keeps ESP-IDF services out of the
portable core. Create it only with real extracted consumers. Its code must not
include S3 pin maps or import anything from the S3 target. P4 must never obtain
shared services by compiling source files out of `esp32s3/`.

Use a few concrete interfaces, beginning with servo output, audio, and camera.
Do not build a general plugin framework. During each extraction, move ownership,
update V1's consumer and its checks, and remove the superseded implementation in
the same change. Avoid duplicate service copies, forwarding wrappers, and
board-selection conditionals spread through the runtime.

### Model and Protocol Contract

- Preserve V1's joint order `R1,R2,L1,L2,R4,R3,L3,L4` in `joints_v1.py`.
  V2 needs its own twelve names, axes, directions, and channel assignments from
  the final frame. Do not derive them by appending four joints to V1.
- Distinguish device ID, model ID, board ID, firmware version, wire version,
  joint-map version, and active joint count. Define their handshake fields and
  compatibility behavior together in the protocol change.
- Preserve the frozen V1 schema and assets. Add an explicitly negotiated joint
  definition for V2; do not silently widen `motion_plan_v1`'s existing eight-joint
  contract. Select a new payload version if its layout or meaning changes.
- Bound storage and message sizes independently of active joint count. Test
  both complete models, wrong-model payloads, invalid channels, and oversized
  input. Sixteen PCA outputs do not make this a sixteen-joint robot.
- Derive Body Control calibration controls and advertised semantic capabilities
  from the selected body's definition and readiness. Keep an explicit legacy V1
  connection path; reject an unknown model instead of guessing V1.
- Keep raw joint calibration in the authorized operator path. MetaHuman receives
  semantic robot commands governed by the body's supported capabilities and
  firmware admission rules.
- Version stored calibration and poses independently of C structure layout.
  Include model ID, joint-map version, joint count, and validated per-joint data.
  Invalid V2 calibration must report unready, not load V1 defaults or invent a
  twelve-servo neutral pose.

### Twelve-Joint Motion Definition

For the initial implementation, use **predefined joint trajectories executed on
the P4**. The V2 model owns these trajectories and their leg coordination; the
portable core owns interpolation and limit validation; the firmware motion task
owns timed execution. The gateway selects a semantic motion and sends its bounded
request or complete supported trajectory. Individual steps never depend on
timely network messages. Inverse kinematics is a later owner decision: if added,
it belongs to V2 motion generation and must produce trajectories accepted by the
same validator and executor. Do not create a second motion loop or speculative
IK interfaces now.

Before implementing walking, the model definition must contain:

| Field | Required meaning |
| --- | --- |
| Joint identity | Twelve stable IDs, leg membership, axis, and unique PCA channel; reserve unused channels explicitly. |
| Geometric zero and sign | A documented reference pose and link/axis convention for each joint, with the positive direction shown against the frame. Mirrored joints have explicit signs. Geometric zero is distinct from servo electrical center. |
| Units | V2 positions use signed centidegrees relative to geometric zero; speed uses centidegrees/second and acceleration uses centidegrees/second². Asset durations use milliseconds; scheduling uses a monotonic clock. Preserve V1's existing units and encoding through its own versioned contract. |
| Position and pulse limits | Mechanical joint range, calibrated pulse endpoints/zero/direction, and the narrower permitted operating range. Validate the intersection of model constraints and device calibration. |
| Dynamic limits | Per-joint maximum speed, acceleration, and braking acceleration, with measured values recorded before walking. Unset limits make the motion unavailable. |
| Trajectory behavior | Continuous position/velocity, bounded acceleration, synchronized leg phases, and checked transitions into/out of poses. Validate interpolated segments and braking, not just keyframe endpoints. |

Ordinary stop should brake the commanded trajectory to a hold within the timing
target below, subject to validated joint limits and clearance. Select initial
motion speeds so their braking envelope fits that target; do not assume that
holding the current commanded position is mechanically safe in every pose.
Emergency disable bypasses trajectory braking. Neither interpolated position
nor accepted PWM is measured leg position.

## P4 Platform Integration

### Build and Wireless

Use a native `esp32p4` ESP-IDF target with its own `app_main`, component manifest,
resolved dependency lock, partition layout, and SDK configuration. Start from
**ESP-IDF 5.5.4**: V1 pins it already, and Waveshare recommends it for this board.
Confirm the delivered P4 silicon revision before choosing revision-specific
configuration. Waveshare distinguishes engineering samples below revision 3.0
from production 3.x parts; a successful build does not establish a flashable
match. [Waveshare ESP-IDF guide](https://docs.waveshare.com/ESP32-P4-WIFI6/ESP-IDF).

Treat P4 host software and the onboard C6 firmware as a compatibility unit.
Waveshare's IDF 5.x examples select `esp_wifi_remote` 0.14.x with `esp_hosted`
1.4.x; its IDF 6.x lane uses different versions. Resolve and pin exact releases
and the matching C6 image during the first P4 build. Do not combine whichever
registry versions happen to be newest. The vendor's published CI checks builds,
not physical SDIO or Wi-Fi operation.
[Vendor host/C6 compatibility guide](https://raw.githubusercontent.com/waveshareteam/ESP32-P4-Platform/main/docs/P4_C6_HOSTED_WIFI.md).

**Resolved for the delivered board:** P4 silicon 1.3, ESP-IDF 5.5.4,
`esp_hosted` 2.12.8, `esp_wifi_remote` 1.6.4 and C6 Hosted 2.12.8 in SDIO packet
mode. The older vendor 1.4.0/0.14.0 pair failed to build against this IDF because
of changed Wi-Fi structure fields. The selected pair builds without modifying
managed dependencies; the real C6 was updated through SDIO and reports 2.12.8.
Exact locks and a reproducible C6 build belong to the native target.

Keep Ainekio's authentication, discovery, provisioning, reconnect, and bounded
WebSocket transport contracts. The P4 target owns C6 transport initialization,
reset/recovery, and connectivity readiness. Validate both station operation and
the setup AP/portal flow on the actual board before declaring networking ready.

### Board Buses

Have one board resource owner create each I2C bus and pass device handles to its
consumers. Reserve onboard camera, codec, SD, and C6 resources before selecting
the PCA9685 pins. The schematic labels the onboard I2C pair GPIO7/8; that is
board-reference information, not an approved external servo-controller wiring
assignment. [Board schematic](https://files.waveshare.com/wiki/ESP32-P4-WIFI6/ESP32-P4-WIFI6-datasheet.pdf).

Use ESP-IDF's current `driver/i2c_master.h` bus/device API consistently. The
legacy I2C driver cannot coexist with it. The documented P4 master supports up
to 400 kHz; a faster peripheral rating does not establish a faster P4 bus.
[ESP-IDF 5.5.4 I2C documentation](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32p4/api-reference/peripherals/i2c.html).

### Servo Output and Failure Behavior

The PCA9685 has sixteen 12-bit outputs, one shared PWM frequency, an internal
oscillator, and active-low OE. OE can disable outputs independently of an I2C
write; its disabled output level depends on configuration. Register updates can
use auto-increment and apply on I2C STOP. Configure sleep/prescale/restart timing
and output mode according to the datasheet.
[NXP PCA9685 datasheet](https://www.nxp.com/docs/en/data-sheet/PCA9685.pdf).

Recommended implementation:

1. The motion task remains the sole writer of pulse frames for movement and
   calibration. It passes a complete, validated pulse frame to the output backend. Geometry,
   angles, and calibration stay outside the PCA register driver. Emergency
   disable has a separate direct path, described below.
2. Initialize with OE disabled, configure the device, and mark unused outputs
   fully off. Ordinary body motion requires valid model calibration and an
   authorized initial frame. Initial operator calibration may enable one selected
   joint within confirmed pulse bounds while all others remain off. Power
   cycling must not resume an old movement.
3. Convert pulse durations using the configured oscillator/frequency and explicit
   bounds. A provisional 50 Hz frame would have a nominal 4.88 microsecond step
   (`20,000 / 4096`); confirm MG90 timing and measure actual pulses before using
   this as calibration evidence.
4. Write each full frame within the timing budget below. On timeout or partial
   failure, invalidate the frame, latch hardware output disable, and report the
   fault. Recovery returns to disabled readiness and requires explicit re-arming
   with a fresh authorized frame.
   Do not report successful motion because a frame was merely queued.
5. Use the advertised OE connection as a separate GPIO-controlled disable path,
   after checking the delivered breakout's pull resistors and reset behavior.
   A bus fault can leave the independent oscillator producing the previous PWM;
   this is an engineering inference from the chip's operation. An I2C-only
   all-off command therefore cannot prove outputs stopped after an I2C failure.
6. Apply the model's validated braking/hold behavior for ordinary stop. V1's
   stand-on-stop pose does not transfer to V2. Until V2's hold and pulse-loss
   behavior are measured, perform motion tests with the body mechanically
   supported; do not advertise loaded walking readiness.

### Emergency Disable, Reset, and Progress Monitoring

The board's output gate owns OE and a latched fault state. Emergency disable
must latch the fault and drive OE high directly, without waiting for the motion
queue, an I2C transaction, a bus mutex, network transmission, or logging. Only
this gate can enable outputs. A short cross-core critical section must serialize
the latch, arm-generation counter, and OE writes; it must never cover blocking
work. Normal frame writes and completion callbacks cannot lower OE.

Every arm attempt and in-flight operation carries the current generation.
Disable invalidates it. Preparing an initial frame happens with outputs disabled;
the final enable checks the generation and latch atomically. A late transaction,
retry, callback, or interrupted arm attempt cannot clear the latch or re-enable
outputs. Re-arming requires fault clearance, successful device checks, valid
calibration, a fresh frame, and explicit operator authorization after an output
fault. Before preparing that frame, drain or cancel old transfers and prove that
no old writer can still reach the device. Generation checks alone cannot undo
an I2C write already in progress. Test disable during each arm/transfer/completion
boundary on both cores, including a delayed write completing during recovery.

Require an electrically verified disabled state throughout reset: OE held high
by the actual circuit while P4 pins are unconfigured, with PCA outputs configured
to an inactive low level. Check cold power-up, software reset, watchdog reset,
brownout, and P4 restart while the PCA/servo supply stays powered. Capture OE and
servo signal traces across the full interval; an application log or GPIO readback
cannot establish absence of a transient pulse. Resolve conflicting breakout
pull resistors and power sequencing before enabling servos.

While outputs are armed, the motion task must publish a monotonic progress
counter/time only after a complete validated output frame from the current
generation succeeds, including periodic hold frames. A separate supervisor checks frame age and in-flight
transfer deadlines. A running timer, network heartbeat, or busy loop is not
motion progress. The supervisor must remain runnable when the motion task is
blocked and use the direct disable path without acquiring its locks.
This detects failed software/output progress, not a mechanically jammed servo
whose frame writes still succeed; position/current sensing has not been selected
to detect that condition.

Also register the motion progress path with the task watchdog. Feed it from that
path, not from an unrelated task; when disabled, feed only after the motion loop
has verified its disabled/idle state. Explicitly configure panic/reset behavior,
including `CONFIG_ESP_TASK_WDT_PANIC` or the runtime `trigger_panic` setting and
the production panic action. ESP-IDF documents that the default task-watchdog
timeout can warn and continue. Interrupt watchdog and reset behavior must cover
loss of supervisor scheduling as well. Perform acceptance tests without JTAG,
which can disable watchdogs.
[ESP-IDF 5.5.4 watchdog documentation](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32p4/api-reference/system/wdts.html).

The whole-MCU-stall deadline below requires hardware evidence. If the P4's
watchdog/reset path cannot meet it, an independently timed OE-disable circuit
must be selected and verified before loaded tests. A software supervisor alone
cannot satisfy that case; the selected board has not yet demonstrated this
behavior.

### Timing and Failure Contract

These are **proposed V2 acceptance targets**, not measured results or MG90
ratings. They do not change V1. Record actual minima/maxima, missed deadlines,
and test conditions; revise an unattainable target explicitly before accepting
the implementation. Output-disable deadlines refer to loss of PWM at the servo
connector, not to mechanical stopping or removal of torque.

| Quantity | Proposed limit and measurement boundary |
| --- | --- |
| Motion update interval | 20 ms; one synchronized twelve-joint frame per tick. This follows the current core's tick as a starting point; servo PWM frequency is a separately verified setting. |
| Frame I2C budget while armed | At most 5 ms from requesting the bus through completion, including contention and retries. No unbounded waits. Measure actual elapsed time, including RTOS tick rounding; setting a 5 ms driver argument alone is insufficient. |
| Tolerated missed updates | One missed 20 ms update at most. At 40 ms since the last successful frame, latch a progress fault. |
| Supervisor interval and stall response | Check at least every 5 ms; outputs disabled within 50 ms of the last successful frame when progress stops. |
| Direct emergency disable | At most 1 ms from entry to the board disable path to inactive servo signals, including contention in the gate's critical section. This excludes remote command delivery time. |
| I2C fault response | Disable within 1 ms of an observed transfer error; if a transfer hangs, disable within 15 ms of its start via the independent deadline check. |
| Watchdog fallback | Propose a 100 ms motion-progress watchdog timeout, panic/reset enabled. For whole-MCU stalls, require inactive outputs within 250 ms of last valid progress via a verified watchdog/reset path or independent hardware gate. |
| Pending movement expiry | Discard a movement that has not started within 1,000 ms of P4 admission, or earlier if its accepted remaining validity ends. Use monotonic time. This local queue limit does not prove end-to-end freshness; the protocol change must retain upstream expiry and reject unverifiable/expired deadlines rather than restart their lifetime on receipt. Stop/disable requests are not delayed behind expiring movement. |
| Network liveness | Retain the current 1 s control heartbeat / 4 s silence threshold unless separately revised. Check staleness at least every 5 ms: detection is due within 4.005 s of the last valid control message. A reported disconnect need not wait for this threshold. |
| Ordinary stop / network-loss stop | Start local braking within 20 ms of detection/admission; reach the validated commanded hold within another 200 ms. If that cannot be done within joint limits, disable outputs and latch a fault. Allowing for stale detection, require hold or disable within 4.23 s of the last valid control message. |

The I2C API permits an infinite wait with `xfer_timeout_ms = -1`; prohibit that
in the armed path. Bus recovery and device reinitialization run with outputs
disabled. If shared-bus contention cannot meet the frame budget, resolve bus
ownership/scheduling or use a suitable separate bus before accepting the design.
[ESP-IDF I2C transfer API](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32p4/api-reference/peripherals/i2c.html).

Run trajectories from a local monotonic schedule with one shared phase for all
joints. After a single missed update, retain the last output and retime the
remaining trajectory with validated velocity/acceleration continuity. Advance
by at most one normal trajectory step per update; never burst overdue frames or
jump to a wall-clock position to catch up. At the 40 ms fault threshold, discard
the remainder. Recovery starts a newly admitted trajectory from a validated
starting condition; it cannot resume an interrupted plan.

| Event | Response | Restart condition |
| --- | --- | --- |
| Wi-Fi/WebSocket loss or stale control | Reject new movement, cancel queued/active work, and execute the bounded local braking/hold if motion and outputs remain healthy. Escalate to disable if they are not. | Authenticated healthy control and a fresh, unexpired command from a validated starting condition. Reconnection alone never resumes a plan. |
| Motion-task stall / overdue trajectory | Supervisor latches disable by the progress deadline and invalidates the active operation. Watchdog reset is the fallback. | Cause resolved, output/calibration checks passed, explicit re-arm, and a fresh command. |
| I2C NACK, timeout, partial write, or deadline overrun | Latch direct OE disable independently of bus completion; mark output state uncertain until reinitialization. | Successful disabled-state bus/device checks, full fresh frame, explicit re-arm. No automatic retry can enable outputs. |
| Reset, brownout, or whole-MCU stall | Hardware gate/reset behavior establishes inactive signals; startup remains disarmed and forgets pending motion. | Stable rails, verified disabled boot, valid calibration and peripheral readiness, explicit arm authorization. |
| Explicit emergency disable | Immediately latch OE disable and invalidate all arm/operation generations. | Fault/stop clearance and explicit re-arm after readiness checks; a late completion is never authorization. |

### Power and Servo Evidence Before Loaded Motion

OE disables control signals; the servo rail stays powered. Verify the actual
MG90 units' behavior on pulse loss while safely supported: hold/release/drift,
current draw, time to respond, and motion when signals return. Repeat for the
planned load and supply conditions; neither assumed freewheeling nor assumed
holding is an acceptable basis for the stop policy.

Loaded-leg and whole-body tests require a recorded power check covering:

- Servo supply voltage and sustained/transient capacity against the intended
  simultaneous motion and credible fault load, using the exact servo variant.
- Distribution wire, ground return, connectors, breakout traces, and protection
  ratings. A board input-voltage rating is not its twelve-servo current capacity.
- Peak current and minimum voltage at the supply, breakout, and farthest servo
  during startup and coordinated movement, including P4/C6 rail behavior. Check
  with a controlled load/support fixture before allowing the body to bear load.
- Voltage sag, resets, heating, and signal-loss/re-enable response within the
  recorded component and calibration limits. Missing ratings or failed
  measurements keep loaded movement unavailable.

Firmware receipts must distinguish an applied output frame, a completed or
aborted trajectory, and an observed physical result. A successful controller
write or schedule completion never confirms that a leg reached its target.

### Camera and Audio

For the OV5647, build a P4 capture pipeline around `esp_video` and its sensor
support. Raw MIPI capture, ISP processing, and JPEG encoding replace V1's
`esp_camera` JPEG acquisition. Espressif documents separate capture and JPEG
devices on P4. Select pixel formats against the actual silicon revision; some
JPEG formats require ECO3. Keep Ainekio's JPEG wire framing and bounded payload
size rather than adopting the vendor example's HTTP server.
[Espressif video component](https://components.espressif.com/components/espressif/esp_video/versions/2.4.1/readme),
[camera sensor architecture](https://docs.espressif.com/projects/esp-video-components/en/latest/esp32p4/ESP_Camera_Sensor/cam_sensor_driver.html).

The vendor video example uses `esp_video` 2.x. Resolve its sensor dependencies
together in the P4 lockfile; component availability is not proof that the complete
application builds or captures correctly.
[Vendor video manifest](https://raw.githubusercontent.com/waveshareteam/ESP32-P4-Platform/main/examples/esp-idf/17_simple_video_server/main/idf_component.yml).

For audio, implement ES8311 control and the board's I2S/amp wiring through
`esp_codec_dev`. Its ES8311 support includes record and playback. Keep the current
16 kHz, 16-bit mono transport and 20 ms/640-byte microphone frames; configure or
convert at the hardware boundary as required. Do not copy V1's external microphone
and amplifier pin configuration. Wake/VAD readiness needs its own P4 build and
runtime evidence; the presence of P4 library files is insufficient.
[Espressif codec component](https://components.espressif.com/components/espressif/esp_codec_dev/versions/1.6.2/readme),
[vendor codec manifest](https://raw.githubusercontent.com/waveshareteam/ESP32-P4-Platform/main/examples/esp-idf/12_I2SCodec/main/idf_component.yml).

### Runtime Behavior to Preserve

The current [runtime service](../../Slave/firmware/esp32s3/components/ainekio_platform/src/runtime_service.c)
already owns bounded queues, sequence/session correlation, command dispatch,
stop handling, and transport failure cleanup. Preserve those semantics when
extracting reusable services. Measure P4 task stack sizes, scheduling, memory,
and contention under simultaneous motion, camera, audio, and Wi-Fi load; S3 task
affinities and buffer budgets are starting evidence, not automatic P4 settings.

Retain action-correlated camera metadata and distinguish reported command
completion from camera observations and physical pose. Preserve the current
battery telemetry/warning-only policy; do not revive older software cutoff logic
while moving code. New P4 display, battery sensing, storage, and sleep support
must reflect selected hardware and advertise their actual readiness.

## Controller Admission and Optional Q6A Deployment

The P4 owns body hardware, local trajectory execution and safety regardless of
where the controller runs. An optional Ubuntu Q6A provides selected processing
services; running STT, TTS, vision or an LLM does not confer body-command authority.
Individual Q6A services require later performance/readiness milestones.

### Existing owners and the necessary foundation changes

| Boundary | Existing owner retained | Step 1 change |
| --- | --- | --- |
| Body authentication and session | `Master/gateway/server/service.py`: robot token, authenticated connection replacement, epoch, sequence, ACK/DONE/cancelled correlation and action age | Optional `command_deadline_v1` adds epoch and a conservative deadline anchored to the body's reported monotonic clock. Legacy V1 wire messages are unchanged. |
| Coordinator action ownership | `environment_adapter/server.py` and existing `action_receipts.py`: action ID, `bodyLease` bodyId/executionId/generation, persistent cancellation and gatewayInstance/robotId/epoch/sequence correlation | Retained. Step 1 changes capability readiness only; it does not create a second coordinator, receipt database contract or Q6A-specific adapter. |
| Portable body command decisions | `core.c`, `control_codec.c`, configuration/provisioning owners | `core/admission.c` wraps the existing lifecycle with authenticated session generation, epoch, deadline, queue age and allowed-command checks. It imports no network, USB or host-location code. |
| Transport to admission | Native P4 `main/controller.c` | One WebSocket client decodes complete bounded messages, identifies the current connection and submits commands through admission. STOP also reaches the independent output gate immediately after current-session authentication. |
| Hardware output | Native P4 `components/ainekio_pca9685` and `main/board.c` | A separate output generation invalidates queued and in-flight arm/recovery operations. Neither new hosts nor network reconnection clear a fault. |

All movement and calibration requests reach the common decoder/admission path.
Step 1 allows mode selection, STOP and operator output diagnostics; it rejects
actual body motions and joint calibration because the V2 model is not ready.
Adding twelve-joint motions later requires model validation/execution behind
this same admission path. It must not introduce transport-specific movement.

`body_capabilities_v1` reports model `v2-12servo` and explicit false values for
motion/camera/microphone/speaker. The adapter advertises only ready features.
V1 retains its existing eight-joint validation and legacy capability behavior.

### Deployment choices and one authority

| Deployment | Selected body-command authority | Processing services |
| --- | --- | --- |
| Remote only | Existing gateway and coordinator on the remote computer | Existing remote providers; Q6A absent |
| Remote coordination with Q6A processing | Same remote coordinator and gateway | Selected health-checked Q6A providers return transcripts, audio, observations or model results to their existing consumers; they never open a body-command channel |
| Future Q6A coordinator | Explicitly select the existing gateway/coordinator deployed on Q6A | Local or remote providers using the same contracts; disable the old coordinator deployment before migration |

The P4 stores one `endpoint_url` and robot credential pair. The operator changes
the selected endpoint with `config controller <ws(s)://host:port/robot>`; commit
quiesces the old controller, latches output disable and restarts. There is no
automatic failover or discovery-based takeover. Ordinary reconnects retry only
that endpoint, replace the session, reset mode to normal, reject old epochs and
local connection generations, and require fresh commands. Gateway epochs may
restart when the gateway moves; the P4's local generation still fences old work.

The gateway remains the single body-wire authority for both the coordinator and
authenticated operator controls. The existing adapter replaces its environment
connection on authenticated takeover; `bodyLease` and receipt fencing remain
the execution-ownership checks. Processing workers must not share coordinator
credentials or independently issue movement. Future automatic failover needs an
explicit authority/evidence design and is outside this foundation.

Body deadlines use an observed P4 clock, remaining upstream validity, a 1,000 ms
maximum dispatch window and a 5 ms margin. While a sample is cached, the gateway
adds the measured monotonic time since receiving it and subtracts command age
at the same instant. It does not estimate or compensate for network delay.
Old clock samples are refused. The body checks expiry again and limits local
queue age to 1,000 ms; network transit
does not start a fresh lifetime. Cancellation and results retain action ID at
the adapter and epoch/sequence at the body. Local connections do not bypass these
checks. Plain LAN WebSocket retains the existing trusted-LAN server assumption;
WSS verifies the server certificate. A future USB adapter must establish the
same authenticated selected session before using admission; USB attachment alone
must not authenticate a controller. No USB command stubs or plugin framework
have been added.

### Smallest later service deployment changes

- Gateway binding, port, private data directory and environment session already
  belong to `Master/gateway/server/__main__.py`. Deploy this existing entry point
  on Q6A when selected; do not fork a second gateway or move safety into it.
- `Master/gateway/plugins.py` already assembles bounded microphone utterances,
  accepts a transcription callback and delivers camera frames. Preserve its
  20 ms PCM transport and complete-utterance STT input.
- In the inspected MetaHuman checkout, Whisper and Kokoro providers call
  `getVoiceServiceUrl()` from `packages/core/src/voice-service-manager.ts`.
  That owner currently constructs `http://127.0.0.1:<port>` and manages local
  processes. Remote Q6A providers therefore need a configurable endpoint and an
  externally-managed lifecycle in **that existing owner**, plus provider health
  checks. This is not already an all-configuration deployment; no MetaHuman files
  were changed here. Vision and LLM backends need their own compatibility and
  measured throughput review before selection, including ARM64/accelerator
  support. Do not assume desktop CUDA packages will run on Q6A.
- Keep service URLs, credentials, deadlines, cancellation and correlated request
  IDs in the existing provider/coordinator owners. Bound queues and reject
  overloaded/unready providers. Advertise STT/TTS/vision only after their health
  and model readiness checks pass, not merely because Ubuntu booted.

### Q6A absence and physical reservation

P4 startup, disabled boot, output supervision and watchdogs never wait for Q6A.
When Q6A processing is absent, booting, overloaded or disconnected, the remote
coordinator either uses an already configured ready provider or reports that
operation unavailable; delayed results cannot issue expired movement. A future
healthy body executes an already admitted bounded trajectory locally. In this
Step 1 target, loss of the selected controller or stale control immediately
latches disable; ordinary joint braking remains Step 3. Stale control keeps the
authenticated WebSocket open for audio, video, status and telemetry. A fresh
control frame can restore admission on that same generation and epoch without
clearing the physical stop or replaying queued work. An actual transport loss
uses the existing reconnect/paired-host selection owner while P4 stays disarmed.
Restored connectivity is never an instruction to resume an interrupted operation.

Start Q6A integration over the existing network transport. Preserve P4 native
USB HS on P1 (MX1.25: pin 1 VCC_5V, 2 D−, 3 D+, 4 GND), with **P4 as device and
Q6A Type-A as host**. P4 Type-C is CH343P debug UART; Q6A Type-C is its PD power
input. The P4 schematic connects P1 VBUS to its 5 V rail: determine isolated
VBUS sensing/single-source power and verify no backfeed before making that USB
cable. Connector continuity, electrical behavior and USB enumeration on the
delivered boards remain unverified. GPIO24/25 for the alternate native USB FS
port are also reserved.
[P4 schematic](https://files.waveshare.com/wiki/ESP32-P4-WIFI6/ESP32-P4-WIFI6-datasheet.pdf),
[Q6A USB roles](https://docs.radxa.com/en/dragon/q6a/hardware-use/usb).

The power budget must include the Q6A's 12 V PD input/regulator losses, storage,
USB loads, cooling fan, measured idle/peak processing current and startup surge,
in addition to P4/C6 and the separate servo rail. Record minimum rail voltages
under simultaneous processing and servo movement. Add the board, storage,
heatsink/fan, regulator, cables and mounts to chassis mass, center of gravity and
leg-load calculations; reserve airflow and connector access. Numeric supply,
cooling and load margins remain unset until parts and measurements are available.
[Q6A power documentation](https://docs.radxa.com/en/dragon/q6a/hardware-use/power-header).

## Recommended Implementation Order and Acceptance

Prove the board and disable path early, then extract shared services in small
working steps. Each stage uses the intended P4 target and real driver ownership;
bench diagnostics must not become a parallel demo firmware or duplicate runtime.
Complete integration still includes media and Body Control.

| Step | Concrete result | Acceptance evidence |
| --- | --- | --- |
| 1. Prove the P4 board and disable path | Native target, board resource owner, matched C6 integration, initial real PCA9685 driver/output gate, and diagnostic entry points. | Identify silicon; build/flash/cold-boot the P4; verify C6 station and setup-AP operation. With servos disconnected initially, measure PWM/OE across bus faults, interrupted arming, stalls, and resets. Complete this hardware proof before broad shared-runtime extraction. |
| 2. Extract the needed shared owners and integrate the model contract | V1 model/output separation, portable V2 joint contract, shared motion/session services, negotiated host capabilities, calibration UI/storage, provisioning, and authenticated connection. | Preserve V1 wire/assets/NVS behavior and pass core/host tests plus a fresh S3 build. Test joints 8–11, model/asset mismatches, expired work, and fault/re-arm races. Build the P4 using these same shared owners. |
| 3. Calibrate and prove basic mechanics | Confirmed MG90 limits, per-device calibration, predefined joint trajectories, bounded braking, and measured supply/pulse-loss behavior. | Test individual joints, a mechanically supported leg, and basic synchronized twelve-joint movement before full media integration. Record clearance, speed/acceleration/braking limits, local execution during network delays, and the power gate before any loaded movement. |
| 4. Complete media and repeat motion/fault acceptance | Camera/JPEG, microphone, speaker, implemented wake/VAD features, storage/diagnostics, bounded transport, and truthful readiness. | Capture/playback/recording evidence and action-image correlation. Repeat the same timing, stall, disconnect, I2C, disable/re-arm, and reset tests under simultaneous camera/audio/Wi-Fi load. |
| 5. Accept complete V2 body behavior | Model-specific semantic motions and host simulation, followed by the complete physical integration. | Progress from supported coordination to loaded standing/walking only after mechanical, pulse-loss, and power checks pass. Record physical observations separately from controller receipts; advertise only accepted capabilities. |

Remaining hardware inputs are the exact MG90 variant and supplier, servo
voltage/pulse limits, twelve joint axes/channel map,
delivered PCA9685 OE/pull-up wiring, and V2 power topology. Model separation,
PCA9685 driver implementation, and P4 build work can proceed with explicit
configuration and readiness checks. Final wiring and calibrated body motion
require those hardware inputs; software checks alone cannot establish physical
readiness.

## Validation Evidence

Current implementation/build/live-network results and all outstanding hardware
evidence are in [STEP1_EVIDENCE.md](STEP1_EVIDENCE.md). The historical review
checks below describe the starting baseline, not the current acceptance state.

The initial source review on 2026-09-15 performed these checks:

- Configured and built the current portable C core with the host compiler;
  **12/12 CTest tests passed**.
- Ran the Python protocol suite; **13/13 tests passed**.
- Inspected the S3 composition, motion/output, storage, media, runtime, and host
  model assumptions described above.
- Reviewed the linked vendor, Espressif, and NXP documentation on 2026-09-15.

Reproduction commands, from the repository root:

```bash
cmake -S Slave/software/core -B /tmp/ainekio-v2-firmware-review-20260915/core
cmake --build /tmp/ainekio-v2-firmware-review-20260915/core -j2
env PYTHONDONTWRITEBYTECODE=1 /usr/bin/ctest --test-dir /tmp/ainekio-v2-firmware-review-20260915/core --output-on-failure
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=Slave/software python3 -m unittest discover -s Slave/software/tests/protocol -v
```

The absolute CTest path avoids a broken user-local Python wrapper on this host.
There was no fresh S3 cross-build, P4 build, flash, or physical test in this
review. Passing these host tests establishes the current baseline only.

The requirements revision before Step 1 checked official watchdog/I2C/PCA9685
documentation and the current tick/liveness constants. That revision changed
documentation only. The subsequent Step 1 implementation and evidence are
recorded separately above; its timing targets still require electrical proof.
