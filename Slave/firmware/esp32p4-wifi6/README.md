# ESP32-P4-WIFI6 body firmware

Native V2 board bring-up target. It uses the portable Ainekio lifecycle,
configuration store and command decoder, with its own P4 startup, board resources,
C6 networking and PCA9685 output driver. It does not compile the S3 platform.

**Step 1 is not accepted.** See the [evidence and remaining checks](../../../docs/v2-12servo/STEP1_EVIDENCE.md)
and [firmware design](../../../docs/v2-12servo/FIRMWARE_DESIGN.md). Movement,
calibration of actual joints, camera, microphone and speaker are unavailable.
The diagnostic pulse range is not an MG90 calibration.

The V2 `walk` asset, eight finite left/right turn clips (15°, 45°, 90°, 180°),
and twenty-one postures/gestures (`sit`, `rest`, `wave`, `dance`, `swim`, `point`,
`nod`, `pushup`, `bow`, `cute`, `freaky`, `worm`, `shake`, `shrug`, `dead`, `crab`,
`celebrate`, `stretch`, `surprised`, `sad`, `curious`)
are compiled into the twelve-joint geometric sampler. See the [model implementation](../../software/models/v2-12servo/README.md)
for timing, source provenance and the remaining calibrated-execution work.
Physical motion is still disabled and is not advertised as ready.
Finite commands hold their semantic final pose. Dead's optional preview recovery
is excluded, so `gait dead 10000` still samples its completed flat pose.

**`0.4.0-p4-motions` is built, not flashed.** Its application requires the new
8 MiB partition. The [integration record](../../../docs/v2-12servo/MOTION_INTEGRATION_20260917.md)
contains the binary hash, verification results and backup/flash commands for
upgrading the currently installed `0.3.0-p4-turns`. An application-only flash is
insufficient for this upgrade.

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
idf.py -B build -D IDF_TARGET=esp32p4 build
bash tools/build_c6.sh
idf.py -B build -D AINEKIO_C6_IMAGE="$PWD/build/c6/network_adapter.bin" build
idf.py -B build -p /dev/serial/by-id/usb-1a86_USB_Single_Serial_5B90184020-if00 -b 921600 flash
idf.py -B build -p /dev/serial/by-id/usb-1a86_USB_Single_Serial_5B90184020-if00 monitor
```

The IDF install and serial paths above are the bring-up workstation's paths;
substitute the actual installation and device on another machine. A C6 update
is only available when a real image is embedded. Run `net c6-update` once if the
installed C6 does not match, then verify its reported version after reboot.
The updater latches maintenance/disarm, streams the image through Espressif's
SDIO OTA API and restarts. Failed updates remain in maintenance until reset.
The installed C6 already reports 2.12.8; normal P4 flashes need no C6 rewrite.

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
| `gait walk <steps> <elapsed-ms>` | Sample installed twelve-joint CAD trajectory; no PWM, arming or motion completion |
| `gait <installed-finite-command> <elapsed-ms>` | Sample a complete turn or gesture, e.g. `gait bow 2500`; holds its recorded final pose after completion; no PWM |
| `net` | C6 network initialization, station IP and AP state |
| `net ap` / `net retry` | Request the existing provisioning state machine's setup AP / return to station operation |
| `net key` | Display this boot's temporary WPA2 setup-AP password locally |
| `disable` | Direct latched emergency disable; no motion queue or I2C wait |
| `config <ssid> <psk> <endpoint> <robot-id> <token>` | Validate and commit configuration, then restart disarmed; quote values containing spaces |
| `config controller <endpoint>` | Change only the selected controller URL, retain credentials, invalidate the old session and restart disarmed |
| `net c6-update` | Real SDIO coprocessor update, only compiled with an embedded image |

Endpoints end in `/robot`, for example `ws://HOST:8790/robot` on a trusted LAN or
`wss://HOST/robot` with a verified server certificate. WSS initializes SNTP for
certificate dates; body deadlines always use the monotonic clock. WSS has not
been exercised in this bring-up. No certificate-validation bypass is provided.
The existing LAN trust model is retained: the body authenticates to the selected
gateway with its token; plaintext LAN WebSocket does not cryptographically
authenticate the server. Use TLS for connections needing server authentication.

The setup AP provides WPA2 association and DHCP. Browser provisioning is a
Step 2 integration, not a functioning portal in this target today. Saved Wi-Fi
configuration and controller selection currently use the console.

## Output bench diagnostics

Keep **every servo and V+ disconnected**. The delivered breakout's pull resistors
and OE bias are not verified. Do not acknowledge wiring or run pulses until the
electrical prerequisites in the evidence record are complete.

After those checks, `wiring verified-no-servos` acknowledges the bench setup in
RAM only. It does not arm and is forgotten at reset. Use the existing authenticated
gateway in calibration mode; its `test_outputs()` method or authenticated,
CSRF-protected `POST /api/diagnostics/output` routes requests through the same
decoder/admission boundary as other body commands. This endpoint is not in the
AI semantic action catalog.

```json
{"t":"mode","name":"calibrate","seq":1,"epoch":1,"deadline_ms":12345}
{"t":"output_test","op":"recover","seq":2,"epoch":1,"deadline_ms":12345}
{"t":"output_test","op":"run","channel":11,"pulse_us":1500,"ms":100,"fault":"none","seq":3,"epoch":1,"deadline_ms":12345}
```

The gateway assigns current sequence, epoch and a fresh body-clock deadline;
the illustrative numbers above must not be reused as actual session values.
`recover` checks/reinitializes the device while disabled. `run` separately arms a
fresh frame, refreshes it locally every 20 ms, and disarms at completion. Run
bounds: channel 0–11, pulse 1000–2000 µs, duration 100–2000 ms; unused channels are
fully off. `fault` may be `none`, `interrupt_arm`, `stall`, or `reset`.

`interrupt_arm` disables after the real frame write, before its completion can
enable OE. `stall` blocks the output task for 200 ms to exercise the independent
40 ms progress guard and 100 ms panic watchdog. `reset` restarts after 20 ms.
I2C faults require actual bench fault injection with measured signals. An ACK
means accepted/applied controller work; DONE means the timed test ended. Neither
is measured servo position, torque, or an electrical timing certificate.

## Focused tests

```bash
cmake -S components/ainekio_pca9685 -B /tmp/ainekio-p4-driver-tests
cmake --build /tmp/ainekio-p4-driver-tests -j4
/usr/bin/ctest --test-dir /tmp/ainekio-p4-driver-tests --output-on-failure
```

Run the portable-core and affected host regressions from the repository root;
their exact commands and results are in the Step 1 evidence record.
