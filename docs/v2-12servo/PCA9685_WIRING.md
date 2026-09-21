# P4 pinout and PCA9685 bench wiring

Updated 2026-09-15 for firmware `0.3.0-p4-turns`. Applies to the selected
**Waveshare ESP32-P4-WIFI6**, with the USB-C socket at the top and C6 antenna
at the bottom when viewing the camera/display connectors. Other P4 boards may
have different layouts.

## Image guides

- [Full P4 pinout — PNG](ESP32P4_Pinout.png) · [editable SVG](ESP32P4_Pinout.svg)
- [P4 → PCA9685 wiring — PNG](PCA9685_Wiring.png) · [editable SVG](PCA9685_Wiring.svg)

The pinout is an original vector illustration checked against Waveshare's
[physical pinout](https://docs.waveshare.com/assets/images/ESP32-P4-WIFI6-details-inter-3472c9ea8e7f1e2665531f8d7e954e06.webp)
and [schematic](https://files.waveshare.com/wiki/ESP32-P4-WIFI6/ESP32-P4-WIFI6-datasheet.pdf).
The wiring diagram is functional: **its PCA9685 terminal order is not a drawing
of the delivered breakout**. Follow the module's printed labels.

`L1–L20` and `R1–R20` are guide row IDs, each counted down from USB-C.
They are not GPIO numbers or Raspberry Pi header numbering. These rows match
the official front view; viewing the underside reverses left and right.

## Five logic connections

**Remove power before adding or moving wires. Keep every servo plug and the
PCA9685 V+ supply disconnected throughout initial testing.**

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

`VCC` powers the PCA9685 logic; `V+` powers servos. Do not bridge them. The P4's
3V3, VBUS, VSYS and USB cable are not the twelve-servo power source. A separately
qualified servo supply/distribution system with common ground is later work.
Leave the breakout's screw power terminal empty for these checks.

### OE and reset bias

OE is active low: **HIGH disables PWM; LOW permits outputs**. This firmware
sets MODE2 so disabled outputs are LOW. OE does not cut servo power or prove a
servo has released torque. See [NXP sections 7.3.2, 7.4 and Table 14](https://www.nxp.com/docs/en/data-sheet/PCA9685.pdf).

The firmware drives GPIO4 high before enabling its output, but this does not
establish its electrical state throughout reset. A real external pull-up to
3.3 V must hold OE high when the P4 cannot drive it. The delivered breakout's
existing OE pull-up/pull-down is unknown. **No resistor value is approved yet.**
A guessed pull-up can form a divider with an onboard pull-down and leave OE
below a valid HIGH. The chip requires at least `0.7 × VCC` at OE for HIGH
(2.31 V at exactly 3.3 V), with practical margin above that threshold.

The [selected HUAREW listing](https://www.amazon.com/dp/B0CRV3MK14) does not
establish this delivered unit's resistor values or reset behavior. The drawings
do not assume another manufacturer's PCA9685 schematic applies to it.

## First hands-on check: unpowered module

1. Disconnect P4 USB and any other supplies. Keep the PCA9685 separate from the
   P4, with no servos attached and no V+ wiring.
2. Confirm the actual module labels: `VCC`, `GND`, `SDA`, `SCL`, `OE` and `V+`.
3. Put the meter's black lead in **COM** and red lead in **V/Ω**, not the current
   socket. Select resistance (Ω); never measure resistance on a powered board.
4. Measure the following pairs. Wait for each reading to settle and record its
   value and units (Ω or kΩ), or `OL`. Record changing readings too. In-circuit
   readings can include semiconductor paths; they help identify the bias and
   are not by themselves a complete schematic.

| Red probe | Black probe | Delivered-module reading |
| --- | --- | --- |
| OE | GND | Not measured |
| OE | VCC | Not measured |
| SDA | VCC | Not measured |
| SCL | VCC | Not measured |

Also check for an unexpected sustained near-zero resistance between VCC and
GND, and between VCC and V+. Stop for an unexplained short or missing label.
Do not remove or bridge resistors based on a guessed clone layout.

## After the bias has been resolved

1. With power removed, fit the verified OE bias and the five logic wires above.
   Keep wires short. Confirm VCC is on **3V3**, not VBUS/VSYS or V+.
2. Return the meter to **DC volts**, keeping the leads in COM and V/Ω. Power the
   P4 through its current USB-C connection, keeping V+ and servos disconnected.
   Against PCA GND, record VCC, OE, SDA and SCL. VCC should be near 3.3 V; OE
   should be high. Check SDA/SCL idle HIGH when no transfer is active. A meter
   can average bus activity, so a low/unstable reading needs investigation.
3. Hold the board's **RST button** and measure OE again. It must remain a valid
   HIGH while reset is held. Release RST and check the disarmed static state.
   Use RST, not the header's `EN` supply-control pin.
4. Capture boot, reset and fault transitions with the equipment below before
   acknowledging wiring or enabling PWM diagnostics. Static readings do not
   prove the absence of brief enable pulses.

Independent PCA-power/P4-power-loss and brownout tests require a controlled
bench arrangement that avoids backfeeding the P4 through GPIO or 3V3. Do not
add a second supply directly to the P4's 3V3 header to attempt those tests.

## Equipment and remaining acceptance

The available multimeter can establish resistance and static voltage evidence.
It cannot prove PWM pulse widths, reset glitches or the fault-response limits.
Step 1 still needs:

- An oscilloscope for voltage/transient evidence, and simultaneous capture of
  OE/PWM/SDA/SCL using a scope or logic analyzer at **10 MS/s or better**.
- A correlated timing marker/trigger for the ≤1 ms disable-entry measurement.
- A current-limited adjustable supply for controlled power sequencing/brownout.

The [Step 1 evidence record](STEP1_EVIDENCE.md#electrical-acceptance-all-still-pending)
contains the unchanged transfer, disable, stall and reset acceptance limits.
The [target's diagnostic instructions](../../Slave/firmware/esp32p4-wifi6/README.md#output-bench-diagnostics)
apply only after those wiring prerequisites. No `wiring verified-no-servos`,
arming or PWM command was run while producing these guides.

The driver exposes channels 0–11 for disconnected-servo bench tests and keeps
12–15 unused. **Joint-to-channel assignment and MG90 calibration are still
pending.** The installed walk/turn samplers do not make servo motion ready.

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
