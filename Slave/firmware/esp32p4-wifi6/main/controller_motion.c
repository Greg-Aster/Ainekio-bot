#include "controller_motion.h"
#include <inttypes.h>
#include <stdio.h>

ainekio_decision_t ainekio_p4_stop_accept(ainekio_admission_t *admission,
    ainekio_pca9685_t *output, uint64_t connection,
    const ainekio_control_message_t *message, uint64_t received_us, uint64_t now_us)
{
    if (connection != admission->generation || !admission->connected ||
        !admission->authenticated || admission->stale)
        return (ainekio_decision_t){.accepted=false, .rejection=AINEKIO_REJECT_STALE};
    if (!message || !message->has_command || message->command.kind != AINEKIO_COMMAND_STOP)
        return (ainekio_decision_t){.accepted=false, .rejection=AINEKIO_REJECT_MALFORMED};
    if (message->command.data.stop.detach && message->has_epoch &&
        message->epoch == admission->core.epoch)
        ainekio_pca_emergency_disable(output, AINEKIO_PCA_FAULT_EMERGENCY);
    return ainekio_admission_accept(admission, connection, message, received_us, now_us, true);
}

size_t ainekio_p4_body_notice(const ainekio_p4_body_event_t *event,
    uint32_t boot_id, char *text, size_t capacity)
{
    if (!event->stalled_joints) return 0;
    const int length=snprintf(text,capacity,
        "{\"t\":\"event\",\"name\":\"servo_stall\",\"event_id\":\"%" PRIu32 ":%" PRIu64 "\","
        "\"clock_us\":%" PRIu64 ",\"seq\":%" PRIu32 ",\"joint_mask\":%u,\"outputs_released\":false}",
        boot_id,event->clock_us,event->clock_us,event->sequence,(unsigned)event->stalled_joints);
    return length>0 && (size_t)length<capacity ? (size_t)length : 0;
}

size_t ainekio_p4_body_receipt(const ainekio_p4_body_event_t *event,
    uint32_t stopped_sequence, char *text, size_t capacity)
{
    if (event->jam_observation || !event->sequence) return 0;
    if (event->sequence<=stopped_sequence)
        return ainekio_encode_cancelled(event->sequence,AINEKIO_CANCEL_STOP,text,capacity);
    if (event->result!=ESP_OK) return 0;
    if (!event->completed)
        return ainekio_encode_cancelled(event->sequence,event->reason,text,capacity);
    if (!event->position_verification)
        return ainekio_encode_done(event->sequence,text,capacity);
    const int length=snprintf(text,capacity,
        "{\"t\":\"done\",\"seq\":%" PRIu32 ",\"position_verified\":%s,\"target_adjusted_joints\":%u}",
        event->sequence,event->position_verification==2?"true":"false",
        (unsigned)event->target_adjusted_joints);
    return length>0 && (size_t)length<capacity ? (size_t)length : 0;
}

size_t ainekio_p4_execution_error(uint32_t sequence, esp_err_t error,
    ainekio_pca_fault_t output_fault, bool restart_pending,
    ainekio_body_state_t state, char *text, size_t capacity)
{
    const ainekio_nak_code_t code = error == ESP_ERR_INVALID_ARG || error == AINEKIO_P4_ERR_REFERENCE ? AINEKIO_NAK_LIMIT :
        error == ESP_ERR_NOT_FOUND ? AINEKIO_NAK_ASSET_MISSING : AINEKIO_NAK_BUSY;
    const char *detail = error == AINEKIO_P4_ERR_REFERENCE ? "Commanded pose cannot close the leg linkage" :
        error == ESP_ERR_INVALID_ARG ? "Motion mapping failed or pulse exceeds PWM timer capacity" :
        error == ESP_ERR_NOT_FOUND ? "Requested asset is unavailable" :
        output_fault == AINEKIO_PCA_FAULT_IO ? "Servo controller I2C transfer failed" :
        output_fault == AINEKIO_PCA_FAULT_DEADLINE ? "Servo controller I2C transfer missed its deadline" :
        output_fault == AINEKIO_PCA_FAULT_PROGRESS ? "Servo frame update missed its deadline" :
        error == ESP_ERR_TIMEOUT ? "Command or motion update missed its deadline" :
        restart_pending ? "Restart is pending" :
        state == AINEKIO_STATE_DOZING || state == AINEKIO_STATE_DEEP_SLEEP ? "Body is asleep; select Idle before moving" :
        error == ESP_ERR_NO_MEM ? "Body lacks memory or command queue space" :
        output_fault ? "Motion stopped after execution failed" :
        "Command could not execute; read body status and retry";
    return ainekio_encode_nak(true,sequence,code,detail,text,capacity);
}

size_t ainekio_p4_rejection(const ainekio_control_message_t *m,
    ainekio_reject_reason_t reason, char *text, size_t capacity)
{
    static const ainekio_nak_code_t codes[] = {
        AINEKIO_NAK_UNKNOWN, AINEKIO_NAK_STALE, AINEKIO_NAK_MODE, AINEKIO_NAK_UNSAFE,
        AINEKIO_NAK_LIMIT, AINEKIO_NAK_UNKNOWN, AINEKIO_NAK_BUSY, AINEKIO_NAK_PROFILE,
        AINEKIO_NAK_ASSET_MISSING, AINEKIO_NAK_MALFORMED,
    };
    const char *detail = reason == AINEKIO_REJECT_LIMIT ?
        "Command parameters are outside their supported range" :
        reason == AINEKIO_REJECT_BUSY ? "Body is busy, asleep, or its outputs are unavailable" : NULL;
    return ainekio_encode_nak(m->has_sequence, m->sequence, codes[reason], detail, text, capacity);
}
