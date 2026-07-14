#include "ainekio/protocol.h"

bool ainekio_intent_is_movement(ainekio_intent_kind_t intent)
{
    return intent == AINEKIO_INTENT_SIT || intent == AINEKIO_INTENT_STAND ||
           intent == AINEKIO_INTENT_NEUTRAL || intent == AINEKIO_INTENT_LOOK ||
           intent == AINEKIO_INTENT_WALK;
}
