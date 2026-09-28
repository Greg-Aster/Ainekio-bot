# Body Control Integration

Started: 2026-09-28

Updated: 2026-09-28 — complete-system audit, recommended settings and ROS 2 role

Status: Living research and decision record

## Purpose and current direction

Record how ROS 2 can supplement Ainekio and MetaHuman OS, compare the two ways
to connect the ESP32-P4 body controller to Q6A, and preserve the findings and
implementation targets for later work.

**Current recommendation: native USB from P4 to onboard Q6A, then Wi-Fi from
Q6A to the remote desktop.** The owner requested this comparison with power
excluded. The reasons are body-link media capacity, removal of radio contention
on that link, and keeping Q6A wireless resources available for the desktop.
The cost is implementing and validating USB transport; Wi-Fi already has an
Ainekio implementation. No measured CPU/RAM saving or command-latency bound is
assigned to USB. This is a recommended build direction, not a completed migration.

**ROS 2 is an optional Q6A integration layer.** Preserve the existing gateway,
body controller and MetaHuman responsibilities. Start with telemetry and tools;
keep the local motion/IMU feedback loop on P4. Details and sources are below.

**Use the [complete system budget](v2-12servo/RESOURCE_BUDGET.md) for design
decisions.** Native USB HS provides a higher-capacity interface and removes radio
contention on the body link; offboard Q6A/Wi-Fi removes carried compute power/mass
and frees a dedicated 3 A servo branch. Those are distinct benefits. Neither
transport is qualified for maximum concurrent media and loaded motion.

The [2026-09-28 audit](v2-12servo/BUDGET_AUDIT_EVIDENCE.md) covers P4 firmware,
gateway and MetaHuman speech paths, manufacturer specifications, Q6A interface
capabilities and a new offline Kokoro timing/memory measurement. It also records
why chip typical-current figures cannot form a guaranteed whole-robot total.

The owner reports Q6A operation from 5 V / 3 A and plans a headless workload
without USB peripherals, monitor, or fan. Do not treat Radxa's recommended supply
rating as actual consumption or use it alone to select onboard versus offboard
placement. The latest transport recommendation above excludes power at the
owner's request. The electrical research below remains available for the later
physical design; it does not determine that transport recommendation.

This is a planning document. It does not amend the system specification, record
a completed transport migration, or authorize firmware flashing or body motion.
Existing implementation and hardware boundaries remain documented in the
[V2 firmware design](v2-12servo/FIRMWARE_DESIGN.md) and
[P4 firmware README](../Slave/firmware/esp32p4-wifi6/README.md).

## Intended responsibility split

| Device | Intended responsibility |
| --- | --- |
| ESP32-P4 | Execute the existing gait and servo control; acquire the planned LSM6DS3 IMU; own local movement supervision and future fast posture correction. |
| Onboard Q6A | Host the existing Ainekio gateway and selected MetaHuman coordination; run local speech recognition, TTS, vision, and lightweight processing. |
| Remote desktop | Provide heavyweight LLM inference and other explicitly assigned expensive processing. |

The Q6A deployment split is still design work. The existing gateway remains the
single body-command authority. Processing services do not acquire an independent
movement channel. The LSM6DS3 has been received; its installation and integration
are planned, not verified. Whether ROS is used for sensors or diagnostics is a
separate decision from wired versus wireless transport.

## Where ROS 2 fits

