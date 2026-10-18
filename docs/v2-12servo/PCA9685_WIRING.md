# P4 pinout and PCA9685 wiring

Header pinout and feedback map updated 2026-10-18. Applies to the selected
**Waveshare ESP32-P4-WIFI6**, with the USB-C socket at the top and C6 antenna
at the bottom when viewing the camera/display connectors. Other P4 boards may
have different layouts.

## Image guides

- [Physical servo → PCA9685 socket → multiplexer input — PNG](Servo_Socket_Map.png)
  · [socket table and assembly notes](SERVO_SOCKET_MAP.md) · [editable SVG](Servo_Socket_Map.svg)
- [LSM6DS3 gyro wiring — PNG](LSM6DS3_Wiring.png)
  · [dedicated wiring and calibration guide](LSM6DS3_IMU.md) · [editable SVG](LSM6DS3_Wiring.svg)
- [P4 → CD74HC4067 servo feedback — PNG](Multiplexer_Wiring.png) · [editable SVG](Multiplexer_Wiring.svg)
  · Uses the owner's C4–C15 input selection and a local EN-to-GND jumper.
- [Current combined assembly image: LCD + servo board + IMU](Assembly_Reference.png)
  · [connection table and sharing explanation](ASSEMBLY_REFERENCE.md)
- [Full P4 pinout — PNG](ESP32P4_Pinout.png) · [editable SVG](ESP32P4_Pinout.svg)
- [P4 → PCA9685 wiring — PNG](PCA9685_Wiring.png) · [editable SVG](PCA9685_Wiring.svg)
- [P4 → 1.9-inch LCD wiring — PNG](LCD_Wiring.png) · [editable SVG](LCD_Wiring.svg) · [LCD instructions](LCD_FACE.md)

The P4 pinout SVG/PNG was updated October 18 to show PCA9685, LCD, LSM6DS3 and
CD74HC4067 assignments, shared 3V3 branches and local straps. Its GPIO assignments
were checked against `main/board.h`, LCD `sdkconfig`/`main/Kconfig.projbuild`,
`main/servo_feedback.c` and the media I2C bus owner. The older combined assembly
image does not show the multiplexer; use the current pinout and dedicated guides
for that addition. Historical startup descriptions below are not pin assignments.

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
The revised driver staggers channels 0–11 evenly across each PWM period, roughly
1.67 ms between adjacent channel starts. OFF counts wrap modulo 4096 so pulse
widths and calibration remain unchanged. All twelve targets still use one I²C
frame write. Channels 12–15 stay off. Signal staggering does not establish that
the MG90 motor-current peaks are staggered; that requires an electrical measurement.

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

## MG90 fourth-wire feedback — October 16, 2026

[Wiring image: P4 → multiplexer, C4–C15](Multiplexer_Wiring.png)
([editable SVG](Multiplexer_Wiring.svg)), added October 17. The owner selected
C4–C15 for the twelve feedback wires; C0–C3 stay unused. This mapping was saved
and read back on October 17. The image is a connection diagram, not the module's
connector layout. See the [per-servo socket map](SERVO_SOCKET_MAP.md).

Firmware `0.8.64-p4-lcd-restored`, used during October 17 calibration, supports the purchased
**CD74HC4067** module. Acquisition and measured-position Stand are separate saved
options; both default off until configured. All twelve loose servos were tested
and their feedback curves saved at 500, 1650 and 2800 us. Acquisition is enabled;
measured Stand remained off at the last readback. Loaded performance remains
unverified; see the [research journal](GAIT_RESEARCH_JOURNAL.md).

The servo's original three wires stay connected to the PCA9685. The added wire
from its potentiometer wiper goes to one multiplexer input. It is an analog
voltage, not I2C. Leave the potentiometer's original connections intact.

| CD74HC4067 label | P4 connection | Header guide row |
| --- | --- | --- |
| VCC | 3V3 | R5 |
| GND | Common ground with P4 and servo supply | e.g. L8 |
| EN / inhibit | GND, selecting enabled operation | Same common ground |
| SIG / COM | GPIO49, ADC2 channel 0 | L10 |
| S0 | GPIO27 | R14 |
| S1 | GPIO28 | L7 |
| S2 | GPIO29 | L6 |
| S3 | GPIO30 | L5 |

