# ESP32-P4-WIFI6 body firmware

Native V2 body-controller target (`0.8.0-p4-color-face`). It uses the portable Ainekio lifecycle,
configuration store and command decoder, with its own P4 startup, board resources,
C6 networking and PCA9685 output driver. It does not compile the S3 platform.

With a saved joint mapping, normal power-on enables PCA9685 channels 0–11 at their home pulses,
starting channels 200 ms apart and continuing to hold the resulting pose.
Default home is **1300 µs at nominal 50 Hz** on every body channel. Channels
12–15 remain off. Startup does not require Wi-Fi or a gateway connection.

This is the electrical assembly reference, not a calibrated chassis-supported
resting pose. The owner has updated the laying pose in the saved Blender scene
`ainekio-variable-gait-Recovery.blend` and exported it to the model's
`motions/gestures/rest/` source on 2026-09-22. Its endpoint has the chassis base
plate grounded and all four lower legs horizontal. Horn
indexing, joint mapping and pulse calibration must connect this geometry to
the actual body. The previously flashed assembly firmware still uses midpoint
pulses; updating geometric source alone does not change those home settings.
The current source integrates twelve-joint operator calibration, provisioning,
profiles/power states, removable storage, OV5647 camera, onboard ES8311 audio,
VAD and the shared wake-word engine. Readiness comes from the actual driver and
asset state. The current assembly uses a **0.96-inch SSD1306 I2C OLED** on
GPIO20 (SCL) and GPIO21 (SDA), selected by default in `sdkconfig.defaults`.
It renders the same face choices and connection guidance in 128×64 monochrome.
The temporary OLED implementation is isolated in `main/display_ssd1306.c`;
normal firmware builds with the current configuration include it, so flashing
other P4 changes retains the working display. Existing local `sdkconfig` files
can retain an older panel choice; confirm `CONFIG_AINEKIO_DISPLAY_SSD1306=y`
before building or flashing this assembly. The 1.9-inch ST7789 RGB565 LCD remains selectable with
`CONFIG_AINEKIO_DISPLAY_ST7789` when its replacement arrives. Its wiring and
expression guide is [here](../../../docs/v2-12servo/LCD_FACE.md). A build
selects one display driver, and the OLED source can be removed when retired.

While a microphone utterance is open (wake, VAD or Open gate), the display overlays
its animated Listening expression. It restores the underlying manual/motion face
when capture closes, including when speaker playback interrupts capture.
The sole body output owner also moves the physical front shoulders (model joints
6 and 9) by +6° over 300 ms, holds while capturing, then returns to the exact
previous commanded pose and pulses. The saved joint-speed limit can lengthen the
transition. Carrier/crank geometry is unchanged. Normal motions take priority;
calibration/manual targets supersede the cue, and existing Stop/disconnect/output
state ownership remains in effect. This feedback never arms detached outputs.

Speaker playback suspends both wake inference and microphone transmission from
TTS/asset start through the existing 800 ms post-playback interval. Wake history
and microphone pre-roll are flushed at playback boundaries. Results from an
in-flight inference are checked again before entering the recording FIFO, so a
speaker start during inference cannot open a stale recording. Dashboard input
telemetry distinguishes listening, capturing and speaker playback. Speaker DMA
writes release the media mutex so incoming audio and status callbacks can run;
cancellation invalidates the write and mutes it before another playback starts.

Body Control's Apply microphone button saves the microphone on/off choice,
Open/VAD/Wake mode and input gain on the P4. These survive power cycles and
controller reconnections; disconnect, sleep and speaker playback suspend capture
without changing the saved choice. Wake enable/model/sensitivity remain saved
by the separate wake settings control. Existing firmware installations retain
their gain and wake settings; apply the microphone choice once after upgrading
to save the formerly temporary on/off and mode settings.

The Audio section exposes microphone gain (0–42 dB in 6 dB steps) and wake
sensitivity (0–100%). Higher sensitivity lowers the model's
probability threshold; gain amplifies the captured signal. Input level is
reported before the wake/VAD gate, so tuning does not require a successful wake
first. The current settings are read back from the robot; changes take effect
without rebooting. The saved gain and
threshold are separate `p4_media` NVS keys, preserving existing wake preferences.

The body executes Stand, CAD Neutral, algorithmic walk/crawl (forward, backward,
left and right), and every gesture compiled from the model catalog. Fixed-angle
turn clips are no longer included in V2. Body Control
builds its pose buttons from the firmware's advertised commands. Walking supports
finite cycles, continuous operation, speed or independent stride/rate updates,
and Finish at the existing gait boundary. See the
[model implementation](../../software/models/v2-12servo/README.md) for the current
catalog, timing and source provenance. Finite commands hold their terminal pose;
Dead's optional preview recovery is excluded.