ROS 2 provides communicating nodes and reusable tooling. It is not a single
robot application with an on/off GUI. Nodes exchange topics, services and
actions; RViz is a separate visualization application. Installing ROS 2 does
not connect Ainekio automatically. [ROS 2 Jazzy node concepts](https://github.com/ros2/ros2_documentation/blob/jazzy/source/Concepts/Basic/About-Nodes.rst).

**Recommendation: supplement the existing system with a Q6A adapter when the
following tools are needed.** No required feature in the audited design was
identified as depending on ROS 2. The benefit is reuse of its interfaces and
tools; adopting it does not require replacing MetaHuman or the P4 gait code.

| Use | Proposed integration | Boundary |
| --- | --- | --- |
| Sensor and robot visualization | Publish camera data, timestamped IMU samples and available body state through a Q6A ROS adapter; inspect them in RViz | Robot pose visualization needs a model and transforms; commanded joint positions must remain distinguishable from measured positions |
| Recording and replay | Use rosbag2 for selected telemetry topics during diagnosis | Recording adds disk/network load; replay of recorded sensor topics is not evidence of live physical response |
| Future perception/planning packages | Exchange observations and bounded action requests through the existing gateway interface | The gateway remains the body-command authority; no second connection writes servo targets |
| Robot status | Expose the existing status projection to ROS consumers, including sample age and service/link health | ROS displays consume status; the local P4 output supervisor retains its existing responsibility |
| Fast balance correction | P4 acquires IMU data and applies corrections inside the existing motion/output owner | A ROS message round trip and desktop/LLM response are outside the local correction loop |

[RViz capabilities](https://github.com/ros2/ros2_documentation/blob/jazzy/source/Tutorials/Intermediate/RViz/RViz-User-Guide/RViz-User-Guide.rst)
include images, robot models and coordinate transforms.
[rosbag2 recording/replay](https://github.com/ros2/ros2_documentation/blob/jazzy/source/Tutorials/Beginner-CLI-Tools/Recording-And-Playing-Back-Data/Recording-And-Playing-Back-Data.rst)
operates on ROS topics. Both require the relevant data to be published first.
Run visualization on the desktop when desired; Q6A can remain headless.

Add the adapter first as a telemetry consumer. Extend it to action requests only
through Ainekio's existing admission, cancellation and result handling. Keep
MetaHuman responsible for cognition/personality and high-level intent, and the
embodied runtime responsible for perception, state estimation and skill execution.
ROS is not selected as a replacement controller in this recommendation.

Installed ROS package size is not its runtime RAM cost. Charge each selected
node, message copy, history queue and recorder to the Q6A budget. Keep camera
queues bounded and consume fresh frames. The audit identified no deployed ROS
robot graph, balance controller or selected YOLO pipeline; these remain
implementation work. See the [host budget](v2-12servo/RESOURCE_BUDGET.md#9-q6a-metahuman-and-desktop-budget).

## Recommended operating targets

These are the proposed final build settings from the audit discussion, not
settings already enabled or proof of simultaneous full-load operation. The
[resource budget](v2-12servo/RESOURCE_BUDGET.md#11-operating-targets-and-adjustment-rules)
owns the detailed arithmetic and alternative profiles.

| Function | Target | Implementation consequence |
| --- | --- | --- |
| Body transport | Native USB HS, P4 device to Q6A host; Q6A Wi-Fi to desktop | Use the separate P1 native interface; USB class and host adapter remain to be implemented |
| Camera | 1920 × 1080 at 30 fps, RGB565 capture, hardware JPEG/YUV420, initially quality 75 | Change current capture/output limits; preserve image quality while budgeting actual encoded byte sizes |
| Physical audio | 24 kHz, 16-bit mono duplex | Shared I2S/codec clock; resize and relocate buffers where required |
| Speaker transport | 24 kHz, 16-bit mono | Preserve Kokoro's native rate across MetaHuman, gateway and firmware |
| Mic for wake/STT and transport | Resample physical capture to 16 kHz, 16-bit mono | Account separately for resampling and physical-rate input buffers |
| IMU | Initial 208 Hz local acquisition | Integrate driver and attitude/controller code; sampling rate alone does not establish fall recovery |
| Servo targets/PWM | Retain 50 Hz | Loaded gait speed remains a separate mechanical qualification |
| LCD | Native pixel resolution; 30 fps target using partial updates | Identify the purchased panel and supported SPI clock before finalizing its driver/pin map |
| Vision inference | Consume the newest frame at the selected model's measured rate | Do not accumulate old frames or equate camera FPS with detector FPS |

H.264 is a later 1080p30 hardware option if streaming requirements justify the
encoder/protocol/decoder changes. The audited firmware disables it, and its
buffer budget must be calculated separately from the current JPEG path.

## Findings that affect the build

| Audit result | Design consequence |
| --- | --- |
| OV5647 supports 5 MP, but the P4 ISP used by the current path is specified to 1920 × 1080 | Use 1080p as the main processed-video target; full 5 MP requires a different capture/processing path |
| Three full 5 MP RGB888 frames require 43.249 MiB, exceeding 32 MiB PSRAM | Reducing copies and selecting formats matters; no blanket claim that every maximum setting fits |
| 256 KiB JPEGs at 30 fps require 62.915 Mbit/s before audio, above the matching 53.4 Mbit/s Hosted TX reference | Native USB offers meaningful capacity for the selected media direction; neither figure proves actual application throughput |
| P4 internal RAM, DMA-capable allocations and PSRAM have distinct constraints | PSRAM free space does not cure internal allocation failures or enlarged microphone stack arrays |
| The link loop can wait 20 ms, then send at most one microphone packet and one JPEG; authenticated send failure disables PCA output | Address media/control scheduling and failure handling within existing owners; changing the cable alone does not repair this behavior |
| Q6A Kokoro generated a five-second phrase in 15.068–15.904 seconds, with 1,537.797 MiB peak process RSS | Speech synthesis is an independent response-time bottleneck; neither ROS nor USB removes it |
| The inspected P4 firmware has no IMU feedback controller | Implement local posture correction through the current gait/output owner; installing the sensor or ROS does not implement balance |

Sources, conditions and exclusions are in the
[complete budget](v2-12servo/RESOURCE_BUDGET.md) and
[audit evidence](v2-12servo/BUDGET_AUDIT_EVIDENCE.md). Whole-robot concurrent
processing and loaded motion remain unqualified; the earlier two-unloaded-servo
timing record is not a full-system result.

## Choice 1: Wired native USB

```text
LSM6DS3 -> P4 <--- native USB ---> Q6A <--- Wi-Fi/router ---> desktop
```

Use the Q6A as USB host and the P4 as USB device. Keep the existing command
admission, authentication, command identity, cancellation, and result handling
behind the transport boundary.

**Advantages**

- Avoids wireless contention, interference, retries, and radio channel switching
  on the body-to-Q6A path.
- Leaves Q6A Wi-Fi resources available for the remote desktop.
- Offers greater potential capacity for camera/audio traffic and more
  predictable delivery timing.
- Keeps local communication independent of the external wireless network.

**Costs and unfinished work**

- Native USB transport is not implemented in the inspected Ainekio firmware.
- Select a USB device class and host integration approach; preserve one gateway
  and one command owner. This document does not select USB networking versus
  another USB protocol.
- The P4 board's normal USB-C connector is the CH343P programming/debug serial
  path. Native high-speed USB is exposed separately on the four-pin P1 connector.
- Resolve VBUS/power ownership before connecting independently powered boards:
  the existing hardware notes say P1's 5 V pin joins the P4 power rail.
- Provide suitable internal cabling and strain relief. Confirm sustained media
  delivery and reconnect behavior after implementation.

USB still incurs host scheduling, firmware, and buffering delays. It does not
make Linux or the complete robot application hard real-time. The existing Wi-Fi
transport can remain available during development, without introducing automatic
controller failover or two simultaneous command authorities.

Hardware references: [Waveshare board documentation](https://docs.waveshare.com/ESP32-P4-WIFI6)
and [Q6A USB ports](https://docs.radxa.com/en/dragon/q6a/hardware-use/usb).

## Choice 2: Direct Wi-Fi to a Q6A hotspot

```text
LSM6DS3 -> P4/C6 <-- private 2.4 GHz hotspot --> Q6A
                                                |
                                         upstream Wi-Fi
                                                |
                                           router/desktop
```

The Q6A provides a private hotspot for the P4 while its client interface connects
to the upstream network. Body traffic terminates at the gateway on the Q6A;
it does not need to traverse the home router. The Q6A makes separate requests
to the desktop. NAT/internet sharing is only needed if the P4 itself needs access
beyond its local Q6A connection.

**Evidence for feasibility, checked 2026-09-28**

- Waveshare uses an ESP32-C6 coprocessor linked to the P4 over SDIO. The C6 is
  a 2.4 GHz device, so the private hotspot must support that band.
- This Q6A identified its wireless device as AIC8800D80, USB ID `a69c:8d81`.
- On kernel `6.18.2-3-qcom`, `iw phy` reported a valid combination containing
  one managed/client interface and one AP interface, with up to three channel
  contexts. NetworkManager also reported AP support.
- The AIC8800D80 datasheet explicitly supports concurrent station, AP, and
  Wi-Fi Direct modes. These findings establish advertised capability; concurrent
  operation was not configured or exercised during this research.

**Advantages**

- Reuses the existing Wi-Fi/WebSocket transport.
- Avoids an additional internal data cable and USB transport development.
- Supports placing the Q6A offboard, reducing onboard weight, heat, and power
  demand, while accepting dependence on the wireless link for Q6A functions.

**Limitations and configuration work**

- Hotspot and upstream connections share wireless resources. Multichannel
  capability does not mean two independent radios or penalty-free simultaneous
  2.4/5 GHz operation.
- Interference, channel switching, retries, power saving, and software queues
  can increase delay even when the boards are close together.
- Configure separate AP/client interfaces, addressing, authentication, and
  startup/reconnect behavior. Do not assume a desktop hotspot toggle preserves
  the existing upstream connection.
- Establish power-saving behavior explicitly. Espressif documents receive
  delays up to the DTIM/listen interval with modem sleep; `WIFI_PS_NONE`
  minimizes those delays at increased power consumption. No explicit override
  was found in the Ainekio networking source inspected; live behavior is unverified.
- For responsiveness, bound media queues and avoid accumulating old camera
  frames. Local image processing can reduce how much data must travel upstream.

Sources: [ESP32-C6 datasheet](https://documentation.espressif.com/esp32-c6_datasheet_en.html),
[AIC8800D80 datasheet hosted by Radxa](https://dl2.radxa.com/zero3/docs/hw/3w/AIC8800D80_DataSheet_v0.1.pdf),
and [Espressif Wi-Fi power-saving documentation](https://docs.espressif.com/projects/esp-idf/en/v5.5.2/esp32c6/api-guides/wifi.html#esp32-c6-wi-fi-power-saving-mode).

## Performance foundation

### Movement latency

The P4 executes gait updates locally; individual servo updates do not require
a Q6A round trip. Link delay affects new commands, changes, and feedback.
Future fast IMU-based posture correction should likewise remain local to the P4.
Camera-guided steering also depends on frame capture, transmission, inference,
and command processing, so network latency is only part of its response time.

A configured local Wi-Fi link is a reasonable engineering choice for semantic
movement commands and moderate media traffic. No source found guarantees
end-to-end latency for this exact Q6A/P4/application combination. Neither
"negligible latency" nor a specific worst-case timing bound is established.

No measured command-delivery bound exists for this hardware/application pair.
Retries, queues, and concurrent Q6A hotspot/client traffic add delay.
Minimum radio sleep and minimum latency are competing objectives:
Espressif documents receive delays up to the DTIM/listen interval with modem
sleep. For example, a configured 100 ms beacon period and DTIM of 3 imply a
300 ms DTIM cycle; these are illustrative settings, not this robot's settings.
`WIFI_PS_NONE` removes that sleep delay at increased power use, but does not
remove congestion or scheduling delays. No explicit power-saving override was
found in the inspected application network initialization.

### Wireless power cost

The [ESP32-C6 datasheet, table 5-7](https://documentation.espressif.com/esp32-c6_datasheet_en.html)
lists active receive current of 78–82 mA and transmit figures of 252–354 mA
at 3.3 V, depending on radio mode and transmit power. Calculated power is
approximately 0.26–0.27 W receiving and 0.83–1.17 W in those transmit conditions.
The table labels these peak figures; transmit characterization uses 100% duty
cycle and receive characterization has CPU idle/peripherals disabled.

These establish the scale of C6 consumption, not average P4-board power, the
increment relative to USB, or the whole link's consumption. Traffic duty cycle,
sleep settings, host processing, conversion losses, and Q6A Wi-Fi operation
remain relevant. A total Q6A-plus-P4 wireless power delta has not been measured.
Replacing an onboard cable with Wi-Fi does not itself establish a power saving;
moving Q6A offboard also moves its supply demand off the robot.

### Audio and image bandwidth

The inspected audio implementation uses 16 kHz, 16-bit mono PCM in 20 ms frames.
The camera sends JPEG frames and accepts a configured rate up to 15 frames/sec;
that configuration ceiling is not measured sustained performance.

| Payload | Calculated bandwidth before protocol overhead |
| --- | --- |
| Continuous microphone audio | 32 kB/s, or 0.256 Mbit/s |
| Continuous speaker audio | 32 kB/s, or 0.256 Mbit/s |
| Both simultaneously | 64 kB/s, or 0.512 Mbit/s |
| Example only: 50 kB JPEGs at 5 frames/sec | 250 kB/s, or 2 Mbit/s |
| Example only: 100 kB JPEGs at 15 frames/sec | 1.5 MB/s, or 12 Mbit/s |

JPEG sizes above are illustrations, not observations of this camera.
Espressif publishes 53.4 Mbit/s TCP transmit and 44 Mbit/s receive for its
ESP-Hosted four-bit SDIO setup using C6 in a shield box with 40 MHz Wi-Fi
bandwidth. This establishes useful capacity for the architecture, not a throughput
promise for Ainekio or concurrent Q6A hotspot/client operation.
[Published benchmark](https://components.espressif.com/components/espressif/esp_hosted/versions/2.12.8/readme?language=en).

### Processing and queues

The C6 handles wireless functions, while the P4 still handles its TCP/IP stack,
WebSocket traffic, buffers, and SDIO transfers. Commands and audio are expected
to have manageable overhead; continuous images add compression, copying, and
transport work. No CPU utilization percentage has been established.
[ESP-Hosted architecture](https://github.com/espressif/esp-hosted-mcu/blob/main/docs/getting-started-mcu.md).

The coprocessor does not eliminate P4 processing overhead. USB also requires
host/device processing; the relative CPU cost depends on the selected USB class
and implementation. There is no basis here for claiming either zero Wi-Fi
overhead or a quantified CPU saving from USB.

The inspected Ainekio implementation shares one WebSocket for control and media.
Its sending loop checks replies and audio before camera packets, but an image
send already underway can occupy the outbound path. Queue behavior remains
relevant with either transport. See [controller.c](../Slave/firmware/esp32p4-wifi6/main/controller.c)
and [media implementation](../Slave/firmware/esp32p4-wifi6/components/ainekio_p4_media/media.c).

## Falling and active walking

Research added 2026-09-28. Wi-Fi suitability for movement commands does not
establish suitability for the complete fast balance feedback loop.

The inspected V2 controller generates gait trajectories and modeled contact
timing. It does not currently use measured IMU attitude or ground-contact/force
feedback to correct a physical fall. See the [model description](../Slave/software/models/v2-12servo/README.md)
and [motion source](../Slave/software/models/v2-12servo/motion.c). The current
[validation record](../Slave/software/models/v2-12servo/CONTROLLER_VALIDATION.md)
does not qualify loaded balance. Older gait timing figures in the firmware
design history must not be treated as measurements of the current application.

Proposed responsibility split:

```text
Q6A -- native USB: direction, speed --> P4 gait + balance controller
                                            ^              |
                                            |              v
                                         wired IMU    PCA9685 / servos
                                            ^              |
                                            +-- body motion+
```

The LSM6DS3 supplies acceleration and angular-rate measurements. A controller
must estimate body attitude and rotation, then adjust the gait's leg targets
and, where feasible, step placement/timing. Those corrections should enter the
existing P4 motion/output owner, not create a second servo writer. Initial local
posture stabilization is a narrower task than dynamic push recovery. IMU data
alone do not establish which feet are supporting weight or actual joint angles.

Keep fast correction independent of wireless packet arrival. Wi-Fi may have
adequate typical latency, but no bound is established for this application's
round trip under contention and media load. If a future balance controller
requires Q6A computation, prefer a wired sensor/command path with an explicit
timing budget; USB and Linux also require scheduling and queue control. Required
rates and recoverable disturbances depend on the mechanism, actuator response,
contact/friction, and control design. No fall-catching performance is promised.

References: [ST LSM6DS3 datasheet, mirrored](https://pccomponents.com/datasheets/ST_MI-LSM6DS3TR.pdf)
and [MIT legged-robot control notes](https://underactuated.mit.edu/humanoids.html).
ROS can support integration, planning, and diagnostics, but installing it does
not supply a tuned balance controller for this robot.

## Power and weight: SHARGE Pouch

Research added 2026-09-28. The owner identified the battery as SHARGE Pouch and
confirmed the proposed load is all twelve MG90 servos plus the P4 on one 3 A
output, using staggered servo activity to reduce peaks.

### Published supply limits

The manufacturer's [Pouch manual](https://cdn.shopify.com/s/files/1/0611/2234/7259/files/Pouch_3_in_1.pdf?v=1735982667),
page 10, identifies power bank P065A, approximately 240 g and 36 Wh. It lists
5 V / 3 A and 12 V / 3 A among the individual-port output modes, but simultaneous
USB-C outputs are limited to **20 W + 20 W**. It does not enumerate the dual-port
voltage/current profiles. The [product page](https://sharge.com/products/pouch)
also lists 5 V / 6 A total and approximately 220 g; retain the owner's 240 g
figure for planning rather than replacing it with the conflicting web weight.

Radxa specifies **12 V input**, recommending a supply rated **2 A or above**
(24 W or more). This is supply capacity, not a measurement of continuous Q6A
consumption. The Pouch's listed single-port 12 V / 3 A mode meets that rating;
its dual-port 20 W allocation per port falls below that recommendation. This
comparison does not establish the actual power needed by the owner's headless
workload or prove that the proposed arrangement cannot run it. The owner reports
operation from 5 V / 3 A; that observation has not been independently measured
here. Do not assume the bank retains 12 V / 3 A when the second port is connected.
[Q6A power requirements](https://docs.radxa.com/en/dragon/q6a/hardware-use/power-header).

### Twelve servos on a shared 3 A branch

At 5 V, 3 A provides 15 W for the entire branch. Dividing 3 A among twelve
servos gives 250 mA each before reserving anything for the P4, radio, camera,
audio, or other peripherals. This is budget arithmetic, not a measured servo
current or a claim that every servo draws the same current.

Staggering movement starts can reduce coincident acceleration peaks. Staggering
PCA9685 control pulses does not guarantee non-overlapping motor current:
supporting joints still exert torque while another joint moves, and motor drive
can extend beyond the command pulse. Scheduling alone does not enforce a 3 A
ceiling. The exact servos' loaded and peak currents remain unqualified; there is
no established basis to promise twelve-servo walking plus P4 within this limit.
[Pololu's measured servo signal/current examples](https://www.pololu.com/blog/17/servo-control-interface-in-detail).

### Distribution and communication

- Feed servo power directly to PCA9685 **V+** through a suitably rated supply
  path. Keep its logic **VCC** at P4 3.3 V and retain a common ground. If sharing
  one 5 V source, split its feed upstream of the P4; this avoids routing servo
  current through the P4 but does not increase the source's 3 A allowance.
- The [Waveshare schematic](https://files.waveshare.com/wiki/ESP32-P4-WIFI6/ESP32-P4-WIFI6-datasheet.pdf),
  sheet 1, shows USB0_5V feeding VCC_5V through Q2 (AO3401). Even an upstream
  VBUS header connection uses board copper and connectors. No verified 2–3 A
  servo-feed rating for the header was found. An absent fuse does not establish
  that rating. Follow the existing [servo power wiring guidance](v2-12servo/PCA9685_WIRING.md).
- Occupying P4 USB-C with power does not eliminate wired communication. Native
  USB uses the separate P1 connector; use a Q6A USB host port and a designed
  VBUS/power arrangement. P1 shares the P4 power rail, so do not simply join
  independently powered 5 V outputs. The USB class/firmware work remains pending.
- A header UART is another possible command link after verifying voltage levels,
  pin selection, and configuration. Native USB remains the preferred wired
  candidate for combined body commands, sound, and images.

**Placement implication:** keeping Q6A offboard removes its weight, any cooling,
and supply demand from the robot and allows separate Pouch outputs for P4 and
servos. That gives the servos their own 3 A allocation but does not establish
that 3 A is sufficient. Actual Q6A consumption under the intended workload,
payload, and communication requirements should determine placement; the adapter
recommendation alone does not decide it.

## Complete robot resource budget

The [robot power, pins, memory and processing budget](v2-12servo/RESOURCE_BUDGET.md)
audits the actual V2 firmware, its recorded build/bench results, and the
Waveshare board schematic. It includes twelve servos, LSM6DS3, OV5647, onboard
audio, C6 Wi-Fi, microSD, and the owner's generic 1.9-inch LCD without touch.
It also covers Q6A services and storage, the remote-desktop ownership boundary,
measured local Kokoro latency/RSS, and wired versus wireless media profiles.

The board has 20 unassigned header GPIOs after existing allocations and the
USB FS reservation. Sharing the media I2C bus for the IMU, adding one interrupt,
and using a conditional six-signal SPI LCD would leave 13. The exact LCD
interface remains unidentified, so this is a proposed allocation, not a final
wiring map. The latest recorded app occupies 2.26 MiB of an 8 MiB app slot.

Prior motion measurements show a maximum 2.897 ms calculation/output frame
within the 20 ms cadence, but did not include the complete camera/wake/display
workload. The resource document separates recorded costs from published
component limits and calculated buffer/transfer requirements. Total concurrent CPU use and whole-board
power remain unmeasured; chip datasheets do not establish the complete robot's
current draw.

**Correction:** the previously assigned aggregate CPU, RAM and electronics-power
allowances have been withdrawn. They were not derived from measured use or
component specifications and do not establish spare capacity. The budget now
uses repository evidence, manufacturer specifications/benchmarks and explicit
buffer/transfer arithmetic. The LCD resolution/interface remains unidentified.

The updated research covers OV5647 1080p30/720p60 capability, ES8311 audio up to
96 kHz/24-bit mono, the P4 encoder's format-dependent benchmark, version-matched
Hosted TCP throughput, and LSM6DS3 output/interface limits. It identifies actual
constraints in the present firmware: image copies, shared blocking media sends
whose failure disables PWM, and audio arrays that cannot simply be enlarged
inside the current microphone stack. Full concurrent operation remains
unqualified; the resource document records the specific evidence and sources.

## Questions to revisit

1. Select the native USB class and host integration while preserving the existing
   gateway/protocol ownership; specify connectors, VBUS handling and reconnects.
2. Address shared media/control scheduling and failure handling before increasing
   stream rates. Define response deadlines and acceptable frame age separately
   from the local 20 ms servo cadence.
3. Implement the recommended media formats across firmware, gateway and MetaHuman;
   retain the budget's buffer ownership, stack and DMA constraints.
4. Integrate LSM6DS3 acquisition and local correction into the current P4 owners;
   identify the LCD before implementing its native-resolution display path.
5. Resolve measured speech latency, install the selected STT service, choose a
   vision runtime and measure their concurrent Q6A demand.
6. Add a ROS telemetry adapter if visualization/recording is selected; keep a
   single command authority and budget the chosen nodes and queues.
7. If wireless body transport is later selected, establish its AP/client channel
   strategy, byte-rate limit and power-saving policy; driver capability is not
   demonstrated concurrent throughput.
8. Revisit placement, mass, electrical distribution and loaded/peak current as a
   separate physical-design decision. Power was excluded only from the latest
   wired-versus-wireless recommendation.

Research should establish the design and expected behavior before physical
scenario testing. Later validation should confirm an agreed design, rather than
serve as a substitute for selecting one.

## Research history

| Date | Finding or decision | Evidence level |
| --- | --- | --- |
| 2026-09-28 | Native USB recommended for onboard P4/Q6A; Q6A Wi-Fi reserved for upstream desktop communication. | Engineering recommendation; implementation pending. |
| 2026-09-28 | Q6A hotspot plus Wi-Fi client is advertised by the installed driver and chipset documentation. | Read-only capability inspection; no networking changes or concurrency trial. |
| 2026-09-28 | Audio payload rates calculated from code; media transport and queue owners inspected. | Source evidence and arithmetic; no live throughput or latency measurement. |
| 2026-09-28 | Pouch dual-port rating is 20 W + 20 W, below Radxa's recommended 24 W supply capacity for Q6A on either port. Twelve servos plus P4 on 3 A remain unqualified; staggering does not guarantee the limit. | Manufacturer specifications, schematic inspection, and budget arithmetic; no physical power or motion tests. |
| 2026-09-28 | Owner clarified headless Q6A operation from 5 V / 3 A and priority of comparing wireless costs. Removed placement inference based solely on recommended adapter capacity. Added C6 active power scale and latency/CPU qualifications. | Owner report, manufacturer radio characteristics, source inspection, and engineering assessment; no complete-link power or latency measurement. |
| 2026-09-28 | Added a firmware-backed P4 resource budget, including generic 1.9-inch LCD without touch. GPIO and flash capacity support further integration; complete concurrent CPU and power totals remain open. | Current source, prior build/bench records, schematic and revision-matched datasheets; conditional display arithmetic and explicitly proposed balance allowances. |
| 2026-09-28 | Withdrew assistant-assigned CPU/RAM/power totals and low-quality workload assumptions after owner correction. Replaced them with repository measurements, identified-part specifications and transparent calculations at higher hardware capabilities. | Published component benchmarks retain their conditions; unidentified parts and unmeasured application costs are explicitly unresolved. |
| 2026-09-28 | Completed the whole-system budget and recorded native USB P4→Q6A / Wi-Fi Q6A→desktop as the recommendation with power excluded from the comparison. Added final media/sensor targets and concrete memory, ISP, transport, scheduling and speech constraints. | Engineering recommendation grounded in the linked audit; implementation and concurrent qualification pending. |
| 2026-09-28 | Clarified ROS 2 as an optional Q6A adapter for telemetry, RViz, recording and future package integration, preserving MetaHuman cognition, gateway command authority and P4 local feedback. | ROS Jazzy documentation and existing ownership boundaries; no robot ROS graph deployed by this document update. |

When revisiting this document, date new findings and label manufacturer claims,
source inspection, calculations, and measured behavior separately. Preserve the
reason for any change to the recommendation.