Follow the delivered board's labels, not an assumed connector order. These pins
leave the PCA9685 GPIO2/3/4 and IMU GPIO7/8 assignments intact. The restored
1.9-inch ST7789 display uses GPIO20/21/22/23/26, as shown in
[the LCD wiring guide](LCD_FACE.md#connections). The feedback pins avoid that
display allocation.

Saved wiring follows Body Control's physical joint labels. Each group is in
shoulder, carrier, crank order:

| Physical leg | PCA9685 sockets | Multiplexer inputs |
| --- | --- | --- |
| Rear left | 0, 1, 2 | C4, C5, C6 |
| Rear right | 3, 4, 5 | C7, C8, C9 |
| Front left | 6, 7, 8 | C10, C11, C12 |
| Front right | 9, 10, 11 | C13, C14, C15 |
| Unused | 12–15 | C0–C3 |

The unconfigured software defaults still map joint IDs 0–11 to inputs C0–C11;
the saved mapping above overrides them. Restore C4–C15 if starting with erased
feedback settings. Do not rewire to the defaults.

The feedback input mapping is configurable. PCA output sockets and feedback
inputs are independent: identify a wire by the joint it measures, using the
existing saved motor mapping. A floating spare input can show a voltage; an ADC
reading is not proof that a feedback wire is connected.

**Electrical commissioning:** with power removed, attach the module wiring.
Before connecting wipers to it, measure each modified servo over its intended
travel. Every input must stay between ground and the module's actual 3V3 supply.
The owner's spare measured about 0.3 V / 1.7 V / 3.2 V at 500 / 1650 / 2800 us;
this does not establish the limits of the other servos or the 400–2900 us range.
Power the P4/multiplexer before powering the servos, and remove servo power
first, to avoid driving an unpowered input. A direct single-module interface
remains conditional on these measurements; no travel reduction is implemented
to make the electronics fit.

**Body Control commissioning:** after installing this firmware and the gateway
update, open Maintenance → Servo feedback. Enable reading, leaving measured
Stand off. Check which raw input follows each manually positioned servo. Capture
three settled positions per joint (low, middle, high command pulse) using Joint
calibration to position the unloaded servo, then entering that actual commanded
pulse in the feedback panel. Capture does not move the robot. Reference pulses
must increase; raw voltage may increase or decrease. Saving feedback calibration
does not alter motor Home, inversion, linkage calibration, or pulse limits.

The reader scans all sixteen inputs independently of motion, discards one ADC
conversion after switching and averages four more. The panel shows raw reading,
voltage where ADC voltage calibration is available, sample age, and sample
spread. Bench checks must establish inter-channel settling, repeatability and
whether the connection changes a servo's behavior. Compare a steady joint while
adjacent inputs move; the software's sample spread alone cannot rule out a
systematic acquisition error. Unused floating channels are diagnostic only.

After all twelve curves are calibrated, enable **Coordinate Stand using measured
positions**. Arrival tolerance is adjustable in pulse-equivalent microseconds
(initial setting 30 us). Startup confirms its fold, then confirms the existing
shift/lift/place/lower stages. It first lifts a leg with its shoulder uncommanded,
then engages that shoulder after measured lift arrival. Normal Stand initializes
its path from measured joint positions. The final receipt follows measured final
arrival. Targets stay applied while joints catch up; there is no added timeout
or automatic shutdown. A new command can replace Stand. If a required reading
fails or a commanded joint cannot arrive, that stage remains active and the
panel lists the joints still waiting. Switching measured Stand off returns the
existing time-based progression.

This measures shaft position, not contact force, motor current, or absolute body
height. Confirmed joint arrival does not itself prove foot clearance, a rigid
linkage, or enough torque under load. No new feedback control is added to walking
or gestures in this change. PCA9685 pulse staggering remains in the common driver.

References: [TI CD74HC4067 datasheet](https://www.ti.com/lit/ds/symlink/cd74hc4067.pdf),
[P4 datasheet](https://www.espressif.com/sites/default/files/documentation/esp32-p4_datasheet_en.pdf),
[ESP-IDF 5.5.4 ADC driver](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32p4/api-reference/peripherals/adc_oneshot.html).

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
