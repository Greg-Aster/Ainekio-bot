#include <assert.h>
#include <stdio.h>
#include <string.h>

#include "ainekio/provisioning_portal.h"

static void test_bounded_initial_and_network_only_payloads(void)
{
    const char initial[] =
        "wifi_ssid=Owner+WiFi&wifi_psk=correct%20horse&endpoint_url="
        "ws%3A%2F%2F192.168.1.5%3A8765&robot_id=ainekio-01&robot_token=token-1";
    ainekio_config_record_t candidate;
    assert(ainekio_portal_parse_config(
               initial,
               strlen(initial),
               false,
               &candidate
           ) == AINEKIO_PORTAL_PARSE_OK);
    assert(strcmp(candidate.wifi_ssid, "Owner WiFi") == 0);
    assert(strcmp(candidate.wifi_psk, "correct horse") == 0);
    assert(strcmp(candidate.endpoint_url, "ws://192.168.1.5:8765") == 0);

    const char network[] = "wifi_ssid=Travel&wifi_psk=12345678";
    assert(ainekio_portal_parse_config(
               network,
               strlen(network),
               true,
               &candidate
           ) == AINEKIO_PORTAL_PARSE_OK);
    assert(candidate.endpoint_url[0] == '\0');
    assert(ainekio_portal_parse_config(
               network,
               strlen(network),
               false,
               &candidate
           ) == AINEKIO_PORTAL_PARSE_MISSING);
}

static void test_malformed_duplicate_and_oversize_payloads_fail_closed(void)
{
    ainekio_config_record_t candidate;
    const char duplicate[] =
        "wifi_ssid=one&wifi_ssid=two&wifi_psk=12345678";
    assert(ainekio_portal_parse_config(
               duplicate,
               strlen(duplicate),
               true,
               &candidate
           ) == AINEKIO_PORTAL_PARSE_DUPLICATE);
    const char malformed[] = "wifi_ssid=bad%ZZ&wifi_psk=12345678";
    assert(ainekio_portal_parse_config(
               malformed,
               strlen(malformed),
               true,
               &candidate
           ) == AINEKIO_PORTAL_PARSE_MALFORMED);
    char oversized[AINEKIO_PORTAL_BODY_MAX + 1U];
    memset(oversized, 'a', sizeof(oversized));
    assert(ainekio_portal_parse_config(
               oversized,
               sizeof(oversized),
               true,
               &candidate
           ) == AINEKIO_PORTAL_PARSE_TOO_LARGE);
}

int main(void)
{
    test_bounded_initial_and_network_only_payloads();
    test_malformed_duplicate_and_oversize_payloads_fail_closed();
    puts("ainekio provisioning portal tests passed");
    return 0;
}