Current source advertises `walk_steering_v1` alongside `walk_controls_v2` for
the existing paired `forward`/`turn` decoder and gait owner. Both are finite
percentages from −100 to +100: positive forward advances, positive turn turns
left. An update ACK confirms admission and leaves the original action running;
only its terminal result ends that action. See the
[negotiated steering contract](../../software/protocol/README.md#directional-locomotion-and-automatic-run).
Older firmware lacking this feature receives no composed steering from the
gateway. Native decoder/model tests cover this source contract; this change has
not been cross-compiled, flashed or tested on a physical body.

All execution uses the existing body output task and device joint calibration.
Entry follows a coordinated carrier/crank path from a commanded reference; this is not measured shaft position. Conservative continuous path bounds and actual linkage closure are checked before execution; the provisional angle envelope is not a runtime dependency. When outputs are off or only some assigned joints have been commanded, a new motion request first engages the saved Home pulses 200 ms apart, then enters the requested motion. Save and reconnection alone leave outputs off. An invalid model reference is reported explicitly before enabling outputs; changing firmware defaults never rewrites measured Home pulses or model angles.
Clip angle envelopes are checked before movement, and every emitted pulse must
fit the PCA9685 timer capacity. An unrepresentable pose returns LIMIT without
silently compressing its geometry. Nominal calibration does not establish horn
alignment or make every modeled pose physically reachable. STOP, controller loss
and output faults cancel execution; reconnection alone does not resume it.

The robot-specific controller uses float circle intersections and two compact
sole profiles (101 Walk/Run vertices, 90 Crawl vertices), with at most four
endpoint evaluations per leg. It rejects unreachable geometry and retains the
linkage branch. No iterative multijoint solver, line search, support tree or
runtime research search bounds remain. Detailed CAD geometry and Python fitting
stay on the workstation. Contact integration retains its bounded substeps and
fixed stance anchors. Run Finish honors already committed airborne landings
before deceleration, including explicit Run after speed changes.

Finite motion playback uses verified cubic segments instead of dense 120 Hz
arrays. Continuous fitting error is bounded to 0.005 degrees before float
rounding; all recorded extrema, holds, endpoints and command durations remain.
The compiler emits clip extrema so startup does not scan every recorded frame.
The body output owner retains the last successfully written model pose alongside
its pulse frame. Automatic motion entry does not invert rounded PWM; manual
calibration pulses establish their literal reference once. Mapping changes and
output faults invalidate the cached model reference. No NVS layout, saved pulse,
channel, inversion, Home angle or us/degree scale is changed.

The existing Stop, generation fencing, output owner, 20 ms cadence and independent
40 ms progress guard remain. The update path uses fixed storage, with no heap
allocation, storage writes or media processing. Console `controller` reports
observed maximum calculation/frame/request time, over-budget counts, body stack
headroom and internal heap. These measurements are observations, not guaranteed
bounds under untested media workloads. See the model's
[controller validation](../../software/models/v2-12servo/CONTROLLER_VALIDATION.md)
for resource costs, removed components and qualification limits.

The current source build is `0.8.0-p4-color-face`; prior deployment records below refer to `0.6.1-p4-motion`. It requires the 8 MiB application partition. Boards still using
the old `0.3.0-p4-turns` partition layout require the migration described in the
[integration record](../../../docs/v2-12servo/MOTION_INTEGRATION_20260917.md),
not just an application-only flash.

## IMU foundation

The [portable IMU component](../../software/imu/README.md) is compiled by the P4
project and exercised by its native test project. It defines timestamped samples,
calibrated sensor-to-body transforms, attitude estimates and freshness/recovery
flags using pinned x-io Fusion sources. It does not start acquisition, transmit
IMU telemetry or modify movement. Wiring, mounting calibration, the sensor driver
and physical timing measurements are the next integration step. The existing
motion/output owner and motion library are unchanged by this component.

## Shared camera streaming and snapshots

The camera owner multiplexes preview JPEGs and correlated stills in one task.
Espressif `esp_video` / `esp_cam_sensor` control CSI and the OV5647, `esp_ipa`
controls the P4 ISP, and ESP-IDF's hardware JPEG encoder compresses the images.
RAW10 stays on the P4; Body Control receives JPEGs. Sensor AEC/AGC adjusts
exposure/gain; Body Control selects capture profiles, not individual shutter
or ISO values. The vendor OV5647 ISP tuning remains unchanged.

`camera_profiles_v1` provides independent preview/still settings; the additional
`camera_adaptive_v1` feature enables `snapshot_res: AUTO | 960P | FHD` alongside
QVGA/VGA/XGA. Preview remains QVGA/VGA at 0–15 fps. Still boot default is AUTO;
JPEG quality remains 75. Changing preview settings preserves the still profile
unless `snapshot_res` is supplied. Neither profile is stored in NVS.

Preview uses the 1280×960 binned mode with one-frame exposure. Stills enable
the OV5647's eight-frame night integration range (about 178 ms in 960p, 267 ms
in 1080p); the sensor still chooses the exposure and gain for the light. After
startup/profile changes, stills collect at least eight frames and wait until
measured exposure and gain remain within 1/16 of an anchor for 300 ms. After
four seconds per mode, a changing scene returns the current image marked
unsettled instead of waiting indefinitely. This does not stop robot motion.

AUTO meters in the full-field 1280×960 mode. If settled exposure × gain is at
most 1/30 second at unity gain, it switches to the vendor's **cropped 1920×1080**
mode and settles again; otherwise it returns 1280×960. This is an explicit
initial selection heuristic, not a measured optimum across scenes. Select
960P to keep a consistent full field of view, or FHD to force cropped detail.
The installed camera is mounted upside down. Every emitted preview/still image
is rotated 180 degrees before JPEG encoding, so saved files and all consumers
receive upright pixels. Preview rotation is folded into the existing resize
sampling; native stills reverse their dequeued RGB565 buffer in place before
hardware JPEG encoding. This adds a CPU pass for native stills, with no additional
full-frame allocation or sensor/ISP Bayer-pattern changes. Exposure and gain
behavior is unchanged. Physical capture latency must be measured on the P4.
The existing 256 KiB JPEG transport capacity remains unchanged; a larger
encoded image returns the existing camera failure, without silently lowering
quality. Full 5 MP raw capture and host-side raw processing are not implemented.

Queued stills retain their requested resolution, work with preview disabled,
and emit `fps:0` metadata with their original correlation. A still does not
reset the next preview deadline. Shared encoding and transport can still delay
preview delivery; concurrent throughput and acquisition age require device
measurements. The two capture buffers are resized when the sensor mode changes;
the resize scratch remains 1024×768 RGB565 and JPEG storage remains 256 KiB.
Status `camera_capture` reports counter, actual width/height, `exposure_us`,
`gain_x16` (16 = unity gain, not calibrated ISO), `settle_ms`, and `settled`.
The settling flag describes sensor settings, not a guarantee of image quality.

