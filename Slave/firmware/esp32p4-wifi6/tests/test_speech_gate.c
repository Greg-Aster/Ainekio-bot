#include "speech_gate.h"
#include "ainekio/control_codec.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

int main(void)
{
    ainekio_control_message_t command;
    const char *edit = "{\"t\":\"mic\",\"seq\":1,\"on\":true,\"gate\":\"wake\",\"vad_mode\":1,\"silence_ms\":2000,\"max_recording_ms\":5000}";
    assert(ainekio_control_decode_for_body(edit, strlen(edit), &command) == AINEKIO_DECODE_OK);
    const ainekio_speech_settings_t settings = command.command.data.microphone.speech;
    assert(settings.has_vad_mode && settings.vad_mode==1);
    assert(settings.has_silence_ms && settings.silence_ms==2000);
    assert(settings.has_max_recording_ms && settings.max_recording_ms==5000);
    const char *legacy = "{\"t\":\"mic\",\"seq\":2,\"on\":true,\"gate\":\"wake\"}";
    assert(ainekio_control_decode_for_body(legacy, strlen(legacy), &command) == AINEKIO_DECODE_OK);
    assert(!command.command.data.microphone.speech.has_vad_mode);
    assert(!command.command.data.microphone.speech.has_silence_ms);
    assert(!command.command.data.microphone.speech.has_max_recording_ms);
    p4_speech_gate_t recording = {0};
    assert(p4_speech_gate_step(&recording, AINEKIO_MIC_GATE_WAKE, true, true, 2000, 15000, 0));
    /* A natural 1.5-second pause remains inside the same wake recording. */
    for (int i=1; i<=75; ++i)
        assert(p4_speech_gate_step(&recording, AINEKIO_MIC_GATE_WAKE, false, false, 2000, 15000, i*20000));
    assert(p4_speech_gate_step(&recording, AINEKIO_MIC_GATE_WAKE, false, true, 2000, 15000, 1520000));
    for (int i=1; i<100; ++i)
        assert(p4_speech_gate_step(&recording, AINEKIO_MIC_GATE_WAKE, false, false, 2000, 15000, 1520000+i*20000));
    assert(!p4_speech_gate_step(&recording, AINEKIO_MIC_GATE_WAKE, false, false, 2000, 15000, 3520000));
    assert(!recording.wake_latched);
    /* Wake acquisition has no independent three-second timer. A detector that
     * initially misses speech must not discard the recording at that boundary. */
    recording = (p4_speech_gate_t){0};
    assert(p4_speech_gate_step(&recording, AINEKIO_MIC_GATE_WAKE, true, false, 1500, 15000, 0));
    for (int i=1; i<=200; ++i)
        assert(p4_speech_gate_step(&recording, AINEKIO_MIC_GATE_WAKE, false, false, 1500, 15000, i*20000));
    assert(p4_speech_gate_step(&recording, AINEKIO_MIC_GATE_WAKE, false, true, 1500, 15000, 4020000));
    assert(p4_speech_gate_step(&recording, AINEKIO_MIC_GATE_WAKE, false, false, 1500, 15000, 5500000));
    assert(!p4_speech_gate_step(&recording, AINEKIO_MIC_GATE_WAKE, false, false, 1500, 15000, 5520000));
    assert(!recording.wake_latched);
    /* With no detected speech at all, only the selected wake maximum applies. */
    assert(p4_speech_gate_step(&recording, AINEKIO_MIC_GATE_WAKE, true, false, 1500, 5000, 6000000));
    assert(p4_speech_gate_step(&recording, AINEKIO_MIC_GATE_WAKE, false, false, 1500, 5000, 10980000));
    assert(!p4_speech_gate_step(&recording, AINEKIO_MIC_GATE_WAKE, false, false, 1500, 5000, 11000000));
    /* Pause seconds measure elapsed time, not how many buffered frames run. */
    recording = (p4_speech_gate_t){0};
    assert(p4_speech_gate_step(&recording, AINEKIO_MIC_GATE_VAD, false, true, 40, 15000, 12000000));
    for (int i=1; i<=50; ++i)
        assert(p4_speech_gate_step(&recording, AINEKIO_MIC_GATE_VAD, false, false, 40, 15000, 12000000+i));
    assert(!p4_speech_gate_step(&recording, AINEKIO_MIC_GATE_VAD, false, false, 40, 15000, 12040000));
    recording = (p4_speech_gate_t){0};
    /* Another wake re-arms; the selected shorter maximum closes even speech. */
    assert(p4_speech_gate_step(&recording, AINEKIO_MIC_GATE_WAKE, true, true, 1000, 5000, 4000000));
    assert(p4_speech_gate_step(&recording, AINEKIO_MIC_GATE_WAKE, false, true, 1000, 5000, 8980000));
    assert(!p4_speech_gate_step(&recording, AINEKIO_MIC_GATE_WAKE, false, true, 1000, 5000, 9000000));
    assert(!p4_speech_gate_step(&recording, AINEKIO_MIC_GATE_WAKE, false, true, 1000, 5000, 9020000));
    /* Session/playback/configuration replacement starts with fresh state. */
    recording = (p4_speech_gate_t){0};
    assert(!p4_speech_gate_step(&recording, AINEKIO_MIC_GATE_WAKE, false, true, 1000, 15000, 10000000));
    assert(p4_speech_gate_step(&recording, AINEKIO_MIC_GATE_VAD, false, true, 40, 15000, 10020000));
    assert(p4_speech_gate_step(&recording, AINEKIO_MIC_GATE_VAD, false, false, 40, 15000, 10040000));
    assert(!p4_speech_gate_step(&recording, AINEKIO_MIC_GATE_VAD, false, false, 40, 15000, 10060000));
    assert(p4_speech_gate_step(&recording, AINEKIO_MIC_GATE_OPEN, false, false, 40, 15000, 10080000));
    puts("Configured recording windows, no acquisition cutoff, pause, re-arm and reset passed");
    return 0;
}
