#include "ainekio/platform/provisioning_portal.h"

#include <stdio.h>
#include <string.h>

#include "esp_random.h"
#include "esp_timer.h"
#include "mbedtls/constant_time.h"
#include "mbedtls/sha256.h"

#define LOGIN_BODY_MAX 32U

static const char LOGIN_PAGE[] =
    "<!doctype html><html><head><meta name=viewport content=\"width=device-width\">"
    "<title>Ainekio setup</title></head><body><main><h1>Ainekio setup</h1>"
    "<form method=post action=/login><label>Setup secret <input type=password "
    "name=secret minlength=12 maxlength=12 required></label><button>Sign in</button>"
    "</form></main></body></html>";

static const char CONFIG_PAGE_INITIAL[] =
    "<!doctype html><html><head><meta name=viewport content=\"width=device-width\">"
    "<title>Ainekio setup</title></head><body><main><h1>Network setup</h1>"
    "<form method=post action=/configure>"
    "<label>WiFi name <input name=wifi_ssid maxlength=32 required></label>"
    "<label>WiFi password <input type=password name=wifi_psk minlength=8 maxlength=64 required></label>"
    "<label>Gateway WebSocket <input name=endpoint_url maxlength=255 required></label>"
    "<label>Robot ID <input name=robot_id maxlength=64 required></label>"
    "<label>Robot token <input type=password name=robot_token maxlength=128 required></label>"
    "<button>Save and connect</button></form></main></body></html>";

static const char CONFIG_PAGE_NETWORK[] =
    "<!doctype html><html><head><meta name=viewport content=\"width=device-width\">"
    "<title>Ainekio setup</title></head><body><main><h1>Network setup</h1>"
    "<form method=post action=/configure>"
    "<label>WiFi name <input name=wifi_ssid maxlength=32 required></label>"
    "<label>WiFi password <input type=password name=wifi_psk minlength=8 maxlength=64 required></label>"
    "<button>Save and connect</button></form></main></body></html>";

