#include "face_timeline.h"
#include "ainekio/face.h"
#include "ainekio/v2_motion.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

int main(void)
{
    /* Replacement owns one deadline; no timer from the previous face survives. */
    ainekio_p4_face_selection_t selection={0};
    ainekio_face_selection_t thinking={.expression="thinking",.token="first",.timeout_ms=1000,.background=true};
    ainekio_face_selection_t happy={.expression="happy",.token="second",.timeout_ms=5000};
    ainekio_p4_face_sample_t base={.elapsed_ms=500};
    assert(ainekio_face_find("stand",&base.face));
    assert(ainekio_p4_face_select(&selection,&thinking,1,100));
    assert(!strcmp(ainekio_face_name(ainekio_p4_face_selected(&selection,base,1,false,false,200).face),"thinking"));
    assert(ainekio_p4_face_selected(&selection,base,2,true,false,300).face==base.face);
    assert(ainekio_p4_face_selected(&selection,base,2,false,true,400).face==base.face);
    assert(!strcmp(ainekio_face_name(ainekio_p4_face_selected(&selection,base,2,false,false,500).face),"thinking"));
    assert(ainekio_p4_face_select(&selection,&happy,2,600));
    ainekio_face_selection_t release={.token="first",.release=true};
    assert(ainekio_p4_face_select(&selection,&release,2,700));
    assert(!strcmp(ainekio_face_name(ainekio_p4_face_selected(&selection,base,2,false,false,1100).face),"happy"));
    ainekio_face_selection_t error={.expression="confused",.token="first",.if_token="first",.timeout_ms=5000};
    assert(ainekio_p4_face_select(&selection,&error,2,1200));
    assert(!strcmp(ainekio_face_name(selection.face),"happy"));
    assert(ainekio_p4_face_selected(&selection,base,2,false,false,5600).face==base.face);
    assert(!selection.active);
    assert(ainekio_p4_face_select(&selection,&thinking,2,6000));
    assert(ainekio_p4_face_select(&selection,&release,2,6100));
    assert(ainekio_p4_face_selected(&selection,base,2,false,false,6200).face==base.face);
    /* Timed feedback must not narrow the legacy library's manual face behavior. */
    happy=(ainekio_face_selection_t){.expression="happy"};
    assert(ainekio_p4_face_select(&selection,&happy,3,7000));
    assert(!strcmp(ainekio_face_name(ainekio_p4_face_selected(&selection,base,3,false,false,99000).face),"happy"));
    assert(ainekio_p4_face_selected(&selection,base,4,true,false,100000).face==base.face);
    ainekio_p4_body_status_t body={0};
    ainekio_p4_face_sample_t sample=ainekio_p4_face_sample(&body,520);
    assert(!strcmp(ainekio_face_name(sample.face),"default")&&sample.elapsed_ms==520);
    for(size_t i=0;i<ainekio_v2_clip_count;++i){
        const ainekio_v2_clip_t *clip=&ainekio_v2_clips[i];
        size_t index;assert(ainekio_face_find(clip->command,&index));
        uint64_t last=0;
        for(size_t k=0;k<clip->face_cue_count;++k){
            const ainekio_v2_face_cue_t *cue=&clip->face_cues[k];
            assert(cue->at_us>=last&&cue->at_us<=clip->duration_us);
            assert(ainekio_face_find(cue->name,&index));last=cue->at_us;
            body=(ainekio_p4_body_status_t){.face_command=clip->command,.face_clip=i,.face_is_clip=true,
                .moving=true,.face_elapsed_us=cue->at_us};
            sample=ainekio_p4_face_sample(&body,999999);
            assert(sample.face==index&&sample.elapsed_ms==0);
        }
    }
    size_t wave;assert(ainekio_v2_clip_find("wave",&wave));
    body=(ainekio_p4_body_status_t){.face_command="wave",.face_clip=wave,.face_is_clip=true,.moving=true,.face_entering=true};
    sample=ainekio_p4_face_sample(&body,999999);
    assert(!strcmp(ainekio_face_name(sample.face),"wave")&&sample.elapsed_ms==0);
    body.face_entering=false;body.face_elapsed_us=ainekio_v2_clips[wave].duration_us;body.moving=false;
    sample=ainekio_p4_face_sample(&body,733);
    assert(!strcmp(ainekio_face_name(sample.face),"stand")&&sample.elapsed_ms==733);
    size_t rest;assert(ainekio_v2_clip_find("rest",&rest));
    body=(ainekio_p4_body_status_t){.face_command="rest",.face_clip=rest,.face_is_clip=true,.moving=false,
        .face_elapsed_us=ainekio_v2_clips[rest].duration_us};
    sample=ainekio_p4_face_sample(&body,100);
    assert(sample.elapsed_ms!=ainekio_p4_face_sample(&body,600).elapsed_ms);
    body=(ainekio_p4_body_status_t){.face_command="crawl",.moving=true,.face_elapsed_us=321000};
    sample=ainekio_p4_face_sample(&body,999999);
    assert(!strcmp(ainekio_face_name(sample.face),"crawl")&&sample.elapsed_ms==321);
    /* A temporary listen overlay retains both manual and motion expressions. */
    size_t love;assert(ainekio_face_find("love",&love));
    ainekio_p4_face_sample_t previous={.face=love,.elapsed_ms=730};
    sample=ainekio_p4_face_listen(previous,true,123);
    assert(!strcmp(ainekio_face_name(sample.face),"listening") && sample.elapsed_ms==123);
    sample=ainekio_p4_face_listen(previous,false,999);
    assert(sample.face==love && sample.elapsed_ms==730);
    previous=ainekio_p4_face_sample(&body,200);
    sample=ainekio_p4_face_listen(previous,true,555);
    assert(!strcmp(ainekio_face_name(sample.face),"listening"));
    sample=ainekio_p4_face_listen(previous,false,999);
    assert(sample.face==previous.face && sample.elapsed_ms==previous.elapsed_ms);
    puts("All 23 motions and retained cues resolve; entry, body clock, terminal idle and continuing Rest animation pass.");
    return 0;
}
