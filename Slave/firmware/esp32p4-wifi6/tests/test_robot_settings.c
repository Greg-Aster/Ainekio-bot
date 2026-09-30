#include <assert.h>
#include <string.h>
#include "robot_settings.h"
#include "ainekio/control_codec.h"
#include "ainekio/admission.h"

int main(void)
{
    ainekio_p4_robot_settings_t s = {.version=1};
    strcpy(s.robot_id, "robot"); strcpy(s.robot_token, "token");
    assert(ainekio_p4_robot_settings_valid(&s));
    assert(ainekio_p4_network_next(&s, -1) == -1);
    ainekio_robot_settings_command_t c = {.operation=AINEKIO_SETTINGS_NETWORK, .has_wifi_password=true};
    strcpy(c.ssid, "Home"); strcpy(c.wifi_password, "home-password");
    strcpy(c.endpoint, "ws://home:8790/robot");
    assert(ainekio_p4_robot_settings_update(&s, &c));
    assert(s.revision == 1 && ainekio_p4_network_next(&s, -1) == 0);
    assert(!ainekio_p4_robot_settings_update(&s, &c)); /* stale editor */
    c.revision=1; c.index=1;
    assert(!ainekio_p4_robot_settings_update(&s, &c)); /* duplicate SSID */
    strcpy(c.ssid, "Ainekio-Robot"); strcpy(c.endpoint, "ws://10.42.77.1:8790/robot");
    assert(ainekio_p4_robot_settings_update(&s, &c));
    assert(ainekio_p4_network_next(&s, 0) == 1 && ainekio_p4_network_next(&s, 1) == 0);
    c.revision=2; c.has_wifi_password=false;
    assert(ainekio_p4_robot_settings_update(&s, &c));
    assert(!strcmp(s.networks[1].password, "home-password"));
    c.revision=3; strcpy(c.ssid, "Changed-name");
    assert(!ainekio_p4_robot_settings_update(&s, &c)); /* no secret reuse with another SSID */
    c.has_wifi_password=true; c.wifi_password[0]=0;
    assert(ainekio_p4_robot_settings_update(&s, &c)); /* explicitly open */
    c=(ainekio_robot_settings_command_t){.operation=AINEKIO_SETTINGS_SECURITY, .revision=4, .has_setup_password=true};
    assert(ainekio_p4_robot_settings_update(&s, &c) && s.setup_password_set && !s.setup_password[0]);
    c.revision=5; strcpy(c.setup_password,"short");
    assert(!ainekio_p4_robot_settings_update(&s, &c));
    c=(ainekio_robot_settings_command_t){.operation=AINEKIO_SETTINGS_REMOVE, .revision=5, .index=0};
    assert(ainekio_p4_robot_settings_update(&s, &c));
    assert(ainekio_p4_network_next(&s, -1) == 1);
    c.revision=6; c.index=1;
    assert(ainekio_p4_robot_settings_update(&s, &c));
    assert(ainekio_p4_network_next(&s, 1) == -1);
    assert(!strcmp(s.robot_token, "token")); /* removal preserves identity */
    char raw[65]; memset(raw,'a',64);raw[64]=0;
    assert(ainekio_p4_wifi_password_valid(raw,sizeof(raw),true));
    raw[0]='z';assert(!ainekio_p4_wifi_password_valid(raw,sizeof(raw),true));
    const char *json="{\"t\":\"robot_settings\",\"seq\":1,\"epoch\":1,\"deadline_ms\":1000,\"op\":\"network\",\"revision\":0,\"index\":0,\"ssid\":\"Home\",\"endpoint\":\"ws://home:8790/robot\",\"wifi_password\":\"\"}";
    ainekio_control_message_t m;
    assert(ainekio_control_decode_for_body(json,strlen(json),&m)==AINEKIO_DECODE_OK);
    assert(m.command.kind==AINEKIO_COMMAND_ROBOT_SETTINGS && m.command.data.robot_settings.has_wifi_password);
    ainekio_admission_t a;
    ainekio_admission_init(&a, AINEKIO_COMMAND_MASK(AINEKIO_COMMAND_ROBOT_SETTINGS), true);
    uint64_t connection = ainekio_admission_open(&a);
    assert(!ainekio_admission_accept(&a, connection, &m, 0, 0, true).accepted);
    assert(ainekio_admission_welcome(&a, connection, 1, AINEKIO_PROFILE_HOME, true, 0));
    assert(ainekio_admission_accept(&a, connection, &m, 0, 0, true).accepted);
    assert(!ainekio_admission_accept(&a, connection, &m, 0, 0, true).accepted); /* replay */
    m.sequence=m.command.sequence=2;
    assert(!ainekio_admission_accept(&a, connection, &m, 0, 1000000, true).accepted); /* expired */
    assert(!ainekio_admission_accept(&a, connection+1, &m, 0, 0, true).accepted);
    assert(ainekio_control_decode(json,strlen(json),&m)!=AINEKIO_DECODE_OK);
    json="{\"t\":\"robot_settings\",\"seq\":1,\"op\":\"apply\"}";
    assert(ainekio_control_decode_for_body(json,strlen(json),&m)!=AINEKIO_DECODE_OK);
    return 0;
}
