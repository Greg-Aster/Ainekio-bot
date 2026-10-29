#pragma once
/* Shared P4 movement wire semantics. Transport owns locking, connection
 * selection, ACK ordering and routing; this module owns no execution state. */
#include "ainekio/admission.h"
#include "body.h"

/* Call after the transport's authenticated/current-control check, under its
 * admission lock. Matching-epoch Release disables PWM even when its sequence
 * is a duplicate; acceptance still uses the existing sequence retirement. */
ainekio_decision_t ainekio_p4_stop_accept(ainekio_admission_t *admission,
    ainekio_pca9685_t *output, uint64_t connection,
    const ainekio_control_message_t *message, uint64_t received_us, uint64_t now_us);

/* Returns zero when the event has no notice/receipt of this kind. The caller
 * retains current-connection and ACK-before-terminal routing. Execution errors
 * use execution_error below so firmware can append its live diagnostics. */
size_t ainekio_p4_body_notice(const ainekio_p4_body_event_t *event,
    uint32_t boot_id, char *text, size_t capacity);
size_t ainekio_p4_body_receipt(const ainekio_p4_body_event_t *event,
    uint32_t stopped_sequence, char *text, size_t capacity);
size_t ainekio_p4_execution_error(uint32_t sequence, esp_err_t error,
    ainekio_pca_fault_t output_fault, bool restart_pending,
    ainekio_body_state_t state, char *text, size_t capacity);

size_t ainekio_p4_rejection(const ainekio_control_message_t *message,
    ainekio_reject_reason_t reason, char *text, size_t capacity);
