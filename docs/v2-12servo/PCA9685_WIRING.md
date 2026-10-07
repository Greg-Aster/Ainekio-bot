# P4 pinout and PCA9685 wiring

Updated 2026-09-22 for firmware `0.4.2-p4-home`. Applies to the selected
**Waveshare ESP32-P4-WIFI6**, with the USB-C socket at the top and C6 antenna
at the bottom when viewing the camera/display connectors. Other P4 boards may
have different layouts.

## Image guides

- [Full P4 pinout — PNG](ESP32P4_Pinout.png) · [editable SVG](ESP32P4_Pinout.svg)
- [P4 → PCA9685 wiring — PNG](PCA9685_Wiring.png) · [editable SVG](PCA9685_Wiring.svg)
- [P4 → 1.9-inch LCD wiring — PNG](LCD_Wiring.png) · [editable SVG](LCD_Wiring.svg) · [LCD instructions](LCD_FACE.md)

The pinout is an original vector illustration checked against Waveshare's
[physical pinout](https://docs.waveshare.com/assets/images/ESP32-P4-WIFI6-details-inter-3472c9ea8e7f1e2665531f8d7e954e06.webp)
and [schematic](https://files.waveshare.com/wiki/ESP32-P4-WIFI6/ESP32-P4-WIFI6-datasheet.pdf).
The wiring diagram is functional: **its PCA9685 terminal order is not a drawing
of the delivered breakout**. Follow the module's printed labels.

`L1–L20` and `R1–R20` are guide row IDs, each counted down from USB-C.
They are not GPIO numbers or Raspberry Pi header numbering. These rows match
the official front view; viewing the underside reverses left and right.

## Five logic connections

**Remove power before adding or moving wires or servo plugs.**

| P4 guide location | P4 printed label / signal | PCA9685 label | Purpose |
| --- | --- | --- | --- |
| R5: fifth right pin from USB-C | `3V3` | `VCC` | 3.3 V chip logic power |
| L13: thirteenth left pin | `GND` | `GND` | Common logic ground |
| L15: fifteenth left pin | `2` / GPIO2 | `SDA` | Dedicated servo-bus data |
| L14: fourteenth left pin | `3` / GPIO3 | `SCL` | Dedicated servo-bus clock |
| L12: twelfth left pin | `4` / GPIO4 | `OE` | Independent output-disable control |

These GPIO assignments are defined in
[`main/board.h`](../../Slave/firmware/esp32p4-wifi6/main/board.h).
The source owns I²C controller 1 at 400 kHz, expects address `0x40`, and configures
nominal 50 Hz PWM. The oscillator and actual waveforms have not been measured.
Do not use the header pins printed **SDA / SCL** (GPIO7/8): those belong to the
onboard codec/camera bus. Use the pins printed **2 / 3** for this driver.

## Servo power and startup

`VCC` powers the PCA9685 logic; `V+` powers servos. Keep VCC on P4 **3V3**.
Do not bridge VCC and V+. Use common ground between the P4, PCA board and servo
supply. The standard breakout's servo ground is the outer row, red/V+ the
middle row, and signal the inner row. With the screw terminal above the servo
rows, channels run from 0 at the left to 15 at the right.

The owner confirmed a servo moving on channel 0 with PC USB feeding P4 and a
P4 5 V-to-PCA V+ jumper. This establishes one-servo operation, not the current
capacity of the P4 header. For multiple servos, remove that jumper and feed
PCA V+ directly from the 5 V servo supply; retain the common ground and all five
logic connections. Do not connect independent +5 V sources together.
See the [PCA9685 power-pin reference](https://learn.adafruit.com/16-channel-pwm-servo-driver/pinouts).

Normal firmware starts channels 0–11 at their saved home pulses, 200 ms apart,
and leaves 12–15 off. Defaults are 1500 µs assembly midpoints; they are not yet
a calibrated laying pose. See [startup and assembly](../../Slave/firmware/esp32p4-wifi6/README.md#startup-and-assembly).
There is no wiring acknowledgement or separate bench firmware to enable first.

## Output enable

OE is active low: HIGH disables PWM and LOW permits it. GPIO4 drives OE high
at initialization and on a stop/fault. OE disables the signal; it does not cut
servo power or establish a safe load current. The generic breakout's default
OE pull-down is accepted for this supervised assembly; firmware cannot guarantee
OE remains high while the P4 is held in reset. No added resistor is required by
the startup procedure. Do not hold reset as a substitute for removing power
while changing wiring. Reset waveform behavior has not been measured.

The earlier owner-reported unpowered readings were OE–GND **9.94 kΩ** and
OE–VCC **43.69 kΩ**. These in-circuit readings are recorded observations, not
acceptance thresholds or a request for further resistance measurements.

## Other connectors to keep clear

- **USB-C:** present PC power/flash/console connection through CH343P.
- **Native USB HS P1:** separate four-pin MX1.25 connector. Schematic numbering:
  1=VCC_5V, 2=D−, 3=D+, 4=GND; match the actual connector/cable orientation,
  not a mating plug's mirrored view. Its power shares the board rail. Future
  Q6A use requires explicit USB roles and power isolation before connection.
- **GPIO24/25:** alternate native USB Full Speed D−/D+, reserved.
- **EN header:** 3.3 V supply enable. **RUN header:** P4 ESP_EN/reset.

Connector roles and routing are checked against the
[manufacturer's hardware description](https://docs.waveshare.com/ESP32-P4-WIFI6#hardware-description)
and schematic linked above. Native USB remains reserved; the current controller
transport is the existing network connection.
