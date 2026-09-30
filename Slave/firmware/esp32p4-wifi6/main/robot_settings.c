#include "robot_settings.h"
#include <string.h>
#include <ctype.h>

static bool text(const char *value, size_t capacity)
{ return memchr(value, 0, capacity) != NULL; }

bool ainekio_p4_wifi_password_valid(const char *password, size_t capacity, bool raw_key)
{
    if (!text(password, capacity)) return false;
    size_t length = strlen(password);
    if (!length) return true; /* Explicit open network. */
    if (length == 64 && raw_key) {
        for (size_t i=0; i<length; ++i) if (!isxdigit((unsigned char)password[i])) return false;
        return true;
    }
    if (length < 8 || length > 63) return false;
    for (size_t i=0; i<length; ++i)
        if ((unsigned char)password[i] < 32 || (unsigned char)password[i] > 126) return false;
    return true;
}

static bool endpoint_valid(const char *endpoint)
{
    if (!text(endpoint, 256)) return false;
    size_t n = strlen(endpoint);
    const char *host = !strncmp(endpoint, "ws://", 5) ? endpoint + 5 :
                       !strncmp(endpoint, "wss://", 6) ? endpoint + 6 : NULL;
    if (!host || n < 12 || strcmp(endpoint + n - 6, "/robot") || *host == '/') return false;
    for (const char *p=host; *p; ++p)
        if ((unsigned char)*p <= 32 || *p == '@' || *p == '#' || *p == '?') return false;
    return true;
}

bool ainekio_p4_robot_settings_valid(const ainekio_p4_robot_settings_t *s)
{
    if (s->version != 1 || !text(s->robot_id, sizeof(s->robot_id)) ||
        !text(s->robot_token, sizeof(s->robot_token)) ||
        !ainekio_p4_wifi_password_valid(s->setup_password, sizeof(s->setup_password), false)) return false;
    for (unsigned i=0; i<AINEKIO_NETWORK_SLOTS; ++i) {
        const ainekio_p4_network_profile_t *p = &s->networks[i];
        if (!text(p->ssid, sizeof(p->ssid))) return false;
        if (!p->ssid[0]) continue;
        if (!s->robot_id[0] || !s->robot_token[0] || !endpoint_valid(p->endpoint) ||
            !ainekio_p4_wifi_password_valid(p->password, sizeof(p->password), true)) return false;
        for (unsigned j=0; j<i; ++j)
            if (!strcmp(p->ssid, s->networks[j].ssid)) return false;
    }
    return true;
}

bool ainekio_p4_robot_settings_update(ainekio_p4_robot_settings_t *s,
                                    const ainekio_robot_settings_command_t *c)
{
    if (s->revision != c->revision || s->revision == UINT32_MAX) return false;
    ainekio_p4_robot_settings_t next = *s;
    if (c->operation == AINEKIO_SETTINGS_NETWORK) {
        if (c->index >= AINEKIO_NETWORK_SLOTS || !text(c->ssid, sizeof(c->ssid)) || !c->ssid[0] ||
            !text(c->endpoint, sizeof(c->endpoint))) return false;
        ainekio_p4_network_profile_t *p = &next.networks[c->index];
        if (!c->has_wifi_password && strcmp(p->ssid, c->ssid)) return false;
        memcpy(p->ssid, c->ssid, sizeof(p->ssid));
        memcpy(p->endpoint, c->endpoint, sizeof(p->endpoint));
        if (c->has_wifi_password) memcpy(p->password, c->wifi_password, sizeof(p->password));
    } else if (c->operation == AINEKIO_SETTINGS_REMOVE) {
        if (c->index >= AINEKIO_NETWORK_SLOTS) return false;
        memset(&next.networks[c->index], 0, sizeof(next.networks[c->index]));
    } else if (c->operation == AINEKIO_SETTINGS_SECURITY) {
        if (c->has_robot_token) {
            if (!c->robot_token[0]) return false;
            memcpy(next.robot_token, c->robot_token, sizeof(next.robot_token));
        }
        if (c->has_setup_password) {
            memcpy(next.setup_password, c->setup_password, sizeof(next.setup_password));
            next.setup_password_set = true;
        }
    } else return false;
    if (!ainekio_p4_robot_settings_valid(&next)) return false;
    ++next.revision;
    *s = next;
    return true;
}

int ainekio_p4_network_next(const ainekio_p4_robot_settings_t *s, int after)
{
    for (unsigned step=1; step<=AINEKIO_NETWORK_SLOTS; ++step) {
        unsigned index = (after + (int)step) % AINEKIO_NETWORK_SLOTS;
        if (s->networks[index].ssid[0]) return (int)index;
    }
    return -1;
}
