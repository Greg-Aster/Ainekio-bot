#include "ainekio/platform/provisioning_portal.h"

#include <string.h>

#include "esp_netif.h"
#include "lwip/sockets.h"

#define PORTAL_RESPONSE_CHUNK_BYTES 384U

static const char CONFIG_PAGE_INITIAL[] =
    "<!doctype html><html><head><meta name=viewport content=\"width=device-width\">"
    "<title>Ainekio setup</title><style>body{font:16px sans-serif;max-width:36rem;"
    "margin:2rem auto;padding:0 1rem}label{display:block;margin:1rem 0}input{display:"
    "block;width:100%;padding:.6rem;box-sizing:border-box}button{padding:.7rem 1rem}"
    "small{display:block;color:#444}</style></head><body><main><h1>Connect Ainekio</h1>"
    "<p>Choose the WiFi used by the brain computer. Local mode finds the paired "
    "Ainekio gateway automatically.</p><form method=post action=/configure>"
    "<label>WiFi network<input name=wifi_ssid maxlength=32 autocomplete=off required></label>"
    "<label>WiFi password<input type=password name=wifi_psk minlength=8 maxlength=64 required></label>"
    "<label>Connection mode<select name=transport_mode>"
    "<option value=local selected>Local WiFi (recommended)</option>"
    "<option value=remote>Remote relay</option></select><small>Local mode stays "
    "on this WiFi network. Remote relay is never used automatically.</small></label>"
    "<label>Remote relay address<input name=endpoint_url maxlength=255 "
    "placeholder=\"wss://robot-gateway.example/robot\"><small>Required only in "
    "remote mode; use a secure wss:// address.</small></label>"
    "<label>Robot name<input name=robot_id maxlength=64 value=ainekio-01 required></label>"
    "<label>Robot pairing token<input type=password name=robot_token maxlength=128 "
    "required><small>This token is created by the brain's robot gateway; it is not "
    "the Ainekio-Setup key.</small></label>"
    "<button>Save and connect</button></form></main></body></html>";

static const char CONFIG_PAGE_NETWORK[] =
    "<!doctype html><html><head><meta name=viewport content=\"width=device-width\">"
    "<title>Ainekio setup</title></head><body><main><h1>Change WiFi</h1>"
    "<p>The robot identity and brain gateway will be preserved.</p>"
    "<form method=post action=/configure>"
    "<label>WiFi network <input name=wifi_ssid maxlength=32 required></label>"
    "<label>WiFi password <input type=password name=wifi_psk minlength=8 "
    "maxlength=64 required></label>"
    "<button>Save and connect</button></form></main></body></html>";

static bool request_from_setup_ap(httpd_req_t *request)
{
    if (request == NULL) {
        return false;
    }
    esp_netif_t *setup_netif = esp_netif_get_handle_from_ifkey("WIFI_AP_DEF");
    esp_netif_ip_info_t setup_ip;
    struct sockaddr_storage local = {0};
    socklen_t local_length = sizeof(local);
    const int socket_fd = httpd_req_to_sockfd(request);
    if (socket_fd < 0 || setup_netif == NULL ||
        esp_netif_get_ip_info(setup_netif, &setup_ip) != ESP_OK ||
        getsockname(socket_fd, (struct sockaddr *)&local, &local_length) != 0) {
        return false;
    }
    if (local.ss_family == AF_INET) {
        const struct sockaddr_in *local_ipv4 =
            (const struct sockaddr_in *)&local;
        return local_ipv4->sin_addr.s_addr == setup_ip.ip.addr;
    }
    if (local.ss_family == AF_INET6) {
        const struct sockaddr_in6 *local_ipv6 =
            (const struct sockaddr_in6 *)&local;
        static const uint8_t ipv4_mapped_prefix[12] = {
            0U, 0U, 0U, 0U, 0U, 0U, 0U, 0U, 0U, 0U, 0xFFU, 0xFFU,
        };
        return memcmp(
                   local_ipv6->sin6_addr.s6_addr,
                   ipv4_mapped_prefix,
                   sizeof(ipv4_mapped_prefix)
               ) == 0 &&
               memcmp(
                   &local_ipv6->sin6_addr.s6_addr[12],
                   &setup_ip.ip.addr,
                   sizeof(setup_ip.ip.addr)
               ) == 0;
    }
    return false;
}

