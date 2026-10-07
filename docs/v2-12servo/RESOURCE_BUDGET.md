# Final robot resource budget — Ainekio / MetaHuman OS

Audited 2026-09-28. **Design reference, not completed-robot qualification.**
Camera source update 2026-10-06: adaptive still capture also supports native
1280×960 and cropped 1920×1080. The 1080p path uses two RGB565 captures, the
existing 1024×768 resize scratch, and one 256 KiB JPEG buffer: **10,129,408 B /
9.660 MiB**, before compressed copies, wake, ISP/driver and other allocations.
Historical throughput/combined-load results below do not qualify this mode.
Scope: twelve servos, P4 / C6, camera, audio, LCD, IMU, storage, Q6A, gateway,
MetaHuman services and remote LLM boundary. This supersedes the earlier partial
budgets and withdrawn invented CPU / RAM / power allowances.

Later owner decision: wireless body with offboard Q6A, remote/manual takeover and
a shared status/routing contract. See the
[distributed foundation](../DISTRIBUTED_ROBOT_FOUNDATION.md). This changes the
selected deployment direction, not the component limits or recorded arithmetic.

[Audit evidence and sources](BUDGET_AUDIT_EVIDENCE.md).
Reproduce arithmetic from the repo root:
`python3 docs/v2-12servo/budget_math.py`.
KiB = 1,024 B; MiB = 1,048,576 B; network Mbit/s = 1,000,000 bit/s.

