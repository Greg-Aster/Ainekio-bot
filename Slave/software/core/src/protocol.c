#include "ainekio/protocol.h"

bool ainekio_intent_is_movement(ainekio_intent_kind_t intent)
{
    return intent == AINEKIO_INTENT_SIT || intent == AINEKIO_INTENT_STAND ||
           intent == AINEKIO_INTENT_NEUTRAL || intent == AINEKIO_INTENT_LOOK ||
           intent == AINEKIO_INTENT_WALK || intent == AINEKIO_INTENT_EMOTE;
}

const char *ainekio_joint_label(uint8_t joint_id)
{
    static const char *const labels[AINEKIO_SERVO_COUNT] = {
        "R1", "R2", "L1", "L2", "R4", "R3", "L3", "L4",
    };
    return joint_id < AINEKIO_SERVO_COUNT ? labels[joint_id] : NULL;
}
