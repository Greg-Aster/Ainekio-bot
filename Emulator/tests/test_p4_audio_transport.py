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
typedef void *esp_websocket_client_handle_t;
#define pdTRUE 1
#define pdMS_TO_TICKS(ms) (ms)
'''+packet+r'''
static packet_t queue[8];
static unsigned queued, failures;
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
    if (queued == 8) return 0;
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
    const bool wake = strcmp(argv[1], "vad") != 0;
    const uint64_t session = strcmp(argv[1], "stale") ? 42 : 41;
    uint8_t pcm[AINEKIO_AUDIO_PAYLOAD_BYTES];
    gate_event(NULL, session, true, wake);
    /* Five pre-roll frames plus the detection frame; delay the sender until
     * close is also queued to expose start/finish overtaking the samples. */
    for (unsigned i = 0; i < 6; ++i) {
        memset(pcm, i + 1, sizeof(pcm));
        microphone(NULL, session, pcm);
    }
    gate_event(NULL, session, false, false);
    assert(failures == 0 && atomic_load(&microphone_tx_drops) == 0);
    assert(listen_opened == (session == 42 ? 1U : 0U));
    assert(listen_closed == (session == 42 ? 1U : 0U));
    for (unsigned i = 0; i < queued; ++i) send_packet(NULL, &queue[i]);
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
        self.assertEqual(subprocess.check_output([str(self.binary), "stale"], text=True), "")
