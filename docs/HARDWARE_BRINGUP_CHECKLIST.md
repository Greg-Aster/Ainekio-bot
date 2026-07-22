# Ainekio Hardware Bring-Up Checklist

This document records the intended power topology and the steps for verifying
the assembled robot before normal motion is accepted. It also records the
software media gates that must pass before physical camera and audio results are
attributed to hardware. It is an execution checklist and evidence record;
`Ainekio - System Specification v1.0.docx` remains the behavior and safety
authority, the externally maintained
[Parts Overview](https://docs.google.com/document/d/1wz0kyqttPK3HHL0P0_9lLtRW_B87U5u4kEt-UhttHFA/edit?usp=sharing)
remains the electrical-parts authority, and
[`PINOUT_DIAGNOSTICS.md`](PINOUT_DIAGNOSTICS.md) records the current flashed
board map and diagnostic values.

The Parts Overview has been reviewed for firmware preparation. Its values below
remain planned values until delivered markings, wiring, measurements, and
photographs confirm them. The controller, OV3660 camera, and eight remapped PWM
allocations now have USB-only evidence; the external power system, physical
servo signals and joints, and attached peripherals remain open physical gates.

The companion MetaHuman OS plan is `docs/implementation-plans/VISION_MODEL_IMPLEMENTATION.md` in the MetaHuman repository. MetaHuman owns provider-neutral image-model routing. Ainekio owns real and virtual capture, bounded JPEG and PCM transport, utterance handling, speaker delivery, and hardware safety. Neither program should import the other's private implementation.

## Owner-confirmed power topology

- MusRock MINI560 PRO buck converter #1 supplies the soldered 5 V servo rail.
- A separate MusRock MINI560 PRO buck converter #2 supplies the Freenove board's 5 V input and the MAX98357A amplifier.
- ESP32-S3 GPIO outputs connect directly to the servo signal inputs and provide 3.3 V control signals.
- The board's regulated 3.3 V output supplies the INMP441, SSD1306 OLED, and other 3.3 V systems; the built-in camera is already part of the board.
- Both buck converters, the battery, microcontroller, servos, amplifier, and 3.3 V devices share a common ground.
- Servo load current travels through the dedicated soldered power rail, not through the microcontroller's 5 V or 3.3 V regulator paths.

The topology above is clear. The checks below do not question it. They establish that the particular buck converter, wiring, connectors, regulator, and power source remain within their ratings when the assembled robot is operating. They also establish values that cannot be obtained from a 5 V output label alone, such as loaded voltage drop and the upstream battery-to-ADC measurement ratio.

## Parts and installed-evidence record

These planning values come from the Parts Overview. Replace or confirm them from delivered labels and manufacturer specifications before applying power.

| Item | Installed value | Source or evidence |
| --- | --- | --- |
| Controller board and PCB revision | Freenove ESP32-S3-WROOM CAM delivered; PCB revision not yet recorded | Delivered board; H2 photo required |
| ESP32-S3 module, flash, and PSRAM | ESP32-S3-WROOM-1 N16R8; 16 MB quad flash + 8 MB octal PSRAM | Parts Overview; module-marking photo required |
| Camera sensor/module | Built-in OV3660 | Delivered module marking and successful firmware identification |
| INMP441 microphone module and L/R strap | INMP441; L/R strap not yet selected/observed | Parts Overview; F inspection required |
| MAX98357A amplifier board and supply voltage | MAX98357A at 5 V from electronics buck | Parts Overview; F inspection required |
| MAX98357A gain/channel/shutdown configuration |  |  |
| Speaker | 8 ohm, 2 W | Owner-confirmed |
| Amplifier local bypass/bulk capacitance |  |  |
| 5 V buck converter make/model | Two MusRock MINI560 PRO 5 A modules; one servo, one electronics | Parts Overview; delivered markings required |
| Buck input-voltage range | Pending manufacturer/delivered-part verification | B evidence required |
| Buck continuous and peak current ratings | Advertised 5 A; actual continuous/thermal capability pending load test | B evidence required |
| Power source/battery chemistry and cell count | Protected 2S1P battery, 2600 mAh | Parts Overview; delivered label required |
| Source nominal, full, and minimum safe voltage | 7.4 V nominal, 8.4 V full; minimum governed by S1/S2 and battery protection | Parts Overview; H5/H9 evidence required |
| Servo make/model and quantity | Eight MG90S | Parts Overview; delivered labels required |
| Servo specified operating-voltage range |  |  |
| Servo no-load, moving, and stall current |  |  |
| Servo rail wire gauge | 22 AWG; battery feed 20 AWG; signals 30 AWG | Parts Overview; A inspection required |
| Connector, switch, and fuse ratings | KCD1 switch planned; connector and fuse ratings pending confirmation | Parts Overview; A inspection required |
| OLED size, controller, and I2C address | 0.96-inch SSD1306 I2C; address `0x3C` planned, physical scan required | Parts Overview; D evidence required |
| Battery-sense ADC pin | GPIO3 / ADC1 channel 2 | System specification 6.3 and Parts Overview |
| Battery-sense upper/lower resistor values | 100 kOhm upper / 47 kOhm lower with 0.1 uF filter | Parts Overview; installed values must be measured |
| Calculated battery-divider factor | `(100 + 47) / 47 = 3.127659...`; firmware stages `3.12766` | Parts Overview; H9 calibration required |

Do not infer the battery-divider factor from the buck converter's 5 V output. A regulated buck output normally stays near 5 V while its input battery voltage changes. Battery state therefore must be measured upstream of the buck with a documented, ADC-safe divider or with another identified battery-monitor circuit.

## Test equipment

- Current-limited bench supply or a fused power source
- Digital multimeter
- USB/UART connection for boot logs
- Oscilloscope or logic analyzer if available, especially for rail droop and servo pulses
- Manufacturer specifications for the board, buck converter, servos, and battery

Start with the servo plugs disconnected and the robot supported so no joint can bear weight or strike anything.

## Firmware preparation record - 2026-07-15

This dated record prepared the original installable image. The later USB-only
board evidence is recorded under the MAP_B remap and Results sections; it does
not close the remaining assembled-hardware gates.

- [x] Re-read System Specification v1.0 sections 6.2-6.7, H2/H3, and the risk register before changing the map.
- [x] Preserve the required SD_MMC bus. No servo was moved to GPIO38/39/40 and SD was not removed.
- [x] Consolidate the Freenove N16R8 module facts, camera pins, accessory pins, and eight servo pins in `components/ainekio_platform/include/ainekio/platform/pin_map.h`.
- [x] Add software validation for duplicate active GPIOs, invalid input/output use, SD conflicts, N16R8 PSRAM-reserved GPIO33-37, logical joint order, and MCPWM resource collisions.
- [x] Configure 16 MB DIO flash at 80 MHz and 8 MB octal PSRAM at 80 MHz with the startup memory test enabled.
- [x] Pin `espressif/esp32-camera` 2.1.7 and integrate an OV3660 camera task using Freenove's GPIO map, 10 MHz XCLK, JPEG, QVGA startup, PSRAM framebuffer, a two-frame drop-oldest media queue, snapshots, QVGA/VGA changes, and protocol counters.
- [x] Configure the planned GPIO3 100 kOhm/47 kOhm divider factor `3.12766` and enable battery monitoring; H9 still compares reported voltage with a multimeter and refines the ADC correction if required.
- [x] Keep the owner-directed all-servo motion profile independent of battery-monitor configuration while retaining the active low-voltage power guard.
- [x] Retain the existing battery policy: 16-sample sets every 5 seconds, warning below 7.0 V, cutoff below 6.8 V, recovery at or above 7.2 V, and three qualifying sets before a state transition. Three startup sets at or below 0.25 V classify the battery input as disconnected; after any plausible battery voltage is seen, near-zero readings use the cutoff path.
- [x] Retain all eight MCPWM channels and the staggered-center implementation behind the physical-motion build gate.
- [x] Apply an initial 25 percent platform motion range around logical center (`67.5`-`112.5` degrees; `1250`-`1750` us with default calibration) and a 100 ms minimum motion-frame duration to normal semantic motions and calibration commands.
- [x] Preserve explicit `stop`/failsafe detachment of all eight signal GPIOs. This affects the 3.3 V PWM signals only; the external 5 V servo rail is not software-switched.
- [x] Add boot reporting for board profile, PSRAM size, camera readiness, battery-monitor state, and the physical-motion build gate; dump remapped GPIO47/48 configuration for H2 evidence.
- [x] Pass all 11 portable C tests after enabling battery monitoring, including battery thresholds and the calibration-motion gate.
- [x] Re-run the complete A1-A30 emulator/protocol acceptance suite after enabling the all-servo profile; all 30 cases pass.
- [x] Cross-build with ESP-IDF 5.5.4 and battery monitoring enabled. Padded image size is `0x119c20` bytes (1,154,080 bytes), leaving 63 percent of a 3 MiB OTA slot free; DIRAM use is 230,875 bytes (67.55 percent).

### MAP_B board-only remap for H2/H3 - 2026-07-21

| Function | GPIO |
| --- | --- |
| Camera | 4-13 and 15-18, using Freenove's exact signal order in `pin_map.h` |
| Servos R1, R2, L1, L2, R4, R3, L3, L4 | 1, 2, 14, 21, 47, 48, 45, 46 |
| Battery ADC | 3 |
| I2S mic DIN, amp DOUT, BCLK, WS | 19, 20, 41, 42 |
| OLED SDA, SCL | 0, 43 after startup |
| CH343 UART TX, RX | 43, 44 during ROM/boot; GPIO43 hands off to OLED SCL |
| SD_MMC CMD, CLK, DAT0 | 38, 39, 40 |
| BOOT | 0 at reset and as the held-button input; GPIO0 hands off to OLED SDA |

Delivered-hardware H2 rejected GPIO33/34: initializing MCPWM on those N16R8 octal-PSRAM signals immediately corrupted memory. The board-only remap preserves the six valid servo outputs and moves only R4/R3 to exposed GPIO47/48. The OLED moves to GPIO0/43. Its open-drain SDA configuration preserves GPIO0's normal high boot strap and allows a continuous five-second BOOT-button hold to remain distinguishable from short I2C transitions. GPIO43 provides boot-time UART output and is handed to I2C when the display starts. If no OLED responds, the failed I2C bus is released and GPIO43 returns to UART so later faults remain visible. The full-feature image enables all eight remapped PWM channels under the reduced-range safety profile; physical servo movement remains unverified until the signal leads and external 5 V rail are connected.

GPIO0/3/45/46 remain H3 strapping tests. GPIO19/20 intentionally sacrifice native USB for I2S after bring-up. Runtime CH343 transmit logging is unavailable after a responding OLED takes GPIO43; ROM/bootloader UART remains available before that handoff, and an absent OLED now restores the UART. GPIO48 is also wired to the board's WS2812 input, so the onboard RGB LED is unavailable and H2 must confirm that the attached LED input does not disturb its servo signal. SD CMD and DAT0 pull-ups remain an H2 schematic/physical check.

### Still requires physical assembly or recorded evidence

- [ ] H1 reference blink, Wi-Fi, and Freenove camera example.
- [ ] H2 GPIO0/43 handoff, GPIO47/48 PWM initialization, module photo, pull-up review, and concurrent soak.
- [ ] H3 boot-strapping matrix with the divider and all servo signal leads attached.
- [ ] H9 installed-divider and ADC calibration against a multimeter.
- [x] OV3660 identification and repeated boot-time camera initialization.
- [ ] Verify the enabled remapped centered/reduced-range signals and physical outputs on delivered hardware before increasing range above 25 percent.

## Foundation 0: prove media contracts without physical hardware

Close this software gate before using physical camera, microphone, or speaker results to diagnose the end-to-end system.

### Virtual vision

- [ ] Add a deterministic, valid JPEG fixture no larger than 120 KiB with a stable visual marker such as `AINEKIO-7` and a prominent color.
- [ ] Prove `snap` produces a protocol-v1 camera JPEG frame, the gateway converts it into a generic Environment Bridge visual observation, and MetaHuman sends it to a captured or fake image-model endpoint.
- [ ] Prove the same known image produces the expected marker/color answer from the configured real image model.
- [ ] Add a Sesame renderer snapshot producer to the browser shim or a bounded browser-capture adapter and use it as a `CameraSource`.
- [ ] Prove a post-action snapshot reflects a visible simulator scene change.
- [ ] Keep continuous video out of the cognition loop; use explicit or low-rate bounded JPEG snapshots first.

### Virtual hearing and speaking

- [x] Build a microphone fixture from multiple 640-byte, 16 kHz mono PCM frames with silence, speech-like energy, and explicit VAD open/close boundaries.
- [x] Buffer a bounded utterance before transcription. Do not invoke speech recognition independently for every 20 ms PCM frame.
- [x] Install the configured transcription path in production gateway startup and prove one utterance becomes one generic Environment Bridge text observation.
- [ ] Define the generic outbound speech-delivery contract separately from `sendText`; conversational text acknowledgement alone does not play the robot speaker.
- [ ] Route synthesized 16 kHz mono PCM through `GatewayService.tts_speak`, preserving start, frame, end, cancellation, and completion order.
- [ ] Use a recording or fixture speaker sink to prove the outbound PCM stream without ALSA or physical hardware.
- [ ] Prove camera frames, microphone frames, and speaker frames retain their bandwidth priority and drop/counter behavior under combined virtual load.

**Pass:** A known virtual image reaches the image model, a bounded virtual utterance reaches MetaHuman as text, and a bounded MetaHuman speech response reaches a recording speaker sink. No physical device, Linux webcam, or ALSA device is required for this pass.

**Hearing evidence (2026-07-17):** Focused gateway and bridge tests prove VAD
grouping, missing-frame silence, bounded duration, WAV validation, one Whisper
call, and one metadata-bearing text observation. A live 2.1-second, 16 kHz mono
PCM fixture passed through the Ainekio binary-envelope parser and MetaHuman's
running `base.en` Whisper server. Whisper returned `Inekio hears this test
phrase.` The full Foundation 0 pass remains open because virtual vision and
outbound speech delivery are separate unfinished gates.

### Local microWakeWord implementation

- [x] Add the authenticated protocol-v1 `wake` command with persistent `enabled` and trained-model `model` fields.
- [x] Store the robot-owned setting in the existing NVS preferences namespace as optional `wake_enabled` and `wake_model` keys.
- [x] Default a first boot or missing-key migration to `enabled=false` and `model=ainekio` without erasing profile, ADC calibration, servo calibration, poses, Wi-Fi, or identity settings.
- [x] Report `wake_enabled`, `wake_model`, and `wake_ready` in firmware and emulator status.
- [x] Add gateway API and dashboard controls for the setting, plus protocol, emulator, gateway, and dashboard coverage.
- [x] Keep `wake_ready=false` and reject both wake enablement and `mic` with `gate=wake` while no trained model is installed. The fixed energy detector is not presented as wake-word detection.
- [x] Select the open microWakeWord quantized TFLite format instead of attempting to reverse engineer proprietary WakeNet weights. Pin TensorFlow Lite Micro 1.3.7, ESP-NN 1.1.2, and the micro-speech frontend 1.2.3.
- [x] Integrate on-device 16 kHz streaming feature generation and TFLite Micro inference. Wake mode now keeps PCM local until a real model detection, emits the wake event once, forwards the following VAD-bounded utterance, closes after approximately 700 ms of silence, and rearms after reset/warm-up.
- [x] Add the bounded `ainekio-microwakeword-v1` installed-model manifest, SHA-256 verification, TFLite/tensor/operator validation, provenance fields, and a tested local packaging tool.
- [x] Document an entirely local training, packaging, and LittleFS loading workflow in `docs/LOCAL_WAKE_WORD.md`. Voice data, generated features, checkpoints, and weights stay on owner-controlled hardware.
- [ ] Freeze the intended pronunciation of “Ainekio,” then locally train, license, version, and evaluate the actual quantized model. Do not mark it ready based on synthetic training accuracy alone.
- [ ] Install the locally trained package and measure RAM, PSRAM, flash, CPU, false accepts, false rejects, camera, Wi-Fi, servo, speaker, and audio coexistence on the N16R8 board.
- [ ] Extend robot status with an installed-model list so the gateway model selector is populated from the robot rather than a hard-coded option.
- [ ] Define and prove an authenticated, checksummed or signed model-package install/activation/rollback path. Switching an installed model should not require application reflashing; a new phrase still requires a trained model artifact.
- [x] Add bounded pre-roll, maximum utterance duration, gateway utterance assembly, speaker-time microphone muting, and cooldown.
- [ ] Calibrate the 100 ms pre-roll, 15 second maximum, 700 ms speech-end hangover, and 800 ms post-speaker cooldown on physical hardware.

**Current result:** The durable control plane and real microWakeWord inference engine are implemented and cross-build. No `Ainekio` weights are installed, so the checked-in image intentionally remains `wake_ready=false` and first boot remains disabled. The gateway is a controller and display surface, not the source of truth.

## A. Unpowered wiring inspection

- [ ] Photograph the finished power and signal wiring clearly enough to trace it later.
- [ ] Verify supply polarity at each buck input and each 5 V output.
- [ ] Verify that the servo rail receives regulated 5 V, not raw battery voltage.
- [ ] Verify that the controller receives 5 V only at its documented 5 V input.
- [ ] Verify that 3.3 V devices receive power only from the board's 3.3 V output.
- [ ] Verify continuity between supply ground, controller ground, servo ground, and peripheral ground.
- [ ] Verify that servo power does not pass through the board regulator or narrow controller traces.
- [ ] Verify that no 5 V line connects to an ESP32 GPIO.
- [ ] Check for shorts between 5 V and ground and between 3.3 V and ground.
- [ ] Check wire, connector, switch, and fuse ratings against the expected combined current.

**Pass:** The wiring matches the topology above, polarity is correct, grounds are common, and no short or over-rated current path is found.

## B. Verify each buck converter by itself

- [ ] Test the servo buck and electronics buck separately with the controller, servos, and peripherals disconnected.
- [ ] Set a conservative current limit on the test supply.
- [ ] Apply the lowest expected source voltage and measure the buck output.
- [ ] Adjust or confirm the output at the intended 5 V setting.
- [ ] Repeat at nominal and maximum source voltage.
- [ ] Add a controlled load within the converter's rating and record output voltage, input current, output current, ripple if measurable, and temperature.
- [ ] Remove input power and verify there is no harmful backfeed from USB or another connected source.

**Pass:** Output remains within the documented voltage limits of every connected 5 V device throughout the intended input and load range, with no shutdown or excessive heating.

## C. Power the controller only

- [ ] Leave every servo disconnected.
- [ ] Apply 5 V to the board's documented 5 V input.
- [ ] Measure the 5 V input and regulated 3.3 V rail at the board.
- [ ] Capture the complete boot log.
- [ ] Confirm the exact ESP32-S3 module, flash size, and PSRAM size reported at boot.
- [ ] Confirm there are no brownout resets, boot loops, regulator overheating, or unexpected current draw.
- [ ] Check whether USB connection changes or backfeeds either power rail.

**Pass:** The board boots repeatedly, reports the expected hardware, and both rails remain within the connected parts' specified limits.

## D. Verify the OLED

- [ ] Connect only the SSD1306 OLED to the documented I2C power and pins.
- [ ] Confirm whether its address is `0x3C` or `0x3D`.
- [ ] Confirm the display initializes without blocking the rest of the firmware if it is absent or faulty.
- [ ] Confirm the setup network, stable eight-character key, and
  `192.168.4.1` setup address are legible on the physical display.
- [ ] Join `Ainekio-Setup` with that key and confirm the configuration form opens
  directly at `http://192.168.4.1/` without a second login prompt.
- [ ] While AP+STA mode is active, confirm the same setup HTTP service rejects a
  request arriving through the normal station interface.
- [ ] Reboot twice and confirm the device setup key remains unchanged; a full
  NVS erase is the only service operation that should replace it.
- [ ] After setup, confirm the joined SSID, DHCP address, and gateway state are
  legible and accurate.
- [ ] Exercise all 37 named expressions and all 48 encoded face frames, checking alignment, corruption, and transitions.
- [ ] Measure the 3.3 V rail during display updates.

**Pass:** Text and faces fit the physical display, all intended frames render, and display activity does not destabilize the 3.3 V rail.

## E. Verify the built-in camera

- [ ] Confirm the exact Freenove board revision and camera sensor from its markings or documentation.
- [ ] Confirm the board's camera pin map rather than assuming a generic ESP32-S3-CAM layout.
- [ ] Confirm PSRAM is detected and enabled.
- [ ] Run the matching Freenove or Espressif camera example before testing the Ainekio camera path.
- [ ] Capture a still JPEG at a conservative frame size such as QVGA or VGA.
- [ ] Record image size, capture time, stability, and 5 V/3.3 V rail measurements.
- [ ] After the reference example passes, test the Ainekio snapshot command.
- [ ] Test streaming only after still capture is reliable.

**Pass:** The reference camera test and Ainekio still capture work repeatedly without resets, corrupted frames, or unacceptable rail droop.

## F. Verify the INMP441, MAX98357A, and speaker

The installed 8 ohm, 2 W speaker is an appropriate load for a MAX98357A operated from 5 V. The amplifier data sheet specifies approximately 1.4 W into 8 ohms at 1% THD+N and 1.8 W at 10% THD+N. Begin at low digital amplitude and verify the actual breakout board, supply, gain, shutdown, wiring, and enclosure rather than assuming those typical values.

Reference constraints:

- INMP441 supply: 1.8-3.3 V; use the board's regulated 3.3 V rail for the installed module unless its manufacturer documentation says otherwise.
- INMP441 output: 24-bit I2S in a 32-clock slot. Its L/R strap must match `CONFIG_AINEKIO_MIC_SLOT_RIGHT`.
- Current flashed audio pins: microphone DIN GPIO19, amplifier DOUT GPIO20, BCLK GPIO41, and WS/LRCLK GPIO42.
- MAX98357A supply: 2.5-5.5 V. A 5 V supply provides the expected output range for the installed 8 ohm speaker.
- Connect the speaker only between amplifier `OUTP` and `OUTN`. Neither speaker lead is a ground connection.
- Keep the amplifier shut down while clocks are absent or being stopped; establish BCLK and LRCLK before enabling its output.

Official references:

- `https://invensense.tdk.com/wp-content/uploads/2015/02/INMP441.pdf`
- `https://www.analog.com/media/en/technical-documentation/data-sheets/MAX98357A-MAX98357B.pdf`

### Unpowered audio inspection

- [ ] Verify the INMP441 VDD, ground, BCLK, WS, SD, and L/R connections against the installed module's labels.
- [ ] Record the L/R strap and select the matching firmware slot.
- [ ] Verify the MAX98357A VDD, ground, BCLK, LRCLK, DIN, gain/channel, and shutdown connections against the installed breakout.
- [ ] Verify the 8 ohm, 2 W speaker is connected between `OUTP` and `OUTN`, with neither output shorted to ground.
- [ ] Confirm local amplifier bypass and bulk capacitance are installed close to the module and account for long supply leads if present.
- [ ] Confirm audio pins do not conflict with camera, SD, OLED, servo, UART, or boot-strapping pins.

### Powered speaker test

- [ ] Start with servos disconnected, amplifier shut down, and speaker output at minimum digital amplitude.
- [ ] Confirm BCLK and LRCLK are stable before enabling the amplifier.
- [ ] Play a bounded 16 kHz test tone or known PCM fixture and increase amplitude gradually.
- [ ] Record amplifier supply voltage/current, 5 V and 3.3 V rails, audible distortion, amplifier temperature, speaker temperature, and speaker underrun counters.
- [ ] Verify stop, cancellation, and TTS end return the output to silence without a persistent tone, pop, or DC-related speaker heating.

### Powered microphone test

- [ ] Capture raw microphone PCM with the speaker silent and verify the selected I2S slot contains changing samples rather than zeros or repeated full-scale values.
- [ ] Record silence level, normal speech level, clipping level, and the resulting VAD open/close behavior.
- [ ] Adjust sample extraction, gain, or VAD threshold from recorded evidence rather than compensating for a wrong L/R slot in software.
- [ ] Confirm the gateway receives ordered 640-byte PCM frames and records microphone drop counters under load.
- [ ] Repeat with speaker playback active and record acoustic feedback, echo, false VAD triggers, and any need for half-duplex policy or echo control.

**Pass:** Speaker playback is intelligible and bounded without clipping, heating, rail instability, persistent output, or excessive underruns; microphone speech is captured in the correct slot without clipping or excessive noise; VAD creates usable utterance boundaries; simultaneous operation has a documented feedback policy.

## G. Add the remaining low-voltage devices

- [ ] Add one 3.3 V device at a time.
- [ ] Verify its supply pin, interface voltage, and GPIO mapping before connection.
- [ ] Measure the 3.3 V rail and board temperature after each device is added.
- [ ] Exercise Wi-Fi, OLED updates, audio input/output, SD access, and camera capture in combinations.
- [ ] Record any pin conflict or boot-strapping-pin behavior.

**Pass:** Each device and the combined peripheral load operate within board-regulator and GPIO limits without boot failure, reset, or excessive heat.

## H. Establish battery measurement and power guards

The owner-directed initial all-servo profile is enabled independently of battery-monitor configuration. Battery monitoring is enabled on GPIO3 with the planned divider and protection thresholds, while this section remains the physical voltage-accuracy and cutoff-behavior validation. Measuring only either regulated 5 V rail cannot provide the upstream battery value.

- [ ] Identify the physical battery-monitor circuit, if one is installed.
- [ ] Verify that it samples the source upstream of the 5 V buck.
- [ ] Record the upper and lower resistor values and the ESP32 ADC pin.
- [ ] Calculate the divider factor from those installed values.
- [ ] Confirm that the highest possible source voltage cannot exceed the ADC pin's allowed voltage.
- [ ] With servos disconnected, compare raw ADC readings and firmware-reported voltage against a multimeter at full, nominal, and lower source voltages.
- [ ] Compare the configured `3.12766` divider factor with the installed resistor values and adjust it if required.
- [ ] Verify the movement-enable, low-voltage, cutoff, recovery, and hysteresis behavior against measured voltages.
- [ ] With battery monitoring enabled, confirm that invalid or implausible readings trigger the documented power guard and detach behavior; also confirm that a startup-disconnected input remains awake and that disconnecting after a plausible battery reading triggers cutoff.

**Pass:** Firmware voltage agrees with the multimeter closely enough for the chosen safety thresholds, and every invalid or low-power condition fails safe.

The current plan is the Parts Overview's 100 kOhm/47 kOhm divider with a 0.1 uF filter on GPIO3, upstream of the bucks. If the battery or divider is disconnected at startup, three readings at or below 0.25 V select the disconnected state and allow USB-only operation. Once a plausible battery voltage is observed, that exception remains disabled until reboot and a later near-zero reading fails safe through cutoff. Omitting or changing the divider still removes meaningful battery protection and must be recorded; the buck specifications alone cannot fill this firmware value.

## I. Test one unloaded servo

- [ ] Support the robot and mechanically unload the selected joint.
- [ ] Connect one servo to the 5 V rail, common ground, and its assigned 3.3 V GPIO signal.
- [ ] Use a current-limited or fused source appropriate to the servo.
- [ ] Confirm the GPIO is inactive/high-impedance through boot until motion is deliberately enabled.
- [ ] Command a small, slow, semantic joint movement within the configured limits.
- [ ] Verify the physical joint, direction, center, limits, and servo-map entry.
- [ ] Measure 5 V rail voltage and current while idle, moving, and briefly resisted without forcing a destructive stall.
- [ ] Issue stop and detach/disable commands and verify the expected electrical and mechanical response.
- [ ] Confirm the controller does not reset when the servo starts or stops.

**Pass:** The correct joint moves in the correct direction within limits, stop behavior works, and servo-current transients do not disturb the controller.

## J. Build up to the complete servo set

- [ ] Repeat the one-servo test for every channel.
- [ ] Add servos one at a time while monitoring total current and rail voltage.
- [ ] Test standing only after every unloaded channel passes.
- [ ] Test low-speed walking and emotes only after standing is stable and the robot is physically restrained against a fall.
- [ ] Exercise the largest credible simultaneous movement while recording peak current, minimum 5 V voltage, board resets, connector temperature, and buck temperature.
- [ ] Compare the result with the supply, buck, wiring, connector, fuse, and servo ratings.
- [ ] Verify hardware and software stop behavior under the combined load.

**Pass:** The complete servo load stays inside every component rating, rail voltage stays above the documented minimum for all connected devices, no connection overheats, and stop behavior remains reliable.

## K. Combined-system soak test

- [ ] Run Wi-Fi, OLED face animation, camera capture, audio, SD activity, and representative servo motion together.
- [ ] Monitor both power rails, logs, resets, memory errors, dropped commands, and temperatures.
- [ ] Run for at least 30 minutes after all shorter tests pass.
- [ ] Verify emergency stop repeatedly during different activities.
- [ ] Save the final configuration, measurements, logs, and wiring photographs.

**Pass:** The combined system completes the test without unsafe motion, brownout, reset, data corruption, excessive heating, or loss of stop control.

## Firmware preparation and gates before expanding the initial motion profile

- [x] Configure the Parts Overview's planned `3.12766` divider factor and enable the GPIO3 battery monitor.
- [ ] Validate the installed divider/ADC against a multimeter at H9 and store any required correction factor.
- [x] Require the same hardware-ready safety gate for calibration motion as for normal motion.
- [x] Validate definite MAP_B GPIO capability, explicit boot-time handoffs, duplicate-use, SD, GPIO33-37 PSRAM, and MCPWM conflicts in firmware.
- [x] Reject GPIO33/34 from delivered-hardware evidence and remap the two servo signals to GPIO47/48.
- [ ] Validate the GPIO0/43 OLED handoff and GPIO48 servo/WS2812 attachment with H2 evidence; do not infer this from a successful build.
- [x] Enable 8 MB octal PSRAM and its startup memory test in the checked configuration.
- [x] Verify the detected 8 MB PSRAM size and startup memory test on the delivered N16R8 board.
- [ ] Verify concurrent PSRAM stability during the assembled-system H2 soak.
- [x] Add the pinned OV3660 ESP32-S3 camera driver, bounded task/queues, and protocol snapshot/stream path.
- [ ] Verify physical OV3660 JPEG capture, streaming, drop counters, and rail stability.
- [ ] Verify the INMP441 L/R strap, 24-bit sample extraction, measured levels, and VAD thresholds.
- [ ] Verify MAX98357A gain/channel/shutdown configuration, stable-clock enable ordering, and bounded initial volume.
- [ ] Prove production microphone utterance transcription and outbound TTS speaker delivery; physical I2S success alone does not close the hearing/speaking loop.
- [x] Enable all eight remapped servo channels at calibrated center under the initial 25 percent range/100 ms minimum-frame profile.
- [ ] Verify the GPIO47/48 signals and all eight physical joints through H2/H3 before increasing range.
- [x] Enable battery monitoring without making the owner-enabled initial motion profile depend on H9 completion; H9 remains required to validate voltage accuracy and cutoff behavior.
- [ ] Verify the centered startup, normal walking, standing, emote, and stop/detach behavior through Sections I and J before increasing the range.

## Stop conditions

Stop power or motion immediately if any of these occur:

- Reversed polarity, an unexpected short, or 5 V present on a GPIO
- A rail outside any connected component's documented operating limits
- Unexpected current, repeated brownout/reset, unstable output, or loss of communications
- Hot wiring, connector, buck converter, regulator, battery, or servo
- Servo chatter, a wrong joint/direction, mechanical binding, or movement outside configured limits
- Camera or peripheral activity causing power instability
- Persistent speaker output, unexpected popping, amplifier/speaker heating, severe clipping, or microphone feedback that defeats the configured gate
- Failure of a stop command or any safety gate

Do not continue by increasing a current limit or bypassing a firmware guard until the cause is identified.

## Results record

| Section/step | Pass/fail | Measured value or observation | Evidence path | Date/operator |
| --- | --- | --- | --- | --- |
| Firmware portable core | Pass | 11/11 tests | `build/acceptance/core` (regenerable; not hardware evidence) | 2026-07-15 / Codex |
| A-series software acceptance | Pass | A1-A30, 30/30 | `build/acceptance/a-series.json` (regenerable; not hardware evidence) | 2026-07-21 / Codex |
| Firmware cross-build | Pass | Image `0x119c20`; battery monitor enabled; OTA slot 63% free; DIRAM 67.55% | `Slave/firmware/esp32s3/build` (regenerable) | 2026-07-15 / Codex |
| Board-only servo remap build | Pass | Safe motion-disabled image `0x14bd40`; OTA slot 57% free; DIRAM 75.36%; A1-A30 30/30 | `Slave/firmware/esp32s3/build`, `build/acceptance/a-series.json` | 2026-07-21 / Codex |
| Full-feature board-only boot | Pass within connected hardware | Image `0x14fc70`; all eight MCPWM channels enabled at center; OV3660 and 8 MB PSRAM ready; LittleFS, audio, Wi-Fi, SD service, telemetry, and provisioning started; missing OLED restored UART; GPIO3 measured 0.000 V and entered startup-disconnected state at 12.488 s, then remained awake through 27.488 s; application flash digest matched; A1-A30 30/30 | `Slave/firmware/esp32s3/build`, live CH343 boot log, `build/acceptance/a-series.json` | 2026-07-21 / Codex |
| Stable-key provisioning image | Pass within connected hardware; portal submission pending | Image `0x14f7c0`; the first two portal guards falsely rejected the owner's legitimate setup client and are superseded by this setup-interface-bound build; application digest readback matched; bootloader, partition table, and LittleFS were already verified; 8 MB PSRAM test and all eight MCPWM channels passed; `Ainekio-Setup` observed at full signal; physical gateway launcher smoke-tested; 11/11 portable C tests and A1-A30 30/30 | `Slave/firmware/esp32s3/build`, live CH343 boot log, `build/acceptance/a-series.json` | 2026-07-21 / Codex |
| H1-H15 physical evidence | Partial | Controller USB-only boot evidence recorded; assembled power, peripherals, physical motion, and soak tests remain open | Add photos/logs/measurements as assembly proceeds | 2026-07-21 / owner pending |

## Completion

Physical bring-up is complete only when Foundation 0 and Sections A-K have recorded evidence, all stop conditions are resolved, and the owner has accepted the installed hardware values and firmware safety gates. Passing physical I2S or camera examples alone is not completion; the generic MetaHuman observation and speech-delivery contracts must also pass without adding Ainekio-specific code to MetaHuman OS.
