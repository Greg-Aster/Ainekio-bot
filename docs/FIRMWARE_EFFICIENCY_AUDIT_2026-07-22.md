# ESP32-S3 Firmware Efficiency Audit

Date: 2026-07-22  
Reviewer: Robot Police  
Target: `Slave/firmware/esp32s3`, including the current uncommitted revisions  
Status: Software findings remediated; build, flash, gateway, camera capture, and audio timing verified; physical audio and broader hardware soak remain pending

## Purpose

This audit reviews the active ESP32-S3 firmware for resource hazards, expensive
background work, partial-start failures, obsolete implementation patterns,
duplicate logic, and firmware-only dead weight. The target board has 16 MB flash
and 8 MB PSRAM, but internal RAM and task stacks remain substantially more
constrained than flash.

The intended remediation is to streamline the existing services. It does not
require a parallel runtime, replacement architecture, or additional long-lived
service. Some small cleanup helpers and diagnostic measurements may be added,
but the runtime should finish with fewer unnecessary wakeups, more usable
internal RAM, and fewer invalid partial-start states.

## Current Verified Baseline

- The current firmware builds under the repo-pinned ESP-IDF v5.5.4 toolchain.
- The local-discovery application binary is `0x158250` bytes (1,409,616),
  leaving `55%` of the 3 MiB OTA application slot free. Compared with the
  1,375,520-byte pre-discovery build, DNS-SD adds 34,096 bytes (about 2.5%).
- The linked mDNS component accounts for 28,838 bytes of flash and 2,346 bytes
  of static RAM. It is trimmed to the upstream minimum of two interface slots,
  one service, an eight-entry action queue, station-only networking, and no CLI
  or multiple-instance support.
- Linked DIRAM use is 218,703 of 341,760 bytes (`63.99%`), leaving 123,057 bytes
  before dynamic task stacks, WiFi, TLS, DMA, driver allocations, and other
  runtime heap use.
- Static BSS is 117,632 bytes.
- The portable core passes strict compilation and all 11 host tests.
- `git diff --check` passes.

These results confirm that application flash is healthy. They do not prove
runtime memory headroom, task-stack safety, CPU idle time, or stability under
concurrent camera, audio, WebSocket, SD, and motion workloads.

## Findings

### F1 - Critical: wake-manifest loader exceeds the main-task stack