The native `camera_profiles_and_snapshots` test runs production `camera.c`
against virtual sensor/encoder/scheduler I/O. It covers independent profiles,
zero-FPS snapshots, settling, changing illumination, native mode selection,
preview resumption, cancellation, session fencing, and pixel orientation across
native/downsampled images and mode switches. It does
not establish physical sensor operation, image quality or encoding latency.

Physical check, 2026-10-06: application `0.8.1-p4-camera-face` was flashed at
`0x20000` with esptool hash verification, preserving NVS. Fresh stills returned
1280×960 and forced 1920×1080 JPEGs; measured night exposures reached 177,621
and 266,513 µs respectively. VGA preview used approximately 16–19 ms exposure
in the tested room. A correlated still during preview arrived at native
1280×960 after about 3 seconds, followed by resumed VGA preview about 0.1 s
later. Camera drops remained zero during these checks. The Body Control page
rendered the six snapshot choices and measured capture details without browser
exceptions. Native tests cover the AUTO bright-scene selection; its automatic
bright-scene transition and image tuning across other environments still need
physical comparison. No gait was exercised during the camera checks.

Camera rollback, 2026-10-09: `0.8.14-p4-camera-revert` restores the
pre-controls camera implementation: one-frame automatic preview exposure,
original preview resolutions and JPEG quality 75. It retains the separate
wake-audio snapshot correlation fix and the current full robot application,
including the SSD1306 OLED driver. It does not advertise `camera_controls_v1`;
Body Control hides the experimental manual controls for this firmware.
The previous `0.8.13-p4-camera-controls` trial is withdrawn because long preview
exposure caused motion blur and automatic exposure showed brightness alternation.
The gateway/protocol support remains compatible with other capable firmware.

### OV5647 automatic exposure and ISO

`0.8.16-p4-iso3200` raises the automatic gain ceiling to 32x (ISO 3200
on the same OV5647 scale), as requested. Preview shutter remains capped at
approximately 66.7 ms; shutter and gain both remain automatic. This changes
the ceiling, not a fixed ISO. Other camera and robot functions are preserved.


