#include "face_timeline.h"
#include "ainekio/face.h"
#include "ainekio/v2_motion.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

int main(void)
{
    /* The notification landmark follows the selected token, including overlays,
     * and ends on replacement, release or expiry without a second timer. */
    ainekio_p4_face_selection_t reaction={0};
    ainekio_face_selection_t surprise={.expression="surprised",.token="be_fixture",.timeout_ms=60000};
    assert(ainekio_p4_face_select(&reaction,&surprise,1,100));
    assert(!strcmp(ainekio_p4_face_token(&reaction,99),""));
    assert(!strcmp(ainekio_p4_face_token(&reaction,100),"be_fixture"));
    ainekio_p4_face_sample_t underlying={0};
    ainekio_p4_face_selected(&reaction,underlying,2,true,true,200);
    assert(!strcmp(ainekio_p4_face_token(&reaction,200),"be_fixture"));
    assert(!strcmp(ainekio_p4_face_token(&reaction,60099),"be_fixture"));
    assert(!strcmp(ainekio_p4_face_token(&reaction,60100),""));
    assert(ainekio_p4_face_select(&reaction,&surprise,2,70000));
    ainekio_face_selection_t replacement={.expression="happy",.token="ordinary_face",.timeout_ms=60000};
    assert(ainekio_p4_face_select(&reaction,&replacement,2,71000));
    ainekio_face_selection_t old_release={.token="be_fixture",.release=true};
    assert(ainekio_p4_face_select(&reaction,&old_release,2,72000));
    assert(!strcmp(ainekio_p4_face_token(&reaction,72000),"ordinary_face"));
    assert(ainekio_p4_face_select(&reaction,&surprise,2,73000));
    assert(ainekio_p4_face_select(&reaction,&old_release,2,74000));
    assert(!strcmp(ainekio_p4_face_token(&reaction,74000),""));
    /* Background work neither replaces the reaction landmark nor extends it.
     * Releasing foreground reveals a still-active background selection. */
    ainekio_face_selection_t backdrop={.expression="thinking",.token="bg",.timeout_ms=60000,.background=true};
    assert(ainekio_p4_face_select(&reaction,&surprise,2,80000));
    assert(ainekio_p4_face_select(&reaction,&backdrop,2,81000));
    assert(!strcmp(ainekio_p4_face_token(&reaction,82000),"be_fixture"));
    assert(!strcmp(ainekio_face_name(ainekio_p4_face_selected(&reaction,underlying,2,false,false,82000).face),"surprised"));
    ainekio_face_selection_t bg_release={.token="bg",.release=true};
    assert(ainekio_p4_face_select(&reaction,&bg_release,2,83000));
    assert(!strcmp(ainekio_p4_face_token(&reaction,83000),"be_fixture"));
    assert(ainekio_p4_face_select(&reaction,&backdrop,2,84000));
    assert(ainekio_p4_face_select(&reaction,&old_release,2,85000));
    assert(!strcmp(ainekio_p4_face_token(&reaction,85000),"bg"));
    assert(!strcmp(ainekio_face_name(ainekio_p4_face_selected(&reaction,underlying,2,false,false,85000).face),"thinking"));
    assert(ainekio_p4_face_select(&reaction,&surprise,2,90000));
    assert(ainekio_p4_face_select(&reaction,&backdrop,2,91000));
    assert(!strcmp(ainekio_p4_face_token(&reaction,150000),"bg"));
    assert(!strcmp(ainekio_p4_face_token(&reaction,151000),""));
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
    assert(!strcmp(ainekio_face_name(selection.foreground.face),"happy"));
    assert(ainekio_p4_face_selected(&selection,base,2,false,false,5600).face==base.face);
    assert(!selection.foreground.active);
    assert(ainekio_p4_face_select(&selection,&thinking,2,6000));
    assert(ainekio_p4_face_select(&selection,&release,2,6100));
    assert(ainekio_p4_face_selected(&selection,base,2,false,false,6200).face==base.face);
    /* Timed feedback must not narrow the legacy library's manual face behavior. */
    happy=(ainekio_face_selection_t){.expression="happy"};
    assert(ainekio_p4_face_select(&selection,&happy,3,7000));
    assert(!strcmp(ainekio_face_name(ainekio_p4_face_selected(&selection,base,3,false,false,99000).face),"happy"));
    assert(ainekio_p4_face_selected(&selection,base,4,true,false,100000).face==base.face);
    ainekio_p4_face_clock_t clock={0};
    ainekio_p4_body_status_t body={0};
    ainekio_p4_face_sample_t sample=ainekio_p4_face_sample(&clock,&body,520);
    assert(!strcmp(ainekio_face_name(sample.face),"default")&&sample.elapsed_ms==0);
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
            sample=ainekio_p4_face_sample(&clock,&body,999999);
            assert(sample.face==index&&sample.elapsed_ms==0);
        }
    }
    size_t wave;assert(ainekio_v2_clip_find("wave",&wave));
    body=(ainekio_p4_body_status_t){.face_command="wave",.face_clip=wave,.face_is_clip=true,.moving=true,.face_entering=true};
    sample=ainekio_p4_face_sample(&clock,&body,999999);
    assert(!strcmp(ainekio_face_name(sample.face),"wave")&&sample.elapsed_ms==0);
    body.face_entering=false;body.face_elapsed_us=ainekio_v2_clips[wave].duration_us;body.moving=false;
    sample=ainekio_p4_face_sample(&clock,&body,733);
    assert(!strcmp(ainekio_face_name(sample.face),"stand")&&sample.elapsed_ms==0);
    /* Live failure: Wave waits at an extended-arm target. Source time must
     * hold the cue while animation continues on the independent wall clock. */
    clock=(ainekio_p4_face_clock_t){0};
    body=(ainekio_p4_body_status_t){.face_command="wave",.face_clip=wave,
        .face_is_clip=true,.moving=true,.servo_feedback_waiting=true,.face_elapsed_us=2000000};
    sample=ainekio_p4_face_sample(&clock,&body,10000);
    assert(!strcmp(ainekio_face_name(sample.face),"wave") && sample.elapsed_ms==0);
    sample=ainekio_p4_face_sample(&clock,&body,10300);
    assert(sample.elapsed_ms==300);
    sample=ainekio_p4_face_sample(&clock,&body,11200);
    assert(sample.elapsed_ms==1200 && body.face_elapsed_us==2000000);
    body.servo_feedback_waiting=false;body.face_elapsed_us=2500000;
    assert(ainekio_p4_face_sample(&clock,&body,11300).elapsed_ms==1300);
    body.face_elapsed_us=6000000;
    sample=ainekio_p4_face_sample(&clock,&body,11400);
    assert(!strcmp(ainekio_face_name(sample.face),"stand") && sample.elapsed_ms==0);
    size_t rest;assert(ainekio_v2_clip_find("rest",&rest));
    body=(ainekio_p4_body_status_t){.face_command="rest",.face_clip=rest,.face_is_clip=true,.moving=false,
        .face_elapsed_us=ainekio_v2_clips[rest].duration_us};
    sample=ainekio_p4_face_sample(&clock,&body,100);
    assert(sample.elapsed_ms!=ainekio_p4_face_sample(&clock,&body,600).elapsed_ms);
    body=(ainekio_p4_body_status_t){.face_command="crawl",.moving=true,.face_elapsed_us=321000};
    sample=ainekio_p4_face_sample(&clock,&body,999999);
    assert(!strcmp(ainekio_face_name(sample.face),"crawl")&&sample.elapsed_ms==0);
    /* A temporary listen overlay retains both manual and motion expressions. */
    size_t love;assert(ainekio_face_find("love",&love));
    ainekio_p4_face_sample_t previous={.face=love,.elapsed_ms=730};
    sample=ainekio_p4_face_listen(previous,true,123);
    assert(!strcmp(ainekio_face_name(sample.face),"listening") && sample.elapsed_ms==123);
    sample=ainekio_p4_face_listen(previous,false,999);
    assert(sample.face==love && sample.elapsed_ms==730);
    previous=ainekio_p4_face_sample(&clock,&body,200);
    sample=ainekio_p4_face_listen(previous,true,555);
    assert(!strcmp(ainekio_face_name(sample.face),"listening"));
    sample=ainekio_p4_face_listen(previous,false,999);
    assert(sample.face==previous.face && sample.elapsed_ms==previous.elapsed_ms);
    puts("All 23 motion cues resolve; wall-clock animation survives target waits, cue changes, entry, terminal holds and overlays.");
    return 0;
}