static esp_err_t send_status(
    httpd_req_t *request,
    const char *status,
    const char *message
)
{
    httpd_resp_set_status(request, status);
    httpd_resp_set_type(request, "text/plain; charset=utf-8");
    httpd_resp_set_hdr(request, "Cache-Control", "no-store");
    httpd_resp_set_hdr(request, "Connection", "close");
    return httpd_resp_sendstr(request, message);
}

static esp_err_t read_body(httpd_req_t *request, char *body, size_t capacity)
{
    if (request->content_len <= 0 || (size_t)request->content_len >= capacity) {
        return ESP_ERR_INVALID_SIZE;
    }
    size_t offset = 0U;
    unsigned int timeouts = 0U;
    while (offset < (size_t)request->content_len) {
        const int received = httpd_req_recv(
            request,
            body + offset,
            (size_t)request->content_len - offset
        );
        if (received == HTTPD_SOCK_ERR_TIMEOUT && timeouts++ < 2U) {
            continue;
        }
        if (received <= 0) {
            return ESP_FAIL;
        }
        offset += (size_t)received;
    }
    body[offset] = '\0';
    return ESP_OK;
}

static esp_err_t root_handler(httpd_req_t *request)
{
    ainekio_provisioning_portal_t *portal = request->user_ctx;
    if (!request_from_setup_ap(request)) {
        return send_status(
            request,
            "403 Forbidden",
            "Connect through Ainekio-Setup."
        );
    }
    httpd_resp_set_type(request, "text/html; charset=utf-8");
    httpd_resp_set_hdr(request, "Cache-Control", "no-store");
    httpd_resp_set_hdr(request, "Connection", "close");
    const char *page = portal->network_only ? CONFIG_PAGE_NETWORK
                                            : CONFIG_PAGE_INITIAL;
    size_t remaining = strlen(page);
    while (remaining > 0U) {
        const size_t chunk_size = remaining < PORTAL_RESPONSE_CHUNK_BYTES
                                      ? remaining
                                      : PORTAL_RESPONSE_CHUNK_BYTES;
        char chunk[PORTAL_RESPONSE_CHUNK_BYTES];
        memcpy(chunk, page, chunk_size);
        const esp_err_t result =
            httpd_resp_send_chunk(request, chunk, (ssize_t)chunk_size);
        if (result != ESP_OK) {
            return result;
        }
        page += chunk_size;
        remaining -= chunk_size;
    }
    return httpd_resp_send_chunk(request, NULL, 0U);
}

