#include <assert.h>
#include <string.h>
#include "gateway_selection.h"
#include "ainekio/admission.h"

int main(void)
{
    ainekio_p4_robot_settings_t settings = {.version=1};
    strcpy(settings.robot_id,"robot"); strcpy(settings.robot_token,"shared-token");
    strcpy(settings.networks[0].ssid,"Home"); strcpy(settings.networks[0].password,"home-password");
    strcpy(settings.networks[0].endpoint,"ws://computer-a:8790/robot");
    ainekio_robot_settings_command_t change={.operation=AINEKIO_SETTINGS_NETWORK,.index=1};
    strcpy(change.ssid,"Home"); strcpy(change.endpoint,"wss://computer-b.example/robot");
    assert(ainekio_p4_robot_settings_update(&settings,&change));
    assert(!strcmp(settings.networks[1].password,"home-password"));
    change.revision=1; change.index=2; change.has_wifi_password=true;
    strcpy(change.ssid,"Hotspot");strcpy(change.wifi_password,"hotspot-password");
    strcpy(change.endpoint,"ws://10.42.77.1:8790/robot");
    assert(ainekio_p4_robot_settings_update(&settings,&change));
    assert(ainekio_p4_network_next(&settings,0)==2 && ainekio_p4_network_next(&settings,2)==0);
    ainekio_p4_gateway_selection_t selection;
    ainekio_p4_gateway_select_network(&selection,&settings,0);
    assert(!strcmp(ainekio_p4_gateway_endpoint(&selection,&settings),"ws://computer-a:8790/robot"));
    assert(!ainekio_p4_gateway_connect_expired(0,9999999,false));
    assert(ainekio_p4_gateway_connect_expired(0,10000000,false));
    assert(!ainekio_p4_gateway_connect_expired(0,UINT64_MAX,true));
    ainekio_p4_gateway_failed(&selection,&settings);
    assert(!strcmp(ainekio_p4_gateway_endpoint(&selection,&settings),"wss://computer-b.example/robot"));
    assert(!selection.needs_discovery);
    ainekio_p4_gateway_failed(&selection,&settings);
    assert(selection.needs_discovery);
    strcpy(selection.discovered[0],"ws://computer-a:8790/robot");
    strcpy(selection.discovered[1],"ws://192.168.1.30:8790/robot");
    strcpy(selection.discovered[2],"ws://192.168.1.40:8790/robot");
    ainekio_p4_gateway_discovered(&selection,&settings,3);
    assert(selection.count==2 && selection.profile==-1 && !selection.needs_discovery);
    assert(!strcmp(ainekio_p4_gateway_endpoint(&selection,&settings),"ws://192.168.1.30:8790/robot"));
    ainekio_p4_gateway_failed(&selection,&settings);
    assert(!strcmp(ainekio_p4_gateway_endpoint(&selection,&settings),"ws://192.168.1.40:8790/robot"));
    ainekio_p4_gateway_failed(&selection,&settings);
    assert(selection.profile==0 && !selection.needs_discovery && selection.count==0);
    /* A new Wi-Fi association cannot reuse discoveries from the old subnet. */
    ainekio_p4_gateway_select_network(&selection,&settings,2);
    assert(!strcmp(ainekio_p4_gateway_endpoint(&selection,&settings),"ws://10.42.77.1:8790/robot"));
    ainekio_p4_gateway_failed(&selection,&settings);
    assert(selection.needs_discovery);
    ainekio_p4_gateway_discovered(&selection,&settings,0);
    assert(selection.profile==2 && !selection.needs_discovery);
    /* Explicit TLS-only networks never downgrade to discovered plain WS. */
    strcpy(settings.networks[0].endpoint,"wss://computer-a.example/robot");
    ainekio_p4_gateway_select_network(&selection,&settings,0);
    ainekio_p4_gateway_failed(&selection,&settings);
    ainekio_p4_gateway_failed(&selection,&settings);
    assert(selection.profile==0 && !selection.needs_discovery);
    /* Changing a shared Wi-Fi credential updates every computer's profile. */
    change=(ainekio_robot_settings_command_t){.operation=AINEKIO_SETTINGS_NETWORK,.revision=2,.index=1,.has_wifi_password=true};
    strcpy(change.ssid,"Home"); strcpy(change.endpoint,"wss://computer-b.example/robot");strcpy(change.wifi_password,"new-password");
    assert(ainekio_p4_robot_settings_update(&settings,&change));
    assert(!strcmp(settings.networks[0].password,"new-password"));
    settings.networks[0].password[0]='X';
    assert(!ainekio_p4_robot_settings_valid(&settings));
    /* Same epochs on independent gateways do not allow old-generation work. */
    ainekio_admission_t admission;
    ainekio_admission_init(&admission,AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_STOP),true);
    uint64_t old=ainekio_admission_open(&admission);
    assert(ainekio_admission_welcome(&admission,old,1,AINEKIO_PROFILE_HOME,true,0));
    ainekio_admission_close(&admission,old);
    uint64_t current=ainekio_admission_open(&admission);
    assert(current!=old && !admission.authenticated);
    assert(ainekio_admission_welcome(&admission,current,1,AINEKIO_PROFILE_HOME,true,0));
    ainekio_control_message_t stop={.has_command=true,.has_sequence=true,.has_epoch=true,.epoch=1,.sequence=1,
        .command={.kind=AINEKIO_COMMAND_STOP,.sequence=1}};
    assert(!ainekio_admission_accept(&admission,old,&stop,0,0,true).accepted);
    assert(ainekio_admission_accept(&admission,current,&stop,0,0,true).accepted);
    assert(ainekio_admission_check_stale(&admission,AINEKIO_ADMISSION_STALE_US));
    assert(!ainekio_admission_accept(&admission,current,&stop,0,AINEKIO_ADMISSION_STALE_US,true).accepted);
    return 0;
}
