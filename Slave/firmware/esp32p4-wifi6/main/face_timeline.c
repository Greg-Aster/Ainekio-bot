#include "face_timeline.h"
#include "ainekio/face.h"
#include "ainekio/v2_motion.h"
#include <string.h>

static bool layer_active(const ainekio_p4_face_layer_t *layer, uint64_t at_ms)
{
    return layer->active && at_ms>=layer->started_ms &&
        (!layer->expires_ms || at_ms<layer->expires_ms);
}

const char *ainekio_p4_face_token(const ainekio_p4_face_selection_t *selection, uint64_t at_ms)
{
    if (layer_active(&selection->foreground,at_ms)) return selection->foreground.token;
    return layer_active(&selection->background,at_ms) ? selection->background.token : "";
}

bool ainekio_p4_face_select(ainekio_p4_face_selection_t *selection,
    const ainekio_face_selection_t *request, uint32_t revision, uint64_t now_ms)
{
    if (request->if_token[0] && strcmp(ainekio_p4_face_token(selection,now_ms),request->if_token)) return true;
    if (request->release) {
        if (request->token[0]) {
            if (!strcmp(selection->foreground.token,request->token)) selection->foreground.active=false;
            if (!strcmp(selection->background.token,request->token)) selection->background.active=false;
        }
        return true;
    }
    size_t face;
    if (!ainekio_face_find(request->expression, &face)) return false;
    ainekio_p4_face_layer_t *layer=request->background ? &selection->background : &selection->foreground;
    *layer=(ainekio_p4_face_layer_t){.face=face, .revision=revision,
        .started_ms=now_ms, .expires_ms=request->timeout_ms ? now_ms+request->timeout_ms : 0,
        .active=true, .background=request->background,
        .legacy=!request->token[0] && !request->timeout_ms && !request->background};
    memcpy(layer->token, request->token, sizeof(layer->token));
    return true;
}

ainekio_p4_face_sample_t ainekio_p4_face_selected(ainekio_p4_face_selection_t *selection,
    ainekio_p4_face_sample_t underlying, uint32_t revision, bool moving, bool talking, uint64_t now_ms)
{
    ainekio_p4_face_layer_t *layers[]={&selection->foreground,&selection->background};
    for (size_t i=0;i<2;++i) {
        ainekio_p4_face_layer_t *layer=layers[i];
        if ((layer->expires_ms && now_ms>=layer->expires_ms) ||
            (layer->legacy && layer->revision!=revision)) layer->active=false;
    }
    for (size_t i=0;i<2;++i) {
        const ainekio_p4_face_layer_t *layer=layers[i];
        if (layer_active(layer,now_ms) && !(layer->background && (moving || talking)))
            return (ainekio_p4_face_sample_t){.face=layer->face, .elapsed_ms=now_ms-layer->started_ms};
    }
    return underlying;
}

ainekio_p4_face_sample_t ainekio_p4_face_sample(ainekio_p4_face_clock_t *clock,
    const ainekio_p4_body_status_t *body,uint64_t now_ms)
{
    ainekio_p4_face_sample_t sample={0};
    ainekio_face_find("default",&sample.face);
    size_t clip_index=SIZE_MAX,cue_index=SIZE_MAX;
    const ainekio_v2_face_cue_t *selected=NULL;
    if(body && body->face_command) {
        ainekio_face_find(body->face_command,&sample.face);
        if(body->face_is_clip) {
            clip_index=body->face_clip;
            const ainekio_v2_clip_t *clip=&ainekio_v2_clips[clip_index];
            if(!body->face_entering)for(size_t i=0;i<clip->face_cue_count;++i)
                if(clip->face_cues[i].at_us<=body->face_elapsed_us) {
                    selected=&clip->face_cues[i];cue_index=i;
                }
            if(selected)ainekio_face_find(selected->name,&sample.face);
        }
    }
    const uint32_t revision=body ? body->face_revision : 0;
    if(!clock->initialized || clock->revision!=revision || clock->face!=sample.face ||
       clock->clip!=clip_index || clock->cue!=cue_index) {
        *clock=(ainekio_p4_face_clock_t){.initialized=true,.face=sample.face,
            .clip=clip_index,.cue=cue_index,.revision=revision,.started_ms=now_ms};
    }
    sample.elapsed_ms=now_ms-clock->started_ms;
    /* The same cue keeps animating while a target is held. Only a new cue or
     * command resets animation; source progress alone never drives its clock. */
    const char *name=ainekio_face_name(sample.face);
    const bool idle=!body || !body->moving;
    const bool idle_identity=idle && (!strcmp(name,"stand") || !strcmp(name,"default") || !strcmp(name,"idle"));
    if(selected && !idle_identity) {
        const uint32_t period=ainekio_face_period_ms(sample.face);
        if(selected->mode==AINEKIO_V2_FACE_ONCE && sample.elapsed_ms>=period)sample.elapsed_ms=period-1;
        if(selected->mode==AINEKIO_V2_FACE_BOOMERANG) {
            sample.elapsed_ms%=2*period;
            if(sample.elapsed_ms>=period)sample.elapsed_ms=2*period-1-sample.elapsed_ms;
        }
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
