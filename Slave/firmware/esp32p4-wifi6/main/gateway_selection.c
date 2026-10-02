#include "gateway_selection.h"
#include <string.h>

void ainekio_p4_gateway_select_network(ainekio_p4_gateway_selection_t *s,
                                     const ainekio_p4_robot_settings_t *settings, int network)
{
    *s = (ainekio_p4_gateway_selection_t){.network=network,
        .profile=ainekio_p4_gateway_next(settings, network, -1)};
}

const char *ainekio_p4_gateway_endpoint(const ainekio_p4_gateway_selection_t *s,
                                      const ainekio_p4_robot_settings_t *settings)
{
    if (s->profile >= 0) return settings->networks[s->profile].endpoint;
    return s->cursor < s->count ? s->discovered[s->cursor] : "";
}

void ainekio_p4_gateway_failed(ainekio_p4_gateway_selection_t *s,
                              const ainekio_p4_robot_settings_t *settings)
{
    if (s->profile < 0 && ++s->cursor < s->count) return;
    const int first = ainekio_p4_gateway_next(settings, s->network, -1);
    const int next = ainekio_p4_gateway_next(settings, s->network, s->profile);
    s->needs_discovery = s->profile >= 0 && next == first &&
        ainekio_p4_gateway_discovery_allowed(settings, s->network);
    s->profile = next;
    s->count = s->cursor = 0;
}

void ainekio_p4_gateway_discovered(ainekio_p4_gateway_selection_t *s,
                                  const ainekio_p4_robot_settings_t *settings, size_t count)
{
    s->needs_discovery = false;
    s->count = s->cursor = 0;
    for (size_t i=0; i<count && i<AINEKIO_DISCOVERY_MAX_RESULTS; ++i) {
        bool configured = false;
        for (unsigned j=0; j<AINEKIO_NETWORK_SLOTS; ++j)
            if (!strcmp(settings->networks[j].ssid, settings->networks[s->network].ssid) &&
                !strcmp(settings->networks[j].endpoint, s->discovered[i])) configured = true;
        if (!configured) {
            if (s->count != i) strcpy(s->discovered[s->count], s->discovered[i]);
            ++s->count;
        }
    }
    if (s->count) s->profile = -1;
}

bool ainekio_p4_gateway_connect_expired(uint64_t started_us, uint64_t now_us, bool authenticated)
{
    return !authenticated && now_us - started_us >= AINEKIO_GATEWAY_CONNECT_TIMEOUT_US;
}
