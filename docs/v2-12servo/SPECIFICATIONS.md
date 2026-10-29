# V2 robot specifications

Scope: `v2-12servo`, the twelve-servo ESP32-P4 Ainekio body. Start with the shared
[robot design core](../../../metahuman/docs/robot/ROBOT_BIBLE.md) for companion
intent. [V1 specifications](../v1-8servo/SPECIFICATIONS.md) describe the separate
eight-servo body. **V2 is the active development target; V1 work is paused.**

Reconciled **2026-10-26** against component records, firmware and the live Blender
assembly. The owner confirms **650 g assembled mass**, that the V2 physical robot
matches the Blender design, and that **SHARGE is no longer used**. Owner reports,
CAD dimensions, electrical ratings and measured performance retain their sources;
an older budget or an empty export field does not override newer evidence.

## Hardware

| Component | V2 specification | Basis and remaining uncertainty |
| --- | --- | --- |
| Body | Four legs, three joints per leg: shoulder, carrier, crank | Twelve modeled joints; model and per-device calibration are distinct |
| Controller | Waveshare ESP32-P4-WIFI6; recorded P4 revision 1.3 | [Hardware record](README.md) and [P4 firmware](../../Slave/firmware/esp32p4-wifi6/README.md) |
| Memory | Recorded 32 MiB flash and 32 MiB PSRAM | Board evidence; separate memory pools and actual free memory are covered by the [resource budget](RESOURCE_BUDGET.md) |
| Wireless | Onboard ESP32-C6 radio coprocessor, connected to P4 through SDIO | Firmware owns C6/SDIO composition; body networking is separate from host-to-host networking |
| Servo driver | PCA9685 breakout; sixteen outputs, twelve used | Owner-selected HUAREW board in the hardware record; source uses address `0x40`, separate I2C1 and OE |
| Servos | Twelve Miuzei MG90S, with added potentiometer-wiper feedback wires | [Servo record](FIRMWARE_DESIGN.md) identifies the owner-linked model; advertised 180° travel is distinct from per-device calibration |
| Joint feedback | HiLetgo CD74HC4067 analog multiplexer; P4 ADC acquisition | Named in the current CAD; [socket/feedback map](SERVO_SOCKET_MAP.md) records all twelve calibrated channels |
| IMU | Purple two-hole GY-LSM6DS3 breakout, 13 × 18 mm; shared I2C0 | [Installed wiring, axes and calibration](LSM6DS3_IMU.md); [board reference](../../Slave/hardware/v2-12servo/GY_LSM6DS3_Two_Hole_Reference_Model/README.txt) |
| Camera | OV5647 CSI module, 5 MP sensor | [Hardware record](README.md); [LCD/camera record](LCD_FACE.md) includes owner-confirmed operation; runtime capture sizes belong to P4 media |
| Audio | Onboard ES8311 codec/microphone, NS4150B amplifier; 20 × 30 × 6.66 mm speaker | CAD records the confirmed speaker envelope; [P4 speaker record](../../Slave/firmware/esp32p4-wifi6/README.md#speaker-output) includes owner-confirmed operation. Board speaker reference: 8 Ω / 2 W in the [audio budget](RESOURCE_BUDGET.md#2-equipment-and-execution-ownership) |
| Face display | XIITIA 1.9-inch ST7789 SPI LCD, ASIN B0DFWMC16W; 170 × 320 panel used in 320 × 170 landscape | [Display owner](LCD_FACE.md) and [dimensioned reference](../../Slave/hardware/v2-12servo/XIITIA_1p9_Display_Reference_Model/README.txt); PCB 29 × 62 mm, active area 22.695 × 42.72 mm |
| Storage | P4 internal flash/NVS and removable SD support | Installed card capacity and contents are device-specific |
| Power assembly | 2S battery pack, Mini560 buck converter, HiLetgo 2S USB-C charger | Current CAD names and dimensions below; [October 15 owner report](GAIT_RESEARCH_JOURNAL.md#2026-10-15--pca9685-staggering-audit-after-reported-supply-brownouts) records an 8.4 V battery and 5 A buck converter |
| Body Control host | Offboard Radxa Q6A is the selected deployment direction; another supported gateway host can serve the body | Q6A is not an extra servo controller or mandatory intermediary for every deployment |

Use [P4 resource ownership](../../Slave/firmware/esp32p4-wifi6/README.md#resource-ownership)
and the hardware records for board details. The [resource budget](RESOURCE_BUDGET.md)
contains dated capacity calculations. Its SHARGE power topology, battery mass and
runtime calculations are historical; they do not describe this V2 assembly.

## Geometry and dimensions

Mechanical design: [`Ainekio-Motion-Working.blend`](../../Slave/hardware/v2-12servo/Ainekio-Motion-Working.blend),
scene **Wireless**. The [checkpoint index](../../Slave/hardware/v2-12servo/CHECKPOINTS.md)
identifies the working project and recovery copies. Metric scale **0.001** means
**1 Blender unit = 1 mm**. The owner confirms the current design matches the robot.

| Quantity | Value | Basis |
| --- | --- | --- |
| Assembled mass | **650 g (0.650 kg)** | Owner report, 2026-10-26; supersedes the earlier 566 g research baseline |
| Overall posed CAD envelope, length × width × height | **245.85 × 182.79 × 109.06 mm** | Evaluated mesh vertices, `Wireless`, frame **168**, live unsaved state on 2026-10-26; includes the raised-leg pose, not a standard standing footprint or maximum motion envelope |
| Carrier / crank / pickup / connecting rod / lower leg | **35 / 20 / 28 / 38 / 55 mm** | Current scene's `Leg design` property and exported `linkage_revision.dimensions_mm` agree |
| Front-to-rear shoulder-axis spacing | **173.434 mm** | Live `REFINED` shoulder-frame origins agree with the geometry export |
| Left-to-right shoulder-axis spacing | **63.500 mm** | Same live shoulder-frame check |
| Shoulder datum Z | **80.962 mm** | CAD world-space shoulder origins; not chassis clearance |
| World axes | **+X forward, +Y left, +Z up** | Motion model body convention; left/right are the robot's own sides |
| Battery pack envelope | **73.6 × 46 × 22 mm** | CAD `REFERENCE \| Battery pack - 73.6 x 46 x 22 mm`; recorded as a measured envelope |
| Mini560 converter envelope | **30 × 18 × 5.6 mm** | CAD `REFERENCE \| Mini560 buck converter - rear` |
| HiLetgo 2S USB-C charger | **36.5 × 17.75 × 1.5 mm PCB; 6.8 mm modeled overall height** | CAD `Model accuracy` records owner-measured bare PCB dimensions |
| Speaker envelope | **20 × 30 × 6.66 mm** | CAD `REFERENCE \| Speaker - 20x30x6.66 mm`; its `Reference accuracy` records confirmed overall dimensions |
| Center of mass | **Not measured** | Total mass does not establish mass distribution; the export's `[0, 0, 65]` mm is explicitly provisional |

The posed envelope includes 375 evaluated assembly meshes: body/electronics,
shell, four leg collections, fitted carapace, installed boot parts and the
multiplexer. It excludes the training stand, tools, detached studies/spares,
offboard Q6A assembly and old battery references. Bounds are X −123.34…122.50,
Y −72.81…109.98, Z 6.09…115.14 mm. Frame, pose and object scope are part of the
measurement; record them when updating it. No scene, pose or saved CAD was changed.

The motion export is [`geometry.json`](../../Slave/software/models/v2-12servo/geometry.json),
ID `compact-35-20-28-38-55-visible-20261005`. Its `source_file` names the older
`ainekio-variable-gait-Recovery.blend`; its captured body bounds use frame 33 and
exclude the full posed outline. Its `mass_kg: null` is an unfilled export field,
not an unknown current robot mass. Linkage lengths and shoulder spacing were
cross-checked above; this does not assert a complete re-export of the latest shell
or calibration. [Motion-model provenance](../../Slave/software/models/v2-12servo/README.md)
remains with that owner. Imported CAD reference labels do not identify a different
installed electronics brand than the component records above.

## Joints, units and calibration

Source owners: [joint definitions](../../Slave/software/protocol/joints_v2.py),
[`model.json`](../../Slave/software/models/v2-12servo/model.json),
[`servo_profile.json`](../../Slave/software/models/v2-12servo/servo_profile.json)
and the [physical socket/feedback record](SERVO_SOCKET_MAP.md).

| Physical leg | Joint IDs: shoulder / carrier / crank | Recorded PCA sockets | Recorded feedback inputs | Legacy CAD name |
| --- | --- | --- | --- | --- |
| Rear left | 0 / 1 / 2 | 0 / 1 / 2 | C4 / C5 / C6 | FL |
| Rear right | 3 / 4 / 5 | 3 / 4 / 5 | C7 / C8 / C9 | FR |
| Front left | 6 / 7 / 8 | 6 / 7 / 8 | C10 / C11 / C12 | RL |
| Front right | 9 / 10 / 11 | 9 / 10 / 11 | C13 / C14 / C15 | RR |

The socket/input assignments were saved and read back during the October 17
loose-servo calibration. Body Control permits per-device remapping. `model.json`
still has several `pca_channel: null` entries and no device calibration; do not
derive a complete installed electrical map from that file or swap physical legs
to match legacy CAD names.

Geometry uses millimetres and radians. Model positions are signed centidegrees
from the recorded CAD neutral; they are not raw PWM microseconds. Home, geometric
zero, solved Stand, Sit and Rest are different poses. Electrical conversion and
feedback curves remain owned by the selected device's saved configuration.

The authoring servo profile records **300–3000 µs**, with provisional conversion
and `travel_measured: false`, `hardware_qualified: false`. These are not certified
physical travel limits. The feedback record's **500, 1650 and 2800 µs** calibration
points are unloaded signal/position observations, not proof that every assembled
joint combination is usable. See [servo assembly](../../Slave/software/models/v2-12servo/SERVO_ASSEMBLY.md).

## Electrical connections and power

| Interface | Source/recorded assignment |
| --- | --- |
| PCA9685 logic | SDA GPIO2, SCL GPIO3, OE GPIO4; address `0x40`, I2C1; logic VCC 3.3 V |
| Servo power | PCA V+ uses the separate 5 V servo supply; common ground with P4 and logic; OE disables PWM signals, not the servo power rail |
| LCD | SPI clock20, MOSI21, CS22, DC23, reset26; VCC/BLK on 3.3 V in the assembly record |
| IMU | Shared I2C0 SDA7/SCL8, address `0x6A`; recorded CS-high and SA0-low wiring |
| Feedback multiplexer | Select GPIO27/28/29/30; firmware reads ADC2 channel0; connector wiring is in the [multiplexer guide](Multiplexer_Wiring.png) |
| P4/C6 radio link | SDIO CLK18, CMD19, D0–D3 GPIO14–17; reset54 and boot6 reserved |
| USB | Board Type-C debug path uses CH343P; native USB HS is reserved, not an implemented replacement robot-command transport |

Pin assignments come from [board.h](../../Slave/firmware/esp32p4-wifi6/main/board.h),
[feedback source](../../Slave/firmware/esp32p4-wifi6/main/servo_feedback.c) and the
[assembly connection table](ASSEMBLY_REFERENCE.md#connection-table). Header-row
labels and GPIO numbers are different numbering systems. Follow those owners for
connector orientation and complete bus reservations.

The current power assembly is the **2S battery / Mini560 buck / HiLetgo 2S USB-C
charger** shown in the working CAD. The October 15 owner report records **8.4 V**
for the battery and a **5 A** buck rating. The assembly wiring above specifies
the separate **5 V servo rail**, common ground and P4-derived **3.3 V logic**.
The buck's rating is not measured simultaneous-load capacity; the report does not
establish the loaded output voltage or a current waveform.

The owner confirmed on 2026-10-26 that SHARGE is no longer used. The older
**36 Wh**, **240 g**,
dual-USB branch and runtime calculations in the [September budget](RESOURCE_BUDGET.md#3-electrical-budget)
must not be transferred to this pack. The selected offboard Q6A has its own power.
Current pack capacity, center of mass, loaded current/voltage and thermal/runtime
results require their own evidence; no replacement ratings are inferred from V1.

## Body Control and remote MetaHuman connections

```text
P4 <-> onboard C6 -- Wi-Fi / authenticated /robot WebSocket --> Body Control host
Remote or same-host MetaHuman -- Environment Bridge /environment --> Body Control
```

The robot initiates its connection to the selected gateway. On the documented
Q6A arrangement it can use the host's robot Wi-Fi hotspot; the host's upstream
connection to remote MetaHuman is a separate link. Both protocol sessions carry
commands, observations and correlated results in both directions.

| Boundary | Contract / default |
| --- | --- |
| Body ↔ gateway | Gateway port `8790`, authenticated `/robot`; selected body advertises its model, peripherals and capabilities |
| Operator ↔ Body Control | Dashboard defaults to `127.0.0.1:8791` on the gateway host |
| Same-host MetaHuman ↔ gateway | `ws://127.0.0.1:8790/environment`, authenticated separately from the robot session |
| Remote MetaHuman ↔ gateway | MetaHuman's existing SSH or Cloudflare TCP forwarder terminates at gateway loopback; SSH may use the configured WireGuard network; remote peers do not bypass the `/environment` loopback contract |
| Remote brain/model placement | Configured MetaHuman hosts and provider owners; remote inference, a public web portal and the body bridge are different connections |

The [gateway reference](../../Master/gateway/README.md#physical-robot-gateway-operation),
MetaHuman [connection owner](../../../metahuman/brain/agents/environment-bridge/connections.ts)
and [forwarder](../../../metahuman/brain/agents/environment-bridge/forwarder.ts)
own these details. Current source uses one Environment Bridge with configured
local/remote endpoints and body selection; the older startup instruction to switch
separate Local/Remote agents is superseded. Private addresses, pairing secrets,
SSH credentials and saved calibration stay with their existing configuration owners.

P4 owns physical execution and peripheral control; Body Control owns the body
connection, semantic translation and manual interface; MetaHuman owns high-level
cognition and durable work. Q6A and a remote host need not both be present for
manual Body Control. Gateway switching is not durable goal migration or proof
that a two-installation MetaHuman deployment is complete. The
[distributed foundation](../DISTRIBUTED_ROBOT_FOUNDATION.md) distinguishes that
design work from implemented connection switching.

## Maintaining this specification

Update affected hardware, geometry and integration entries with their source when
those facts change. Keep live firmware identities, model assignments, transient
settings, experiments and qualification narratives in their existing owners and
dated evidence. Do not infer installed readiness from source support, a successful
build or a historical receipt. The [documentation authority](../README.md) retains
its normative-contract process; this reference adds no runtime restrictions or
changes to motion, prompts, calibration or connection behavior.
