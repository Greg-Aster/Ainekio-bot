# Ainekio Pinout and Diagnostic Values

This is the wiring and bench-diagnosis reference for the most recently flashed
and boot-verified Freenove ESP32-S3-WROOM CAM controller image. It records the
active firmware profile `freenove-esp32s3-cam-n16r8-map-b-remap`, not the older
provisional MAP_B pin plan.

The controller GPIO assignments come from the current firmware
[`pin_map.h`](../Slave/firmware/esp32s3/components/ainekio_platform/include/ainekio/platform/pin_map.h).
Electrical supply and power-topology values come from the normative system
specification and the externally maintained
[Parts Overview](https://docs.google.com/document/d/1wz0kyqttPK3HHL0P0_9lLtRW_B87U5u4kEt-UhttHFA/edit?usp=sharing).
Delivered markings, the current firmware boot result, and H-series measurements
take precedence for the installed robot. In particular, the delivered camera is
an **OV3660** even though the older Parts Overview still says OV2640.

## Firmware configuration captured

| Firmware item | Value represented by this document |
| --- | --- |
| Board profile | `freenove-esp32s3-cam-n16r8-map-b-remap` |
| Flash and PSRAM | 16 MB flash; 8 MB octal PSRAM |
| Detected camera | OV3660; 10 MHz XCLK |
| Physical servo outputs | Enabled; eight MCPWM channels |
| Initial motion range | 25 percent around center; 100 ms minimum frame |
| Servo startup | 20 ms channel-to-channel stagger |
| Battery monitor | Enabled on GPIO3; divider factor `3.12766` |
| Microphone slot | Left; `CONFIG_AINEKIO_MIC_SLOT_RIGHT` is not set |
| OLED address | `0x3C` |

These values were cross-checked against the current full-feature `sdkconfig`,
`sdkconfig.defaults`, central pin map, and delivered-board bring-up record. If
any of those selections changes before the next flash, update this document at
the same time.

## How pins are numbered

View the Freenove board from the component side, with the antenna at the top and
the two USB-C ports at the bottom, as shown in the checked-in
[Freenove pinout](Freenove_ESP32_S3_WROOM_Board-main/ESP32S3_Pinout.png).

- `L1` through `L20` number the left header from top to bottom.
- `R1` through `R20` number the right header from top to bottom.
- `GPIO` numbers are ESP32-S3 chip GPIO numbers; they are not connector
  positions.
- Peripheral diagnostic IDs such as `MIC-1` identify electrical functions by
  their printed module label. Generic breakout boards can arrange those labels
  differently, so the label on the delivered module controls physical order.

## Measurement rules

- Measure DC voltage relative to the common system ground at `R20`.
- `5 V` and `3.3 V` below are nominal targets, not yet measured acceptance
  bands. Record actual unloaded and loaded values during the H-series checks.
- Every ESP32 signal is **3.3 V logic**. Never apply 5 V to a GPIO.
- Make continuity and resistance checks only with battery and USB disconnected.
- Use a scope or logic analyzer for PWM, I2S, I2C, UART, camera, and SD signals.
  A multimeter average is not a valid timing test.
- Leave the servo plugs disconnected for controller-only tests. USB can operate
  the controller and its signal outputs, but it does not power the external
  servo rail.
- Until the backfeed checks pass, keep master battery power off while USB is
  connected and do not connect both controller USB ports at once.

## Expected power states

| Test point | Fully off | USB-UART only, master power off | Battery system on |
| --- | --- | --- | --- |
| Battery after master switch | 0 V | 0 V | 7.4 V nominal; 8.4 V full |
| Buck #1 input | 0 V | 0 V | Same as switched battery, less wiring drop |
| Buck #1 servo output | 0 V | 0 V | 5.0 V nominal |
| Buck #2 input | 0 V | 0 V target; any voltage indicates reverse backfeed | Same as switched battery, less wiring drop |
| Buck #2 electronics output | 0 V | About 5 V if already tied to the USB-powered board; otherwise isolate it for the backfeed check | 5.0 V nominal |
| Freenove `5V` header | 0 V | About 5 V from USB; verify backfeed direction | 5.0 V nominal from Buck #2 |
| Freenove `3V3` header | 0 V | About 3.3 V | About 3.3 V |
| Servo rail `+5V` | 0 V | 0 V | 5.0 V nominal from Buck #1 |
| Battery ADC, GPIO3 | 0 V | Near 0 V when divider is disconnected | Battery divided by 3.12766 |
| Any ground | 0 V reference | 0 V reference | 0 V reference; all grounds common |

Do not treat a nominal value as a pass by itself. Ripple, loaded droop, current,
temperature, polarity, and backfeed still require the procedures in
[`HARDWARE_BRINGUP_CHECKLIST.md`](HARDWARE_BRINGUP_CHECKLIST.md).

## Controller header: left side

| Position | Board label | Active Ainekio use | Expected diagnostic value |
| --- | --- | --- | --- |
| L1 | `3V3` | Regulated peripheral supply | About 3.3 V when powered |
| L2 | `EN/RST` | Chip enable and reset | Normally about 3.3 V; 0 V while reset is held |
| L3 | `GPIO4` | Camera SCCB SDA | Onboard camera only; open-drain 0-3.3 V activity, normally high when idle |
| L4 | `GPIO5` | Camera SCCB SCL | Onboard camera only; open-drain 0-3.3 V activity, normally high when idle |
| L5 | `GPIO6` | Camera VSYNC | Onboard camera only; 0-3.3 V frame timing |
| L6 | `GPIO7` | Camera HREF | Onboard camera only; 0-3.3 V line timing |
| L7 | `GPIO15` | Camera XCLK | Onboard camera only; 10 MHz, 0-3.3 V clock after camera start |
| L8 | `GPIO16` | Camera D7 | Onboard camera only; high-speed 0-3.3 V data |
| L9 | `GPIO17` | Camera D6 | Onboard camera only; high-speed 0-3.3 V data |
| L10 | `GPIO18` | Camera D5 | Onboard camera only; high-speed 0-3.3 V data |
| L11 | `GPIO8` | Camera D2 | Onboard camera only; high-speed 0-3.3 V data |
| L12 | `GPIO3` | Battery ADC, ADC1 channel 2 | See the battery-divider table; never connect raw battery voltage |
| L13 | `GPIO46` | Servo joint 7, L4 | Reset-time strap: do not force; runtime PWM as described below |
| L14 | `GPIO9` | Camera D1 | Onboard camera only; high-speed 0-3.3 V data |
| L15 | `GPIO10` | Camera D3 | Onboard camera only; high-speed 0-3.3 V data |
| L16 | `GPIO11` | Camera D0 | Onboard camera only; high-speed 0-3.3 V data |
| L17 | `GPIO12` | Camera D4 | Onboard camera only; high-speed 0-3.3 V data |
| L18 | `GPIO13` | Camera PCLK | Onboard camera only; high-speed 0-3.3 V pixel clock |
| L19 | `GPIO14` | Servo joint 2, L1 | Runtime PWM as described below |
| L20 | `5V` | Board 5 V input from electronics rail | 5.0 V nominal when powered |

The camera signals are already connected by the Freenove board and camera flex
cable. Do not use their exposed header positions for accessories.

## Controller header: right side

| Position | Board label | Active Ainekio use | Expected diagnostic value |
| --- | --- | --- | --- |
| R1 | `GPIO43` | Boot UART TX, then OLED SCL | Boot: 115200-baud 0-3.3 V UART. Runtime with OLED: I2C clock, normally high. Returns to UART if no OLED responds. |
| R2 | `GPIO44` | Boot UART RX | 0-3.3 V UART input, normally high when idle |
| R3 | `GPIO1` | Servo joint 0, R1 | Runtime PWM as described below |
| R4 | `GPIO2` | Servo joint 1, R2 | Runtime PWM as described below |
| R5 | `GPIO42` | I2S WS/LRCLK | 16 kHz, 0-3.3 V after audio starts |
| R6 | `GPIO41` | I2S BCLK | 1.024 MHz, 0-3.3 V after audio starts |
| R7 | `GPIO40` | SD_MMC DAT0 | Board-mounted SD only; 0-3.3 V data, expected pulled high when idle |
| R8 | `GPIO39` | SD_MMC CLK | Board-mounted SD only; 0-3.3 V clock during card activity |
| R9 | `GPIO38` | SD_MMC CMD | Board-mounted SD only; 0-3.3 V command, expected pulled high when idle |
| R10 | `GPIO37` | Octal PSRAM | Reserved. Do not connect, load, or use as an accessory pin. |
| R11 | `GPIO36` | Octal PSRAM | Reserved. Do not connect, load, or use as an accessory pin. |
| R12 | `GPIO35` | Octal PSRAM | Reserved. Do not connect, load, or use as an accessory pin. |
| R13 | `GPIO0` | BOOT at reset, then OLED SDA | No press: normally high. BOOT pressed: 0 V. Runtime: open-drain I2C data, normally high. |
| R14 | `GPIO45` | Servo joint 6, L3 | Reset-time strap: do not force; runtime PWM as described below |
| R15 | `GPIO48` | Servo joint 5, R3; also wired to onboard WS2812 input | Runtime PWM. Onboard RGB LED is unavailable; H2 must verify its input does not load the servo signal. |
| R16 | `GPIO47` | Servo joint 4, R4 | Runtime PWM as described below |
| R17 | `GPIO21` | Servo joint 3, L2 | Runtime PWM as described below |
| R18 | `GPIO20` | I2S amplifier data out; native USB D- is sacrificed | Dynamic 0-3.3 V I2S data; zeros/silence when no audio is playing |
| R19 | `GPIO19` | I2S microphone data in; native USB D+ is sacrificed | Dynamic 0-3.3 V I2S input when microphone is connected |
| R20 | `GND` | Common system ground | 0 V reference |

GPIO33 through GPIO37 belong to the N16R8 module's octal PSRAM. GPIO33 and
GPIO34 are not on these headers, but they are equally reserved. The prior servo
plan using GPIO33/34 corrupted PSRAM and is not valid for this board.

## USB ports

With the board in the same antenna-up orientation:

| ID | Physical port | Purpose in this build | Expected host result |
| --- | --- | --- | --- |
| U1 | Left USB-C, nearest `RST` | CH343 USB-UART; use this for flashing and boot logs | A CH343 serial device. Linux naming can vary; the working board appeared as `/dev/ttyACM0` during bring-up. |
| U2 | Right USB-C, nearest `BOOT` | ESP32-S3 native USB-OTG on GPIO19/20 | May work in ROM/recovery, but the running Ainekio firmware reassigns GPIO19/20 to I2S and does not provide a persistent native-USB console. |

U1 is the normal Ainekio programming port. Boot output is available on U1, but
if the OLED responds, GPIO43 is handed from UART TX to OLED SCL after startup,
so later runtime log output is intentionally unavailable on that UART.

## Eight servo outputs

The logical joint order is frozen. This is also the order printed in firmware
boot allocation logs.

| Joint ID | Joint | Signal position | GPIO | MCPWM allocation | Expected signal |
| --- | --- | --- | --- | --- | --- |
| 0 | R1 | R3 | 1 | group 0, operator 0, generator 0 | 50 Hz PWM when attached |
| 1 | R2 | R4 | 2 | group 0, operator 0, generator 1 | 50 Hz PWM when attached |
| 2 | L1 | L19 | 14 | group 0, operator 1, generator 0 | 50 Hz PWM when attached |
| 3 | L2 | R17 | 21 | group 0, operator 1, generator 1 | 50 Hz PWM when attached |
| 4 | R4 | R16 | 47 | group 0, operator 2, generator 0 | 50 Hz PWM when attached |
| 5 | R3 | R15 | 48 | group 0, operator 2, generator 1 | 50 Hz PWM when attached |
| 6 | L3 | R14 | 45 | group 1, operator 0, generator 0 | 50 Hz PWM when attached |
| 7 | L4 | L13 | 46 | group 1, operator 0, generator 1 | 50 Hz PWM when attached |

Expected PWM behavior for the current full-feature image:

- Logic low is about 0 V and logic high is about 3.3 V.
- The frame period is 20 ms, or 50 Hz.
- Default center is 1500 microseconds high.
- The initial 25 percent safety range produces approximately 1250-1750
  microseconds with default calibration.
- The eight outputs are centered with a 20 ms startup stagger after boot and
  calibration load.
- Reset, explicit stop, failsafe, and detach place each signal in high
  impedance. High impedance is not the same as a driven 0 V output.
- PWM detachment does not switch off the external 5 V servo rail.

Each physical servo connection needs three electrical roles: its GPIO signal,
the Buck #1 `+5V` rail, and common ground. The repository does **not** yet record
a left-to-right pin order or keyed orientation for the hand-soldered 3-pin servo
headers. Mark and photograph that orientation before soldering; do not infer it
from this signal table or from wire color alone.

## Battery divider and GPIO3

The planned installed divider is:

```text
switched battery+ -- 100 kOhm --+-- GPIO3 / ADC1 channel 2
                                |
                              47 kOhm
                                |
common ground ------------------+

0.1 uF ceramic: GPIO3 to common ground
```

Firmware reconstructs battery voltage with a staged divider factor of
`3.12766`. The expected GPIO3 voltages before the H9 multimeter calibration are:

| Battery voltage | Expected GPIO3 voltage | Firmware meaning |
| --- | --- | --- |
| 8.40 V | 2.686 V | Full 2S pack |
| 7.40 V | 2.366 V | Nominal 2S pack |
| 7.20 V | 2.302 V | Recovery threshold after cutoff |
| 7.00 V | 2.238 V | Warning boundary; movement locks below this after qualification |
| 6.80 V | 2.174 V | Cutoff boundary; deep-sleep path below this after qualification |
| 0.25 V reconstructed | 0.080 V | Maximum startup reading still classified as disconnected |
| 0 V | 0 V | Disconnected divider or unpowered system |

The firmware averages at least 16 calibrated ADC samples every 5 seconds and
requires three qualifying sets for state changes. Three startup sets at or below
0.25 V reconstructed battery voltage classify the battery input as disconnected,
allowing USB-only operation. After any plausible battery voltage is observed,
that exception latches off and a later near-zero input follows the normal cutoff
path.

The divider connects to battery voltage after the master switch and before the
buck converters. Never derive battery state from either regulated 5 V output.

## INMP441 microphone

The current image uses 16 kHz, 32-bit stereo I2S and reads the **left** slot;
`CONFIG_AINEKIO_MIC_SLOT_RIGHT` is not set.

| ID | Module label | Connect to | Expected value |
| --- | --- | --- | --- |
| MIC-1 | `VDD` | Controller 3V3, L1 | About 3.3 V; INMP441 allowed supply is 1.8-3.3 V |
| MIC-2 | `GND` | Common ground, R20 | 0 V |
| MIC-3 | `SCK` or `BCLK` | GPIO41, R6 | 1.024 MHz, 0-3.3 V |
| MIC-4 | `WS` or `LRCLK` | GPIO42, R5 | 16 kHz, 0-3.3 V |
| MIC-5 | `SD` | GPIO19, R19 | 24-bit microphone data in a 32-clock slot, 0-3.3 V |
| MIC-6 | `L/R` | Installed module's left-slot select level | Current firmware expects left. Common INMP441 modules use low/GND for left, but confirm the delivered module before soldering. |

Keep the microphone wires short and away from servo power runs. The physical
module's printed labels control pad order.

## MAX98357A amplifier and speaker

| ID | Module label | Connect to | Expected value |
| --- | --- | --- | --- |
| AMP-1 | `VIN` or `VDD` | Buck #2 electronics 5 V | 5.0 V nominal; MAX98357A supply range is 2.5-5.5 V |
| AMP-2 | `GND` | Common ground | 0 V |
| AMP-3 | `BCLK` | GPIO41, R6 | 1.024 MHz, 0-3.3 V after audio starts |
| AMP-4 | `LRC`, `LRCLK`, or `WS` | GPIO42, R5 | 16 kHz, 0-3.3 V after audio starts |
| AMP-5 | `DIN` | GPIO20, R18 | I2S audio data, 0-3.3 V; zeros/silence while idle |
| AMP-6 | `SD`, `MODE`, or enable strap | Breakout-specific | No controller GPIO is assigned in the current pin map; record the installed strap before power-up. |
| AMP-7 | `GAIN` | Breakout-specific strap | Not firmware-controlled; record the installed state. |
| AMP-8 | `OUTP` / `+` | Speaker positive lead | Differential speaker output; not a DC supply |
| AMP-9 | `OUTN` / `-` | Speaker negative lead | Differential speaker output; never connect to ground |

The installed speaker is 8 ohm, 2 W and connects only between `OUTP` and
`OUTN`. Start playback at low digital amplitude. The unresolved gain and
shutdown/mode straps remain an H-series inspection item, not a value to guess
from a generic breakout photograph.

## SSD1306 OLED

| ID | Module label | Connect to | Expected value |
| --- | --- | --- | --- |
| OLED-1 | `VCC` | Controller 3V3, L1 | About 3.3 V |
| OLED-2 | `GND` | Common ground, R20 | 0 V |
| OLED-3 | `SDA` | GPIO0, R13 | Open-drain 0-3.3 V; normally high; also the BOOT line at reset |
| OLED-4 | `SCL` | GPIO43, R1 | Open-drain 0-3.3 V; normally high after UART handoff |

The current firmware address is `0x3C`. The installed module must still be
scanned for `0x3C` versus `0x3D`. A missing OLED must not block boot; the
firmware releases the bus and returns GPIO43 to UART TX if the display does not
respond.

## Buck converters, charger, and power rail IDs

Use the pad labels printed on each delivered power board. Pad order is not
standardized here.

| ID | Board/pad | Connection | Expected value |
| --- | --- | --- | --- |
| PWR-1 | Master switch input | Protected battery positive | 7.4 V nominal, 8.4 V full |
| PWR-2 | Master switch output | Both buck `IN+` pins and divider upper resistor | 0 V off; switched battery voltage on |
| B1-1 | Buck #1 `IN+` | Switched battery positive | 7.4 V nominal, 8.4 V full |
| B1-2 | Buck #1 `IN-` | Common ground | 0 V |
| B1-3 | Buck #1 `OUT+` | Dedicated servo rail | 5.0 V nominal |
| B1-4 | Buck #1 `OUT-` | Common ground | 0 V |
| B2-1 | Buck #2 `IN+` | Switched battery positive | 7.4 V nominal, 8.4 V full |
| B2-2 | Buck #2 `IN-` | Common ground | 0 V |
| B2-3 | Buck #2 `OUT+` | Freenove 5V input and amplifier VIN | 5.0 V nominal |
| B2-4 | Buck #2 `OUT-` | Common ground | 0 V |
| CHG-1 | Charger USB-C | Charge input only; not either controller USB port | USB input while charging |
| CHG-2 | Charger `BAT+` | Battery positive | Must never charge the 2S pack above 8.4 V |
| CHG-3 | Charger `BAT-` | Battery negative/common ground | 0 V reference |
| CHG-4 | Charger TEMP/NTC, if present | Unresolved | Insulate and leave disconnected until charger compatibility is verified |

The servo rail includes a 1000 uF electrolytic capacitor rated at least 10 V,
mounted near the rail. Confirm capacitor polarity before power-up. Both buck
converters, the controller, amplifier, microphone, OLED, battery, and all eight
servos share common ground; servo load current must not travel through the
Freenove board regulator or narrow controller traces.

## Diagnostic checkpoints

1. With all power removed, verify no short between 5 V and ground or between
   3.3 V and ground, then verify ground continuity across both bucks, the board,
   servo rail, amplifier, microphone, and OLED.
2. Power each buck separately with its load disconnected. Confirm polarity and
   adjust or verify 5.0 V before connecting any downstream device.
3. Use U1 for a USB-only controller boot. Expect the N16R8 profile, 16 MB flash,
   8 MB octal PSRAM, OV3660 detection, eight MCPWM allocations, and a
   disconnected-battery state after three near-zero sets.
4. Scope each servo GPIO without servo power. Expect all eight independent
   centered 50 Hz signals after startup and high impedance after stop/detach.
5. Connect and test one peripheral subsystem at a time: OLED, microphone,
   amplifier/speaker, battery divider, then the external servo rail.
6. Do not connect servo power until signal identity, connector orientation,
   common ground, rail polarity, and 5 V output have all been checked.

This document records expected wiring and measurements. It does not by itself
close H2, H3, H9, or any other physical acceptance gate.