Quick reference: [power](#3-electrical-budget) ·
[P4 memory](#4-p4-memory-separate-pools-and-owned-allocations) ·
[camera](#5-camera-throughput-and-storage) ·
[audio](#6-audio-quality-memory-and-delay) ·
[pins and sensors](#7-imu-lcd-pins-and-buses) ·
[motion](#8-cpu-deadlines-walking-speed-and-servo-lag) ·
[Q6A](#9-q6a-metahuman-and-desktop-budget) ·
[wired/Wi-Fi](#10-wired-versus-wireless) ·
[settings](#11-operating-targets-and-adjustment-rules).

## 1. Decisions at a glance

| Question | Audited answer |
| --- | --- |
| Meaningful benefit from a cable? | **Yes: removes radio contention on the body link and provides a higher-capacity interface.** Native USB HS is the wired candidate. It does not fix motor current, speech synthesis or application scheduling. |
| Meaningful benefit from offboard Q6A / Wi-Fi? | **Yes: removes Q6A battery demand / mass and frees a Pouch port for a dedicated 3 A servo branch.** Q6A still consumes power externally. |
| Q6A hotspot and upstream Wi-Fi together? | **Installed driver advertises AP + managed concurrently**, with up to three channels. Verified by read-only host query; simultaneous throughput is not a measured budget entry. |
| Everything at maximum settings? | **No.** Three full-sensor RGB888 frames exceed P4 PSRAM; the current ISP is specified only to 1920 × 1080. Large-frame 1080p 30 MJPEG exceeds the published Hosted TCP reference. Higher PCM settings exceed existing stack / format limits without changes. |
| Is the complete robot proven under budget? | **No complete power, internal-RAM or concurrent deadline qualification exists.** Required inputs and exact pass conditions are in §12. This is not proof that the design is impossible. |
| Defensible final media target? | **1080p 30 RGB565 → hardware JPEG / YUV420**, supported by sensor / encoder specifications; admit transport by actual encoded byte rate. Preserve Kokoro's native **24 kHz / 16-bit mono** speech. Higher-rate audio alternatives are costed below. |
| What corrects a fall? | A local IMU-feedback controller and mechanically capable actuators. That controller is absent from inspected P4 firmware. The IMU, ROS and network transport do not implement it by themselves. |

**Q6A placement and transport are separate decisions.** An onboard Q6A using
Wi-Fi still consumes onboard power. A cable does not require Q6A power to pass
through the P4.

## 2. Equipment and execution ownership

| Equipment / service | Quantity | Final role / resource owner | Established identity or capacity |
| --- | ---: | --- | --- |
| SHARGE Pouch | 1 | Robot electrical source | 36 Wh cells; 5 V / 3 A per USB-C branch, 5 V / 6 A combined in this mode; owner's mass 240 g |
| Waveshare ESP32-P4-WIFI6 | 1 | Motion, sensing, media I/O, display | Recorded P4 rev 1.3; two 360 MHz HP cores; 32 MiB PSRAM / 32 MiB flash |
| Onboard ESP32-C6-MINI-1 | 1 | Radio coprocessor | Separate 160 MHz CPU / 512 KiB HP SRAM; 2.4 GHz Wi-Fi |
| PCA9685 board | 1 | Servo pulse generation | 16 channels, 12 used, 50 Hz configured; servo V+ separate from logic |
| MG90-family servos | 12 | Three joints per leg | Later repo note identifies owner-linked Miuzei MG90S; installed electrical / current / speed data not qualified |
| LSM6DS3 / breakout | 1 | Angular velocity and acceleration | Six axes; 8 KiB sensor FIFO; I2C / SPI; breakout identity not recorded |
| OV5647 module + CSI ribbon | 1 | Image capture | Sensor: 2592 × 1944 at 15 fps, 1080p 30, 720p 60; module variant / input current not identified |
| ES8311 + onboard microphone | 1 each | Audio conversion / capture | Mono ADC / DAC, up to 96 kHz / 24-bit |
| NS4150B + speaker | 1 each | Amplification / sound | Board supports an 8 Ω / 2 W-rated speaker; rating is not constant input consumption |
| Generic 1.9-inch LCD, no touch | 1 | Face / status | Purchased controller / pixels / backlight not identified; CAD names a Waveshare 1.9-inch reference |
| P4 microSD | 1 planned | Assets / captures | Four-bit SDMMC; card capacity / current unspecified; separate from Q6A card |
| Radxa Dragon Q6A + antenna | 1 | Gateway, selected coordination, speech, vision | QCS6490 eight-core CPU, Adreno 643, Hexagon; 12 GB-class unit, Linux-visible RAM 11.288 GiB |
| Q6A microSD | 1 | OS / apps / Qwen | Actual block device 31.915 GB decimal |
| Q6A USB storage | 1 currently used | Kokoro model cache | Actual 31.407 GB device; conflicts with no-USB-storage deployment until cache relocation |
| Remote desktop / server | 1 | Heavy LLM | Off robot battery; hardware / model / context allocation not supplied in robot records |
| Ainekio gateway / adapter | 1 authority | Commands and media | Existing Python WebSocket path; native USB transport not implemented |
| MetaHuman / Robot Status | Existing system | Coordination and state projection | Host processes; separate from P4 motion deadline |
| Kokoro / Whisper | Host services | TTS / STT | CPU Kokoro installed; Whisper configured base.en / int8 / CPU, configured environment absent here |
| YOLO | Proposed | Q6A object detection | No selected / implemented pipeline found in gateway source |
| ROS 2 Jazzy | Installed, optional | Sensor / tool interoperability | No selected ROS robot graph or ROS balance integration identified |
| Chassis, mounts, cables, distribution | Required | Mechanical / electrical load | Include in mass, resistance and power-path equations |

Capacity sources: [Waveshare](https://docs.waveshare.com/ESP32-P4-WIFI6),
[revision-matched P4](https://files.waveshare.com/wiki/common/Esp32-p4_datasheet_en.pdf),
[Radxa Q6A](https://docs.radxa.com/en/dragon/q6a).
The linked Google Parts Overview was read: it is the older S3 / eight-servo / OLED
design. The owner's newer hardware choices govern this budget. [Audit](BUDGET_AUDIT_EVIDENCE.md).

## 3. Electrical budget

### Branch limits

Define:

- **Ew / Eu:** complete P4 electronics 5 V input with Wi-Fi / USB respectively,
  including camera, LCD, IMU, audio, SD, board devices and conversion losses.
- **S:** total servo-branch input, including distribution losses.
- **Q:** Q6A branch input including attached devices.

These are whole-branch quantities. Do not add chip consumption again after
measuring its board input.

| Two-port arrangement | Branch 1 condition | Branch 2 condition | Robot battery demand |
| --- | --- | --- | --- |
| Onboard Q6A, wired P4 | Q ≤ 15 W | Eu + S ≤ 15 W | Q + Eu + S |
| Onboard Q6A, Wi-Fi P4 | Q ≤ 15 W | Ew + S ≤ 15 W | Q + Ew + S |
| Offboard Q6A, Wi-Fi P4 | Ew ≤ 15 W | S ≤ 15 W | Ew + S; Q supplied externally |

**Unused capacity on one 3 A port does not satisfy an overload on the other.**
A cable changes Eu versus Ew. Moving Q6A offboard also removes Q and changes
port allocation. No application-specific Wi-Fi-to-USB power delta is measured.

The owner reports Q6A working headless at 5 V. This budget uses that architecture;
3 A is its source allowance, not its consumption. Other negotiated Pouch profiles
are separate electrical designs. [Pouch ratings](https://sharge.com/products/pouch).

### Every electrical load

| Load | Published / recorded operating figure | Treatment in final input sum |
| --- | --- | --- |
| P4 chip | 360 MHz table 5-7: typical idle 35–65 mA; listed active cases 70–123 mA; at 3.3 V roughly 0.116–0.406 W | Characterized cases, not all-feature maximum. Board memory, regulators / peripherals additional |
| C6 chip | At 3.3 V: RX 78–82 mA = 0.257–0.271 W; listed TX 252–354 mA = 0.832–1.168 W | Mode / duty dependent; not constant Wi-Fi overhead. P4 networking additional |
| PSRAM, flash, regulators, LEDs, USB-UART | Included when measuring P4 board input | No combined all-feature board-input bound in cited board documentation |
| PCA9685 logic | 6 mA typical / 10 mA max in no-load test at 1 MHz SCL, VDD 2.3–5.5 V | At 3.3 V: 19.8 / 33 mW under that test; board LEDs / pull-ups additional; excludes servo V+ |
| LSM6DS3 | Typical 0.9 mA combined normal 208 Hz; 1.25 mA combined high-performance | At 3.3 V: 2.97 / 4.125 mW chip; breakout regulator / LED additional |
| OV5647 module | Sensor datasheet operating-current table 8-3 contains **TBD** entries | Installed module rating / input measurement required; a different vendor's 300 mA module is not substituted |
| ES8311 | Advertised 14 mW playback + record operating point | Codec only; microphone bias and amp included separately in complete board input |
| NS4150B + 8 Ω speaker | At 5 V: 1.3 W output at 1% THD, 1.7 W at 10% THD. At 3.6 V / 0.6 W output, 90% efficiency gives 0.667 W input | Use actual supply / volume; 2 W is speaker rating, not guaranteed clean output or constant demand |
| LCD + backlight | Installed-module input specification absent | P_LCD includes controller / backlight / regulator; animation FPS does not determine backlight watts |
| P4 SD card | Model absent | Include idle / read / write input and write peaks |
| Twelve servos | Applicable installed-batch current specification absent | Sum instantaneous holding / motion / acceleration current; 3 A is permitted sum, not demonstrated demand |
| Q6A + storage / radio | Working 5 V operation reported | Q must be measured for intended concurrent services and thermal state |
| Wires / connectors | P_loss = I²R; V_drop = IR | Example equation: 0.1 Ω at 3 A loses 0.9 W and 0.3 V; not a measured cable value |
| Desktop / router | Outside robot battery | Account separately for whole-installation energy |

Primary electrical sources:
[P4 table 5-7](https://files.waveshare.com/wiki/common/Esp32-p4_datasheet_en.pdf),
[C6](https://documentation.espressif.com/esp32-c6_datasheet_en.html),
[PCA9685 table 14](https://www.nxp.com/docs/en/data-sheet/PCA9685.pdf),
[LSM6DS3](https://pccomponents.com/datasheets/ST_MI-LSM6DS3TR.pdf),
[OV5647](https://www.arducam.com/downloads/modules/RaspberryPi_camera/OV5647DS.pdf),
[codec](https://files.waveshare.com/wiki/common/ES8311.DS.pdf),
[amp table 7](https://www.micros.com.pl/mediaserver/ULNS4150b_NSIWAY_0001.pdf).

Sum **watts**, not milliamps across different rails:
`P_input = Σ(V_rail × I_rail / efficiency_rail) + losses not already counted`.
Typical points under different conditions do not constitute a guaranteed maximum.

### Twelve servos on 3 A

`mean permitted servo current = (3 A − other load on that branch)/12`.
These are allocation thresholds, not electronics-load predictions.

| Other load on branch | Total available to servos | Mean allowed per servo |
| ---: | ---: | ---: |
| 0 A: dedicated servo branch | 3.00 A | 250.0 mA |
| 0.25 A | 2.75 A | 229.2 mA |
| 0.50 A | 2.50 A | 208.3 mA |
| 1.00 A | 2.00 A | 166.7 mA |
| 1.50 A | 1.50 A | 125.0 mA |

At each moment, holding current + motion increment + other loads must fit 3 A.
Staggered PWM pulses do not enforce this: servos continue driving / holding between
pulses. Current gait updates all 12 targets and has no measured-current limiter.
P4 reports battery_available=false.

The P4 header is not a documented 3 A servo distribution output. Its USB power
path includes an AO3401; traces / connectors have not been qualified at this motor
load. Split servo supply upstream through rated distribution; retain common
signal ground. [Schematic](https://files.waveshare.com/wiki/ESP32-P4-WIFI6/ESP32-P4-WIFI6-datasheet.pdf),
[PCA wiring](PCA9685_WIRING.md).

### Runtime and mass

Runtime hours = usable_output_Wh / average_robot_W.
Pouch cell energy is 36 Wh. Published rated delivered capacity at 5 V / 3 A is
5,500 mAh = **27.5 Wh**. Do not calculate 10,000 mAh × 5 V = 50 Wh.

| Average demand used in equation | Ideal 36 Wh ceiling, before conversion losses |
| ---: | ---: |
| 10 W | 3.60 h |
| 15 W | 2.40 h |
| 20 W | 1.80 h |
| 30 W | 1.20 h |

At rated 15 W, 27.5 / 15 = **1.83 h** from the manufacturer's output-capacity rating.
Other loads / dual-port use need their delivered-energy result; these are not
claimed robot runtimes. [Pouch specification](https://sharge.com/products/pouch).

Use owner's **240 g** Pouch mass. Add servos, body boards, camera, speaker,
IMU, LCD, cards, chassis, cabling / mounts, and Q6A assembly when onboard.
Offboard mass saving = Q6A assembly + removed cable / mount mass.
COM = Σ(mass × position) / Σmass. Geometry has no measured total mass; final
torque / support / fall-recovery calculations therefore require assembled mass data.

## 4. P4 memory: separate pools and owned allocations

### Capacity and baseline

| Pool | Capacity | Audited use / limit |
| --- | --- | --- |
| HP internal | 768 KiB physical L2MEM | Cache / system reservations reduce allocator space; IDF 5.5.4 default pre-v3 layout implies about 562.95 KiB HP regions, not a recovered runtime free-heap figure |
| LP / scratchpad | 32 KiB / 8 KiB | Distinct regions, not arbitrary HP heap / DMA substitutes |
| PSRAM | 32 MiB, recorded 200 MHz | Bulk storage; does not automatically satisfy internal allocations |
| Flash | 32 MiB physical | Active app slot 8 MiB; latest recorded app 2,369,264 B; remainder 6,019,344 B = 5.741 MiB |
| C6 HP SRAM | Separate 512 KiB | Radio firmware owns it; not P4 heap |

Nearby matched build: static data+BSS **39,260 B**, occupied internal including
code **138,494 B**. Earlier compact-motion run: free internal **254,875 B**,
minimum free **229,523 B**. These are distinct scopes: do not add static size,
stack reservations and runtime free heap as independent total uses.
[Build / runtime evidence](../../Slave/software/models/v2-12servo/CONTROLLER_VALIDATION.md),
[board evidence](STEP1_EVIDENCE.md),
[IDF layout](https://github.com/espressif/esp-idf/blob/v5.5.4/components/esp_system/ld/esp32p4/memory.ld.in).

Flash is partitioned storage, not extra RAM. The default
[partition table](../../Slave/firmware/esp32p4-wifi6/partitions.csv) contains one
8 MiB factory app. The optional
[full layout](../../Slave/firmware/esp32p4-wifi6/partitions-full.csv) defines two
8 MiB OTA slots and 15.875 MiB LittleFS. Installed evidence records an OTA app at
0x20000; do not assume that a template file proves the flashed partition layout.

### Stack and dynamic memory ledger

| Owner | Explicit stack / payload | Condition |
| --- | ---: | --- |
| Output guard | 3 KiB | Core 0, highest app priority, 5 ms checks |
| Body output | 12 KiB | Core 1, priority 10, 20 ms targets |
| Body control / link / WebSocket | 12 / 14 / 16 KiB | Controller active; WebSocket also configures 1,024 B buffer |
| Network / storage / system | 8 / 6 / 4 KiB | Wi-Fi / SD / state workers |
| Camera / mic / speaker | 6 / 10 / 4 KiB | Media initialized; P4 wake inference overflowed the former 6 KiB mic stack |
| Console | 12 KiB | Existing firmware |
| Explicit stack subtotal | **107 KiB** | Excludes SDK / Hosted / lwIP / TLS tasks, TCBs, transient main and optional HTTP |
| Setup HTTP / transient main | 6 / 12 KiB | Additional while alive |
| Speaker queue | 32,200 B | 50 × (640 PCM + 4 generation); RTOS overhead extra |
| Mic queued payload | 0–5,160 B | Eight × (640 PCM + 5 header); producer / in-flight extra |
| I2S DMA PCM | 5,120 B minimum | Four × 640 B per direction; slot padding / alignment / descriptors extra |
| Mic input / pre-roll | 3,840 B | Six 640 B local arrays **inside stack**, not added again |
| Fixed camera pixels / JPEG | **6,750,208 B / 6.4375 MiB** | Two 1280 × 960 RGB565 captures + 1024 × 768 RGB565 resize + 256 KiB JPEG |
| Other camera payload copies | Up to **5 × 256 KiB** envelope | Two queued + producer + sender + one pending SD capture; headers / allocator extra |
| Wake model / arena | Up to 512 / 512 KiB | Caps, not chosen-model size; PSRAM preferred, internal fallback |
| Wake variable arena | 2 KiB | Frontend / interpreter additional |
| Other queues | Body 1 / 1 / 16; controller 8 / 16 / 8; camera requests 4; storage requests 4 | Structs / strings / RTOS / allocator metadata additional |
| LCD / balance controller | Not implemented in P4 target | Pixel / sample costs below; future driver / control allocations require accounting |

Camera fixed + five compressed copies + max wake model / arena = **8.6875 MiB**,
before other drivers / media / UI. Copy envelope is not measured simultaneous occupancy.
Sources: [main](../../Slave/firmware/esp32p4-wifi6/main),
[media](../../Slave/firmware/esp32p4-wifi6/components/ainekio_p4_media),
[wake](../../Slave/firmware/components/ainekio_wake/wake_word_service.cpp).

**Actual internal-memory failure:** Hosted TX / RX queues 20 caused a 12,800 B
main-task allocation failure with largest block 6,656 B. Restoring queues 8 fixed
startup. Total PSRAM does not cure internal fragmentation.

### Final camera layouts

Raw storage = width × height × bytes_per_pixel × frames.
Three-frame scenario = two captures + full-size working image.
Two-frame alternative removes the working copy and requires pipeline changes.

| Sensor mode | One RGB565 | Three RGB565 | Three RGB888 | Three RGB565 + six 256 KiB JPEG buffers + 1 MiB max wake |
| --- | ---: | ---: | ---: | ---: |
| 1280 × 720 / 60 fps | 1.758 MiB | 5.273 MiB | 7.910 MiB | **7.773 MiB** |
| 1920 × 1080 / 30 fps | 3.955 MiB | 11.865 MiB | 17.798 MiB | **14.365 MiB** |
| 2592 × 1944 / 15 fps | 9.611 MiB | 28.833 MiB | **43.249 MiB** | **31.333 MiB** |

Excludes audio, LCD, drivers, stacks, metadata and alignment.
Three full-sensor RGB888 frames are **11.249 MiB over PSRAM** by themselves.
Full-sensor RGB565 camera / wake subtotal leaves **0.667 MiB**.

Adding 170 × 320 double RGB565 LCD plus 96k / 24-bit audio queues, eight DMA blocks,
six mic staging blocks and one speaker block gives **31.941 MiB** counted bulk
payload: only **60.14 KiB** remains if charged to a 32 MiB bulk pool. Some DMA
and staging needs internal placement; that is an additional constraint, not
unaccounted free memory. The same bulk layout at 1080p is **14.974 MiB**.

Removing one full 5 MP working image saves **9.611 MiB**, reducing camera / wake
subtotal to **21.722 MiB** before other loads. This is a storage calculation;
it does not overcome the ISP limit below or establish a working 5 MP pipeline.

**256 KiB is a packet allocation, not a guaranteed JPEG size at any quality.**
Increasing it changes every copy, queue, gateway limit and bandwidth calculation.

## 5. Camera throughput and storage

Preview selects 1280 × 960 RAW10 / 45 fps capture into RGB565 and emits QVGA / VGA,
default 2 fps / max 15 fps. Stills also support XGA, native 1280×960, and cropped
1920×1080 RAW10 / 30 fps, with automatic long-exposure capture in dim light.
Native stills skip CPU resizing but rotate 180 degrees in place in the dequeued
RGB565 buffer for the installed mounting; preview combines rotation with resizing.
No extra frame allocation is needed. Output uses hardware JPEG quality 75 / YUV420.
The sensor rates are nominal: longer night exposures lower acquisition rate.
H.264 is disabled.
These are software choices, not sensor maxima.
[Camera source](../../Slave/firmware/esp32p4-wifi6/components/ainekio_p4_media/camera.c).

**The P4 ISP is specified for a maximum 1920 × 1080.** The current source enables
CSI + ISP to produce RGB565. Full 2592 × 1944 sensor output exceeds that ISP
specification even if its buffers fit. Full-resolution use needs a different
capture/processing path, such as transferring supported raw capture to a host
for conversion; that path is not implemented or qualified here. The 5 MP rows
below are sensor/storage arithmetic, not a supported current preset.
[P4 datasheet §4.2.1.2](https://files.waveshare.com/wiki/common/Esp32-p4_datasheet_en.pdf).

| Requested mode | Capture writes alone | Published isolated encoder result | Requested / benchmark throughput |
| --- | ---: | ---: | ---: |
| 720p 60 RGB565→YUV420 | 110.592 MB/s | 88 fps | 68.2% |
| 1080p 30 RGB565→YUV420 | 124.416 MB/s | 40 fps | 75.0% |
| 1080p 30 RGB565→YUV422 | Same | 36 fps | 83.3% |
| 1080p 30 RGB565→YUV444 | Same | 24 fps | **125%: benchmark below target** |
| 1080p 30 RGB888→YUV422 | 186.624 MB/s | 26 fps | **115.4%: benchmark below target** |
| 5 MP / 15 RGB565 | 151.165 MB/s | No matching result in cited table | Sensor rate does not establish P4 pipeline rate |

Ratios are **encoder throughput, not CPU utilization**. Benchmark runs only JPEG
code at 360 MHz / 200 MHz PSRAM. Capture, resize, copies and contention add work.
[Espressif benchmark](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32p4/api-reference/peripherals/jpeg.html).
Sensor modes: [OV5647](https://www.arducam.com/downloads/modules/RaspberryPi_camera/OV5647DS.pdf).

JPEG size J bytes at F fps needs 8J × F bit/s. Resolution does not uniquely determine J.

| JPEG / frame | Images at 15 fps | At 30 fps | At 60 fps |
| ---: | ---: | ---: | ---: |
| 64 KiB | 7.864 Mbit/s | 15.729 Mbit/s | 31.457 Mbit/s |
| 128 KiB | 15.729 | 31.457 | 62.915 |
| 192 KiB | 23.593 | 47.186 | 94.372 |
| 256 KiB | 31.457 | 62.915 | 125.829 |

Add mic payload to P4 TX: 0.256 Mbit/s at 16k / 16-bit, 1.152 at 48k / 24-bit,
2.304 at 96k / 24-bit. Speaker is reverse traffic.
256 KiB / 30 fps + 96k / 24 mic = **65.219 Mbit/s TX**, plus **2.304 RX**.

Matching Hosted 2.12.8 C6 four-bit-SDIO shield-box benchmark: **53.4 Mbit/s TCP TX / 44 Mbit/s RX**, tested separately with 40 MHz Wi-Fi bandwidth. 65.219 exceeds TX
reference by **11.819 Mbit/s** before overhead. It is not guaranteed household
throughput, and TX / RX cannot be added.
[Version-matched benchmark](https://components.espressif.com/components/espressif/esp_hosted/versions/2.12.8/readme?language=en).

Admission: 8J × F + mic_bps + overhead_bps < sustained_TX.
At 53.4 Mbit/s, 30 fps, 96k / 24 mic, ceiling is **207.91 KiB / JPEG** before any
overhead / reverse-traffic / contention allowance. At 15 fps, 256 KiB + same mic is
**33.761 Mbit/s**. Neither is a validated full-system preset.

**H.264 is a hardware alternative:** P4 specifies baseline YUV420 encoding up to
1080p30, with I/P frames and rate control. It is disabled in this firmware.
For an implemented stream at R bit/s, substitute R for `8 × J × F` in the
transport equation. This requires encoder/reference buffers, a stream protocol
and host decoding; the JPEG buffer totals do not describe that pipeline.
No fixed bitrate is assigned to a promised image quality or latency.
[P4 datasheet §4.2.1.5](https://files.waveshare.com/wiki/common/Esp32-p4_datasheet_en.pdf).

Gateway base64 observations expand images: 4 × ceil(J / 3).
256 KiB becomes **349,528 B** before JSON; forwarding each image at 30 fps needs
**83.887 Mbit/s** of base64 text. Sending selected observations reduces that.
Adapter camera queue depth 1, JSON cap 384 KiB.

Continuous recording, if implemented: J × F B/s, 3600J × F B / hour.
256 KiB / 30 fps = **7.864 MB/s / 28.312 GB / hour** before filesystem overhead.
Existing storage saves requested captures; continuous video recording is not
qualified. Card speed-class throughput does not bound individual write stalls.
The [SD implementation](../../Slave/firmware/esp32p4-wifi6/main/storage.c) rotates
four 1 MiB log files and 32 captures, each capped at 1 MiB. With the current
256 KiB camera cap, those captures contain at most 8 MiB of JPEG payload.

## 6. Audio quality, memory and delay

ES8311 supports mono 8–96 kHz / up to 24-bit. The current P4, gateway validation,
speech adapter and MetaHuman resampling fix 16k / 16-bit / mono / 20 ms frames.
Higher rates require changes across all those owners.
[Codec specification](https://files.waveshare.com/wiki/common/ES8311.DS.pdf).

| Mono format, duplex | One 20 ms block | Duplex payload | Current-depth speaker+mic queues | Eight DMA blocks, PCM only |
| --- | ---: | ---: | ---: | ---: |
| 16k / 16-bit | 640 B | 0.512 Mbit/s | 36.484 KiB | 5.000 KiB |
| 24k / 16-bit | 960 B | 0.768 | 54.609 KiB | 7.500 KiB |
| 48k / 16-bit | 1,920 B | 1.536 | 108.984 KiB | 15.000 KiB |
| 48k / packed 24-bit | 2,880 B | 2.304 | 163.359 KiB | 22.500 KiB |
| 96k / packed 24-bit | 5,760 B | 4.608 | 326.484 KiB | 45.000 KiB |
| 96k / 24-bit in 32-bit containers | 7,680 B | 6.144 | 435.234 KiB | 60.000 KiB |

Queue formula: 50 × (block + 4) + 8 × (block + 5); RTOS metadata, alignment and slot padding
additional. 96k packed 24 adds **290 KiB** queues over current, exceeding the
earlier observed 224.1 KiB internal minimum-free heap. Suitable buffers need
PSRAM ownership and DMA placement review.

The DMA column is the PCM payload for 80 ms per direction, not proof that each
20 ms block fits one descriptor. IDF limits an I2S DMA buffer to **4,092 B**;
a 96k/24-bit mono block is **5,760 B**, so it requires smaller DMA blocks and
an adjusted descriptor count. Slot padding can increase the allocation.
[IDF I2S limits](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32p4/api-reference/peripherals/i2s.html).

Six mic input / pre-roll arrays currently live on its 10 KiB stack. At 48k / 16-bit
they alone need **11,520 B**; even 24k / 16 needs 5,760 B before call frames.
Increasing constants without changing ownership is not viable.
Wake / VAD expects 16 kHz; higher capture requires a compatible downsampled stream.

**Speech target:** Kokoro generates 24 kHz. Preserve 24k / 16-bit output to avoid
current 16 kHz downsampling. Upsampling to 96 kHz does not add information absent
from synthesis. 48k / 24-bit is a separately costed capture / playback option.
The actual mic, speaker and amplifier still constrain acoustic quality.

The proposed 24k speaker / 16k mic profile describes **network PCM formats**.
The existing ES8311 path uses shared BCLK/WS on I2S0 with one duplex sample rate.
Run that physical path at a compatible common rate, such as 24 kHz, and resample
capture to 16 kHz for wake/STT and transport. Charge DMA/capture buffers at the
physical rate, then add the resampler's storage and compute; the network-rate
sum alone is not its complete memory allocation.

| Delay / storage mechanism | Exact behavior / evidence |
| --- | --- |
| Synthesis | Offline Q6A test: 5 s voice took **15.068–15.904 s**; **1,537.797 MiB** peak process RSS |
| MetaHuman delivery | Collects all Kokoro chunks before staging / enqueueing robot speech |
| Gateway | Up to five-frame initial prebuffer, then 20 ms pacing |
| P4 startup buffer | Four queued frames or end-of-stream; 80 ms of audio, not a fixed 80 ms network wait |
| Speaker queue | 50 × 20 ms = 1 s capacity; not normal latency |
| I2S DMA | Four × 20 ms = 80 ms capacity per direction |
| Mic queue / pre-roll | 160 / 100 ms audio capacity; queue full drops packets |
| VAD hangover | 50 × 20 ms = 1 s after detected speech under current logic |
| Amp enable | Manufacturer lists 120 ms typical startup under its test conditions |

Do not add every full queue as if always occupied.
Sources: [Kokoro measurement](BUDGET_AUDIT_EVIDENCE.md),
[P4 audio](../../Slave/firmware/esp32p4-wifi6/components/ainekio_p4_media/media.c),
[gateway speech](../../Master/gateway/environment_adapter/speech_transport.py),
[amp](https://www.micros.com.pl/mediaserver/ULNS4150b_NSIWAY_0001.pdf).

## 7. IMU, LCD, pins and buses

### IMU sampling

One accel+gyro sample contains 12 raw bytes. A single 12-byte register read uses
about 135 I2C clocks including addressing, register selection and acknowledgments.

| Both sensors' ODR | Raw payload | 400 kHz I2C occupancy, one read / sample | Sample interval |
| ---: | ---: | ---: | ---: |
| 104 Hz | 1,248 B/s | 3.51% | 9.615 ms |
| 208 Hz | 2,496 B/s | 7.02% | 4.808 ms |
| 416 Hz | 4,992 B/s | 14.04% | 2.404 ms |
| 833 Hz | 9,996 B/s | 28.114% | 1.200 ms |
| 1,666 Hz | 19,992 B/s | 56.228% | 0.600 ms |

Extra status reads, driver gaps and bus sharing add cost. FIFO bursts amortize
addressing. Separate maximums, accel 6,664 Hz plus gyro 1,666 Hz, produce
**49,980 B/s**; byte+ACK clocks alone need **449,820 clocks/s**, exceeding 400 kHz
I2C. Rated 10 MHz SPI can carry that **0.400 Mbit/s raw payload**.
[LSM6DS3 datasheet](https://pccomponents.com/datasheets/ST_MI-LSM6DS3TR.pdf).

An **initial 208 Hz acquisition target** supplies over four samples per existing
20 ms servo interval at 7.02% theoretical bus occupancy. That is a design choice
derived from these costs, not a demonstrated rate for catching a fall. Keep
attitude estimation / correction local to P4; Q6A / desktop receives telemetry and
selects higher-level actions. Sensor sampling cost does not specify controller
code size or CPU time.

### LCD without an invented part identity

CAD names a Waveshare 1.9-inch module: that vendor's panel is 170 × 320,
ST7789V2 / SPI. The owner identifies the purchased screen as generic. Verify that
identity before applying its electrical data. The second row budgets a larger
240 × 320 pixel extent as a comparison, not the claimed resolution of this panel.

| RGB565 extent | One framebuffer | Two buffers | Full-refresh pixel data at 30 fps | At 60 fps |
| --- | ---: | ---: | ---: | ---: |
| 170 × 320 reference panel | 108,800 B | 212.5 KiB | 26.112 Mbit/s | 52.224 Mbit/s |
| 240 × 320 comparison | 153,600 B | 300 KiB | 36.864 Mbit/s | 73.728 Mbit/s |

At an explicitly selected 40 MHz SPI clock, ideal full-refresh ceilings are
45.96 / 32.55 fps respectively, before commands / gaps. This is arithmetic, not
the generic module's validated clock. Partial updates transfer fewer pixels;
stripe rendering reduces P4 buffering. The display controller's RAM is separate
from P4 RAM. No touch buffers or touch pins are needed.
[Reference module](https://www.waveshare.com/product/displays/lcd-oled/1.9inch-lcd-module.htm).

### Pins and interfaces

| Resource | Assignment | Impact on exposed GPIO budget |
| --- | --- | ---: |
| PCA9685 | I2C1 SDA2, SCL3, OE4 | 3 |
| Codec / camera control | I2C0 SDA7 / SCL8; addresses 0x18 / 0x36 | 2 shared |
| USB-FS reservation | GPIO 24 / 25 | 2 |
| Camera pixels | Dedicated CSI | No additional exposed GPIO |
| C6 | SDIO 14–19, reset 54, boot 6 reserved | Onboard; outside exposed-27 count |
| Audio | I2S9–13, amplifier 53 | Onboard |
| SD | GPIO 39–44, supply control 45 | Onboard |
| Debug | UART37 / 38, boot 35 | Onboard |
| IMU on I2C | Share 7 / 8, address 0x6A / 0x6B; optional IRQ | 0 data + 1 optional |
| IMU on SPI | CLK / MOSI / MISO / CS; optional IRQ | 4 + 1 optional; compatible clock / MOSI can share LCD bus |
| Reference SPI LCD | CLK / DIN / CS / DC / RST / BL | 6; generic interface must match |
| Native USB HS | Dedicated P1 D+ / D− | 0 data GPIO; self-powered VBUS sense can require 1 GPIO / circuit |

27 exposed − 7 assigned / reserved = **20** before additions.
I2C IMU+IRQ and six-signal LCD leaves **13**; USB VBUS sense leaves **12**.
Separate SPI IMU+IRQ plus LCD leaves **9**, or **8** with VBUS sense; compatible
shared CLK / MOSI returns two. These are wiring options, not an installed map.

Available before those additions:
`5,20,21,22,23,26,27,28,29,30,31,32,33,46,47,48,49,50,51,52`.
Both HP I2C controllers already have owners. IMU must join an existing bus owner,
not instantiate a second I2C0 driver. Servo I2C1 is separate from media / storage.
[P4 README](../../Slave/firmware/esp32p4-wifi6/README.md),
[board source](../../Slave/firmware/esp32p4-wifi6/main/board.c),
[USB requirements](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32p4/api-reference/peripherals/usb_device.html).

## 8. CPU deadlines, walking speed and servo lag

| Item | Source / measurement | Budget implication |
| --- | --- | --- |
| Body targets | 20 ms / 50 Hz | Updates local targets independently of network packet cadence |
| Output supervision | 5 ms checks, 40 ms progress limit | Detects stopped progress and disables outputs; does not stabilize posture |
| Earlier compact calculation | Maximum 1.315 ms | 6.575% of a 20 ms interval in that test, not total CPU utilization |
| Earlier calculation through PCA output | Maximum 2.897 ms | 14.485% of interval; 17.103 ms observed interval remainder, not latest all-feature headroom |
| Request / preflight / arming | Maximum 6.596 ms | Admission work, not physical travel time |
| PCA write | 66 bytes × 9 clocks / 400 kHz = 1.485 ms | 7.425% bus time at 50 Hz; already inside measured through-output time |
| PCA PWM | 50 Hz / 4,096 ticks | Nominal 4.883 µs tick; pulse timing and servo response are distinct |
| Wake | Synchronous microphone-task inference | Must fit sustained audio cadence; selected-model worst-case time not recorded |
| Camera | CPU resize, then hardware encode | Loops scale with emitted pixels × fps; memory traffic adds contention |
| Networking | P4 protocol / TCP / WebSocket / SDIO + C6 radio | Not zero P4 overhead; no defensible fixed CPU percentage |

Recorded compact test: 33,365 frames, twelve calculated targets but **two unloaded
physical servos**, camera absent, wake capture off, display deferred. Latest gait
changes lack a replacement concurrent timing record.
[Controller validation](../../Slave/software/models/v2-12servo/CONTROLLER_VALIDATION.md).

**Media scheduling is an independent bottleneck.** The current link loop waits
up to 20 ms for replies, then drains at most one mic packet and one JPEG. An open
mic produces 50 packets/s. Stable draining needs average service interval ≤ 20 ms,
including sends; the empty-reply wait leaves no guaranteed send-time allowance.
Queue depth delays drops, not sustained overload. A failed binary send at its
250 ms timeout calls `fail_link`, disabling PCA output. Raw Wi-Fi throughput
alone cannot qualify this behavior.
[Controller source](../../Slave/firmware/esp32p4-wifi6/main/controller.c).

### Command-speed math from current compiler inputs

The compiler reads full walk sweep **92 mm**, ground-contact fraction **0.7**,
base cycle **1.8 s**. The old loop-contract text still says 52 mm; it is not used
for these calculations.
`v_reference = (92 × stride_fraction / 0.7) × rate / 1.8`.

| Command | Stride / rate | Cycle period | 20 ms frames / cycle | Reference translation |
| --- | --- | ---: | ---: | ---: |
| Walk speed 25 | 50% / 1 | 1.8 s | 90 | 36.51 mm/s |
| Walk speed 50 | 100% / 1 | 1.8 s | 90 | 73.02 mm/s |
| Walk speed 100 | 100% / 2 | 0.9 s | 45 | 146.03 mm/s |
| Explicit stride 100 / rate 3 | 100% / 3 | 0.6 s | 30 | 219.05 mm/s |
| Forward run speed 200, steady | 104 mm sweep, duty 0.42, rate 2.667, base 1.2 s | 0.45 s | 22.5 | 550.26 mm/s |

These are **commanded kinematic speeds**, not measured physical speed. Walk
changes transition over a cycle; run blending uses four cycles. Run includes
flight phases and explicitly remains `hardware_qualified=false`. Higher rate
retains 50 Hz target updates, reduces samples / cycle and increases demanded joint
speed. Sources: [motion](../../Slave/software/models/v2-12servo/motion.c),
[compiler](../../Slave/software/models/v2-12servo/tools/compile_walk.py),
[run](../../Slave/software/models/v2-12servo/motions/run/config.json).

Physical correction latency = sample wait + sensor / filter delay + compute and
scheduling + bus / PWM delay + loaded servo response. A local correction avoids a
network round trip. A remote correction adds both transport directions and host
processing. Current feedback reports commanded / model position, not shaft position.

TowerPro's separate MG90S specifies 0.10 s / 60° at 4.8 V, equivalent 600° / s nominal.
The installed Miuzei servos are not that identified product; this is a comparison,
not their loaded response bound. [TowerPro](https://towerpro.com.tw/product/mg90s-3/).

## 9. Q6A, MetaHuman and desktop budget

Eight host cores and **11.288 GiB Linux-visible RAM** are separate from P4 pools.
GPU / DSP acceleration also uses buffers / host memory; a 12-TOPS product figure does
not determine application FPS or available CPU.

| Owner | Established memory / storage fact | Processing / latency fact |
| --- | --- | --- |
| Ubuntu / shared services | Snapshot about 7.5–7.7 GiB available during audit | Instantaneous observation, not final headless reservation |
| Gateway | Camera queue 1; body frame cap 256 KiB + 5 B; bridge JSON 384 KiB / binary 512 KiB | Python / SSL / WebSocket heap additional to payloads |
| MetaHuman speech | Input stream cap 3 MiB / 64 chunks; individual WAV 2 MiB; PCM ≤ 480,000 B; four staged files | Conversions / copies additional; preparation collects full speech before dispatch |
| Kokoro | **1,537.797 MiB peak process RSS** measured | Five-second phrase: **15.068–15.904 s** synthesis, eight threads |
| Whisper base.en / int8 | Configuration present; configured environment absent | No local working-set / runtime result; do not borrow another machine / model's benchmark |
| Optional Qwen 3.5-0.8B | 532,517,120 B text weights + 204,987,232 B projector = **703.339 MiB on disk** | Four A78 threads, context 4096, one slot; model-file size is not runtime RAM |
| Optional YOLO | No selected model. YOLO11n example: 2.6M parameters, 6.5 GFLOPs at 640; FP32 weight arithmetic ≈ 10.4 MB before runtime / activations | 30 fps requires 195 GFLOP/s by that operation count; no Q6A FPS inferred |
| ROS 2 Jazzy | 204 installed packages report 138,865 KiB installed size, excluding non-ROS dependencies | RAM / CPU depend on chosen nodes / messages / history; no fixed ROS allowance assigned |
| Remote desktop LLM | Server-owned weights, KV cache, runtime, OS | Off robot battery; exact model / context / concurrency / server required to rate this branch |

YOLO example: [model-author table](https://docs.ultralytics.com/models/yolo11).
Source ownership and host measurements: [audit](BUDGET_AUDIT_EVIDENCE.md).

Historical Q6A Qwen 0.8B means: fresh routing 7.70 s, cached 4.50 s, scene description
8.28 s. Later fault-affected tuning recorded one cached request at 11.27 s.
Uncooled tests reached about 95°C; records also document USB / PCIe / storage errors.
These are local workload evidence, not a forecast of remote desktop performance.

Host admission equation:
`OS + gateway/MetaHuman + concurrent TTS/STT/vision working sets + buffers + optional model runtime < usable RAM`.
Use proportional set size or whole-host deltas when adding shared processes;
summing every RSS can double-count shared pages. zram is not extra physical RAM
or a guarantee against latency.

Kokoro model cache still resides on USB despite the planned no-USB-peripheral
deployment. Relocate that cache before declaring the headless configuration
self-contained. Whisper and chosen vision runtime also need actual installed
services and concurrent resource measurements.

## 10. Wired versus wireless

| Item | Native USB HS P4→Q6A | P4 / C6 Wi-Fi→Q6A |
| --- | --- | --- |
| Link fact | **480 Mbit/s signaling**, not measured payload | Hosted TCP reference **53.4 TX / 44 RX Mbit/s**, separate shield-box tests |
| Existing implementation | Device class, host adapter and firmware integration required | Existing Hosted / SDIO / WebSocket path |
| Pixel / audio memory | Capture / encoder / queues remain unless redesigned | Same media allocations plus networking |
| P4 CPU / RAM delta | USB stack / buffers replace or coexist with networking; no measured delta | C6 handles radio; P4 retains TCP / protocol / copying / SDIO work |
| Body-link radio contention | Removed | Remains; proximity does not bound retries / queues |
| Q6A upstream | Wi-Fi can serve remote server while body uses USB | AP+station advertised; coexistence / forwarding share hardware resources |
| Local balance | No transport round trip required | No transport round trip required |
| Battery / mass | Depends on Q6A placement | Offboard removes Q6A load; onboard Wi-Fi does not |
| Required qualification | Sustained payload, power roles, reconnect and scheduling | Sustained payload, scheduling, interference and link-failure behavior |

Use P4's **P1 native HS connector**, not CH343 USB-C debug serial. At 115200
baud / 8N1, UART ideal payload is **11,520 B/s**; even one current audio direction
requires 32,000 B/s. A 256 KiB image takes **22.76 s**. A debug cable is not a
high-speed media transport.

A 256 KiB image contains 2,097,152 bits. At 53.4 Mbit/s, ideal serialization is
**39.27 ms**. At 480 Mbit/s signaling, **4.37 ms** is only a theoretical lower
bound before USB overhead. Neither is command RTT or end-to-end vision latency.
Small control packets and large images have different delay budgets.

With separately powered boards, do not directly join two source VBUS rails.
Select the power path and self-powered VBUS detection required by the USB stack.
[USB hardware requirements](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32p4/api-reference/peripherals/usb_device.html).

**Selection rule:** onboard native USB serves body-link capacity and independence
from radio contention, subject to shared servo-branch power. Offboard Q6A / Wi-Fi
serves the present battery-port and carried-mass constraints, with media admitted
by actual byte rate. Neither is “instant / zero overhead / qualified at full load.”

## 11. Operating targets and adjustment rules

These are implementation targets and rejection boundaries, not already validated
presets. They retain high-quality options rather than defining existing low
defaults as the final robot.

| Profile | Settings / payload | Resource conclusion and required work |
| --- | --- | --- |
| Existing software ceiling | XGA 15, JPEG Q75, 16k / 16-bit mono duplex, 50 Hz targets | Source allocations known; LCD / IMU missing and camera absent from timing test; not full-feature qualification |
| Native-quality speech | Network: 24k / 16 speaker, 16k / 16 mic for STT / wake | 48,000 + 32,000 = **80,000 B/s / 0.640 Mbit/s** PCM; shared physical clock and resampling as in §6; update format owners and buffers |
| Full-HD video target | 1080p 30 RGB565 / YUV420 + native-quality speech | Camera / wake subtotal 14.365 MiB. At J = 128 KiB: **31.713 TX / 0.384 RX Mbit/s**; scheduling / transport qualification required |
| Full-HD + higher-rate PCM | 1080p 30 + 48k / 24 duplex | At J = 128 KiB: **32.609 TX / 1.152 RX**. At J = 256 KiB: **64.067 TX**, above Wi-Fi reference; lower byte rate or native USB |
| Maximum codec rate | 96k / 24 duplex | 4.608 Mbit/s; 326.484 KiB queues; 45 KiB packed DMA; ownership / format / resampler changes required |
| Fast video | 720p 60 RGB565 / YUV420 | Smaller raw frames, more images / s. At J = 128 KiB + 96k mic: **65.219 Mbit/s TX**, above reference |
| Full sensor resolution | 2592 × 1944 / 15 | Exceeds current ISP specification; different capture/processing path required. Three RGB888 frames also exceed PSRAM; reducing copies alone does not enable this mode |
| H.264 alternative | Hardware capability: 1080p30 YUV420 baseline | Disabled in source; budget actual bit rate R plus audio/overhead, new encoder/reference buffers and host decoding |
| Posture sensing | Initial 208 Hz local IMU feeding 50 Hz targets | 2,496 B/s; 7.02% theoretical I2C; control algorithm and mechanical qualification required |
| LCD | Native panel resolution, partial / full refresh admitted by §7 | Preserve pixels; select update area / rate for the identified clock / rendering path |

J = 128 KiB in the table is an explicit encoded-size scenario, not a prediction
that 1080p quality 75 images will have that size. Do not silently enforce an
image-byte cap by claiming unchanged visual quality.

| Adjustment | Quantified benefit | Cost that remains |
| --- | --- | --- |
| Camera 30→15 fps, equal JPEG bytes | Half transport / recording payload and encode jobs | Fixed buffers unchanged; sensor capture mode must change to reduce its traffic |
| Three RGB565 1080p→720p frames | 11.865→5.273 MiB, **6.592 MiB saved** | Encoded bytes remain content / quality dependent |
| Remove one working frame | Saves 3.955 MiB at 1080p / 9.611 MiB at 5 MP | Pipeline change, not a config-only option |
| 96k / 24→48k / 24 | Half PCM payload / sample memory for same duration | Driver / code / wake stream remain |
| Shorter queues | Less storage and maximum queued delay | Does not increase sustained consumer speed |
| Lower LCD refresh / partial rectangles | Fewer pixel transfers / render jobs | Full buffers unchanged unless renderer changes; backlight power separate |
| Lower gait rate | Longer cycle, lower kinematic speed, more frames / cycle | 50 Hz loop still runs; motor current does not scale from speed alone |
| Lower volume | Lower output power for same waveform / load | Exact amplifier input saving needs its operating point; synthesis CPU unchanged |

## 12. Qualification boundaries and required inputs

A complete numerical total requires every material term. Replacing an
unidentified load or unimplemented algorithm with an invented allowance would
invalidate the requested facts-only budget.

| Required input / change | Why it affects the answer | Exact pass condition |
| --- | --- | --- |
| LCD identity / backlight specification | Pins, native pixels, bus clock, watts | Add its verified allocations / current to selected profile / branch |
| Installed servo current / load / speed | 3 A adequacy and achievable physical movement | Branch remains ≤ 3 A; actual joint following and torque support gait |
| Whole P4 electronics 5 V input; camera / card identities | Chip typicals do not bound board / modules | E + S ≤ 15 W when shared; each dedicated branch ≤ 15 W |
| Q6A concurrent-service power / thermal result | Battery demand and sustained processing | Q ≤ 15 W on chosen branch and required request latency sustained |
| Complete P4 concurrent allocations | Internal heap, PSRAM, largest blocks, DMA, stacks | Every allocation fits its required pool and stack / contiguous-block requirement |
| Media producer / consumer timing | Current link loop and synchronous wake can backlog audio | Sustained 50 mic packets/s, bounded media queues, no body-deadline violation |
| Local balance controller | Absent; sensor data alone cannot correct pose | Correction meets selected local deadline and plant follows it |
| Native USB, if selected | Signaling rate does not establish payload / power roles | Sustains selected bidirectional profile with defined reconnect / power behavior |
| Whisper / YOLO / remote LLM choices | Changes host working sets and response latency | Concurrent host fits 11.288 GiB and selected latency targets; desktop sized separately |
| Assembled mass / COM | Changes support and torque demands | Gait evaluated against real load distribution |

**Closed conclusions:** maxed three-frame RGB888 is over RAM; large-frame 30-fps
MJPEG exceeds published Wi-Fi throughput; full 5 MP exceeds the current ISP
specification; high-rate audio needs implementation
changes; a shared 3 A servo / electronics branch permits less than 250 mA mean per
servo; installed CPU Kokoro has measured seconds of synthesis delay.

**Full-tilt under-budget certification is not supported by the present evidence.**
This document supplies capacities, accounted allocations, part-specific operating
points, equations and concrete rejection boundaries without invented margins.
See [Body Control Integration](../BODY_CONTROL_INTEGRATION.md) and
[audit evidence](BUDGET_AUDIT_EVIDENCE.md).
