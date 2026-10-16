#pragma once
#include <stddef.h>
#include <sys/types.h>
#include "esp_err.h"
typedef void *httpd_handle_t;
enum { HTTP_GET, HTTP_POST };
typedef struct { httpd_handle_t handle; int method; size_t content_len; } httpd_req_t;
typedef struct { const char *uri; int method; esp_err_t (*handler)(httpd_req_t *); } httpd_uri_t;
esp_err_t httpd_resp_set_status(httpd_req_t *, const char *);
esp_err_t httpd_resp_set_type(httpd_req_t *, const char *);
esp_err_t httpd_resp_set_hdr(httpd_req_t *, const char *, const char *);
esp_err_t httpd_resp_sendstr(httpd_req_t *, const char *);
esp_err_t httpd_sess_trigger_close(httpd_handle_t, int);
int httpd_req_to_sockfd(httpd_req_t *);
esp_err_t httpd_req_get_hdr_value_str(httpd_req_t *, const char *, char *, size_t);
int httpd_req_recv(httpd_req_t *, char *, size_t);
esp_err_t httpd_register_uri_handler(httpd_handle_t, const httpd_uri_t *);

#define HTTPD_RESP_USE_STRLEN (-1)
esp_err_t httpd_resp_send_chunk(httpd_req_t *, const char *, ssize_t);
size_t httpd_req_get_url_query_len(httpd_req_t *);
esp_err_t httpd_req_get_url_query_str(httpd_req_t *, char *, size_t);
esp_err_t httpd_query_key_value(const char *, const char *, char *, size_t);
