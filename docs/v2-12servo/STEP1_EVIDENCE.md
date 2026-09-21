# Step 1: P4 board and output-disable verification

Date: 2026-09-15. **NOT ACCEPTED — electrical evidence incomplete.**

The native target is implemented and flashed. P4/C6 boot, station networking and
real gateway admission have been exercised. The PCA9685 remains disconnected
and unpowered; the owner has a multimeter but cannot take its resistance readings
yet, and has no oscilloscope, logic analyzer or current-limited bench supply.
No PWM, OE voltage/timing, servo movement or power measurements are claimed.

## Actual board and software pairing

| Item | Evidence |
| --- | --- |
| P4 | esptool and firmware both identify **revision 1.3**; 40 MHz crystal, 32 MiB flash, runtime 32 MiB PSRAM at 200 MHz with memory test passing; CPU 360 MHz |
| USB used | CH343P USB-UART, `/dev/serial/by-id/usb-1a86_USB_Single_Serial_5B90184020-if00`, currently `/dev/ttyACM0`; this is not native USB |
| Host | ESP-IDF **5.5.4**, `esp_hosted` **2.12.8**, `esp_wifi_remote` **1.6.4**, WebSocket **1.7.0**, pinned manifest/lock |
| C6 | Built from the pinned Hosted package with its own dependency lock; installed by real SDIO OTA from the P4, then reported **2.12.8** after restart |
| SDIO | 40 MHz, four-bit packet mode on both sides; board's documented pin assignment |
| C6 image | 1,209,600 bytes; SHA256 `43e78006e6c91f3a6024c9492450f32f5b67db36c8a0b73f6666c8c05f3f79f3` |
| Initial Step 1 P4 image | SHA256 `55d7aae00d1b417ac409499030e4b79e17f364b6b04ae25351043f5648d3f46c`; all esptool written-region hashes verified. Superseded by the later turn-integration application flash linked below. |

The factory C6 answered SDIO but reported an unknown 0.0.0 version and failed the
firmware-version RPC. It was replaced using the upstream OTA protocol's version-
dependent activation procedure. No C6 jumper or extra serial adapter was needed.
The vendor 1.4.0/0.14.0 host pair failed against IDF 5.5.4's changed Wi-Fi struct;
the final pair requires no patches to managed dependencies.

Before P4 flashing, bytes `0x000000–0x41ffff` were backed up as
`build/p4-step1/original-0-420000.bin` (4,325,376 bytes), SHA256
`169556daf70649a728555d6c336f588db68baa3c430602585cc343b76ede344e`.
This covers the region occupied by the new layout, not a full 32 MiB flash dump.
NVS/PHY offsets are retained; firmware does not erase NVS on an error.

## Changes and ownership

- `Slave/firmware/esp32p4-wifi6/`: independent startup, configuration/NVS,
  partition layout, resources, C6 networking/update, console diagnostics,
  WebSocket adapter, local output task, watchdog and independent supervisor.
- `components/ainekio_pca9685/` within that target: real synchronous register
  driver, OE gate, explicit recovery/arm and generation fencing; focused tests.
- `Slave/software/core/{include/ainekio,src}/admission.*`: transport-independent
  session/expiry admission composed with the existing command lifecycle.
  Protocol/codec/core and tests add an opt-in operator diagnostic command;
  V1's eight-joint decoder/default behavior remains intact.
- `Slave/software/protocol/`: feature/envelope validation, schema and fixtures.
- `Master/gateway/server/service.py`: negotiated deadlines/model/readiness and
  diagnostic submission using existing authentication/session/result ownership.
  `dashboard/server.py` adds an authenticated operator route;
  `environment_adapter/server.py` suppresses unready motion/media features.
- `Emulator/tests/test_p4_foundation.py`: compatibility, deadlines, correlation,
  capability and validation checks. Documentation records Q6A placement/USB/power
  constraints without creating Q6A services or extracting the broad S3 runtime.

Pre-existing action-receipt, adapter and hardware-layout work in the shared
worktree was preserved. No commit or push was performed for this milestone.

## Build, flash and software checks

