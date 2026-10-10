"""Run the P4's C microphone callbacks through the real gateway assembler.

Only the queue, session check and WebSocket I/O are replaced. Extracting these
small static callbacks avoids duplicating their logic or shimming unrelated
Wi-Fi/servo owners just to compile the complete controller translation unit.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from gateway.plugins import AudioUtteranceAssembler

ROOT = Path(__file__).resolve().parents[2]
CONTROLLER = ROOT / "Slave/firmware/esp32p4-wifi6/main/controller.c"
CORE = ROOT / "Slave/software/core"


def controller_function(source: str, name: str) -> str:
    start = source.index(f"static void {name}(")
    # These functions all end at the unindented closing brace.
    end = source.index("\n}", start) + 2
    return source[start:end]


class P4AudioTransportTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.work = tempfile.TemporaryDirectory(prefix="ainekio-p4-audio-")
        cls.binary = Path(cls.work.name) / "audio_transport"
        source = CONTROLLER.read_text()
        packet = next(
            item for item in re.findall(r"typedef struct \{[^}]*\} \w+;", source)
            if item.endswith("} packet_t;")
        )
        harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdatomic.h>
#include "ainekio/binary_codec.h"
#include "ainekio/control_encode.h"
#include "ainekio/p4_media.h"
typedef void *esp_websocket_client_handle_t;
#define pdTRUE 1
#define pdMS_TO_TICKS(ms) (ms)
#define ESP_LOGW(tag, ...) ((void)(tag), (void)fprintf(stderr, __VA_ARGS__))
'''+packet+r'''
static packet_t queue[50];
static unsigned queued, failures;
static uint64_t clock_us;
static esp_err_t snapshot_result = ESP_OK;
uint64_t now_us(void) { return clock_us; }
const char *esp_err_to_name(esp_err_t result) { (void)result;return "fixture"; }
esp_err_t ainekio_p4_media_snapshot(ainekio_camera_origin_t origin, uint32_t id)
{
    assert(origin == AINEKIO_CAMERA_ORIGIN_AUDIO);
    printf("SNAPSHOT %u\n", id);
    return snapshot_result;
}
static void *audio_packets = queue;
static atomic_uint microphone_counter, microphone_tx_drops, stopped_sequence;
static bool current_connection(uint64_t session) { return session == 42; }
static struct { struct { ainekio_mode_t mode; } core; } admission;
static void enter(void) {}
static void leave(void) {}
static unsigned listen_opened, listen_closed;
static void ainekio_p4_body_listen(bool active) { if(active)listen_opened++;else listen_closed++; }
static void fail_link(void) { ++failures; }
static int xQueueSend(void *handle, const void *item, unsigned timeout)
{
    (void)timeout;
    assert(handle == audio_packets);
    if (queued == 50) return 0;
    queue[queued++] = *(const packet_t *)item;
    return pdTRUE;
}
static int esp_websocket_client_send_text(void *client, const char *text, size_t size, unsigned timeout)
{
    (void)client; (void)timeout;
    printf("%.*s\n", (int)size, text);
    return (int)size;
}
static int esp_websocket_client_send_bin(void *client, const char *data, size_t size, unsigned timeout)
{
    (void)client; (void)timeout;
    assert(data && size >= AINEKIO_BINARY_HEADER_BYTES);
    printf("PCM ");
    for (size_t i = 0; i < size; ++i) printf("%02x", (unsigned char)data[i]);
    putchar('\n');
    return (int)size;
}
static void reply(uint64_t session, const char *text)
{
    assert(session == 42);
    puts(text);
}
/* The previous controller sent gate events through an unrelated queue. Model
 * the permitted case where those events drain before its delayed PCM FIFO. */
void media_event(uint64_t session, uint32_t sequence, const char *text)
{
    (void)sequence;
    if (current_connection(session)) puts(text);
}
'''
        harness += "\n".join(controller_function(source, name) for name in (
            "microphone", "gate_event", "send_packet",
        ))
        harness += r'''
int main(int argc, char **argv)
{
    assert(argc == 2);
    admission.core.mode = AINEKIO_MODE_NORMAL;
    const bool wake = strncmp(argv[1], "vad", 3) != 0;
    const uint64_t session = strncmp(argv[1], "stale", 5) ? 42 : 41;
    const bool photo = strstr(argv[1], "photo") != NULL;
    if (strcmp(argv[1], "photo-error") == 0) snapshot_result = ESP_FAIL;
    const unsigned frames = photo ? 15 : strcmp(argv[1], "short") == 0 ? 14 : 6;
    const unsigned turns = photo ? 2 : 1;
    uint8_t pcm[AINEKIO_AUDIO_PAYLOAD_BYTES];
    for (unsigned turn = 0; turn < turns; ++turn) {
        gate_event(NULL, session, true, wake);
        /* Delay the sender until close is queued to expose boundaries
         * overtaking PCM. Snapshot capture never needs to finish first. */
        for (unsigned i = 0; i < frames; ++i) {
            memset(pcm, i + 1, sizeof(pcm));
            microphone(NULL, session, pcm);
            clock_us += 20000;
        }
        gate_event(NULL, session, false, false);
        assert(failures == 0 && atomic_load(&microphone_tx_drops) == 0);
        assert(listen_opened == (session == 42 ? turn + 1 : 0U));
        assert(listen_closed == (session == 42 ? turn + 1 : 0U));
        for (unsigned i = 0; i < queued; ++i) send_packet(NULL, &queue[i]);
        queued = 0;
    }
    assert(failures == 0);
    return 0;
}
'''
        path = Path(cls.work.name) / "audio_transport.c"
        path.write_text(harness)
        subprocess.run([
            "cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
            "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
            "-I", str(CORE / "include"), str(path),
            "-I", str(ROOT / "Slave/firmware/esp32p4-wifi6/components/ainekio_p4_media/include"),
            "-I", str(ROOT / "Slave/firmware/esp32p4-wifi6/tests/body_shim"),
            str(CORE / "src/binary_codec.c"), str(CORE / "src/control_encode.c"),
            "-o", str(cls.binary),
        ], check=True, capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.work.cleanup()

    async def test_wake_and_vad_deliver_complete_ordered_recordings(self) -> None:
        for mode in ("wake", "vad"):
            with self.subTest(mode=mode):
                completed = []
                assembler = AudioUtteranceAssembler(completed.append)
                identity = {"robot_id": "p4-test", "epoch": 1}
                wire = subprocess.check_output([str(self.binary), mode], text=True).splitlines()
                events = []
                for line in wire:
                    if line.startswith("PCM "):
                        raw = bytes.fromhex(line[4:])
                        await assembler.handle_frame({
                            **identity, "frame_type": raw[0],
                            "counter": int.from_bytes(raw[1:5], "little"), "payload": raw[5:],
                        })
                    else:
                        event = json.loads(line)
                        events.append(event["name"])
                        await assembler.handle_event({**identity, **event})
                self.assertEqual(events, ["vad_open", "wake_word", "vad_close"]
                                 if mode == "wake" else ["vad_open", "vad_close"])
                self.assertEqual(len(completed), 1)
                recording = completed[0]
                self.assertEqual(recording.pcm, b"".join(bytes([i + 1]) * 640 for i in range(6)))
                self.assertEqual(recording.frame_count, 6)
                self.assertEqual(recording.duration_ms, 120)
                self.assertEqual(recording.missing_frames, 0)
                self.assertEqual(recording.wake_triggered, mode == "wake")
                self.assertFalse(recording.truncated)

    async def test_old_connection_cannot_deliver_audio_or_boundaries(self) -> None:
        for mode in ("stale", "stale-photo"):
            self.assertEqual(subprocess.check_output([str(self.binary), mode], text=True), "")

    async def test_wake_photos_share_recording_identity_and_do_not_hold_audio(self) -> None:
        for mode in ("photo", "photo-error", "vad-photo", "short"):
            with self.subTest(mode=mode):
                completed = []
                assembler = AudioUtteranceAssembler(completed.append)
                identity = {"robot_id": "p4-test", "epoch": 1}
                snapshots = []
                boundaries = []
                result = subprocess.run([str(self.binary), mode], check=True, capture_output=True, text=True)
                self.assertEqual(result.stderr.count("Wake speech snapshot enqueue failed"), 2 if mode == "photo-error" else 0)
                for line in result.stdout.splitlines():
                    if line.startswith("SNAPSHOT "):
                        snapshots.append(int(line.split()[1]))
                    elif line.startswith("PCM "):
                        raw = bytes.fromhex(line[4:])
                        await assembler.handle_frame({**identity, "frame_type": raw[0],
                            "counter": int.from_bytes(raw[1:5], "little"), "payload": raw[5:]})
                    else:
                        event = json.loads(line)
                        if event["name"] in ("vad_open", "vad_close"):
                            boundaries.append(event)
                        await assembler.handle_event({**identity, **event})
                self.assertEqual(snapshots, [0, 15] if mode in ("photo", "photo-error") else [])
                self.assertEqual(len(completed), 1 if mode == "short" else 2)
                for index, recording in enumerate(completed):
                    origin = index * 15
                    self.assertEqual(recording.utterance_id, f"audio:p4-test:1:{origin}")
                    self.assertEqual(recording.duration_ms, 280 if mode == "short" else 300)
                    self.assertEqual(recording.frame_count, 14 if mode == "short" else 15)
                    self.assertEqual(recording.wake_triggered, mode != "vad-photo")
                    self.assertEqual([boundary.get("origin_id") for boundary in boundaries[index*2:index*2+2]], [origin, origin])

    async def test_p4_speech_and_photos_reach_the_bridge_with_matching_ids(self) -> None:
        from gateway.environment_adapter import EnvironmentAdapter, EnvironmentAdapterConfig
        from protocol.binary_helpers import CAMERA_JPEG_FRAME_TYPE
        from Emulator.tests.test_environment_adapter import FakeGateway, FakeWebSocket

        gateway, websocket = FakeGateway(), FakeWebSocket()
        adapter = EnvironmentAdapter(gateway, EnvironmentAdapterConfig(receipt_path=":memory:", token="fixture"))
        adapter._websocket = websocket
        identity = {"robot_id": "test-body", "epoch": 1}
        async def event(value):
            for callback in gateway.event_callbacks:
                await callback(value)
        async def frame(value):
            for callback in gateway.frame_callbacks:
                await callback(value)
        for line in subprocess.check_output([str(self.binary), "photo"], text=True).splitlines():
            if line.startswith("SNAPSHOT "):
                origin = int(line.split()[1])
                await event({**identity, "t": "cam_meta", "res": "XGA", "fps": 0,
                    "counter_base": origin, "origin": "audio", "origin_id": origin})
                await frame({**identity, "frame_type": CAMERA_JPEG_FRAME_TYPE,
                    "counter": origin, "payload": b"\xff\xd8\xff\xda\x00\x00\xff\xd9"})
            elif line.startswith("PCM "):
                raw = bytes.fromhex(line[4:])
                await frame({**identity, "frame_type": raw[0],
                    "counter": int.from_bytes(raw[1:5], "little"), "payload": raw[5:]})
            else:
                await event({**identity, **json.loads(line)})
        audio_ids, image_ids = [], []
        for message in websocket.sent:
            if isinstance(message, bytes):
                size = int.from_bytes(message[8:12], "little")
                audio_ids.append(json.loads(message[12:12+size])["utteranceId"])
            else:
                value = json.loads(message)
                if value.get("type") == "environment.observation":
                    observation = value["observation"]
                    image_ids.append(observation["visual"]["metadata"]["audioUtteranceId"])
                    self.assertEqual(image_ids[-1], observation["metadata"]["audioUtteranceId"])
        self.assertEqual(audio_ids, ["audio:test-body:1:0", "audio:test-body:1:15"])
        self.assertEqual(image_ids, audio_ids)
        self.assertEqual(gateway.calls, [], "Firmware photos do not require a second gateway capture command")