static esp_err_t configure_handler(httpd_req_t *request)
{
    ainekio_provisioning_portal_t *portal = request->user_ctx;
    if (!request_from_setup_ap(request)) {
        return send_status(
            request,
            "403 Forbidden",
            "Connect through Ainekio-Setup."
        );
    }
    char body[AINEKIO_PORTAL_BODY_MAX + 1U];
    if (read_body(request, body, sizeof(body)) != ESP_OK) {
        return httpd_resp_send_err(request, HTTPD_400_BAD_REQUEST,
                                   "invalid configuration");
    }
    ainekio_portal_candidate_t candidate = {.network_only = portal->network_only};
    const ainekio_portal_parse_result_t result = ainekio_portal_parse_config(
        body,
        (size_t)request->content_len,
        portal->network_only,
        &candidate.record
    );
    memset(body, 0, sizeof(body));
    if (result != AINEKIO_PORTAL_PARSE_OK) {
        return httpd_resp_send_err(request, HTTPD_400_BAD_REQUEST,
                                   "invalid configuration");
    }
    if (uxQueueSpacesAvailable(portal->candidate_queue) == 0U) {
        memset(&candidate, 0, sizeof(candidate));
        return send_status(
            request,
            "409 Conflict",
            "validation already in progress"
        );
    }
    httpd_resp_set_type(request, "text/plain; charset=utf-8");
    httpd_resp_set_hdr(request, "Cache-Control", "no-store");
    httpd_resp_set_hdr(request, "Connection", "close");
    const esp_err_t response_result = httpd_resp_sendstr(
        request,
        "Configuration accepted. Watch the OLED, then reconnect this device to "
        "the selected WiFi network."
    );
    if (response_result != ESP_OK) {
        memset(&candidate, 0, sizeof(candidate));
        return response_result;
    }

    /*
     * Publish the candidate only after the success response has entered the
     * TCP send path. Staged validation can change the station association and
     * AP channel, so exposing the candidate first can strand the browser on a
     * response that never arrives.
     */
    const BaseType_t queued =
        xQueueSend(portal->candidate_queue, &candidate, 0U);
    memset(&candidate, 0, sizeof(candidate));
    return queued == pdPASS ? ESP_OK : ESP_FAIL;
}

esp_err_t ainekio_provisioning_portal_init(ainekio_provisioning_portal_t *portal)
{
    if (portal == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    memset(portal, 0, sizeof(*portal));
    portal->candidate_queue = xQueueCreateStatic(
        1U,
        sizeof(ainekio_portal_candidate_t),
        portal->candidate_queue_bytes,
        &portal->candidate_queue_storage
    );
    if (portal->candidate_queue == NULL) {
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}

esp_err_t ainekio_provisioning_portal_start(
    ainekio_provisioning_portal_t *portal,
    bool network_only
)
{
    if (portal == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    portal->network_only = network_only;
    if (portal->server != NULL) {
        return ESP_OK;
    }
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.stack_size = 5120U;
    config.task_caps = MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT;
    config.core_id = 1;
    config.max_uri_handlers = 2U;
    config.lru_purge_enable = true;
    esp_err_t result = httpd_start(&portal->server, &config);
    if (result != ESP_OK) {
        return result;
    }
    const httpd_uri_t routes[] = {
        {.uri = "/", .method = HTTP_GET, .handler = root_handler, .user_ctx = portal},
        {.uri = "/configure", .method = HTTP_POST, .handler = configure_handler, .user_ctx = portal},
    };
    for (size_t index = 0U; index < sizeof(routes) / sizeof(routes[0]); ++index) {
        result = httpd_register_uri_handler(portal->server, &routes[index]);
        if (result != ESP_OK) {
            (void)httpd_stop(portal->server);
            portal->server = NULL;
            return result;
        }
    }
    return ESP_OK;
}

esp_err_t ainekio_provisioning_portal_stop(ainekio_provisioning_portal_t *portal)
{
    if (portal == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    const esp_err_t result = ainekio_provisioning_portal_suspend(portal);
    xQueueReset(portal->candidate_queue);
    return result;
}

esp_err_t ainekio_provisioning_portal_suspend(ainekio_provisioning_portal_t *portal)
{
    if (portal == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    if (portal->server == NULL) {
        return ESP_OK;
    }
    const esp_err_t result = httpd_stop(portal->server);
    portal->server = NULL;
    xQueueReset(portal->candidate_queue);
    return result;
}

bool ainekio_provisioning_portal_take_candidate(
    ainekio_provisioning_portal_t *portal,
    ainekio_portal_candidate_t *candidate,
    TickType_t wait_ticks
)
{
    return portal != NULL && candidate != NULL &&
           xQueueReceive(portal->candidate_queue, candidate, wait_ticks) == pdPASS;
}