static uint32_t now_ms(void)
{
    return (uint32_t)(esp_timer_get_time() / 1000);
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

static bool authenticated(
    const ainekio_provisioning_portal_t *portal,
    httpd_req_t *request
)
{
    if (portal->session_token[0] == '\0') {
        return false;
    }
    char cookie[128];
    if (httpd_req_get_hdr_value_str(request, "Cookie", cookie, sizeof(cookie)) !=
        ESP_OK) {
        return false;
    }
    const char marker[] = "ainekio_setup=";
    const char *value = strstr(cookie, marker);
    if (value == NULL) {
        return false;
    }
    value += sizeof(marker) - 1U;
    return strlen(value) >= 32U &&
           mbedtls_ct_memcmp(value, portal->session_token, 32U) == 0 &&
           (value[32] == '\0' || value[32] == ';');
}

static void generate_session_token(ainekio_provisioning_portal_t *portal)
{
    static const char hex[] = "0123456789abcdef";
    uint8_t random[16];
    esp_fill_random(random, sizeof(random));
    for (size_t index = 0U; index < sizeof(random); ++index) {
        portal->session_token[index * 2U] = hex[random[index] >> 4U];
        portal->session_token[index * 2U + 1U] = hex[random[index] & 0x0FU];
    }
    portal->session_token[32] = '\0';
    memset(random, 0, sizeof(random));
}

static esp_err_t root_handler(httpd_req_t *request)
{
    ainekio_provisioning_portal_t *portal = request->user_ctx;
    httpd_resp_set_type(request, "text/html; charset=utf-8");
    httpd_resp_set_hdr(request, "Cache-Control", "no-store");
    if (!authenticated(portal, request)) {
        return httpd_resp_send(request, LOGIN_PAGE, HTTPD_RESP_USE_STRLEN);
    }
    const char *page = portal->network_only ? CONFIG_PAGE_NETWORK
                                            : CONFIG_PAGE_INITIAL;
    return httpd_resp_send(request, page, HTTPD_RESP_USE_STRLEN);
}

static esp_err_t login_handler(httpd_req_t *request)
{
    ainekio_provisioning_portal_t *portal = request->user_ctx;
    if (!ainekio_portal_login_allowed(&portal->rate_limit, now_ms())) {
        return send_status(request, "429 Too Many Requests", "login rate limited");
    }
    char body[LOGIN_BODY_MAX + 1U];
    if (read_body(request, body, sizeof(body)) != ESP_OK) {
        return httpd_resp_send_err(request, HTTPD_400_BAD_REQUEST, "invalid login");
    }
    const char prefix[] = "secret=";
    const char *secret = body + sizeof(prefix) - 1U;
    uint8_t candidate_hash[AINEKIO_SETUP_HASH_BYTES];
    const bool body_valid = strncmp(body, prefix, sizeof(prefix) - 1U) == 0 &&
                            strlen(secret) == AINEKIO_SETUP_SECRET_CHARS;
    const int hash_result = body_valid
                                ? mbedtls_sha256(
                                      (const unsigned char *)secret,
                                      AINEKIO_SETUP_SECRET_CHARS,
                                      candidate_hash,
                                      0
                                  )
                                : -1;
    const bool valid = hash_result == 0 &&
                       mbedtls_ct_memcmp(
                           candidate_hash,
                           portal->secret_hash,
                           AINEKIO_SETUP_HASH_BYTES
                       ) == 0;
    memset(candidate_hash, 0, sizeof(candidate_hash));
    memset(body, 0, sizeof(body));
    if (!valid) {
        ainekio_portal_login_failed(&portal->rate_limit, now_ms());
        return httpd_resp_send_err(request, HTTPD_401_UNAUTHORIZED, "invalid login");
    }
    ainekio_portal_login_succeeded(&portal->rate_limit);
    generate_session_token(portal);
    char cookie[96];
    const int written = snprintf(
        cookie,
        sizeof(cookie),
        "ainekio_setup=%s; Path=/; HttpOnly; SameSite=Strict",
        portal->session_token
    );
    if (written <= 0 || (size_t)written >= sizeof(cookie)) {
        return ESP_FAIL;
    }
    httpd_resp_set_hdr(request, "Set-Cookie", cookie);
    httpd_resp_set_hdr(request, "Location", "/");
    return send_status(request, "303 See Other", "signed in");
}

static esp_err_t configure_handler(httpd_req_t *request)
{
    ainekio_provisioning_portal_t *portal = request->user_ctx;
    if (!authenticated(portal, request)) {
        return httpd_resp_send_err(request, HTTPD_401_UNAUTHORIZED,
                                   "authentication required");
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
    if (xQueueSend(portal->candidate_queue, &candidate, 0U) != pdPASS) {
        memset(&candidate, 0, sizeof(candidate));
        return send_status(
            request,
            "409 Conflict",
            "validation already in progress"
        );
    }
    memset(&candidate, 0, sizeof(candidate));
    httpd_resp_set_type(request, "text/plain; charset=utf-8");
    httpd_resp_set_hdr(request, "Cache-Control", "no-store");
    return httpd_resp_sendstr(request, "Configuration accepted for validation.");
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
    ainekio_portal_rate_limit_init(&portal->rate_limit);
    return ESP_OK;
}

esp_err_t ainekio_provisioning_portal_generate_secret(
    ainekio_provisioning_portal_t *portal,
    char secret[AINEKIO_SETUP_SECRET_CHARS + 1U]
)
{
    if (portal == NULL || secret == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    static const char base32[] = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
    uint64_t random = 0U;
    esp_fill_random(&random, sizeof(random));
    for (size_t index = 0U; index < AINEKIO_SETUP_SECRET_CHARS; ++index) {
        secret[index] = base32[random & 0x1FU];
        random >>= 5U;
    }
    secret[AINEKIO_SETUP_SECRET_CHARS] = '\0';
    if (mbedtls_sha256(
            (const unsigned char *)secret,
            AINEKIO_SETUP_SECRET_CHARS,
            portal->secret_hash,
            0
        ) != 0) {
        memset(secret, 0, AINEKIO_SETUP_SECRET_CHARS + 1U);
        return ESP_FAIL;
    }
    const esp_err_t result =
        ainekio_nvs_adapter_store_setup_hash(portal->secret_hash);
    if (result != ESP_OK) {
        memset(secret, 0, AINEKIO_SETUP_SECRET_CHARS + 1U);
        memset(portal->secret_hash, 0, sizeof(portal->secret_hash));
        return result;
    }
    portal->secret_ready = true;
    return ESP_OK;
}

esp_err_t ainekio_provisioning_portal_start(
    ainekio_provisioning_portal_t *portal,
    bool network_only
)
{
    if (portal == NULL || portal->server != NULL || !portal->secret_ready) {
        return ESP_ERR_INVALID_STATE;
    }
    portal->network_only = network_only;
    portal->session_token[0] = '\0';
    ainekio_portal_rate_limit_init(&portal->rate_limit);
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.max_uri_handlers = 3U;
    config.lru_purge_enable = true;
    esp_err_t result = httpd_start(&portal->server, &config);
    if (result != ESP_OK) {
        return result;
    }
    const httpd_uri_t routes[] = {
        {.uri = "/", .method = HTTP_GET, .handler = root_handler, .user_ctx = portal},
        {.uri = "/login", .method = HTTP_POST, .handler = login_handler, .user_ctx = portal},
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
    memset(portal->secret_hash, 0, sizeof(portal->secret_hash));
    memset(portal->session_token, 0, sizeof(portal->session_token));
    portal->secret_ready = false;
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
    memset(portal->session_token, 0, sizeof(portal->session_token));
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
