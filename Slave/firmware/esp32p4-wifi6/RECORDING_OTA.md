# P4 camera recording and Wi-Fi application updates

Recording/OTA started in `0.8.21-p4-record-ota`; `0.8.22-p4-body-maintenance` adds
internal-card downloads and Body Control maintenance. `0.8.34-p4-rolling-logs`
adds owner-requested automatic reuse of the oldest completed clips and Wi-Fi logs. Initial USB installation and controller-only
hardware testing are recorded below; powered motion is not qualified. The pre-existing
dirty firmware, IMU, gait, calibration and gateway work was retained.

## Existing owners and hardware evidence

- `main/app_main.c`, `board.c`, `body.c` own startup and the twelve-joint body.
  The output task is priority 10 on core 1, with 20 ms targets. The core-0
  supervisor has highest application priority and a 5 ms cadence; existing
  progress protection is 40 ms. The body task configures a 100 ms task watchdog,
  overriding the 5-second sdkconfig default. None of these timings was changed.
- `main/network.c` owns ESP-Hosted Wi-Fi. Framework **ESP-IDF 5.5.4**, Hosted
  **2.12.8**, Wi-Fi Remote **1.6.4**, WebSocket client **1.7.0**, esp_video
  **2.5.0** remain pinned. The C6 runs its separate Hosted firmware, linked over
  SDMMC slot 1: CLK18, CMD19, D0–3=14–17, reset54, 4-bit 40 MHz.
- [Recorded board evidence](../../../docs/v2-12servo/STEP1_EVIDENCE.md) identifies
  **P4 silicon revision 1.3**, 360 MHz, 32 MiB flash and 32 MiB PSRAM at 200 MHz,
  with C6 **2.12.8** installed. These are historical measurements, not a new live
  interrogation. A separate PCB revision/silkscreen is not recorded. Current
  configuration targets pre-V3 P4. The October 17 display restoration returns
  current builds to the 1.9-inch ST7789 LCD; SSD1306 observations below describe
  the earlier temporary assembly.
- `components/ainekio_p4_media/camera.c` is the sole camera owner. OV5647 RAW10
  enters CSI/ISP, then two RGB565 capture buffers. It resizes/rotates the image
  and uses the hardware JPEG encoder once, quality 75, YUV420. Preview starts
  disabled; its source defaults are VGA (640×480), 2 FPS. The existing command
  can select QVGA/VGA/XGA and 0–15 FPS. The measured live operator selection is VGA at 1 FPS, preview on, AUTO snapshots.
  The sensor's binned 1280×960/45-FPS mode is not the Wi-Fi delivery rate.
  Native 960p/1080p snapshots use the same owner and can interrupt preview while
  exposure settles. Two capture buffers, a 1024×768 RGB565 scratch buffer and
  256 KiB encoder output remain unchanged. The two capture buffers grow from
  about 4.69 MiB to 7.91 MiB when switching to 1080p stills.
- `main/controller.c` copies JPEGs into its existing two-entry transmit queue;
  the link task sends metadata/binary packets over the selected gateway's
  WebSocket. Audio, control replies and heartbeats share that transport.
  The gateway and MetaHuman consume JPEG frames; neither requires a new service
  or changed protocol for these additions. Prior camera timeout, queue-drop,
  exposure and microphone-stack issues are recorded in the main README.

