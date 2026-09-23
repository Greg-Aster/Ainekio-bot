#include "portal.h"
#include "config.h"
#include "board.h"
#include "network.h"
#include "system.h"
#include "ainekio/provisioning_portal.h"

#include <inttypes.h>
#include <stdio.h>
#include <string.h>
#include "esp_http_server.h"
#include "esp_netif.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "lwip/sockets.h"

static httpd_handle_t server;
static char csrf[33];

/* HTTP listens on both netifs. Require the local socket address to belong to
 * the setup AP, not merely a peer inside a guessed private address range. */
static bool setup_request(httpd_req_t *request)
{
    esp_netif_t *ap = esp_netif_get_handle_from_ifkey("WIFI_AP_DEF");
    esp_netif_ip_info_t ip;
    struct sockaddr_storage local = {0};
    socklen_t size = sizeof(local);
    if (!ainekio_p4_network_setup_active() || !ap ||
        esp_netif_get_ip_info(ap, &ip) != ESP_OK ||
        getsockname(httpd_req_to_sockfd(request), (struct sockaddr *)&local, &size) != 0)
        return false;
    if (local.ss_family == AF_INET)
        return ((struct sockaddr_in *)&local)->sin_addr.s_addr == ip.ip.addr;
    if (local.ss_family == AF_INET6) {
        const struct sockaddr_in6 *v6 = (const struct sockaddr_in6 *)&local;
        static const uint8_t prefix[12] = {0,0,0,0,0,0,0,0,0,0,255,255};
        return memcmp(v6->sin6_addr.s6_addr, prefix, sizeof(prefix)) == 0 &&
               memcmp(v6->sin6_addr.s6_addr + 12, &ip.ip.addr, 4) == 0;
    }
    return false;
}

static esp_err_t reply(httpd_req_t *request, const char *status, const char *body)
{
    httpd_resp_set_status(request, status);
    httpd_resp_set_type(request, "text/plain; charset=utf-8");
    httpd_resp_set_hdr(request, "Cache-Control", "no-store");
    httpd_resp_set_hdr(request, "Connection", "close");
    return httpd_resp_sendstr(request, body);
}

static esp_err_t root(httpd_req_t *request)
{
    if (!setup_request(request)) return reply(request, "403 Forbidden", "Connect to the robot setup Wi-Fi.");
    httpd_resp_set_type(request, "text/html; charset=utf-8");
    httpd_resp_set_hdr(request, "Cache-Control", "no-store");
    httpd_resp_set_hdr(request, "X-Frame-Options", "DENY");
    httpd_resp_set_hdr(request, "Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'");
    const char *header = "<!doctype html><html><head><meta name=viewport content='width=device-width'>"
        "<title>Ainekio setup</title><style>body{font:16px sans-serif;max-width:36rem;margin:2rem auto;padding:0 1rem}"
        "label{display:block;margin:1rem 0}input,select{display:block;width:100%;box-sizing:border-box;padding:.6rem}"
        "button{padding:.7rem 1rem}</style></head><body><h1>Connect Ainekio</h1>";
    esp_err_t result = httpd_resp_sendstr_chunk(request, header);
    char form[128];
    snprintf(form, sizeof(form), "<form method=post action='/configure?%s'>", csrf);
    if (result == ESP_OK) result = httpd_resp_sendstr_chunk(request, form);
    if (result == ESP_OK) result = httpd_resp_sendstr_chunk(request,
        "<label>Wi-Fi network<input name=wifi_ssid maxlength=32 autocomplete=off required></label>"
        "<label>Wi-Fi password<input type=password name=wifi_psk minlength=8 maxlength=64 required></label>");
    if (result == ESP_OK && !ainekio_p4_config()) result = httpd_resp_sendstr_chunk(request,
        "<label>Connection mode<select name=transport_mode><option value=local>Local gateway</option>"
        "<option value=remote>Secure remote gateway</option></select></label>"
        "<label>Gateway address<input name=endpoint_url maxlength=255 placeholder='ws://computer:8790/robot' required></label>"
        "<label>Robot identity<input name=robot_id maxlength=64 autocomplete=off required></label>"
        "<label>Robot pairing token<input type=password name=robot_token maxlength=128 required></label>");
    else if (result == ESP_OK) result = httpd_resp_sendstr_chunk(request,
        "<p>The robot identity, pairing token and selected controller are preserved.</p>");
    if (result == ESP_OK) result = httpd_resp_sendstr_chunk(request,
        "<p>Saving restarts the controller. If Wi-Fi cannot connect, setup remains available.</p>"
        "<button>Save and connect</button></form></body></html>");
    return result == ESP_OK ? httpd_resp_send_chunk(request, NULL, 0) : result;
}

