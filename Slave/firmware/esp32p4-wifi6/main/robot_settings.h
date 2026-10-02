#pragma once
#include "ainekio/config_store.h"
#include "ainekio/protocol.h"

typedef struct {
    char ssid[33], password[65], endpoint[256];
} ainekio_p4_network_profile_t;
/* One atomic NVS blob; legacy configuration remains readable for migration. */
typedef struct {
    uint32_t version, revision;
    char robot_id[65], robot_token[129], setup_password[64];
    bool setup_password_set;
    ainekio_p4_network_profile_t networks[AINEKIO_NETWORK_SLOTS];
} ainekio_p4_robot_settings_t;
bool ainekio_p4_robot_settings_valid(const ainekio_p4_robot_settings_t *settings);
bool ainekio_p4_robot_settings_update(ainekio_p4_robot_settings_t *settings,
                                    const ainekio_robot_settings_command_t *command);
bool ainekio_p4_wifi_password_valid(const char *password, size_t capacity, bool raw_key);
/* Returns the next occupied slot, or -1 when none are configured. */
int ainekio_p4_network_next(const ainekio_p4_robot_settings_t *settings, int after);
/* Gateways on the associated Wi-Fi network, in slot order. A connected gateway
 * stays selected; callers advance only after closing the previous connection. */
int ainekio_p4_gateway_next(const ainekio_p4_robot_settings_t *settings,
                           int network, int after);
bool ainekio_p4_gateway_discovery_allowed(const ainekio_p4_robot_settings_t *settings,
                                        int network);