[`read_manifest`](../Slave/firmware/esp32s3/components/ainekio_platform/src/wake_word_service.cpp#L156)
contains a 4,097-byte local array. The current compiled function reserves 4,176
bytes of stack. The configured main-task stack is 3,584 bytes, and ESP-IDF adds
512 bytes for the selected newlib configuration, producing an effective 4,096
byte stack.

The function frame alone is therefore 80 bytes larger than the complete main
task stack, before its callers and other live local variables are counted. The
normal boot path reaches it synchronously through
[`app_main`](../Slave/firmware/esp32s3/main/app_main.c#L209), runtime startup,
audio startup, and wake-word startup when LittleFS is mounted. The compiled
frame is entered before `fopen()` returns, so a missing manifest does not avoid
the overrun.

Expected improvement after correction:

- Eliminate a deterministic boot-time stack corruption/reset path.
- Restore measurable main-task stack headroom.
- No meaningful CPU cost is expected.
- Moving this temporary manifest storage to heap or PSRAM should have little or
  no application-flash impact.

### F2 - High: cold data consumes excessive internal static RAM

The global
[`ainekio_asset_store_t`](../Slave/firmware/esp32s3/components/ainekio_platform/include/ainekio/platform/asset_store.h#L45)
occupies 49,572 bytes of internal BSS. It embeds all motion, face, and audio
indexes plus a 16 KiB motion I/O buffer. The
[`ainekio_audio_service`](../Slave/firmware/esp32s3/components/ainekio_platform/src/audio_service.c#L37)
singleton occupies another 24,056 bytes.

Together these two objects use 73,628 bytes, or 62.6% of all static BSS. The
existing runtime service correctly places its large runtime buffers in PSRAM;
the asset store has not yet adopted the same separation between cold storage
and internal real-time state.

Expected improvement after correction:

- Moving only the motion I/O buffer releases approximately 16 KiB of internal
  RAM.
- Separating the cold asset indexes can release substantially more. A realistic
  target is 25-45 KiB total internal-RAM recovery, subject to a new linker map.
- Audio DMA and latency-sensitive state should remain internal unless hardware
  testing proves otherwise. The objective is not to move everything blindly.
- More internal free space and a larger contiguous block should reduce startup
  allocation failures and improve WiFi/TLS/camera coexistence.

The exact recovered amount cannot be verified until the implementation is
built and measured with `idf.py size` and `idf.py size-components`.

### F3 - High: failed startup can leave orphan tasks and initialized hardware

[`ainekio_runtime_start`](../Slave/firmware/esp32s3/components/ainekio_platform/src/runtime_service.c#L2349)
starts motion, display, camera, transmission, dispatcher, and supervisor work in
sequence. If a later task creation fails, the function returns
`ESP_ERR_NO_MEM` without stopping work that already started. Similar incomplete
rollback exists after I2S initialization in
[`audio_service.c`](../Slave/firmware/esp32s3/components/ainekio_platform/src/audio_service.c#L472),
display initialization in
[`display_service.c`](../Slave/firmware/esp32s3/components/ainekio_platform/src/display_service.c#L510),
and ADC initialization in
[`telemetry_service.c`](../Slave/firmware/esp32s3/components/ainekio_platform/src/telemetry_service.c#L104).

Expected improvement after correction:

- Allocation failures produce one clean, known state instead of a half-running
  runtime.
- Tasks, queues, drivers, and hardware handles are not stranded.
- Retry or safe reboot behavior becomes deterministic.
- Normal steady-state performance will not materially change, but low-memory
  failure behavior will be substantially safer.

This correction may add a small amount of explicit rollback code. That is not a
new service or parallel system; it completes the ownership responsibilities of
the existing services.

### F4 - Medium: avoidable periodic polling

The
[`camera_task`](../Slave/firmware/esp32s3/components/ainekio_platform/src/camera_service.c#L113)
wakes every 10 ms even when camera streaming is disabled, producing up to 100
idle wakeups per second. The
[`telemetry_task`](../Slave/firmware/esp32s3/components/ainekio_platform/src/telemetry_service.c#L30)
wakes every 100 ms while the battery sampling interval is five seconds,
producing approximately 50 checks per actual sample.

Expected improvement after correction:

- Eliminate nearly all camera-task wakeups while the camera is disabled.
- Reduce telemetry due-check wakeups by approximately 98%.
- Reduce scheduler activity and allow more idle time.
- Improve power and CPU use slightly; the percentage improvement must be
  measured on the board because the current code does not record task runtime.

The preferred change is blocking notifications or calculated wake deadlines
inside the existing tasks, not additional worker tasks.

### F5 - Medium: WebSocket timeout exceeds microphone buffering

[`send_binary`](../Slave/firmware/esp32s3/components/ainekio_platform/src/runtime_service.c#L663)
can wait up to one second for the client lock or WebSocket write. The microphone
queue contains ten 640-byte frames. At 16 kHz, 16-bit mono, that is approximately
200 ms of buffered audio.

A single full write timeout can therefore outlast the queue by roughly five
times and cause microphone drops and delayed camera/control traffic.

Expected improvement after correction:

- Better bounded latency during a slow or failing network connection.
- Fewer microphone drops if timeout and buffering are tuned to measured network
  behavior.
- The tradeoff is that a shorter timeout may disconnect sooner. This must be
  verified with network impairment testing rather than changed by guesswork.

### F6 - Low: duplicated station-address logic

IPv4 address lookup and formatting are duplicated in
[`runtime_service.c`](../Slave/firmware/esp32s3/components/ainekio_platform/src/runtime_service.c#L276)
and
[`wifi_adapter.c`](../Slave/firmware/esp32s3/components/ainekio_platform/src/wifi_adapter.c#L236).

Expected improvement after correction:

- One owner for station address behavior.
- Slightly less flash and lower drift risk.
- No measurable runtime performance change is expected.

### F7 - Low: emulator manifest is included in the firmware filesystem image

The shared seed directory contains a 118,301-byte `motions-v1.json` manifest
used by the emulator. The active firmware reads the 3,909-byte
`motions-bin-v1.json` manifest, but the LittleFS build currently includes both.

Expected improvement after correction:

- Approximately 118 KiB less firmware filesystem content.
- Less firmware-specific packaging and flash input work.
- No OTA application-slot improvement because LittleFS is a separate fixed
  partition.
- Keep the source manifest for the emulator; exclude it only from the firmware
  image rather than deleting shared project data.

## Outdated Methods and Orphan-Code Result

No obvious obsolete ESP-IDF driver surface was found in the active path. The
firmware uses the ESP-IDF 5.5 I2S standard driver, I2C master bus API, MCPWM
prelude API, and ADC oneshot API. Component versions are explicitly pinned.

No residual provisioning password/hash/session/login implementation was found
after the current provisioning revisions. Local connection now has one active
path: DNS-SD supplies the endpoint and the old saved LAN URL is ignored. Remote
relay mode is explicit and does not participate in local fallback. The
duplicated station-address logic and firmware-only inclusion of the emulator
manifest are the remaining concrete low-level cruft found in this pass.

This is a review against the repo-pinned toolchain. It is not an internet-based
claim that every third-party dependency is the newest available release.

## System Specification Compatibility Review

The proposed remediation was compared with the normative
`Ainekio - System Specification v1.0.docx`. No finding requires a new service,
replacement runtime, protocol generation, or change to the robot's semantic
command and local-safety architecture. The following constraints are mandatory
during implementation.

| Finding | Compatibility result | Implementation constraint |
| --- | --- | --- |
| F1 | Compatible | Allocate manifest scratch storage during startup in heap or PSRAM. Allocation or model failure makes wake-word unavailable; it must not crash the body. |
| F2 | Compatible | Move cold asset indexes and temporary buffers only. DMA, servo safety state, and latency-critical audio state remain internal unless hardware evidence proves another placement safe. Asset validation still completes before motion becomes executable. |
| F3 | Compatible only with scoped rollback | Mandatory runtime-backbone failure rolls back cleanly. Display, audio, camera, or SD failure disables only that optional subsystem and must not block networking, provisioning, motion, or safety. No automatic reboot loop may be introduced. |
| F4 | Compatible with timing gates | Preserve the section 6.1 task/core ownership. Telemetry must still obtain a battery sample set at least every five seconds during sustained motion. Camera commands and snapshots must wake the existing camera task promptly. |
| F5 | Compatible only if protocol queue contracts remain fixed | Preserve control priority, stop/ping bypass, independent RX/TX, TTS ordering, the 10-frame configurable microphone queue, 25-frame speaker queue, two-frame camera queue, control-overflow disconnect behavior, and the 100 ms E-stop path. Do not hide slow writes by blindly growing queues. |
| F6 | Compatible | Consolidate address lookup inside the existing platform/WiFi boundary; do not add a network service. |
| F7 | Compatible | Exclude only the emulator JSON from the firmware image. Preserve the versioned binary manifest, `.amot` records, all required seed motions, bounded validation, and parity tests. |

The specification's status protocol defines one `heap` field. Internal-heap,
largest-block, and stack-watermark measurements will use boot or diagnostic
logging first. Permanent protocol fields require protocol fixtures and a
numbered specification decision rather than being added silently.

The implemented local wake-word engine is already recorded in `docs/README.md`
as a post-v1.0 delta awaiting specification consolidation. Correcting its stack
defect does not expand that feature. First boot remains wake-disabled unless an
accepted model and owner-approved configuration are present.

## Will the Firmware Be Leaner?

The software result is leaner: the linked image recovers 49,472 bytes of static
BSS and the confirmed stack overrun is removed without adding a task, queue, or
long-lived service. Reduced idle wakeups and bounded network-write latency are
confirmed structurally and by cross-build; their CPU, power, and drop-rate
effects still require on-board measurement.

The intended result is:

- no new long-lived service;
- no second runtime or duplicate architecture;
- existing buffers moved to the appropriate memory class;
- existing tasks blocked efficiently instead of polling;
- existing startup functions given complete rollback behavior;
- duplicate helper logic consolidated;
- unused firmware packaging input excluded;
- temporary diagnostics used to prove the result, with only useful operational
  measurements retained.

Source line count may rise slightly because correct rollback paths and memory
diagnostics require explicit code. Runtime footprint, scheduler activity, and
invalid failure states should decrease. Fewer source lines are not the goal;
less resource use and clearer ownership are.

## Required Verification After Remediation

The system should not be declared better or leaner until all applicable checks
below pass.

1. Rebuild with the pinned ESP-IDF toolchain and record `idf.py size`,
   `idf.py size-components`, and the linker map.
2. Confirm that the wake manifest no longer creates a stack frame larger than
   the main task and record the main-task stack high-water mark during boot.
3. Record internal free heap, minimum-ever internal heap, and largest internal
   free block separately from PSRAM.
4. Compare static BSS and internal DIRAM against the baseline in this audit.
5. Repeat strict portable-core compilation and all host tests.
6. Run repeated boots with LittleFS mounted and with the wake manifest both
   present and absent; no stack canary, reset loop, or corrupted status is
   acceptable.
7. Run a controller-only soak with servos disconnected or physical motion
   disabled, exercising WiFi/WebSocket, camera, audio, SD, provisioning, and
   reconnect behavior together.
8. Inject slow and failed WebSocket writes and compare microphone drops,
   reconnect time, and control latency with the current baseline.
9. Deliberately exercise startup allocation failures where practical and verify
   that no earlier service or task remains active.
10. Re-run the hardware safety and physical-motion gates separately before
    treating controller-only stability as proof of safe servo operation.

Current evidence status:

- Items 1, 4, and 5 pass in the final software build.
- Item 2 passes for the compiled frame; its on-board watermark remains pending.
- Item 3 is instrumented; live boot values remain pending.
- Item 8 now has a source-level bounded-write correction and build proof;
  degraded-network measurements remain pending.
- Items 6, 7, 9, and 10 require the controller or a dedicated ESP-IDF fault
  harness and are not claimed by this software-only pass.

## Remediation Order

1. Correct F1 before further reliability claims or broad optimization.
2. Add the measurements needed to establish internal heap and stack headroom.
3. Split cold asset storage from internal real-time state.
4. Complete startup rollback and ownership paths.
5. Replace the two polling loops with blocking/deadline-based waits.
6. Tune WebSocket timeout and queue behavior using measured impairment results.
7. Consolidate duplicate address logic and exclude the emulator-only manifest
   from the firmware filesystem input.

## Implementation Progress Ledger

This ledger is append-only for the remediation work. Entries record the local
working-tree state; they do not claim hardware acceptance unless hardware
evidence is explicitly named.

### 2026-07-22 11:12 PDT - Remediation authorized and started

- Owner authorized updating this audit and beginning firmware remediation.
- Re-read the normative v1.0 specification and recorded the compatibility
  constraints above.
- Confirmed the work must streamline the current services rather than create a
  parallel runtime or new long-lived service.
- Preserved the existing uncommitted firmware and documentation revisions as
  the implementation baseline.
- Next action: correct F1 and verify the compiled stack frame before broader
  memory or scheduling changes.

### 2026-07-22 - F1 corrected and build-verified

- Replaced the 4,097-byte automatic manifest buffer with bounded startup
  allocation that prefers PSRAM and falls back to internal 8-bit RAM.
- Added explicit release on every manifest-read and parse exit path.
- `idf.py build` passed under the pinned ESP-IDF v5.5.4 toolchain.
- The compiler now folds manifest loading into
  `ainekio_wake_word_service_start`, whose complete frame reserves `0x210`
  bytes (528 bytes), down from the prior `read_manifest` frame of `0x1050`
  bytes (4,176 bytes).
- The application binary decreased from `0x14ff10` to `0x14fed0` bytes. OTA
  slot headroom remains 56 percent.
- Result: the confirmed main-task stack overrun is removed in the built image.
  Repeated on-board boot and stack-watermark evidence remains pending.
- Next action: reduce cold internal-RAM ownership without moving DMA or safety
  state out of internal memory.

### 2026-07-22 - F2 and F4 implemented and build-verified

- Split the asset store's cold motion, face, and audio indexes plus its 16 KiB
  motion I/O buffer from the internal control object.
- The cold storage now uses one bounded PSRAM allocation during asset startup.
  The mutex, counts, mount state, servo reference, audio DMA state, and all
  safety state remain internal.
- Allocation or index-load failure releases the PSRAM block, clears published
  counts, leaves the asset store unmounted, and follows the existing optional
  asset failure path.
- Reworked the existing camera task so it blocks indefinitely when streaming is
  disabled and otherwise waits for either a command or the next frame deadline.
  No task, queue, priority, or core assignment was added or changed.
- Reworked the existing telemetry task to sleep directly until the next
  five-second battery deadline. A failed ADC read retains a bounded 100 ms retry,
  and every real sample still requests the required motion quiet window.
- `idf.py build` and `idf.py size` passed.
- Static BSS fell from 117,632 to 68,160 bytes: 49,472 bytes recovered.
- Total linked DIRAM fell from 218,703 bytes (`63.99%`) to 169,231 bytes
  (`49.52%`). Reported internal headroom rose from 123,057 to 172,529 bytes.
- The application binary is `0x14fef0` bytes with 56 percent OTA headroom.
- Source-level idle wakeup removal is confirmed. Board CPU-idle and power impact
  remain pending measurement.
- Next action: add scoped startup rollback without turning optional-subsystem
  failure into an all-or-nothing boot policy.

### 2026-07-22 - F3 implemented with specification-scoped rollback

- Runtime TX, dispatcher, and supervisor tasks now begin behind a startup gate.
  They are released only after mandatory runtime startup commits.
- Partial runtime-task creation deletes every task that was created, deletes the
  dynamic camera queue, and frees the runtime PSRAM buffer.
- Mandatory motion-service startup failure performs the same rollback. No
  automatic reboot or retry loop was introduced.
- Optional display, camera, SD, telemetry, and audio failures remain local and
  continue to use the specification's degraded-operation policy.
- Display startup now releases I2C device/bus ownership and restores the shared
  UART pin after initialization, first-buffer, or task-creation failure.
- Audio startup now releases partially created I2S channels and wake-model
  resources after queue, I2S, or task-creation failure.
- Telemetry startup now releases its ADC/calibration resources if its task
  cannot be created. Camera startup already had complete queue/camera rollback.
- `idf.py build` passed. Deliberate task-allocation fault injection remains
  pending on-board or under a dedicated ESP-IDF test harness.

### 2026-07-22 - F6 and F7 consolidated

- Removed the runtime's duplicate `esp_netif` station-address implementation.
  Runtime dependencies now receive the existing WiFi adapter and use its
  station-address owner.
- Added a generated firmware-only LittleFS staging directory under `build/`.
  The shared source asset directory remains unchanged.
- Firmware staging excludes only the 118,301-byte emulator `motions-v1.json`.
  It retains `motions-bin-v1.json`, every face/audio asset, and all 19 required
  `.amot` motion records.
- The rebuilt LittleFS image confirms the excluded manifest is absent and all
  required motion records remain present.

### 2026-07-22 11:25 PDT - Final software validation for this pass

- Added one protocol-neutral structured boot diagnostic containing internal
  free heap, minimum-ever internal heap, largest internal block, PSRAM free
  space, and main-task stack high-water mark. No WebSocket schema or status
  field was changed.
- Final `idf.py build` passed under ESP-IDF v5.5.4.
- Final application binary is `0x150220` bytes and retains 56 percent OTA slot
  headroom. The small 784-byte increase over the audit baseline is the explicit
  cleanup/gating and retained boot diagnostics.
- Final linked DIRAM is 169,267 of 341,760 bytes (`49.5%`), leaving 172,493
  bytes. Static BSS remains 68,160 bytes.
- The compiled wake startup frame remains `0x210` bytes (528 bytes); the prior
  4,176-byte overrun has not returned.
- Strict portable-core compilation passed and all 11 host tests passed.
- `git diff --check` passed.
- F5 write-timeout tuning was intentionally not guessed. The specification's
  queue sizes, drop policies, control priority, TTS ordering, and E-stop path
  remain unchanged. Slow/failing-network injection and on-board microphone-drop
  measurements are required before changing the write bound.
- Not yet claimed: flashed boot stability, live heap values, main/task stack
  watermarks, CPU-idle or power improvement, concurrent peripheral soak, or
  startup allocation-failure behavior on hardware.

Owner authorization covers the scoped remediation above. It does not authorize
a rewrite or expansion of the firmware architecture.

### 2026-07-22 11:47 PDT - F5 corrected and flash-ready build verified

- Separated the application write bound from the 10-second connection timeout.
  Runtime ownership-lock waits are now bounded to 10 ms and WebSocket operations
  to 60 ms instead of using one 1,000 ms value for both.
- Confirmed against pinned `esp_websocket_client` 1.7.0 source that the client
  may spend the supplied timeout on its internal lock, WebSocket header write,
  and payload write. A compile-time invariant keeps those waits plus the runtime
  lock within 190 ms, below the ten-frame microphone queue's 200 ms audio
  window.
- A 645-byte microphone frame remains one WebSocket client chunk. Larger camera
  messages now use standard WebSocket fragmentation in 4,096-byte chunks with a
  shared decreasing timeout budget instead of receiving a fresh full timeout
  for every chunk. Failure follows the existing disconnect/failsafe path.
- No queue length, drop policy, task, priority, core assignment, protocol frame,
  TTS ordering rule, control-overflow behavior, or E-stop path changed.
- Final ESP-IDF v5.5.4 build passed. The application is `0x150430` bytes with
  `56%` free in each 3 MiB OTA slot. The F5 correction adds 528 bytes of flash
  code over the prior remediation build and no static RAM: DIRAM remains 169,267
  of 341,760 bytes (`49.53%`) and BSS remains 68,160 bytes.
- The final wake startup frame remains `0x210` bytes (528 bytes). The bootloader
  and application images both pass `esptool image_info` checksum and validation-
  hash checks.
- All 11 strict portable-core tests and all 13 Python protocol contract tests
  pass. The first direct Python discovery invocation lacked the repository
  module path; the recorded successful command is
  `PYTHONPATH=Slave/software python3 -m unittest discover -s Slave/software/tests/protocol -v`.
- Firmware asset staging retains `motions-bin-v1.json` and all 19 `.amot`
  records while excluding only emulator `motions-v1.json`.
- Flash-ready files and offsets are recorded in `build/flash_args`: bootloader
  `0x0`, partition table `0x8000`, OTA data `0x1a000`, application `0x20000`,
  and LittleFS `0x620000`.
- Final application SHA-256:
  `7b7ea24d8bf18b103fc902189ea6f51282f677ba5731b13aefe4821d02d0dcc2`.
  Final LittleFS SHA-256:
  `cc48c77e3bfaedb49ca3c2629791fa1ef85cf82f9666d3f34ec37ef3966d1965`.
- No serial controller was present at `/dev/ttyACM0` or `/dev/ttyUSB0`. The
  system is flash-ready, but flashed boot behavior, live memory/stack values,
  impairment results, soak stability, allocation-failure rollback, and physical
  safety gates remain explicitly unclaimed hardware evidence.

### 2026-07-23 11:01 PDT - Camera DMA correction flashed and hardware-verified

- The flashed controller detected the OV3660 camera but repeatedly reported
  `NO-EOI - JPEG end marker missing` and frame-capture timeouts with optional
  direct PSRAM camera DMA enabled. This was captured over the controller UART;
  it was not inferred from the dashboard.
- Disabled `CONFIG_CAMERA_PSRAM_DMA` in both the tracked defaults and resolved
  configuration, returning the driver to its default non-direct-PSRAM DMA path.
  Camera pins, clock, resolution, JPEG format, task ownership, protocol, and
  queue sizes were not changed.
- Rebuilt successfully under ESP-IDF v5.5.4. The application binary is
  `0x158970` bytes (1,411,440), leaves 55 percent of each 3 MiB OTA slot free,
  and has SHA-256
  `1605c51d4ec77a2f435977bf939d3533dcb761ff8ea3aeb3e83c07546b5fb139`.
  Linked DIRAM is 171,683 of 341,760 bytes (`50.23%`), including 70,544 bytes
  of BSS.
- Flashed the application partition only at `0x20000`, preserving NVS, OTA
  state, and LittleFS. The flasher verified the write hash, and a separate
  `esptool verify_flash` digest comparison passed.
- After reboot, `ainekio-01` reconnected to the physical gateway as epoch 14.
  During a 35-second observation window, the gateway accepted 241 camera JPEG
  frames (counters 623 through 863), approximately 6.9 frames per second, with
  seven status updates and no disconnect event. The protocol validator accepts
  camera frames only when the payload has valid JPEG start/end markers and is
  within the 120 KiB bound.
- The camera-only UART monitor showed no recurrence of the prior `NO-EOI` or
  frame-timeout errors during the same live stream. This verifies the camera
  capture and robot-to-gateway media path; visual image quality and a longer
  concurrent-peripheral soak remain owner-observed hardware checks.
- Separate unresolved evidence: the audio task reports `speaker DMA write
  failed` every 20 ms. That 50 Hz failure/log loop is real resource waste and
  may indicate incorrect I2S state. It was not changed during this controlled
  camera test and requires its own root-cause pass before the controller can be
  called fully clean or soak-ready.

### 2026-07-23 11:15 PDT - Audio DMA timing loop corrected and flashed

- Confirmed the missing external speaker was not the source of the driver
  failure. The ESP32-S3 I2S transmitter has no amplifier or speaker
  acknowledgement path; it writes to its local DMA channel whether or not an
  output device is attached.
- The firmware requested a 25 ms I2S write timeout for one 20 ms audio frame.
  At the configured 100 Hz FreeRTOS tick rate, ESP-IDF converted that deadline
  to two ticks, exactly 20 ms. This left no scheduling margin and matched the
  measured failure cadence.
- Kept the existing full-duplex audio task, microphone clocking, speaker queue,
  TTS behavior, wake-word path, pins, sample rate, frame size, core assignment,
  and priority. No audio capability or other robot function was disabled.
- Defined the 16 kHz sample rate and 320-sample frame once, increased the
  bounded write deadline to 60 ms, and added a compile-time check that its
  tick-rounded duration exceeds one audio frame.
- A genuine future write failure now reports the ESP-IDF result and partial byte
  count at most once every five seconds. A one-frame delay bounds retry CPU use
  if the driver returns an immediate persistent error. Successful recovery is
  reported once.
- ESP-IDF v5.5.4 build and `idf.py size` passed. The application is `0x158a30`
  bytes (1,411,632), 192 bytes larger than the camera-verified image, with 55
  percent OTA-slot headroom. DIRAM is 171,691 of 341,760 bytes (`50.24%`);
  static BSS increased by only eight bytes to 70,552 bytes.
- Application SHA-256:
  `1e1ed35a9277828b37231feb61328d2229e604fb595415dedd86629c2882de0f`.
  The application-only flash at `0x20000` passed the flasher hash check and an
  independent `esptool verify_flash` digest comparison. NVS, OTA state, and
  LittleFS were preserved.
- A controlled reboot showed the OV3660 camera ready with direct PSRAM DMA
  disabled, WiFi connected, OTA acceptance after gateway authentication, and
  continuing five-second status reports. The final connection remained
  authenticated after the intentional flash/verification/monitor resets.
- No speaker/I2S write failure or recovery message appeared during more than
  110 seconds of filtered live UART observation. The old loop would have
  emitted roughly 5,500 warnings in that interval. This verifies removal of
  the failure/log loop with the current no-speaker hardware state.
- After the UART window, Body Control issued three snapshot commands on the
  same authenticated epoch. The gateway accepted three corresponding
  protocol-valid JPEG frames with counters 0, 1, and 2 while the corrected audio
  service remained active. Status continued afterward without a disconnect.
  This closes the immediate camera/audio-clock regression check; sustained
  multi-peripheral soak remains separate.
- Known non-audio states remained explicit: the disconnected OLED made display
  startup unavailable, the SD card reported unavailable, and the optional wake
  model package was not found. These are not compile-time-disabled functions
  and were not altered by this correction.

### 2026-07-23 12:10 PDT - Fresh XGA still path implemented, flashed, and verified

- Traced the observed snapshot lag to the ESP camera driver's single-buffer
  `CAMERA_GRAB_WHEN_EMPTY` behavior. The driver fills an available buffer
  immediately, so the former capture path could return the image waiting since
  the previous request. The three prior snapshots were about six seconds apart,
  making a roughly one-request-old image consistent with the implementation.
- Kept the existing single camera task, single driver framebuffer, bounded
  two-entry drop-oldest transmit queue, and semantic `snap` command. No second
  framebuffer, camera task, image-resize stage, video codec, or continuous
  still-capture loop was added.
- The camera task now holds its one framebuffer between requested captures.
  Releasing it only when a snapshot or preview interval is due makes the sensor
  acquire one fresh frame and leaves the capture engine idle between frames.
  Preview remains off by default and explicitly limited to QVGA/VGA; XGA is
  rejected as a preview-stream setting.
- Snapshot capture now temporarily selects the OV3660's native XGA mode
  (1024x768, 4:3), retains JPEG quality 10, performs no crop, resize, rotation,
  or aspect-ratio conversion, and reports `cam_meta.res=XGA`. If low-resolution
  preview is active, its configured resolution is restored after the still.
- The driver allocates framebuffer capacity from its initialization resolution.
  Initialization therefore uses XGA even though streaming remains disabled.
  This prevents an XGA capture from inheriting a QVGA-sized PSRAM allocation.
  Only one driver buffer is still allocated.
- The necessary dynamic-memory tradeoff is explicit: the driver's automatic
  JPEG buffer grows from about 15,360 bytes at QVGA to about 157,286 bytes at
  XGA, approximately 142 KiB of additional PSRAM plus unchanged DMA overhead.
  It does not consume internal static RAM, and the final live status still
  reported 8,173,088 bytes of free heap.
- Raised the protocol-valid JPEG ceiling from 120 KiB to a bounded 256 KiB
  consistently across firmware, protocol schema/helper, gateway WebSocket
  limit, and emulator. This is a validation/transport ceiling, not a static
  256 KiB firmware allocation. The physical driver's automatic XGA JPEG buffer
  remains approximately 154 KiB plus DMA overhead.
- Updated the physical dashboard label to `Snapshot · XGA`; the preview form
  still offers only QVGA and VGA and defaults to one frame per second when
  enabled. The emulator now mirrors the physical split: XGA for snapshots and
  QVGA/VGA for explicit preview.
- Portable C build and all 11 CTest targets passed. The focused protocol,
  emulator, and gateway run passed 70 tests. The complete A-series acceptance
  suite then passed 30/30 gates: emulator, protocol, portable C, and dashboard
  browser.
- ESP-IDF v5.5.4 build and `idf.py size` passed. The application binary is
  `0x158d00` bytes (1,412,352), 720 bytes larger than the last flashed image,
  with 55 percent of the 3 MiB app partition free. DIRAM is 171,699 of 341,760
  bytes (`50.24%`), including 70,560 bytes of BSS; static BSS increased by
  eight bytes.
- Application SHA-256:
  `62f31502ef67bcac82787a6eb9c91f7b70a748f2d0352f3c7783daca6cf84d17`.
- Flashed only the application partition at `0x20000`, preserving NVS, OTA
  state, and LittleFS. The flasher verified its write hash and a separate
  `esptool verify_flash` comparison passed for all 1,412,352 bytes.
- Restarted the physical gateway so its live process loaded the new XGA metadata
  and 256 KiB transport contract. With preview off, an authenticated dashboard
  snapshot returned a valid 29,618-byte baseline JPEG at exactly 1024x768.
  A separate local command-to-new-JPEG measurement returned a valid
  28,885-byte 1024x768 frame in 969 ms.
- The complete mixed-mode hardware sequence passed: QVGA preview at one frame
  per second produced a 320x240 frame at counter 8; the next explicit snapshot
  produced a 1024x768 frame at counter 9; the following preview frame returned
  to 320x240 at counter 10. After an explicit camera-off command, zero camera
  frames were recorded more than one second later.
- The final authenticated status showed the robot connected over LAN with no
  pending commands, 877 ms heartbeat age, RSSI -51 dBm, 8,173,088 bytes free
  heap, and zero camera, speaker, or microphone drops. Camera preview was left
  off.
- One diagnostic snapshot attempt emitted XGA metadata and then coincided with
  a WebSocket 1006 disconnect while a UART monitor was attached. The robot
  reconnected automatically after 21 seconds; the subsequent timed snapshot,
  mixed-mode sequence, continuing status, and zero drop counters all passed.
  The disconnect was not reproduced, but remains explicit evidence for the
  longer multi-peripheral soak.
- The controller's per-snapshot `age_ms` log could not be decoded after startup
  because MAP_B hands console GPIO43 to OLED SCL. The measured 969 ms
  command-to-JPEG result is therefore the current physical responsiveness
  evidence; the code-level stale-frame cause and single-buffer ownership fix
  remain independently confirmed.
