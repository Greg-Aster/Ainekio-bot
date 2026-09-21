#ifndef AINEKIO_ADMISSION_H
#define AINEKIO_ADMISSION_H

#include "ainekio/core.h"
#include "ainekio/control_codec.h"

#define AINEKIO_ADMISSION_MAX_QUEUE_US UINT64_C(1000000)
#define AINEKIO_ADMISSION_STALE_US UINT64_C(4000000)
#define AINEKIO_COMMAND_MASK(kind) (UINT32_C(1) << (kind))

/* A transport's selected, credentialed connection owns a generation. The
 * caller serializes state access; transport callbacks and queued messages carry
 * that generation, never a caller-supplied hostname or an authentication flag.
 * The existing gateway verifies the device token before returning welcome.
 * Peer trust (configured LAN endpoint or verified TLS) remains a transport duty. */
typedef struct {
    ainekio_core_t core;
    uint64_t generation;
    uint64_t last_control_us;
    uint32_t allowed_commands;
    bool connected;
    bool authenticated;
    bool stale;
    bool require_deadline;
} ainekio_admission_t;

void ainekio_admission_init(ainekio_admission_t *admission,
                           uint32_t allowed_commands, bool require_deadline);
uint64_t ainekio_admission_open(ainekio_admission_t *admission);
void ainekio_admission_close(ainekio_admission_t *admission, uint64_t generation);
bool ainekio_admission_welcome(ainekio_admission_t *admission, uint64_t generation,
                              uint32_t epoch, ainekio_profile_t profile,
                              bool deadline_supported, uint64_t now_us);
bool ainekio_admission_control(ainekio_admission_t *admission,
                              uint64_t generation, uint64_t now_us);
bool ainekio_admission_check_stale(ainekio_admission_t *admission, uint64_t now_us);
/* model_supported is computed from the decoded semantic command. Rejection
 * still passes through the same session, expiry and sequence checks. */
ainekio_decision_t ainekio_admission_accept(ainekio_admission_t *admission,
    uint64_t generation, const ainekio_control_message_t *message,
    uint64_t received_us, uint64_t now_us, bool model_supported);

#endif