The SD owner was already implemented: FAT on slot 0, 4-bit 20 MHz,
CLK43/CMD44/D0–3=39–42, active-low GPIO45 card-power gate, LDO4 I/O power.
It initializes after Hosted and deinitializes only its own slot. This matches
the [Waveshare ESP32-P4-WIFI6 schematic](https://files.waveshare.com/wiki/ESP32-P4-WIFI6/ESP32-P4-WIFI6-datasheet.pdf)
and [IDF 5.5.4 SDMMC API](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32p4/api-reference/peripherals/sdmmc_host.html).
The two slots share IDF's transaction mutex. A faulty card can hold it for the
existing write-command timeout (5 seconds) and disturb Wi-Fi, potentially
triggering existing link-loss behavior. Small yielding writes reduce ordinary
contention; they cannot guarantee Wi-Fi continuity during a card fault.

Hardware bring-up exposed two required configuration fixes: the SDK's default
eight VFS registrations were exhausted before mounting SD, and FAT long filenames
were disabled. This project now selects twelve VFS registrations and heap-backed
long filenames. Existing saved sdkconfig files must select these explicitly.

Entering Doze with the camera streaming also exposed a DMA teardown race in
[the pinned SDK source](https://raw.githubusercontent.com/espressif/esp-idf/v5.5.4/components/esp_hw_support/dma/dw_gdma.c).
Its last channel released the register clock before removing the shared interrupt;
the observed panic was `shared_intr_isr`, reading `0x50081030`. The project build
applies the narrow ordering correction through `cmake/idf_dw_gdma.cmake`: remove
the interrupt first, then release the group. It compiles a corrected source in
the build directory; the installed SDK, managed components and public driver APIs
remain unchanged. Revisit this correction when deliberately changing SDK versions.

## Record and retrieve video

Use an already formatted FAT card. Firmware never formats a card. Enable camera
preview through existing Body Control, keeping its current resolution/FPS. From
this firmware directory, use the robot's Wi-Fi address shown by `net` or the
connection screen (not the gateway's address):

```sh
python3 tools/maintenance.py ROBOT_IP record start
python3 tools/maintenance.py ROBOT_IP record status
python3 tools/maintenance.py ROBOT_IP record stop
```

Each command prompts privately for the **existing robot pairing token**, or reads
`AINEKIO_ROBOT_TOKEN`. Serial equivalents are `system recording start`,
`system recording status`, and `system recording stop`.

Recording copies the already-encoded preview JPEG after the streaming callback
has copied it. At most **three 256 KiB JPEGs**, including the writer's in-flight
frame, can be retained. Queue/lock pressure drops recording frames rather than
waiting in the camera task. The existing priority-2 storage task writes 4 KiB
chunks, yielding between chunks. There is no second capture, second encoding,
audio mux, whole-recording allocation, or in-memory AVI index.

Files are `ainekio/video-BOOTID-SEQUENCE.avi` on the card, ordered by sequence
within a boot. They are standard MJPEG AVI; indexing is optional in the
[AVI format](https://learn.microsoft.com/en-us/windows/win32/directshow/avi-riff-file-reference).
Segments rotate at the next received frame after 60 seconds, before 64 MiB,
or when resolution/FPS changes. Dropped-frame chunks preserve elapsed playback
time between received preview frames. Native stills retain their existing
separate JPEG capture behavior and are not inserted into the video.

Start arms recording; it does not enable preview or change the camera profile.
No preview, Doze, or loss of the camera's gateway session means no new video
frames. A long period without frames does not create empty segments. Recording
does not automatically resume after reboot. Status reports recording state,
completed frames/segments, drops, maximum observed write time, path, mount/free
space and errors. Counters accumulate for the current boot. A storage failure
remains visible until an explicit new recording start.

Missing cards reject start. Write failures stop recording and retain the failed
file. Near capacity, completed video files are reused as described below. Use Body Control **Retry mount** after resolving the storage issue, then start again. Existing clear
only covers old event logs/still captures; it does not delete these videos.
Stop drains preceding queued frames and finalizes the AVI. A timeout/error is
reported instead of claiming completion. Controlled sleep/restart also drains
and closes recording through the existing storage owner.

The card can remain installed inside the robot. In **Body Control → SD card**:

1. Enable preview in Camera at the existing resolution/frame rate.
2. Select **Start recording**. Streaming continues using the same encoded JPEGs.
3. Select **Stop recording** to finalize the active segment.
4. Select **Refresh recordings**, choose a clip, then **Download selected clip**.

Downloads use the existing dashboard login. The gateway resolves the selected
robot's authenticated WebSocket peer address and supplies its pairing credential;
credentials are never sent to browser JavaScript. The new robot GET
`/api/recordings` streams the file list; `?name=video-XXXXXXXX-NNNNNNNN.avi`
streams one file. `.avi.part` files are also listed and downloadable for recovery.
An active file download reads only its initial size and may require recovery;
stop first for a finalized clip. Downloading does not stop recording or preview.
The storage owner locks each filesystem read, releases the lock before network
writes, and coordinates unmount with open readers. Downloads use a 4 KiB P4
buffer and 64 KiB gateway chunks, not whole-file buffering. Read/network failure
aborts the download; it does not mark a truncated clip successful.

Downloads leave files on the card until they are reused by rolling recording.
With less than **64 MiB free** (one maximum-sized segment), each new segment
reuses the **oldest completed recorder file** automatically. No review, unlink,
bulk deletion, or formatting is involved. The writer renames that file to the
new sequence's `.avi.part`, opens it without truncation, and writes over its
existing data clusters. On successful close, it trims only that clip's unused
tail, syncs, and finalizes its `.avi` name. This avoids deleting and reallocating
a whole clip. The old content is irreversibly replaced as writing proceeds.

The writer retains a **32-entry oldest-file index (2,176 bytes)**. It scans the
directory once at mount and refills the batch when exhausted, yielding every
32 entries. Ordinary frames and the next 32 eligible reuse selections do not
rescan the directory. It queries free space at segment boundaries; all of this
runs in the existing low-priority storage worker. Existing capture and stream
queues and frame ownership are unchanged. New clips continue a card-wide
sequence across boots, so oldest-first order needs no network clock. Files from
older firmware used per-boot sequence numbers: their relative order across
boots cannot be recovered exactly; equal old sequences tie by filename.

A reused segment closes when it reaches its old file capacity or the usual
60-second/64-MiB bound. This can produce shorter clips as frame sizes vary.
The next frame moves to the next oldest slot. A small slot can grow enough to
hold its first frame if free space permits. If no reusable slot or enough space
for even one frame remains, the existing recording-error path reports failure.
The system does not overwrite unrelated files, logs, snapshots, unfinished
`.part` files, or a clip currently being downloaded. Download pinning also follows
an active `.part` through finalization. Repeated power losses can accumulate
unfinished files; those require explicit recovery rather than automatic reuse.
A failed write or power loss during overwrite cannot restore the previous clip.
Other completed slots remain untouched. Body Control reports the rolling policy
and the number of reused clips since boot.

During writing the name ends in `.avi.part`. Header lengths are checkpointed and
synced about once per second; stop syncs/closes and renames to `.avi`. Unexpected
power loss can leave a stale/torn header or partial last JPEG. Previous finalized
segments normally remain playable, but FAT/card caches are not power-failure
proof. The firmware neither deletes nor attempts destructive repair of `.part`
files. Copy them off the card first. FFmpeg may salvage complete JPEGs:

```sh
ffmpeg -i video-BOOTID-SEQUENCE.avi.part -c:v copy recovered.avi
```

Recovery is best effort, not a guarantee for damaged FAT metadata or headers.

## Upload and activation

The same HTTP server used for setup now remains available on station Wi-Fi.
The setup form remains AP-only. Maintenance uses `Authorization: Bearer TOKEN`
with the boot-time pairing token. This retains the existing trusted-LAN model:
**HTTP is not encrypted; use the protected robot LAN/setup AP, not port forwarding
to the Internet.** No new server, gateway authority, framework upgrade, C6 update,
SD staging, Secure Boot key or eFuse change is involved.

```sh
python3 tools/maintenance.py ROBOT_IP status
python3 tools/maintenance.py ROBOT_IP upload build/ota/ainekio_p4_body.bin
python3 tools/maintenance.py ROBOT_IP activate next_boot
# Or select and restart now:
python3 tools/maintenance.py ROBOT_IP activate restart
```

Upload only the **P4 application `.bin`**, not a merged flash image, bootloader,
partition table, C6 image or filesystem image. The owner-approved upload policy
enters existing Doze and finishes recording before flash writes. While writing,
ordinary command/state changes cannot re-enable the body; STOP and the normal
communications tasks remain available. Once preparation succeeds, upload
completion/failure leaves Doze in place. Preparation failure does not start flash
writing. Resume Idle using existing Body Control when appropriate.

The receiver checks ESP image magic, P4 chip ID, and project identity before
preparing the robot. IDF's `esp_ota_begin/write/end` uses the inactive slot with
incremental erasure and validates the complete image/checksum/hash and silicon
compatibility. Transfers use a 4 KiB buffer and yield between writes. Truncated,
timed-out and invalid uploads do not select a boot partition. A slot already
selected for the next boot cannot be overwritten by another upload.

Successful upload reports `staged`; the boot selection is still unchanged.
`activate next_boot` selects it without rebooting; `activate restart` selects it
and invokes the existing controlled restart, including storage drain and ACK
grace. If restart preparation fails, selection may already have succeeded:
read status before retrying. Restarting **before** explicit activation discards
the RAM-only staged selection and continues the existing firmware; upload again
if needed. Activation does not alter credentials, calibration or asset data.

The servo-feedback scan schedule skips elapsed 20 ms periods after a flash
stall. It retains the normal 50 Hz cadence instead of replaying missed scans:
ADC reads can only measure the present. Before this correction, the priority-3
feedback task could starve the priority-2 storage worker after upload. Live
diagnostics captured a runnable storage request waiting about 49 seconds and
feedback consuming 3.39 seconds of a four-second activation timeout while
storage received no CPU time. This is a sampling-schedule correction; the
storage timeout, task priorities, and OTA preparation sequence are unchanged.

An authenticated reconnect can also confirm the already-selected profile during
OTA without writing NVS or changing output state. Previously, the profile
setter rejected even that no-op while an upload was busy, causing WELCOME to
tear the connection down repeatedly until upload completed. A different profile
remains subject to the existing OTA restriction. Regression tests exercise the
production scan scheduler and profile setter in
`Emulator/tests/test_p4_feedback_cadence.py` and
`Emulator/tests/test_p4_ota_preparation.py`.

On 2026-10-20, `0.8.108-p4-ota-fix` passed two consecutive Body Control
upload/immediate-activation cycles across both OTA slots. Uploads took 35.57
and 33.12 seconds; first-attempt activations took 0.41 and 0.37 seconds, with
no activation retries or intervening delays. Temporary storage diagnostics and
FreeRTOS CPU profiling were removed from this image.

The LCD shows preparing, writing percentage, validation, staged,
next-boot/restart, accepted and failure states. Update messages keep the display
on during Doze. Success/failure notices last 15 seconds; otherwise normal face
and sleep behavior returns. During first boot, pending validation is displayed.
The ROM/USB bootloader does not run the application display task, so USB flashing
itself cannot show this overlay.

The synchronous HTTP server handles one request at a time. During upload, watch
the screen for progress; HTTP status queries wait for the upload handler. Existing
WebSocket controls/heartbeats are independent.

## Robot logs over Wi-Fi

In **Body Control → Robot logs**, select **Read robot logs** to view diagnostics
or **Download robot logs** to save a text file on the computer. This uses the
existing dashboard login and the selected robot's pairing credential through
`GET /api/robot/logs`; the robot endpoint is `GET /api/logs`. Logs are fetched
on request, without another service or continuous network traffic.

The recorder retains the last **4 KiB of the current boot and 4 KiB of the
previous boot** in RTC memory (8,208 bytes including metadata). Startup stage
markers and reset reason are recorded from application entry. Normal SDK logs
are captured after gateway authentication/startup acceptance with the pinned
[IDF logging hook](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32p4/api-reference/system/log.html).
The normal console remains available. Each formatted message is bounded to
383 bytes; simultaneous writers can drop messages instead of waiting. A read
temporarily allocates at most 8,704 bytes for a consistent snapshot.

IDF's panic printer bypasses the normal logging hook and ROM output channels.
`cmake/idf_panic_log.cmake` compiles a project-local copy of the pinned SDK panic
printer with an additional character sink into the same bounded recorder. This
does not change panic reset, watchdog or OTA acceptance behavior, or modify the
installed SDK. Startup breadcrumbs write directly to the buffer. The OTA startup report
also prints readiness masks, body stack space, C6 version/RPC result and output fault
to the console, before normal runtime capture starts. ROM bootloader output before application entry is not captured.

Retention is for warm resets; **power loss clears these logs**. Previous-boot
recovery requires both applications to preserve the same RTC log layout; it
cannot recover a crash from firmware without this recorder. Failures before
application entry may leave no usable report. Logs are best effort, may be truncated, and
do not replace full core dumps. There are no background SD or flash writes for
these diagnostic logs.

## Rollback and C6 compatibility

Rollback follows [ESP-IDF 5.5.4 OTA semantics](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32p4/api-reference/system/ota.html).
On activation, the existing readiness of camera, microphone, speaker, display
and servo controller is saved in a separate `p4_ota` NVS namespace. The first boot
is accepted only at the existing authenticated-gateway welcome point after:

- NVS/configuration and ordinary application startup have completed;
- previously ready peripherals are ready again (absent optional devices are not
  newly required); the servo controller uses its successful boot-time hardware
  probe when outputs are deliberately disabled, rather than requiring them to
  be armed or clearing their disable latch;
- the body task exists and output status has no I/O/deadline/progress fault;
- the C6 version RPC works and reports a nonzero version, and gateway
  authentication/communication has succeeded.

Then `esp_ota_mark_app_valid_cancel_rollback()` accepts the image. A failed check
or unavailable gateway leaves it pending; a crash, reset, power loss or deliberate
restart **before acceptance** makes the bootloader return to the previous usable
OTA image. There is no extra automatic reboot timer. These startup checks do not
prove gait, sustained recording, image quality or full hardware health.

The P4 project remains pinned to Hosted 2.12.8; the recorded C6 is already 2.12.8.
Build updates from that compatible project. P4 OTA never writes C6 flash. The
existing explicit `net c6-update` maintenance-image workflow remains separate.

## Initial USB installation / migration

Existing build output before this change was **2,859,216 bytes**, with a single
8 MiB factory app at `0x20000`; the checked-in optional full table already defined
the following compatible addresses. The initial source-only investigation did not read installed partitions; the
2026-10-13 USB inspection subsequently confirmed this full layout was already installed.
An app-only update cannot install a partition table or rollback bootloader.

| Partition | Address | Size |
| --- | ---: | ---: |
| NVS | `0x9000` | `0x6000` (unchanged) |
| PHY | `0xf000` | `0x1000` (unchanged) |
| OTA data | `0x10000` | `0x2000` |
| OTA 0 | `0x20000` | `0x800000` |
| OTA 1 | `0x820000` | `0x800000` |
| LittleFS assets | `0x1020000` | `0xfe0000` (existing optional layout) |

Fresh sdkconfig defaults select the full table and rollback. For an existing
configuration, copy it to a separate configuration and use menuconfig to select
`partitions-full.csv`, `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y`,
`CONFIG_VFS_MAX_COUNT=12`, and `CONFIG_FATFS_LFN_HEAP=y`; defaults do
not override an existing saved choice. Retain the current display/board options.

```sh
# From this directory, after activating the existing ESP-IDF 5.5.4 environment:
cp sdkconfig /tmp/ainekio-ota.sdkconfig
idf.py -B build/ota -D SDKCONFIG=/tmp/ainekio-ota.sdkconfig menuconfig
idf.py -B build/ota -D SDKCONFIG=/tmp/ainekio-ota.sdkconfig build
```

For the first installation, support the robot and isolate servo power before a
USB reset/flash: the existing normal-boot Home behavior is preserved. Back up the
installed flash to a private location, inspect its partition table, and confirm
these addresses before writing. Do not use `erase_flash`. The one-time targeted
write for the recorded pre-V3 board is the generated bootloader at `0x2000`,
partition table at `0x8000`, **initial erased OTA data** at `0x10000`, and this
application at `0x20000`. The generated `build/ota/flash_args` lists them.
Only initialize OTA data when migrating from a factory-only layout. If the full
layout is already present, preserve its table and OTA data and inspect the selected
slot before writing the application. Use `esptool verify_flash` afterward.
NVS/PHY and LittleFS are outside those
regions. Do not write the generated asset image over installed assets.

Once both the full table and rollback-enabled bootloader are installed, use
application-only Wi-Fi updates. **Never reinitialize OTA data during routine
updates**: that would discard the active slot/rollback state. USB ROM recovery
remains available if a migration or application fails. The installation below
required no partition or OTA-data rewrite.

## Validation and resource limits

The firmware builds with the installed SDK, both OTA slots, rollback enabled and
SSD1306 retained. Host checks exercise production OTA handlers against SDK/I/O
fakes: authorization, wrong chip/project, truncated upload, flash/image failure,
unchanged boot selection until activation, startup readiness and display text.
The production recorder producer is tested for copied-buffer ownership, the
three-frame bound, queue saturation and zero-wait admission. The AVI writer is
tested for headers, padding, dropped-frame timing and write failure. FFprobe and
FFmpeg recognized and decoded a generated VGA/2-FPS clip with a dropped frame.

Recording reserves no new task stack. Its payload bound is **768 KiB PSRAM plus
allocator/queue overhead**. The HTTP owner now uses an **8 KiB stack** (previously
6 KiB only while setup was active), and uploads allocate **4 KiB** temporarily.
AVI uses no growing index. Existing camera buffers and transmit queues retain
their limits. Initial `0.8.21` application: **2,878,416 bytes**, leaving **5,510,192 bytes**
in each 8 MiB slot. Compared with the pre-existing build artifact, the binary
grew **19,200 bytes** and the linker reports **328 additional bytes of static
internal RAM**. That initial static internal occupancy is **150,806 bytes** including
internal code/data/BSS. These linker values exclude runtime task/heap allocations.

The broader native suite passed **46/47** tests. Its existing locomotion-generator
test fails for Run: `Gait stance_output_min_deg: 40.886 < 45`; this independent
model issue was left unchanged. The final focused OTA/AVI/body/camera/display
run passed **5/5**, and the recording/gateway/media policy and audio/bridge
regressions passed **22/22**. Both display sources compile; the complete image
selects SSD1306. Existing test harnesses needed the missing face-library link
on two configuration tests and a FreeRTOS tick typedef in the extracted audio
fixture. The full native run used an existing Python environment with NumPy;
the asynchronous audio fixture passed outside the restricted sandbox.

## Controller-only hardware validation of 0.8.21, 2026-10-13

The owner connected USB, inserted the card and confirmed servos disconnected.
Readback identified P4 silicon 1.3 / 32 MiB flash; boot identified 32 MiB PSRAM,
SSD1306, OV5647 and C6 Hosted 2.12.8. A private full 32 MiB flash backup was saved
outside the repository before any writes. The installed 0.8.19 image already had
the full partition layout. Only the P4 bootloader and application were written;
separate flash verification confirmed NVS, PHY, partition table and OTA data were
unchanged before first boot. Assets and C6 firmware were not written.

Initial tests exposed the VFS/long-filename settings and camera DMA teardown bug
explained above. After correction, the installed version is **0.8.21-p4-record-ota**.
The application artifact is `build/ota/ainekio_p4_body.bin`; the matching build
configuration is saved as `build/ota/sdkconfig.installed` (both ignored artifacts).
SHA256: `0f170832cd591aceb4f3191ac2d9cc86323e3e9628369bf2eb72c1c6bdce063f`.

Measured checks:

- The card mounted with 976,977,920 bytes free. Existing VGA / **1 FPS** preview
  was retained. A JPEG retrieved from the gateway during recording decoded as
  640×480 MJPEG. Recording wrote **107 frames, zero recording drops, two finalized
  AVI segments**, including a normal 60-second segment transition. Final path was
  `ainekio/video-9953353d-00000002.avi`; the preceding segment ends in `00000001.avi`.
- Maximum observed whole-frame recording write time was **114,535 us**. This is
  the storage worker's elapsed write/checkpoint time, not a continuous CPU stall.
  Observed control diagnostics reported maximum frame work **3,183 us**, zero
  output I/O failures and zero reported over-5-ms motion calculations. Internal
  heap samples during recording were **167,711–173,931 bytes**. This short test does not establish long-term
  heap stability or loaded motion responsiveness.
- Explicit upload entered Doze, stopped/finalized recording and remained connected.
  A complete 2,878,416-byte image was validated and staged with running/boot both
  still `ota_0`. The owner confirmed the staged-update screen was visible.
- Controlled activation booted `ota_1`, authenticated with the existing gateway
  and reported **accepted**, with `pending_verify=false`.
- Deliberately closing an upload after sending 16 KiB reported an upload timeout
  (12,576 bytes had been committed), preserving running/boot `ota_1`.
- A subsequent complete upload plus `next_boot` selected `ota_0` while execution
  remained in `ota_1`. A controlled restart then booted the candidate; one USB
  reset eight seconds after its app startup, before gateway authentication,
  caused actual bootloader rollback to **ota_1**. Final status: boot/running
  `ota_1`, no pending verification, no staged update, card mounted.
- An unavailable-card recording start returned HTTP 409 without changing boot
  selection or formatting the card. Physical removal, full-card writes and
  electrical card faults were not injected.

Intermittent WebSocket send-timeout/reconnect events were observed both before
recording and during recording. Therefore **uninterrupted streaming has not been
qualified**, although concurrent recording and delivered camera frames were
observed. Recordings on this physical card have not yet been copied to a computer
and decoded; the AVI writer's synthetic playback test is separate evidence.
No powered-servo motion, extended memory soak, card power-loss recovery or
full-card qualification was performed. Keep the current camera settings until
those remaining tests and the intermittent network behavior are resolved.


## Body Control maintenance, 0.8.22

**Robot firmware** accepts the compiled P4 application `.bin`. Select **Upload
firmware**, then **Activate on next boot** or **Activate and restart** after it
reports staged. Upload uses the previously approved Doze-and-finish-recording
sequence. Upload progress shows browser transfer progress; validation completion
and the robot screen identify when flash writing finishes. Select Idle afterward
when ready to resume normal operation; the camera preview preference is retained.
The C6 firmware is not changed. Ordinary use requires neither USB nor card
removal. Keep USB available for recovery from loss of networking or both slots.
The one-time OTA bootloader setup described above is already complete on the
owner's tested robot.

The dashboard keeps its existing password/session/CSRF mechanism. New routes
`/api/robot/recording`, `/api/robot/recordings`, `/api/robot/firmware`, and
`/api/robot/firmware/activate` run in existing HTTP request threads and stream
bytes to the selected robot. They do not run on the robot-control event loop.
The P4 reuses the existing HTTP server, following
[IDF 5.5.4 HTTP file-serving and chunked-response APIs](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32p4/api-reference/protocols/esp_http_server.html).
Its single HTTP worker serializes maintenance requests; a long clip transfer can
delay another maintenance request. WebSocket streaming/control and the storage
writer remain separate tasks. No extra service, codec, or framework upgrade.

Build/source checks: 0.8.22 application is 2,881,680 bytes (3,264 more than 0.8.21),
with 5,506,928 bytes free in an 8 MiB slot. Native AVI/OTA tests pass. Dashboard,
body-storage and recording tests pass 39/39, including authenticated selected-peer
uploads/downloads and bounded transfer chunks. A separate peer-resolution test
and JavaScript maintenance/motion race tests pass. Physical installation and
clip decoding for this version are pending at the time of this paragraph.

A six-minute physical camera A/B observation on 0.8.21, with recording stopped,
used the existing VGA/1 FPS configuration: camera on for 120 seconds, off for
120 seconds, on for 120 seconds. Each on interval saw one WebSocket reconnect;
the off interval saw none. All samples reported zero camera queue drops. Free
internal heap ranged 168,475–175,311 bytes with no sustained decline; RSSI was
about -51 to -53 dBm. This implicates camera traffic but does not prove camera
buffer exhaustion or isolate the root cause. The observed SDK
`transport_poll_write(0)` means a socket-writability timeout, per the pinned
[IDF transport implementation](https://github.com/espressif/esp-idf/blob/v5.5.4/components/tcp_transport/transport_ws.c).
Camera and control share that socket. No speculative buffer enlargement,
frame-rate reduction, or timeout relaxation was made. Wi-Fi stability remains
an open issue, not a claimed fix.


## Rolling-video validation, 0.8.23

Host tests execute the production storage selection, overwrite and AVI writer
against a temporary filesystem: oldest selection from 40 out-of-order clips,
32 cached selections without rescanning, recovery of sequence order after a
simulated reboot, reuse with zero reported free data space, preservation of the
same file inode/allocation on open, trimming stale tail bytes on close, download
pinning, and preservation of logs, snapshots and unrelated/unfinished files.
The existing bounded-queue ownership test, native AVI/OTA/download tests and
JavaScript maintenance handlers also pass. The FAT implementation was checked
against the pinned [IDF 5.5.4 VFS source](https://github.com/espressif/esp-idf/blob/v5.5.4/components/fatfs/vfs/vfs_fat.c).
The firmware build passes: **2,883,216 bytes**, 1,536 bytes larger than 0.8.22,
with 5,505,392 bytes free in the OTA slot. The index itself uses 2,176 static
bytes; no new recording task or JPEG buffers were added. These are host tests
and build measurements, not a full-card physical soak or throughput measurement.
Deployment is still pending the previously requested gateway restart/OTA approval.


## Installed rolling recording and Wi-Fi logs: 0.8.34, 2026-10-13

The owner reconnected USB for diagnosis. The USB trace identified two independent
issues in the maintenance additions, now corrected:

- OTA authentication deliberately calls the existing emergency-disable operation,
  which clears the driver's `ready` flag. Checking that flag afterward incorrectly
  rejected an initialized PCA device. Board initialization now exposes its probe
  result; OTA recognizes a deliberate disable while retaining I/O, deadline and
  progress-fault rejection. It never rearms outputs as part of this check.
- A 16,400-byte retained log bank exhausted contiguous early-boot task memory:
  `esp_startup_start_app` asserted when creating the main task, before `app_main`.
  The bank is now 8,208 bytes (4 KiB per boot). Stack sizes, watchdogs and the
  framework remain unchanged. IDF's early allocations precede release of the
  startup-stack heap regions; aggregate runtime free memory was not evidence that
  this early allocation could succeed.

Both `ota_0` and `ota_1` were installed and accepted using the existing Wi-Fi
uploader. Final running/boot slot is `ota_1`, pending verification is false,
version is `0.8.34-p4-rolling-logs`. The second boot checked `required=0x1f`,
`ready=0x1f`, C6 2.12.8, and 8,708 free body-stack bytes with outputs deliberately
disabled. No flash write used USB in this diagnostic/install round. A USB
restart returned an unaccepted diagnostic image to the working slot. Another
candidate's early startup panic also triggered actual bootloader rollback.

Body Control's authenticated Wi-Fi maintenance paths were exercised on hardware:

- Start/stop recording alongside the unchanged VGA/1-FPS preview: **241 JPEG
  frames, zero recording drops, five finalized segments**, storage error ESP_OK.
  Maximum observed frame write time was **137,562 microseconds**.
- Downloaded a **2,780,834-byte** completed AVI while recording continued.
  FFprobe reported MJPEG, 640x480, 1 FPS, 60 seconds, 55 encoded frames; FFmpeg
  decoded it without errors. Empty timing chunks account for frame gaps.
- Six telemetry samples over 50 seconds showed **172,031–173,603 bytes** free heap,
  zero camera queue drops, heartbeat age **58–349 ms**, and increasing camera
  counters. This is a short stability sample, not an endurance result.
- The observed body counters reported a maximum output-frame time of **2,422 us**,
  maximum bus transfer **2,381 us**, zero bus failures and an empty command queue.
  These counters include startup; no powered gait or loaded-motion test was run.
- Wi-Fi logs were downloaded before and after a controlled Wi-Fi OTA restart.
  The previous boot's `transport_poll_write(0)` failure survived, alongside new
  startup markers. Both slots now have the same retained-log layout, so compatible
  future rollback images can expose previous-boot diagnostics.
- Final state: streaming on, recording stopped, card mounted, **960,380,928 bytes**
  free. Start recording again through Body Control when desired.

One reconnect occurred during the recording run; the existing firmware also
showed association retries and WebSocket timeouts before these additions ran.
The logs now expose those failures over Wi-Fi. The bounded camera/recording queues
reported no drops during the measured run, but that does not establish the cause
of the intermittent connection. Recording follows preview availability, so a
lost gateway/camera session can leave gaps.

Full-card overwrite, forced SD write failure/removal, power-loss recovery and
powered gait remain untested on hardware. Production-code host tests cover oldest
slot selection, reuse with zero reported free space, cached directory indexing,
active/download pinning and bounded frame ownership. No test filled the owner's
card with artificial data or overwrote their older clips.

This image is **2,844,128 bytes**, leaving **5,544,480 bytes** in either 8 MiB slot.
The linker reports **155,992 bytes DIRAM**, **8,264 bytes LP RAM** (8,208 for logs),
and **892 bytes HP core RAM**, excluding runtime allocations. Recording retains
its three-frame/768-KiB PSRAM bound; the oldest-file index is 2,176 bytes; log
snapshots allocate at most 8,704 bytes. Binary size comparisons with earlier
images also include the owner's concurrent gait changes and are not a feature-only
size delta. Installed application SHA-256:
`93f7ca0f843717f208cafd115d12bff6ebb469e382d6e5c2087bff5bfdd4ee57`.

The final image includes the current gait/body implementation from the build
snapshot, verified against workspace gait files after testing. Concurrent IMU
telemetry edits added afterward to controller/CMake and new telemetry files were
left untouched and are not in this image. The build used an isolated source copy;
no baseline gait files were copied back into the workspace.

The final firmware build, OTA regression (including deliberately disabled outputs
and real output failures), three logging/recording host tests, eight P4 foundation
tests, dashboard maintenance JavaScript checks and diff whitespace checks passed.
The gateway dashboard's 33 tests also passed during this maintenance work. These
checks do not qualify the independent ongoing IMU/gait edits or powered motion.


## Wi-Fi investigation, 2026-10-13

The desktop adapter's power saving was disabled live, for its active
NetworkManager profile, and in a persistent NetworkManager default. No desktop
interface restart was used. Two gateway reconnects still occurred in a five-minute
sample afterward. This desktop configuration is outside the firmware repository.

P4 diagnostic 0.8.35 queried the actual C6 setting: `WIFI_PS_MIN_MODEM`,
not the no-sleep setting in Hosted's optional pre-provisioned startup example.
The network owner now requests `WIFI_PS_NONE` through the existing Hosted RPC
and logs both the set result and readback. The installed 0.8.36 body-events
build included this change and reported both operations successful. This uses
more radio power; current consumption was not measured. C6 firmware remains
2.12.8. See the [IDF 5.5.4 C6 power-saving documentation](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32c6/api-guides/wifi.html#esp32-c6-wi-fi-power-saving-mode).

With both radios awake, a 20-packet ping sample had no loss and 2.9 ms average
latency. Gateway disconnects nevertheless occurred with camera streaming disabled
as well as enabled. Camera buffering is therefore not the sole cause. TCP header
captures showed missing sequence ranges, duplicate acknowledgements, and socket
closure before loss recovery; they do not identify where the original packet
was lost. Send diagnostics caught 100 ms control timeouts and a 1000 ms camera
metadata timeout. `transport_poll_write(0)` reports a poll result of zero, not
a configured timeout of zero. No receiver zero window was observed.

Candidate 0.8.37 uses the pinned WebSocket client's supported separate TX lock
so blocking sends do not lock out receive callbacks. Existing build directories
must also enable `CONFIG_ESP_WS_CLIENT_SEPARATE_TX_LOCK=y` in their active
`sdkconfig`; defaults only initialize unset options. The local board configuration
and the tested isolated build both enable it. Its send wait is derived
from `CONFIG_LWIP_TCP_RTO_TIME` plus one 500 ms TCP slow-timer interval (2000 ms
in this build). Previously 100 ms control/audio metadata, 250 ms audio, and
1000 ms camera waits could close the socket before the configured initial
1500 ms TCP retry. This permits loss recovery; it does not eliminate RF loss
or guarantee uninterrupted service under persistent loss. The 4-second control
heartbeat deadline, task priorities, bounded queues, camera format/rate, storage,
and motion owners are unchanged. Per-chunk WebSocket waits remain bounded;
a multi-chunk frame may take longer than a single wait.

The build snapshot includes the current body-event, IMU, and gait source.
Fifteen focused Python transport/foundation/recording/log tests passed. The wider
native suite completed with 35 passes, 13 failures, and 3 skips: 12 failures
are in the current motion/calibration suite and one requires missing NumPy.
Those failures are outside the changed network/controller-send code and were
not altered as part of this work. Hardware installation and recovery observations follow.


### Installed 0.8.37 recovery test

Uploaded and activated through Body Control over Wi-Fi; `ota_1` reported
`accepted`, pending verification false, and startup devices `0x1f/0x1f`. C6
readback confirmed power saving off. No USB or C6 firmware replacement was used.
Image size is 2,847,904 bytes (8 MiB application slot); SHA-256
`3406447507cdfab90ee952b3a2038d67bf942f134d40186e9ab2f14fa755c325`.
The versioned and default ignored OTA application binaries point to this build.

The owner ended the planned ten-minute observation early. Collected evidence:

- 235 status samples spanning 469 seconds: one connection epoch, no reconnects.
- Simultaneous VGA/1-FPS streaming and recording: 411 recorded frames, eight
  finalized segments, zero recording drops, zero sampled camera queue drops.
- A new 2,880,846-byte clip downloaded while streaming and recording continued.
  FFprobe reported MJPEG 640x480, 1 FPS, a 60-second timeline and 54 actual frames;
  FFmpeg decoded it without errors.
- Median sampled heartbeat age 16 ms; maximum 1,459 ms, below the unchanged
  four-second deadline. TCP captures showed a 1,270 ms cumulative acknowledgement
  delay recover on the same connection, rather than forcing a reconnect.
- Free heap ranged from 152,375 to 173,779 bytes. First/last minute medians were
  170,579 / 169,307 bytes. These short samples are not a memory-leak soak test.
- Maximum observed card frame write was 267,615 us. Final card free space was
  938,344,448 bytes. Recording stopped cleanly at the owner's request; streaming
  remained enabled. No old recordings needed overwriting during this test.

This fixes the observed premature connection teardown and verifies short-run
recovery under real packet delay/loss. The original radio/transport packet-loss
location is not established. No powered gait, sustained audio traffic, forced
network outage or long endurance test was performed. Motion/output timing
counters describe startup with outputs disabled, not loaded physical motion.
No new buffers, tasks, restrictions, automatic stops or heartbeat deadline
changes were added for Wi-Fi recovery; the WebSocket option adds one mutex.
