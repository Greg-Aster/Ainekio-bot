# Resource-budget audit evidence

Audit date: 2026-09-28. Companion to [the system budget](RESOURCE_BUDGET.md).
This is a source, specification and selected host-measurement audit, not a
completed-robot load test. No body command, firmware flash, network reconfiguration
or production-code change was performed.

Final document verification: the arithmetic calculator executed successfully;
camera/audio allocations, link rates, servo allocation thresholds, flash remainder
and gait equations were reviewed. Local links, section anchors and table column
counts were checked across the budget, evidence, integration record, documentation
index and MetaHuman audit note. `git diff --check` passed in both repositories.
Application builds and robot load tests were not used to claim qualification.

Publication note: upstream commit `afc30d7` was integrated after this audit.
The budget calculator's output was unchanged after that update. Source findings
and recorded timing evidence retain the audit revision below; this publication
does not certify the newer firmware or motion implementation under full load.

## Source identity and coverage

| Authority inspected | Identity / result |
| --- | --- |
| Ainekio | Git `b46a5f7da7d25db945ca2c6e6321d344030acc3c`; P4 application, media, wake engine, PCA driver, protocol, gateway and V2 gait sources read. Existing budget/integration/index document changes preserved and expanded. |
| MetaHuman OS | Git `b57d205895d785d96194b9b9893f7c0b07838447`; repository guidance and maintained architecture read; voice lifecycle, Kokoro/Whisper servers, robot speech conversion/staging inspected. Pre-existing `etc/voice-servers.json` CPU settings preserved. |
| Installed host | Radxa Q6A, aarch64, kernel `6.18.2-3-qcom`; eight CPUs, four A55 and four A78. `/proc/meminfo` MemTotal = 11,835,852 KiB = 12,119,912,448 B. |
| Host storage | microSD block device 31,914,983,424 B; removable USB 31,406,948,352 B. Capacities are not RAM. |
| Local installation records | `Projects/ROBOT-SOFTWARE.md`, Q6A Qwen comparison and tuning summaries. Historical raw model tests were deleted at the owner's request; their summaries are explicitly historical. |
| Parts Overview | [Linked Google Doc](https://docs.google.com/document/d/1wz0kyqttPK3HHL0P0_9lLtRW_B87U5u4kEt-UhttHFA/edit) read through Google Drive. It describes the older S3/OV2640/eight-servo/OLED/2S-buck design. The owner's newer P4/OV5647/twelve-servo/1.9-inch LCD/Pouch choices govern this budget. |
| Missing equipment identifiers | Installed LCD controller/panel/backlight, camera module variant, SD card, twelve servos' electrical datasheet and final mechanical mass distribution are not established by those records. Their required budget inputs appear in the main document. |

## New offline Kokoro measurement

Used the installed MetaHuman Kokoro Python environment on this Q6A. Network
downloads disabled with `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`. No server,
speaker playback, personal text, robot connection or new model download.
Kokoro 0.9.4, PyTorch 2.14.0+cpu, American English, `af_heart`, speed 1,
eight PyTorch threads, existing cached model. All CPUs 0–7 were available;
no finite CPU quota was exposed in the inspected cgroup ancestry. Background
work, scheduling, thermal state and the existing OS remained uncontrolled.

Text: “The robot is ready. Camera, microphone, and body control are connected.”

| Stage | Elapsed seconds | Produced audio | Peak process RSS |
| --- | ---: | ---: | ---: |
| Construct KPipeline | 15.350627 | — | 1,503.378906 MiB |
| Synthesize 1 | 15.903561 | 5.000 s at 24 kHz | 1,537.796875 MiB |
| Synthesize 2 | 15.115047 | 5.000 s at 24 kHz | 1,537.796875 MiB |
| Synthesize 3 | 15.067830 | 5.000 s at 24 kHz | 1,537.796875 MiB |

Real-time factors: 3.180712, 3.023009, 3.013566. A factor above 1 means synthesis
was slower than playback. `resource.getrusage(RUSAGE_SELF).ru_maxrss` records a
process high-water mark, not steady resident use or incremental system RAM.
Elapsed load time starts immediately before KPipeline construction; Python and
package-import startup is excluded. These are three repetitions of one phrase,
not a universal ceiling, all-feature benchmark or thermal-soak result.

Reproduce inside the existing Kokoro environment, with the offline variables above:

```python
import time, resource, torch
from kokoro import KPipeline
torch.set_num_threads(8)
p = KPipeline(lang_code='a', device='cpu', repo_id='hexgrad/Kokoro-82M')
for _ in range(3):
    start = time.perf_counter()
    n = sum(r.output.audio.numel() for r in p(
        'The robot is ready. Camera, microphone, and body control are connected.',
        voice='af_heart', speed=1, split_pattern=None))
    elapsed = time.perf_counter() - start
    print(elapsed, n / 24000, elapsed / (n / 24000),
          resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
```

## Q6A Wi-Fi capability readback

Read-only `iw list` on the host, with sandbox permission granted. Driver reported:

```text
Supported interface modes: managed, AP, AP/VLAN, monitor, mesh point,
                           P2P-client, P2P-GO, P2P-device
valid interface combinations:
  #{ managed, mesh point } <= 1, #{ AP } <= 1,
  #{ P2P-client, P2P-GO } <= 1, #{ P2P-device } <= 1,
  total <= 4, #channels <= 3
```

Both 2.4 GHz and 5 GHz bands were listed, HE capability for managed/AP, one
spatial stream. **AP + station is advertised concurrently.** This is not proof
of simultaneous traffic throughput or independent radios. No hotspot was
created and the upstream connection was not changed.

## New source findings that affect final behavior

| Source owner | Finding / design consequence |
| --- | --- |
| P4 `main/controller.c`, `link_task` | Waits up to 20 ms on replies each iteration, then drains at most one microphone and one camera packet. A 20 ms audio producer requires at least 50 packet services/s while its gate is open. Send/wait time must be budgeted together; raw Wi-Fi throughput alone cannot qualify it. |
| Same file, `microphone` | Eight queued PCM packets; full queue increments `microphone_tx_drops`. It does not apply backpressure to microphone capture. |
| Same file, `send_packet` / `fail_link` | Binary send timeout 250 ms; metadata 100 ms. Failed authenticated link disables PCA outputs. A media transport failure can therefore interrupt body output. |
| P4 `components/ainekio_p4_media/media.c` | Four-block playback prebuffer, four DMA descriptors per direction; wake processing runs synchronously in microphone task. Larger sample blocks also enlarge local stack arrays. |
| Same file, `audio_start` | TX/RX use the same BCLK/WS GPIOs and duplex codec rate. A 24k speaker/16k mic network profile needs resampling; physical buffers follow the common rate. IDF's 4,092-byte DMA-buffer limit also prevents a packed 96k/24-bit 20 ms mono block from fitting one descriptor. |
| P4 `components/ainekio_p4_media/camera.c`, initialization; `sdkconfig.defaults` | Enables CSI + ISP for RGB565. Revision-matched P4 datasheet §4.2.1.2 limits ISP to 1920×1080, so sensor 5 MP capability is not current-pipeline capability. Hardware H.264 supports 1080p30 YUV420 (§4.2.1.5), but is disabled in configuration. |
| MetaHuman `tts/robot-speech.ts` | Collects the Kokoro stream before staging and enqueuing speech; cap 3 MiB / 64 chunks. Robot delivery does not begin at the first synthesis chunk. |
| MetaHuman `tts/robot-audio.ts` | Converts to 16 kHz mono 16-bit PCM, cap 480,000 B / 15 s; individual WAV cap 2 MiB; four staged artifacts. Raising P4 codec rate alone does not preserve higher-quality speech. |
| Ainekio `Master/gateway/environment_adapter/speech_transport.py` | Validates that same fixed format, frame length and 15 s cap. |
| Gateway `server/service.py` | Five-frame initial send prebuffer, thereafter 20 ms pacing; JSON/control and media use one WebSocket. Clock/state liveness is separate from physical joint feedback. |
| Gateway `environment_adapter/server.py` | One-item camera delivery queue drops the previous queued image when full. Base64 camera observations expand image storage/wire payload; JSON cap 384 KiB, binary cap 512 KiB. |
| `geometry.json` + `tools/compile_walk.py` | Compiled walk uses 92 mm full-stride stance sweep. `motions/walk/loop-contract.json` still says 52 mm. The budget derives speeds from the compiler's actual input, not the stale document. |
| Archived sampled `motions/locomotion/walk_forward/source.json` | Geometry hashes match but embedded `motion.c` and `walk_kinematics.c` hashes do not match current files. Excluded its sampled peak joint speeds from current motor qualification. |
| Local host storage dependency | Qwen model/projector now on microSD. Kokoro model cache still links to removable USB. The intended no-USB-peripheral robot therefore needs that cache relocated or an explicit USB-storage budget. |

## Measurement limits and closure inputs

The P4 was not connected to a current profiler for this audit. No current final
assembled robot exists in the recorded tests. Datasheets do not provide a
maximum current for the exact combined board, an unspecified LCD/SD/servo batch,
or execution time for an unimplemented controller. Consequently this audit
establishes capacities, source-owned allocations, documented component operating
points, rejected configurations and exact inequalities for the remaining loads.
It does not label a partial sum as a measured complete-system total.

The host process view in the normal sandbox exposed only sandbox processes;
it was not used to invent a resident-memory total for all host services. A
memory snapshot showed roughly 7.5–7.7 GiB available during the audit; that is
an instantaneous OS observation, not a reservation for the final robot.

## Primary specification register

| ID | Source / use |
| --- | --- |
| S1 | [Waveshare board](https://docs.waveshare.com/ESP32-P4-WIFI6) and [schematic](https://files.waveshare.com/wiki/ESP32-P4-WIFI6/ESP32-P4-WIFI6-datasheet.pdf): actual board, connectors and component identities. |
| S2 | [P4 datasheet v0.5](https://files.waveshare.com/wiki/common/Esp32-p4_datasheet_en.pdf): revision-matched capacity and current table 5-7. Newer generic P4X/400 MHz specifications are not substituted. |
| S3 | [C6 datasheet](https://documentation.espressif.com/esp32-c6_datasheet_en.html): radio operating currents and separate coprocessor capacity. |
| S4 | [Hosted 2.12.8](https://components.espressif.com/components/espressif/esp_hosted/versions/2.12.8/readme?language=en): four-bit SDIO TCP benchmark; C6 shield-box, 40 MHz Wi-Fi condition. |
| S5 | [IDF 5.5.4 JPEG benchmark](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32p4/api-reference/peripherals/jpeg.html): isolated 360 MHz / 200 MHz PSRAM encoder results. |
| S6 | [OmniVision OV5647 datasheet, Arducam mirror](https://www.arducam.com/downloads/modules/RaspberryPi_camera/OV5647DS.pdf): 2592×1944 at 15 fps; electrical-current table 8-3 contains TBD entries. [Manufacturer video announcement](https://www.ovt.com/press-releases/omnivision-introduces-1-4-inch-5-megapixel-raw-sensor-for-high-performance-mobile-applications/): 1080p30/720p60. |
| S7 | [ES8311 datasheet](https://files.waveshare.com/wiki/common/ES8311.DS.pdf): mono conversion, sample rates, word lengths and codec power. |
| S8 | [NS4150B manufacturer datasheet, distributor mirror](https://www.micros.com.pl/mediaserver/ULNS4150b_NSIWAY_0001.pdf): Jun.2022 v1.1, table 7, 8-ohm output and characterized efficiency. |
| S9 | [LSM6DS3 manufacturer datasheet](https://pccomponents.com/datasheets/ST_MI-LSM6DS3TR.pdf): ODR, FIFO, buses and currents. |
| S10 | [NXP PCA9685](https://www.nxp.com/docs/en/data-sheet/PCA9685.pdf): electrical table 14, PWM and I2C capacity. |
| S11 | [SHARGE Pouch](https://sharge.com/products/pouch) and [manual](https://cdn.shopify.com/s/files/1/0611/2234/7259/files/Pouch_3_in_1.pdf?v=1735982667): port ratings, 36 Wh and rated delivered capacity. Pouch Mini is a different product. |
| S12 | [Radxa Q6A](https://docs.radxa.com/en/dragon/q6a) and [product brief](https://dl.radxa.com/dragon/q6a/docs/rad-doc-0150_radxa_dragon_q6a_product_brief__revision_1.4_gdd1ea4b.pdf): CPU, accelerators and interfaces. Supply recommendation is not measured demand. |
| S13 | [Waveshare 1.9-inch module](https://www.waveshare.com/product/displays/lcd-oled/1.9inch-lcd-module.htm): CAD-reference candidate, 170×320 ST7789V2, six control/data signals; not confirmation of the owner's generic module. |
| S14 | [TowerPro MG90S](https://towerpro.com.tw/product/mg90s-3/): comparison only, 0.10 s/60° at 4.8 V; no stall-current rating. Not treated as the installed Miuzei servo's specification. |
| S15 | [P4 USB device stack](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32p4/api-reference/peripherals/usb_device.html): dedicated D+/D− and self-powered VBUS-sense requirement. |
| S16 | [YOLO11 model table](https://docs.ultralytics.com/models/yolo11): optional model operation/parameter counts; no Q6A FPS inferred from another CPU or GPU. [faster-whisper](https://github.com/SYSTRAN/faster-whisper): published CPU figures use a different machine/model and are not assigned to base.en on Q6A. |
| S17 | [IDF 5.5.4 I2S](https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32p4/api-reference/peripherals/i2s.html): shared full-duplex BCLK/WS and maximum 4,092-byte DMA buffer; packed network PCM is distinct from physical slot allocation. |

The missing installed-module identities cannot be filled by a same-size screen
or same-family servo listing. For example, Arducam B0033 publishes a 300 mA camera
peak, but that applies to its identified module, not every OV5647 assembly.