Build instructions, including the C6 image, are in the
[target README](../../Slave/firmware/esp32p4-wifi6/README.md#build-and-flash).
The actual final P4 flash command ran from its `build/` directory:

```bash
/home/greggles/.espressif/python_env/idf5.5_py3.12_env/bin/python -m esptool \
  --chip esp32p4 \
  --port /dev/serial/by-id/usb-1a86_USB_Single_Serial_5B90184020-if00 \
  --baud 921600 --before default_reset --after hard_reset write_flash @flash_args
```

The generated arguments write bootloader `0x2000`, partition table `0x8000`, and
P4 app `0x20000` for 32 MiB flash. C6 update used the native `net c6-update` command.
The S3 build was checked with `idf.py -B build build` under its own target and
the same IDF installation; **S3 was not flashed**.

| Check | Result |
| --- | --- |
| Native P4 build | PASS |
| Matched C6 build, including portable `${IDF_PATH}` lock entry | PASS; reproduced same image hash |
| Existing S3 build | PASS |
| Portable C core | **13/13 CTest tests PASS** |
| PCA9685 component | **1/1 CTest executable PASS**, containing initialization/register sequence, failure at every initialization transfer, readback mismatch, interrupted arm/recovery, stale queued work/completions, outstanding-transfer recovery, upper channels, deadlines and late-writer tests |
| Affected gateway/dashboard/adapter/receipt/P4 tests | **83/83 PASS** |
| Python protocol tests | **13/13 PASS** |

Reproduction from repository root:

```bash
cmake -S Slave/software/core -B /tmp/ainekio-p4-core-tests
cmake --build /tmp/ainekio-p4-core-tests -j4
/usr/bin/ctest --test-dir /tmp/ainekio-p4-core-tests --output-on-failure
cmake -S Slave/firmware/esp32p4-wifi6/components/ainekio_pca9685 -B /tmp/ainekio-p4-driver-tests
cmake --build /tmp/ainekio-p4-driver-tests -j4
/usr/bin/ctest --test-dir /tmp/ainekio-p4-driver-tests --output-on-failure
PYTHONPATH=Master:Slave/software:Emulator:Emulator/tests python3 -m unittest \
  Emulator.tests.test_gateway_service Emulator.tests.test_gateway_dashboard \
  Emulator.tests.test_environment_adapter Emulator.tests.test_environment_speech \
  Emulator.tests.test_environment_command_catalog Emulator.tests.test_action_receipts \
  Emulator.tests.test_p4_foundation
PYTHONPATH=Slave/software python3 -m unittest discover -s Slave/software/tests/protocol -v
```

Socket tests require local loopback access. An initial sandboxed run could not
bind sockets; the complete affected suite was rerun with access. The corrected
import path includes `Emulator/tests` for the existing receipt test helper.

## Live board/network evidence

| Check | Observed result |
| --- | --- |
| Startup and software/EN resets | Native firmware boots, reports output `armed=0`, `wiring_verified=0`; absent PCA produces an I2C fault. This is software state, not an OE measurement. |
| Station | Saved NetworkManager profile selected by active UUID and provisioned privately; DHCP gave **192.168.0.89**; C6/P4 established a real gateway connection. Credentials never entered tracked source. |
| Gateway | Existing `GatewayService` on isolated ports, actual P4 over Wi-Fi; token-authenticated session reports model `v2-12servo`, motion/camera/microphone/speaker all false. |
| Commands | Calibration-mode selection ACK; absent-device recovery and unverified-wiring run NAK `unsafe`; unavailable movement/joint calibration NAK `unknown`; STOP ACK. |
| Admission | On-wire expired deadline and wrong epoch both NAK `stale`; a fragmented WebSocket mode message reassembled and ACKed. |
| Session recovery | Suppressed application heartbeats caused disconnect and a new epoch; wrong token was rejected; restoring the configured token established another fresh session. |
| Silence timing | Host observed socket closure **5.077 s** on the final image (earlier run 5.123 s) after its last control send. Socket teardown includes transport work; this neither verifies nor waives the **4.005 s detection / 4.23 s hold-or-disable** requirement. Electrical timing remains pending. |
| Setup AP | Owner joined with a phone/tablet; actual C6 association at 602.648 s and DHCP lease **192.168.4.2** at 603.059 s in `ap-and-recovery.log`. The ten-minute setup window expired and disconnected the client. This proves AP association/DHCP, not a browser portal. |
| Final AP recovery | On the final image, `net ap` enabled the AP; `net retry` stopped it at 15.113 s. At 80 s, station remained connected and AP remained off, beyond the 60 s fallback threshold. Final board status was disarmed/unverified and controller authenticated. |
| Explicit host change | `config controller` switched from port 18790 to a separate existing-gateway instance at 18792 and back. The old connection closed, the new instance began epoch 1 and ACKed mode selection, with no firmware rebuild. Both endpoints were on this computer; no Q6A hardware/service execution is claimed. |
| True cold power cycle | Owner confirmed USB power removal for at least 5 seconds with LEDs off, then reconnection. Without opening serial, the gateway received a new P4 hello at **7.581 s device uptime**, authenticated epoch **5**, and established TCP from **192.168.0.89**. This proves cold-start/network recovery, not reset-time OE behavior. |

Local raw evidence is ignored under `build/p4-step1/`: `first-boot.log`,
`c6-update.log`, `station-boot.log`, `ap-and-recovery.log`, `ap-recovery-final.log`,
`session-check.log`, `session-final.log`,
flash logs and the original-region backup. `provisioning.json` is private mode
0600 and contains secrets; do not publish it or include it in a report bundle.

At the initial Step 1 handoff the temporary observers were stopped, no background
service was installed, and the P4 retained bench port 18790. In the subsequent
owner-requested Body Control integration, its private credential was registered
alongside V1 and the saved controller changed explicitly to
`ws://192.168.0.44:8790/robot`. The existing foreground gateway was restarted
through its canonical launcher with both registrations and its password retained.
The [subsequent turn-integration record](../../Slave/software/models/v2-12servo/motions/turns/README.md#verification-and-application-flash-2026-09-15)
documents application `0.3.0-p4-turns`, read-only on-board samples and the live
authenticated connection. Physical motion remains unavailable; these later
checks do not complete Step 1 electrical acceptance.

## Electrical acceptance: all still pending

The [P4 pinout and PCA9685 wiring guide](PCA9685_WIRING.md) now maps the firmware's
GPIO assignments onto the official physical header layout and gives the initial
multimeter procedure. Creating these guides added no electrical measurements.

The [HUAREW HR-PCA9685 listing](https://www.amazon.com/HUAREW-PCA9685-Interface-Compatible-Raspberry/dp/B0CRV3MK14)
documents an OE pin, 3.3 V controller compatibility and 220 Ω output series
resistors. It does **not** supply the delivered board's OE/SDA/SCL pull-resistor
values or a verified schematic. Another brand's schematic cannot establish this
unit's wiring. The owner confirms soldered headers only.

| Required evidence | Unchanged acceptance target / blocker |
| --- | --- |
| Unpowered wiring | Measure OE↔GND, OE↔VCC, SDA↔VCC, SCL↔VCC; confirm labels, common ground and pull-up/pull-down topology. Owner cannot take readings yet. |
| Logic voltage/reset bias | PCA VCC and I2C must use 3.3 V logic. Verify OE stays high with P4 reset/unpowered and PCA powered; resolve conflicting resistors/backfeed. No voltage or resistance readings yet. |
| Normal PWM | Measure nominal 50 Hz period and commanded pulse widths on channels 0 and 11, with 12–15 inactive; internal oscillator tolerance remains uncalibrated. No scope/analyzer. |
| Transfer timing | ≤5 ms entire armed transfer including scheduling; actual 400 kHz waveforms/ACK and completion evidence required. A 5 ms API argument is not proof. |
| Direct disable / observed I2C error | Inactive servo signal ≤1 ms after gate entry / observed error. Requires a correlated entry/error timing marker and OE/PWM capture. |
| Hung bus | Inactive output ≤15 ms after transfer begins; inject a controlled SDA/SCL fault and record transfer plus OE/PWM, without shorting a power rail. |
| Interrupted arming / late completion | No enable pulse after disable, including real multicore timing and outstanding transfers; `interrupt_arm` exercises the real write-before-enable boundary. Software races pass, electrical trace missing. |
| Motion-progress stall | 20 ms update, fault at 40 ms, supervisor every 5 ms, inactive output ≤50 ms since last completed frame; `stall` diagnostic available but not run against hardware output. |
| Watchdog / resets | 100 ms progress watchdog configured with panic/reset. Whole-MCU inactive output ≤250 ms; capture cold start, software/watchdog reset, brownout and independent P4 reset with PCA rail held up. No proven reset bias, trace or controlled supply. |
| MG90 pulse loss and loaded power | Later Step 3 prerequisites: actual servo variant, pulse-loss response, current, wiring/connector capacity, rail sag and supported-leg mechanics. No servo has been powered by this milestone. |

Required equipment: a scope for voltage/transient evidence, a logic analyzer or
scope with enough simultaneous channels for OE/PWM/SDA/SCL (10 MS/s or better
for the 400 kHz bus), and a current-limited adjustable supply for controlled
power sequencing/brownout checks. Whole-MCU and ≤1 ms entry-response tests also
need a correlated timing marker/trigger; console timestamps alone are inadequate.
A multimeter can establish static wiring/voltage, not absence of brief pulses.

Next electrical sequence, once the meter is available:

1. Leave everything unpowered, all servo plugs/V+ disconnected; obtain the four
   resistance readings and verify the delivered breakout's labels.
2. Resolve a real external OE pull-up to 3.3 V against those readings. No resistor
   value is accepted by assumption. With PCA powered and P4 held reset, verify
   disabled bias before connecting live signal tests.
3. Confirm the board header orientation before wiring GPIO2→SDA, GPIO3→SCL,
   GPIO4→OE, 3.3 V→VCC and GND→GND. Leave V+ and servos disconnected.
4. Measure VCC, OE and bus idle levels; capture reset/boot behavior. Only then
   acknowledge `wiring verified-no-servos` and explicitly recover/arm a bounded
   diagnostic through the authenticated gateway.
5. Capture the required normal/fault/reset traces with test conditions and
   measured maxima. Failed targets remain failures until explicitly resolved;
   complete this proof before broad shared-runtime extraction.

The AP test exposed a target integration bug: after setup ended, an existing
station address did not produce a new GOT_IP event, leaving provisioning waiting
and reopening the AP after 60 seconds. The final target reports its current
station link to the existing provisioning state machine each cycle; that machine
retains manual AP operation until its requested exit. The final `net retry`
recovery check passed beyond that 60-second threshold; the final image's complete
ten-minute automatic-expiry cycle was not rerun.

The optional Q6A's USB routing, power isolation, thermal and chassis-load budgets
are specified in [the firmware design](FIRMWARE_DESIGN.md#controller-admission-and-optional-q6a-deployment).
No Q6A services, USB transport or numeric power/load margins are claimed ready.
