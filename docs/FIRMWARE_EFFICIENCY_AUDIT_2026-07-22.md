# ESP32-S3 Firmware Efficiency Audit

Date: 2026-07-22  
Reviewer: Robot Police  
Target: `Slave/firmware/esp32s3`, including the current uncommitted revisions  
Status: Software remediation pass build-verified; hardware validation and F5 tuning pending

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
- The application binary is `0x14ff10` bytes, leaving `56%` of the 3 MiB OTA
  application slot free.
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
after the current provisioning revisions. The duplicated station-address logic
and firmware-only inclusion of the emulator manifest are the concrete low-level
cruft found in this pass.

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

The expected answer is yes, but only the stack defect and unnecessary wakeup
counts can be proven directly from the current code. Final improvement must be
measured after implementation.

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