static esp_err_t configure(httpd_req_t *request)
{
    char token[sizeof(csrf)];
    if (!setup_request(request) || httpd_req_get_url_query_str(request, token, sizeof(token)) != ESP_OK ||
        strcmp(token, csrf) != 0)
        return reply(request, "403 Forbidden", "Open setup again before saving.");
    if (ainekio_p4_system_status().restart_pending)
        return reply(request, "409 Conflict", "A power transition is already in progress.");
    char content_type[64];
    if (httpd_req_get_hdr_value_str(request, "Content-Type", content_type, sizeof(content_type)) != ESP_OK ||
        strcmp(content_type, "application/x-www-form-urlencoded") != 0)
        return reply(request, "415 Unsupported Media Type", "Use the setup form.");
    char body[AINEKIO_PORTAL_BODY_MAX + 1];
    if (!request->content_len || request->content_len > AINEKIO_PORTAL_BODY_MAX)
        return reply(request, "400 Bad Request", "Configuration exceeds the supported size.");
    size_t received = 0;
    const int64_t deadline = esp_timer_get_time() + 5000000;
    while (received < request->content_len) {
        if (esp_timer_get_time() >= deadline) {
            memset(body, 0, sizeof(body));
            return reply(request, "408 Request Timeout", "Configuration upload took too long.");
        }
        int n = httpd_req_recv(request, body + received, request->content_len - received);
        if (n <= 0) {
            memset(body, 0, sizeof(body));
            return reply(request, "408 Request Timeout", "Configuration was not received completely.");
        }
        received += (size_t)n;
    }
    body[received] = 0;
    const ainekio_config_record_t *existing = ainekio_p4_config();
    ainekio_config_record_t candidate;
    const ainekio_portal_parse_result_t parsed = ainekio_portal_parse_config(body, received, existing != NULL, &candidate);
    memset(body, 0, sizeof(body));
    if (parsed != AINEKIO_PORTAL_PARSE_OK) {
        memset(&candidate, 0, sizeof(candidate));
        return reply(request, "400 Bad Request", "Invalid configuration. Nothing saved.");
    }
    if (existing) {
        memcpy(candidate.transport_mode, existing->transport_mode, sizeof(candidate.transport_mode));
        memcpy(candidate.endpoint_url, existing->endpoint_url, sizeof(candidate.endpoint_url));
        memcpy(candidate.robot_id, existing->robot_id, sizeof(candidate.robot_id));
        memcpy(candidate.robot_token, existing->robot_token, sizeof(candidate.robot_token));
    }
    ainekio_pca_emergency_disable(ainekio_p4_output(), AINEKIO_PCA_FAULT_EMERGENCY);
    const esp_err_t saved = ainekio_p4_config_save_record(&candidate);
    memset(&candidate, 0, sizeof(candidate));
    if (saved != ESP_OK) return reply(request, "500 Internal Server Error", "Save failed. Outputs remain disabled; retry setup.");
    if (ainekio_p4_system_restart() != ESP_OK)
        return reply(request, "503 Service Unavailable", "Saved, but restart preparation failed. Outputs remain disabled; retry restart from the controller or serial console.");
    return reply(request, "200 OK", "Saved. The controller is restarting; reconnect to your selected Wi-Fi.");
}

esp_err_t ainekio_p4_portal_start(void)
{
    if (server) return ESP_OK;
    snprintf(csrf, sizeof(csrf), "%08" PRIx32 "%08" PRIx32 "%08" PRIx32 "%08" PRIx32,
             esp_random(), esp_random(), esp_random(), esp_random());
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.stack_size = 6144;
    config.max_open_sockets = 2;
    config.recv_wait_timeout = 3;
    config.send_wait_timeout = 3;
    config.lru_purge_enable = true;
    esp_err_t result = httpd_start(&server, &config);
    const httpd_uri_t root_uri = {.uri="/", .method=HTTP_GET, .handler=root};
    const httpd_uri_t configure_uri = {.uri="/configure", .method=HTTP_POST, .handler=configure};
    if (result == ESP_OK) result = httpd_register_uri_handler(server, &root_uri);
    if (result == ESP_OK) result = httpd_register_uri_handler(server, &configure_uri);
    if (result != ESP_OK && server) (void)ainekio_p4_portal_stop();
    return result;
}

esp_err_t ainekio_p4_portal_stop(void)
{
    if (!server) return ESP_OK;
    esp_err_t result = httpd_stop(server);
    if (result == ESP_OK) { server = NULL; memset(csrf, 0, sizeof(csrf)); }
    return result;
}