The published Raspberry Pi V1/OV5647 ISO convention is ISO 100/200/400/800
for overall gains 1/2/4/8. It prefers analogue gain over digital gain. The
[PiCamera ISO documentation](https://picamera.readthedocs.io/en/release-1.13/api_camera.html#picamera.PiCamera.iso)
distinguishes this convention from the standards-calibrated V2 sensor mapping;
it does not establish absolute ISO calibration for this P4/module/lens assembly.
The [Raspberry Pi OV5647 helper](https://github.com/raspberrypi/libcamera/blob/main/src/ipa/rpi/cam_helper/cam_helper_ov5647.cpp)
confirms sensor register gain code = analogue gain × 16 and explicitly accounts
for two unreliable startup/mode-switch frames.

[Raspberry Pi's OV5647 tuning](https://github.com/raspberrypi/libcamera/blob/main/src/ipa/rpi/vc4/data/ov5647.json)
provides exposure-mode curves, noise calibration, black level, white balance,
colour matrices, lens shading and gamma. Its primary normal exposure curve uses
1–8× gains; using the register's entire 1–63.9375× numerical range is not an
image-quality qualification. These parameters target Raspberry Pi's ISP and
must be translated and measured on P4, not copied as a drop-in configuration.
[Espressif esp_ipa](https://github.com/espressif/esp-video-components/blob/master/esp_ipa/README.md)
is the existing P4 owner for noise, enhancement, colour and exposure algorithms.
[OmniVision's OV5647 datasheet, section 4.6](https://docs.arducam.com/Raspberry-Pi-Camera/Native-camera/source/OV5647DS.pdf)
documents exposure convergence, night integration and 50/60 Hz anti-banding.
`0.8.15-p4-auto-iso` keeps the sensor's AEC, AGC and frame-length control
fully automatic. Preview permits exposure up to approximately 66.7 ms instead
of one frame; stills keep their eight-frame range. The automatic gain ceiling
is 8x (ISO 800 on the documented OV5647 scale), rather than 63.9375x.
These limits do not fix either shutter or gain: the sensor meters the scene.
Body Control displays measured exposure and ISO-equivalent gain. This is the
published sensor convention, not a new absolute ISO calibration. Dim scenes
can remain dark at these limits, and longer exposures can blur motion.
The firmware retains the entire robot application and SSD1306 OLED. It does
not re-enable the withdrawn manual-controls trial. Native tests verify the
control registers and changing readback; real image quality requires a
lighting comparison on the actual module.

Initial USB-powered check of `0.8.15-p4-auto-iso`: application-only flash verified,
SSD1306 reports `driver_ready=1`, saved calibration remains present, and camera
reports zero drops. Twenty VGA preview frames delivered 0.92 fps at the saved
1 fps setting; the longest observed delivery gap was 2.08 s. The dim scene
reached both configured ceilings: 66,567 us and gain code 128 (8x/ISO 800).
It remained underexposed, so this is **not** evidence of qualified image quality
or measured adaptation to changing illumination. The initial post-reboot camera
restore was rejected as stale; reapplying the same saved camera setting started
the stream. No motion command was used. An illumination-change check remains
necessary; the software tests only establish automatic control configuration
and preservation of changing sensor readback.

## Command diagnostics

Body Control saves command results (including the robot's rejection code and
message), dashboard request failures, and robot clock gaps of at least one
second in its existing `operations.jsonl`. The physical launcher uses
`build/gateway/physical/operations.jsonl`; the preceding segment is
`operations.jsonl.1`. Records include robot identity, connection epoch and
command sequence where available, plus walking speed and gait for correlation.
Pairing tokens and Wi-Fi/setup passwords are excluded from these records.

P4 status and execution failures include `output_timing` (last and maximum I2C
call duration in microseconds, transfer/failure counts, and the existing timing
budget and last failed ESP-IDF result, retained until the next failure/reboot),
`motion_timing` (existing calculation/frame/request maxima and the
output queue depth), and `controller_queue_depth`. Maxima and counts are since
boot. Serialization runs in the controller tasks, outside the servo output
loop. These observations retain the existing clock and I2C deadline rules.
The serial console also includes ESP-IDF's I2C failure messages, distinguishing
hardware NACKs from hardware/software timeouts without logging each frame.

The eight-entry controller queue and one-entry output queue buffer work between
tasks. They are not a playlist that waits for each entire motion to finish:
walking updates adjust the active walk, and a new motion can replace it. The
gateway's fresh-clock check happens before a command reaches either robot
queue; an I2C deadline failure happens while the robot executes it.

## Build and flash

Use ESP-IDF **5.5.4**. The tested board is P4 **revision 1.3**, 32 MiB flash and
32 MiB PSRAM. `sdkconfig.defaults` explicitly selects pre-3.0 silicon. Recheck
revision before using this configuration on another board.

The manifest and lock pin `esp_hosted` **2.12.8**, `esp_wifi_remote` **1.6.4** and
`esp_websocket_client` **1.7.0**. The C6 runs the matching Hosted **2.12.8** slave
from the same resolved package, with its own committed dependency lock. Both
sides use SDIO packet mode. No vendor library patches are required.

From the repository root, after installing ESP-IDF 5.5.4:

```bash
source /home/greggles/esp/esp-idf-v5.5.4/export.sh
cd Slave/firmware/esp32p4-wifi6
idf.py -B build -D IDF_TARGET=esp32p4 -D AINEKIO_C6_IMAGE= build
idf.py -B build -p /dev/serial/by-id/usb-1a86_USB_Single_Serial_5B90184020-if00 -b 460800 app-flash
idf.py -B build -p /dev/serial/by-id/usb-1a86_USB_Single_Serial_5B90184020-if00 monitor
```

The IDF install and serial paths above are the bring-up workstation's paths;
substitute the actual installation and device on another machine. A C6 update
is only available when a real image is embedded. Run `net c6-update` once if the
installed C6 does not match, then verify its reported version after reboot.
The updater latches maintenance/disarm, streams the image through Espressif's
SDIO OTA API and restarts. Failed updates remain in maintenance until reset.
The installed C6 already reports 2.12.8; normal P4 flashes need no C6 rewrite.
Embedding its updater is a separate maintenance operation: run
`bash tools/build_c6.sh`, then build with
`-D AINEKIO_C6_IMAGE="$PWD/build/c6/network_adapter.bin"` when that update is needed.
The normal build clears this cached option to omit the unused updater payload.

`partitions.csv` assigns NVS at `0x9000`, PHY at `0xf000`, and an 8 MiB app at
`0x20000`. P4 configuration uses namespace `p4_config` and the existing staged
two-slot store. There is no automatic NVS erase. Back up occupied flash before
changing another board's partition layout. Build outputs and credentials are
ignored, and must not be committed.

## Resource ownership

`main/board.c` creates the PCA bus and owns OE. Consumers receive its output
driver; they never create a second bus or write OE directly.

| Resource | Assignment / reservation |
| --- | --- |
| PCA9685 | I2C controller 1, SDA GPIO2, SCL GPIO3, address `0x40`, 400 kHz; OE GPIO4 |
| Face display | Current OLED: SDA GPIO21, SCL GPIO20, VCC 3V3, common GND. Alternative ST7789 LCD: SPI2 SCLK20, MOSI21, CS22, DC23, RESET26; VCC and BLK on 3V3. Select the connected panel in menuconfig. |
| Header reference | With USB-C at top, component side facing you: GPIO2=L15, GPIO3=L14, GPIO4=L12, GND=L13, 3V3=R5. L/R are top-down guide row IDs; see the [pinout and wiring guide](../../../docs/v2-12servo/PCA9685_WIRING.md). These correspond to schematic U10 pins 15/14/12/13/36. |
| Onboard codec/camera I2C | GPIO7/8 reserved; no competing legacy I2C driver |
| C6 SDIO | CLK18, CMD19, D0–D3 14–17, reset54; C6 boot6 reserved |
| Debug console | UART37/38 through CH343P and the board's Type-C connector |
| Native USB HS | P1 four-pin MX1.25 connector reserved: 1=VCC_5V, 2=D−, 3=D+, 4=GND |
| Other reserved resources | USB FS GPIO24/25, boot35, SD39–45, codec/I2S9–13 and PA53, MIPI camera/display lanes |

The [Waveshare schematic](https://files.waveshare.com/wiki/ESP32-P4-WIFI6/ESP32-P4-WIFI6-datasheet.pdf)
routes Type-C to CH343P, and P1 to native USB. P1's 5 V pin joins the board power
rail. Future Q6A USB must resolve VBUS isolation/power ownership before connecting
two powered boards. Native USB is reserved; no USB command implementation exists.

## Console diagnostics

Use a private 115200-baud serial terminal. Opening a terminal can reset this
board through DTR/RTS; wait for the `ainekio-p4>` prompt before sending commands.

| Command | Behavior |
| --- | --- |
| `board` | Chip revision, flash, reset cause, pin assignment and driver state |
| `controller` | Selected connection generation, epoch and capability readiness |
| `face` / `face list` / `face NAME` / `face auto` | Display driver/frame diagnostics, available expressions, manual face, return to motion-driven selection; no PWM output |
| `gait walk <cycles> <elapsed-ms> [speed | stride rate]` | Evaluate variable walking to elapsed time; automatic Speed or independent stride/rate; no PWM or motion completion |
| `gait <installed-finite-command> <elapsed-ms>` | Sample a complete gesture, e.g. `gait bow 2500`; holds its recorded final pose after completion; no PWM |
| `net` | C6 network initialization, station IP and AP state |
| `net ap` / `net retry` | Request the existing provisioning state machine's setup AP / return to station operation |
| `net key` | Display the device's persistent WPA2 setup-AP password locally |
| `disable` | Direct latched emergency disable; no motion queue or I2C wait |
| `home` | Resume the saved home after a stop; starts enabled channels 200 ms apart |
| `config home` | Show the twelve saved home pulses; zero means off |
| `config home <channel> <pulse-us or off>` | Save one channel (0–11, pulse within PWM timer capacity, or `off`), disable outputs, then restart using the new home |
| `config <ssid> <psk> <endpoint> <robot-id> <token>` | Validate and commit configuration, then restart at home; quote values containing spaces |
| `config controller <endpoint>` | Change only the selected controller URL, retain credentials, then restart at home |
| `net reset` | Clear saved Wi-Fi while retaining pairing identity, then prepare a restart |
| `system` | Profile, state, uptime, heap, OTA and storage status |
| `system profile home` / `system profile tether` | Persist the selected resource profile; camera and microphone remain under explicit user control |
| `system idle` / `system doze` / `system sleep <seconds>` | Resume media availability / disable outputs and media / prepare timed deep sleep |
| `system storage retry` / `system storage clear` | Wait for actual mount / clear only Ainekio logs and captures |
| `system restart` | Drain services and restart; preparation failure leaves outputs disabled |
| `net c6-update` | Real SDIO coprocessor update, only compiled with an embedded image |

Endpoints end in `/robot`, for example `ws://HOST:8790/robot` on a trusted LAN or
`wss://HOST/robot` with a verified server certificate. WSS initializes SNTP for
certificate dates; body deadlines always use the monotonic clock. WSS has not
been exercised in this bring-up. No certificate-validation bypass is provided.
The existing LAN trust model is retained: the body authenticates to the selected
gateway with its token; plaintext LAN WebSocket does not cryptographically
authenticate the server. Use TLS for connections needing server authentication.

The setup AP defaults to WPA2 association and provides DHCP and browser provisioning at
`http://192.168.4.1/`. The HTTP listener accepts the AP interface only, validates
bounded configuration input and a per-start CSRF token, and preserves existing
pairing identity for network-only changes. The setup key persists across boots.
The serial configuration commands remain available.

Firmware advertising `robot_settings_v1` also supports authenticated settings
readback, per-slot network writes/removal, setup-hotspot password and pairing-token
changes, and a separate restart-to-apply command through Body Control Settings.
`gateway_switching_v1` adds multiple Body Control computers on one Wi-Fi and
uses the existing DNS-SD owner shared with the S3 target. Four ordered connection
slots each contain a network and controller URL. Slots for the same SSID share
one password and must have distinct URLs; their NVS layout/version is unchanged.
While offline, the network task tries the next distinct network every 15 seconds.
A working Wi-Fi link stays selected. The existing controller link task cycles
that network's configured URLs after connection failure, followed by up to eight
discovered protocol-v1 LAN gateways on the current station subnet. TLS-only
networks never discover plain WS; explicit `wss://` URLs retain certificate-bundle
verification. The MDNS dependency is pinned to the S3 target's `1.11.3` version.
An attempt must authenticate within 10 seconds; a healthy authenticated session
remains selected until loss or explicit gateway shutdown. Old admission/client
state closes before another WebSocket is created, and network-generation changes
discard old discoveries. No movement replay, task migration or second admission
owner is added. Existing output disable, emergency stop and stale fencing remain.

Control silence and transport loss have separate consequences. The four-second
control timeout disables physical outputs and latches stopped execution while
retaining the authenticated bridge for media and telemetry. Fresh control
traffic can recover on the same generation/epoch; it does not re-arm outputs,
reset sequence history, or replay movement. Actual Wi-Fi/WebSocket failure still
uses the existing reconnect and paired-gateway selection loop. Firmware logs the
stale-output stop explicitly. This source behavior requires a firmware update;
host tests alone do not establish continuous operation on a flashed robot.
The existing
60-second setup fallback remains active while cycling unavailable networks.
Settings saves disable outputs and use an atomic P4 NVS blob with revision checks;
running credentials remain immutable until restart. Legacy single-network records
and the generated setup key are imported without erasing NVS. All network slots
are cleared by `net reset`, retaining identity, pairing and setup credentials.
Explicit empty Wi-Fi passwords select open networks. Settings readbacks never
include passwords or tokens. See [Body Control setup](../../../Master/gateway/README.md)
for the save/apply and token-transition workflow. Firmware compilation and host
tests do not qualify physical Wi-Fi switching, setup recovery or servo behavior.

Native switching and discovery tests compile the production selection, settings,
DNS-SD and shared admission owners with `-Wall -Wextra -Werror -Wpedantic`.
The gateway software tests exercise two independent real loopback WebSocket
servers, verified TLS and the production SIGTERM entrypoint with simulated body
I/O. Actual ESP-IDF build, mDNS/Wi-Fi operation and Cloudflare-to-P4 use still need
the SDK and authorized device validation; these fixtures do not prove motion.

## Startup and assembly

Power off before adding a servo or moving its connector. Use the assigned
joint channels as the body is assembled. On the standard breakout viewed with the
screw terminal above the servo rows, channels run from 0 at the left to 15 at
the right. Ground is the outer row, V+ the middle row, and signal the inner row.
The owner confirmed physical movement from channel 0 on 2026-09-22.

The first leg being assembled is **physical front-left** (driver's front).
The legacy CAD group for this leg is `RL`; `model.json` owns the physical names
and channel assignments. Its three assigned channels match its stable joint IDs:

| Physical front-left joint | PCA channel | Mechanism reference |
| --- | --- | --- |
| Shoulder: sideways leg movement | 6 | `h_Part002` |
| Upper-leg carrier | 7 | Servo `Part_006`, carrier `Part_023` |
| Crank driving the linkage rod | 8 | Servo `Part_005`, crank `Part_009` |

Channel 6 is the seventh slot counting from the known channel-0 end. These are
assembly assignments, not evidence of installed or calibrated joints. The owner
has now attached the front-left shoulder and is establishing its horn index;
channel-0 movement was previously confirmed with a loose servo. Other legs remain unassigned in the model. Fit one servo at a time,
center its output before indexing its horn to the current mounting offsets. The laying pose is a separate motion, not the midpoint reference. No pulse direction, travel scale or joint limit has yet been
measured; `device_calibration` remains unset.

Power-on starts the configured channels over about 2.2 seconds. This staggers
engagement, not the speed of each servo: each starts toward its own home as soon
as enabled. The controller does not read shaft position or detect plugged-in
servos. Every enabled channel is driven whether a servo is present or not.

Keep the chassis supported and the joint unloaded while establishing horn
indexing. Centering a servo does not establish the correct horn angle for an
already assembled linkage. Do not force a powered servo against a mechanical
stop. The revised laying geometry and the physical horn positions must agree
before calling this a body rest pose.

`disable` or an authenticated gateway stop latches output disable immediately.
Use `home` locally or Home/Move in Calibration to establish a known reference before semantic motion. Entering calibration reinitializes the driver with all
channels off; it does not move a joint. I2C faults, stalled frame updates and loss of an already
authenticated controller also disable outputs; reconnecting alone does not
resume them. Initial Wi-Fi/gateway unavailability does not block startup home.
After a reported brownout, watchdog, panic or other fault reset, automatic home
is inhibited; `home` permits an explicit retry. A complete power loss can still
appear as a fresh power-on and restart home. Firmware cannot cut the servo rail.

Joint settings use one compact `p4_config/joint_mapping` record: twelve channel
assignments, Home pulses, inversion, model angles at Home and µs/degree. Each
joint is 12 bytes; the versioned record is 148 bytes. There are no stored pulse
endpoints or old-record import paths in the firmware. Missing or invalid saved
mapping leaves startup outputs off; explicit calibration remains available.

For installation on a previously configured board, export its existing mapping
before flashing, then restore Home/channel/inversion/angle/scale through the new
calibration service. Existing device data has not been erased. The P4 was offline
when this source cleanup was checked; a fresh transfer has not been performed.
This update is not a compatible interpretation of the old NVS record.

Default Home is 1300 µs, with model offsets
shoulder 0°, carrier +1.17°, crank −40.41° for non-inverted servos. These references
balance the restored leg-joint trajectories without changing motion or gait.
Saved mappings are retained; re-index horns and explicitly update Home angles
when adopting this mounting reference. The 11.111111 µs/degree conversion implies
234° across the observed 300–2900 µs span but remains provisional; pulse endpoints do not measure
shaft travel. Follow [the assembly guide](../../software/models/v2-12servo/SERVO_ASSEMBLY.md)
and verify each installed servo's scale, direction and horn index.

Body Control reads the device's twelve records, stages settings without moving,
commands a selected pulse or selected/all home, and explicitly saves. Changes to
the mapping and Save disable PWM; Home/Move resumes it deliberately. Save commits
without rebooting. Duplicate active channels and pulses the PWM timer cannot
represent are rejected; channel `-1` disables a joint. There are no per-joint
pulse Min/Max fields in the firmware, protocol or P4 interface.
Status reports `pulse_min_us`/`pulse_max_us` from the configured timer;
these describe hardware pulse capacity, not measured servo travel. At nominal
25 MHz and prescale 121, accepted integer requests are 3–19986 µs. This is not a
recommended servo sweep. Normal motion targets and clip/entry extrema use this
same timer capacity. The direct model checks actual rod/pickup closure.
A manual pose that cannot close the linkage is rejected for
semantic entry; operator recovery is required. Entry preflight includes
intermediate path extrema. Gaits, named motions and entry transitions share an
owner-configurable commanded joint speed limit in degrees per second. Body
Control reads and saves it through `motion_speed` / `joint_speed_limit_v1`.
The robot persists it independently of calibration and the named-motion
multiplier. The initial displayed value is the former nominal 545.4545 °/s;
there is no fixed upper ceiling. Automatic Run increases stride, leg lift, body
bounding and requested cadence together through its Speed range. The configured
limit retimes the whole motion while preserving its requested stride. Independent
stride/rate mode and other motions also retime together at the configured limit,
without the former 125% trigger or separate pulse-speed entry bound.
Status reports `speed_limited`, `joint_speed_limit_deg_s` and `gait_cadence`
(commanded/requested cycles per second and stride percentages). These describe
commanded timing, not measured shaft tracking. Manual calibration pulses and
startup Home remain direct pulse operations. Saving uses the existing output
disarm behavior; a subsequent operator motion resumes outputs.
Motion converts model angles
using `home_us + direction * (angle - home_angle) * us_per_degree`. Calibration
exposes that reference and scale. A manual pulse remains the literal commanded
pulse. Readback reports commanded pulses, never measured shaft position.
Home-all completes readback after its last channel is written.

The negotiated `body_calibration_v2` and `storage_control_v1` operations wait for
ACK plus correlated device status. Media readiness is refreshed through status
capabilities. Storage retry/clear waits for its own worker completion; clear
removes only bounded Ainekio logs and captures, never formats the card. Battery
voltage/current are not fabricated: `power_monitor_ready=false` until an actual
measurement path is specified.

The existing output task owns homing and the PCA driver. There is no separate
test build, timed servo-test adapter, wiring-acknowledgement gate or firmware
fault-injection command. The direct OE stop and progress watchdog remain.

## Servo power

During assembly testing, PC USB supplies the P4 and all twelve servos through
the P4 5 V terminal. The intended finished supply is 5 V / 3 A; its adequacy
under actual motion remains unmeasured. Startup
staggering reduces simultaneous starts but does not limit total holding/stall
current. A brownout does not prove that cables, connectors or the P4 power path
are safe at that load; this firmware has no current or temperature measurement.
Do not use repeated brownouts or a jammed linkage as a current-limit test.

For multiple servos, feed the PCA V+ terminal directly from the selected 5 V
servo supply and retain common ground with the P4. Remove the P4 5 V-to-V+
jumper before connecting that supply; retain P4 3V3-to-VCC and the signal wires.
Never join two independent +5 V sources. A 2.4 A bank remains a limited test
supply, not an established twelve-servo operating supply. See the
[power-pin reference](https://learn.adafruit.com/16-channel-pwm-servo-driver/pinouts).

## Host driver checks

These tests run on the workstation and are not linked into the firmware:

```bash
cmake -S components/ainekio_pca9685 -B /tmp/ainekio-p4-driver-tests
cmake --build /tmp/ainekio-p4-driver-tests -j4
/usr/bin/ctest --test-dir /tmp/ainekio-p4-driver-tests --output-on-failure
```

Historical deployment, 2026-09-22: ESP-IDF build and host PCA driver tests passed.
The `0.4.2-p4-home` application was flashed at `0x20000` with esptool hash verification.
Live startup reported `home holding; startup complete`, twelve valid 1500 µs
settings, and `ready=1 armed=1 fault=0`. This is controller evidence; physical
movement was previously confirmed only for the connected channel-0 servo. The
application is 3,732,512 bytes, SHA-256
`b1596d06bc503f852106c6a765ec67de3b1496b3170994aefc941b144397f3ea`.

Earlier system-port deployment, 2026-09-22: `0.5.0-p4-body` was flashed with the full layout
and voice/wake assets. All written regions passed esptool hash verification;
NVS/PHY readback before boot matched the full recovery backup byte-for-byte.
The first boot exposed a pre-main heap shortage on revision 1.3. The production
defaults now bound Hosted SDIO TX/RX queues to eight, freeing approximately
38.44 KiB before main starts without changing task stacks or driver code.
The rebuilt and verified application is 4,513,136 bytes, SHA-256
`69a6674decc36803b3bd8fbacba98d4ced6d150e3a748a6fbde1c0fb0bbde85b`.

The corrected boot completed home and reported `ready=1 armed=1 fault=0`, twelve
valid 1500 µs home settings (`saved=0 dirty=0`), and an authenticated gateway
connection. Voice/wake assets loaded; microphone/speaker/wake report ready.
Camera and SD card were not detected. These startup reports do not establish
physical pose, recording, playback, or combined-load performance.

Current motion deployment, 2026-09-22: `0.6.1-p4-motion` uses the same full layout
and assets. It includes the installed motion catalog, calibrated single-task
PWM execution and a 250 ms clock-sample interval for reliable command dispatch.
See the [current verification record](../../../docs/v2-12servo/FIRMWARE_DESIGN.md#motion-integration-verification-2026-09-22)
for the image hash, timing measurements and remaining pose-to-servo range
incompatibilities. Enabled controls are not proof that every modeled pose fits
the assembled mechanism.


## Speaker output

The onboard ES8311 output is set to 100 in `0.8.4-p4-speaker-output`.
Earlier firmware fixed it at 55, adding 22.5 dB of attenuation relative to 100
after the dashboard had already scaled its test tone. Body Control's **Audio →
Test volume** slider still controls the two-second tone's PCM amplitude; 100%
sends full-scale PCM without that extra firmware attenuation. It is a test-tone
control, not a saved master volume setting for other audio.

The codec change also raises playback of streamed speech and stored sounds.
Start the physical speaker comparison at a low test volume and increase it as
needed. Successful initialization or command completion alone does not establish
audible volume, distortion, or speaker power.

Installed 2026-10-06: the ESP-IDF build and dashboard speaker-volume test passed.
The application-only write at `0x20000` passed esptool hash verification; saved
calibration remained intact. After reconnect, a 10% dashboard tone completed
(`done`, sequence 4) with zero reported speaker underruns and output faults.
The owner then tested the connected speaker in Body Control and reported that
it works. Application SHA-256:
`0568911593943fed17d69a4feca1b3d1194366d11504a8637e8978f54f0f5f21`.

## Wake-word recording

`0.8.5-p4-wake-recording` sends `vad_open` as well as `wake_word` when the
on-device detector recognizes Ainekio. The earlier P4 callback sent only
`wake_word`, so the gateway never opened an utterance for the following PCM.
Recording start/finish events now share the microphone PCM FIFO, preserving
pre-roll and final samples even when the link task is delayed. Wake detection,
speech endpoint timing and the gateway's existing WAV assembly are unchanged.

Wake-triggered utterances lasting at least 300 ms now queue one still when the
recording closes, matching the S3 speech-photo behavior. The recording boundaries
and camera metadata share the first PCM counter as `origin_id` (including zero),
so Body Control correlates the photo with the same utterance it forwards to
MetaHuman. Capture runs on the existing camera task using the configured still
profile, independently of microphone delivery and transcription. Ordinary VAD/Open
recordings do not request this automatic still. Missing/unavailable photos remain
missing evidence; they do not hold transcription for an image timeout.

This source change requires a P4 application flash and a live wake-word/photo
check. It does not add continuous hazard detection or autonomous avoidance.

In Body Control, enable **Wake word enabled**, select **Ainekio**, and **Save
wake setting**. Then select **Microphone → Gate: Wake word → Apply microphone**
with Microphone checked. The wake preference is saved on the robot; microphone
capture remains session-scoped and must be enabled again after a reconnect.

Regression coverage compiles the production P4 microphone callbacks and packet
sender against queue/WebSocket shims, then passes their actual wire messages to
the gateway assembler. Both wake and ordinary VAD preserve the full recording,
and packets belonging to an old connection are discarded. Run it with:

```bash
PYTHONPATH=Master:Slave/software python3 -m unittest Emulator.tests.test_p4_audio_transport -v
```

This test does not establish acoustic wake-word accuracy or live MetaHuman
transcription; those require a spoken test with the robot and its receiver.

Installed 2026-10-06: ESP-IDF build, the P4 transport regression and the gateway
WAV/utterance tests passed. The application-only flash at `0x20000` passed hash
verification. After reboot, saved calibration remained intact, the saved Ainekio
wake model was enabled and ready, and microphone wake mode was applied through
Body Control. Application SHA-256:
`9df9471fe4ee96983af01bfe8c3af62fbda8f72f23529706ebdbc72fd97d7db0`.

The first live wake test exposed a separate pre-existing stack shortage: the
P4's `p4_mic` task overflowed its 6144-byte stack in ESP-NN
`qacc16_run_channels` during model inference. `0.8.6-p4-wake-stack` allocates
10240 bytes for that task, including its 3840-byte PCM/pre-roll arrays. The
`controller` USB-console command reports the microphone's minimum free stack
in bytes so deployed inference headroom can be checked. The model, detection
threshold, audio format and task priority are unchanged.

The `0.8.6` application was installed with hash verification on 2026-10-06.
With microphone wake mode enabled, the P4 remained on the same controller
connection through a 60-second inference check, reported zero microphone drops,
and measured **3712 bytes minimum free microphone stack**. Application SHA-256:
`d4ead5303592af87635f1f1a7c9c46c3d657183e669f83a9e3627683162afbc5`.

Follow-up acoustic check on 2026-10-06: direct P4 PCM capture preserved the
16 kHz sample rate with no TCP gaps or microphone-frame counter gaps. The saved
model recognized the captured phrases on the workstation and in two temporary
P4 microphone-task comparisons (eight seconds of audio processed in 390/388 ms).
Live wake mode then delivered `vad_open`, `wake_word`, PCM and `vad_close` on the
same connection, with zero reported microphone drops. The comparison code and
embedded test recording were removed; the exact normal `0.8.6` application hash
above was reinstalled and wake-mode capture acknowledged after reconnect.
No recorded speech or temporary comparison code is part of the source tree.

The owner reported that live recognition needed close, loud speech; normal
speaking-distance accuracy remains unqualified. The ES8311 input-gain API is
still set to 30 dB and the model cutoff to 0.66. A captured eight-second speech
segment peaked at 23.8% sample amplitude and 7.49% frame RMS, without clipping.
Body Control's current meter displays received PCM RMS on a linear 0–1 scale,
so even that speech uses only 7.49% of the bar. In wake mode the meter receives
no fresh samples before detection; it is not an on-device listening indicator.
These measurements do not establish live MetaHuman transcription or justify
claiming reliable recognition across a room.

## Optional voice/wake asset layout

The default partition table retains the factory layout. The optional
`partitions-full.csv` preserves NVS/PHY and app offset `0x20000`, and adds two
8 MiB OTA slots plus LittleFS at `0x1020000`. OTA support validates a pending
image after an authenticated controller session; it does not add an unauthenticated
firmware upload endpoint. Selecting a layout during a build does not migrate a
board.

To build the full layout separately, use a separate `SDKCONFIG` file and select
`partitions-full.csv` under Partition Table. Build with that configuration:

```bash
idf.py -B build/full -D IDF_TARGET=esp32p4 -D SDKCONFIG=/tmp/ainekio-p4-full.sdkconfig menuconfig
idf.py -B build/full -D SDKCONFIG=/tmp/ainekio-p4-full.sdkconfig build
```

The LittleFS build target stages only the canonical `audio-v1.json`, `audio/`
and validated `wake/` seed/local assets; it excludes V1 motions and all display
assets. The image is generated separately and is **not** added to normal flash
arguments. Keep device-local wake models out of Git. Mounting never formats on
failure. Without an installed asset partition, streamed TTS still works, while
asset SAY and wake models correctly remain unavailable.

The pre-deployment default and full-layout builds both passed at
4,418,640 bytes. The corrected deployed full-layout app leaves 46% of its 8 MiB
partition free. Shared native tests,
PCA driver tests, focused Python checks and the isolated browser interaction
checks passed. The S3 regression build also passed.

The connected board now uses the full layout, with the separate LittleFS image
installed at `0x1020000`; normal flash arguments still omit that image.
Current implementation/review and deployment status is tracked in
[FIRMWARE_DESIGN.md](../../../docs/v2-12servo/FIRMWARE_DESIGN.md).

## Saved robot speaker volume

Body Control's **Audio → Robot speaker volume** sends a `speaker` command with
`volume_percent` (0–100). **Save volume on robot** persists the value under
`p4_media/spk_volume` in NVS and applies it to the shared speaker output path for
streamed TTS, test tones and local audio assets. It survives reboot, reconnect
and sleep; 0 mutes and 100 leaves PCM unchanged. An unset value defaults to 100
so installing this firmware preserves the previous full output. The codec stays
at unity gain; the master percentage scales each PCM frame once at playback.
Repeated saves of the same value do not rewrite NVS. Failed saves leave the
previous volume active. Heartbeat `audio.speaker_volume_percent` reports the
confirmed value; older bodies without that field do not expose this control.
