#include "face_timeline.h"
#include "ainekio/face.h"
#include "ainekio/v2_motion.h"
#include <string.h>

bool ainekio_p4_face_select(ainekio_p4_face_selection_t *selection,
    const ainekio_face_selection_t *request, uint32_t revision, uint64_t now_ms)
{
    if (selection->expires_ms && now_ms>=selection->expires_ms) selection->active=false;
    if (request->if_token[0] && (!selection->active || strcmp(selection->token, request->if_token))) return true;
    if (request->release) {
        if (request->token[0] && !strcmp(selection->token, request->token)) selection->active=false;
        return true;
    }
    size_t face;
    if (!ainekio_face_find(request->expression, &face)) return false;
    *selection=(ainekio_p4_face_selection_t){.face=face, .revision=revision,
        .started_ms=now_ms, .expires_ms=request->timeout_ms ? now_ms+request->timeout_ms : 0,
        .active=true, .background=request->background,
        .legacy=!request->token[0] && !request->timeout_ms && !request->background};
    memcpy(selection->token, request->token, sizeof(selection->token));
    return true;
}

ainekio_p4_face_sample_t ainekio_p4_face_selected(ainekio_p4_face_selection_t *selection,
    ainekio_p4_face_sample_t underlying, uint32_t revision, bool moving, bool talking, uint64_t now_ms)
{
    if ((selection->expires_ms && now_ms>=selection->expires_ms) ||
        (selection->legacy && selection->revision!=revision)) selection->active=false;
    if (!selection->active || (selection->background && (moving || talking))) return underlying;
    return (ainekio_p4_face_sample_t){.face=selection->face, .elapsed_ms=now_ms-selection->started_ms};
}

ainekio_p4_face_sample_t ainekio_p4_face_sample(const ainekio_p4_body_status_t *body,
                                              uint64_t idle_ms)
{
    ainekio_p4_face_sample_t sample={.elapsed_ms=idle_ms};
    ainekio_face_find("default",&sample.face);
    if(!body||!body->face_command)return sample;
    ainekio_face_find(body->face_command,&sample.face);
    if(body->face_entering){sample.elapsed_ms=0;return sample;}
    if(!body->face_is_clip){
        if(body->moving)sample.elapsed_ms=body->face_elapsed_us/1000;
        return sample;
    }
    sample.elapsed_ms=body->face_elapsed_us/1000;
    const ainekio_v2_clip_t *clip=&ainekio_v2_clips[body->face_clip];
    const ainekio_v2_face_cue_t *selected=NULL;
    for(size_t i=0;i<clip->face_cue_count;++i)
        if(clip->face_cues[i].at_us<=body->face_elapsed_us)selected=&clip->face_cues[i];
    if(selected&&ainekio_face_find(selected->name,&sample.face)){
        sample.elapsed_ms=(body->face_elapsed_us-selected->at_us)/1000;
        if(!body->moving)sample.elapsed_ms+=idle_ms;
        const uint32_t period=ainekio_face_period_ms(sample.face);
        if(selected->mode==AINEKIO_V2_FACE_ONCE&&sample.elapsed_ms>=period)sample.elapsed_ms=period-1;
        if(selected->mode==AINEKIO_V2_FACE_BOOMERANG){
            sample.elapsed_ms%=2*period;
            if(sample.elapsed_ms>=period)sample.elapsed_ms=2*period-1-sample.elapsed_ms;
        }
    }
    /* The standing identity keeps breathing and blinking after the terminal
     * standing-face cue, as it does at power-on. */
    if(!body->moving){
        const char *name=ainekio_face_name(sample.face);
        if(!strcmp(name,"stand")||!strcmp(name,"default")||!strcmp(name,"idle"))sample.elapsed_ms=idle_ms;
        else if(!selected)sample.elapsed_ms+=idle_ms;
    }
    return sample;
}


ainekio_p4_face_sample_t ainekio_p4_face_listen(ainekio_p4_face_sample_t previous,
                                             bool capturing, uint64_t elapsed_ms)
{
    if (capturing) {
        ainekio_face_find("listening", &previous.face);
        previous.elapsed_ms = elapsed_ms;
    }
    return previous;
}
