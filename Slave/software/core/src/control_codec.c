#include "ainekio/control_codec.h"

#include <errno.h>
#include <limits.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

#include "ainekio/assets.h"

#define JSON_MAX_TOKENS 400U
#define JSON_MAX_DEPTH 8U
#define JSON_STRING_BUFFER 192U

typedef enum {
    JSON_TOKEN_OBJECT = 0,
    JSON_TOKEN_ARRAY,
    JSON_TOKEN_STRING,
    JSON_TOKEN_PRIMITIVE,
} json_token_type_t;

typedef struct {
    json_token_type_t type;
    uint16_t start;
    uint16_t end;
    int16_t parent;
    uint16_t children;
} json_token_t;

typedef struct {
    const char *json;
    size_t length;
    size_t cursor;
    json_token_t tokens[JSON_MAX_TOKENS];
    uint16_t count;
    bool token_overflow;
} json_parser_t;

static void skip_space(json_parser_t *parser)
{
    while (parser->cursor < parser->length) {
        const char value = parser->json[parser->cursor];
        if (value != ' ' && value != '\t' && value != '\r' && value != '\n') {
            break;
        }
        ++parser->cursor;
    }
}

static int allocate_token(
    json_parser_t *parser,
    json_token_type_t type,
    int parent,
    size_t start
)
{
    if (parser->count >= JSON_MAX_TOKENS || start > UINT16_MAX) {
        parser->token_overflow = true;
        return -1;
    }
    const int index = (int)parser->count++;
    parser->tokens[index] = (json_token_t){
        .type = type,
        .start = (uint16_t)start,
        .parent = (int16_t)parent,
    };
    return index;
}

static bool hex_digit(char value)
{
    return (value >= '0' && value <= '9') || (value >= 'a' && value <= 'f') ||
           (value >= 'A' && value <= 'F');
}

static int parse_value(json_parser_t *parser, int parent, unsigned int depth);

static int parse_string(json_parser_t *parser, int parent)
{
    if (parser->cursor >= parser->length || parser->json[parser->cursor] != '"') {
        return -1;
    }
    ++parser->cursor;
    const size_t start = parser->cursor;
    const int token_index = allocate_token(parser, JSON_TOKEN_STRING, parent, start);
    if (token_index < 0) {
        return -1;
    }
    while (parser->cursor < parser->length) {
        const unsigned char value = (unsigned char)parser->json[parser->cursor++];
        if (value == '"') {
            parser->tokens[token_index].end = (uint16_t)(parser->cursor - 1U);
            return token_index;
        }
        if (value < 0x20U) {
            return -1;
        }
        if (value != '\\') {
            continue;
        }
        if (parser->cursor >= parser->length) {
            return -1;
        }
        const char escape = parser->json[parser->cursor++];
        if (strchr("\"\\/bfnrt", escape) != NULL) {
            continue;
        }
        if (escape != 'u' || parser->length - parser->cursor < 4U) {
            return -1;
        }
        for (size_t index = 0U; index < 4U; ++index) {
            if (!hex_digit(parser->json[parser->cursor + index])) {
                return -1;
            }
        }
        parser->cursor += 4U;
    }
    return -1;
}

static bool primitive_delimiter(char value)
{
    return value == ' ' || value == '\t' || value == '\r' || value == '\n' ||
           value == ',' || value == ']' || value == '}';
}

static bool number_syntax(const char *value, size_t length)
{
    size_t cursor = 0U;
    if (cursor < length && value[cursor] == '-') {
        ++cursor;
    }
    if (cursor >= length) {
        return false;
    }
    if (value[cursor] == '0') {
        ++cursor;
    } else if (value[cursor] >= '1' && value[cursor] <= '9') {
        do {
            ++cursor;
        } while (cursor < length && value[cursor] >= '0' && value[cursor] <= '9');
    } else {
        return false;
    }
    if (cursor < length && value[cursor] == '.') {
        ++cursor;
        const size_t fraction_start = cursor;
        while (cursor < length && value[cursor] >= '0' && value[cursor] <= '9') {
            ++cursor;
        }
        if (cursor == fraction_start) {
            return false;
        }
    }
    if (cursor < length && (value[cursor] == 'e' || value[cursor] == 'E')) {
        ++cursor;
        if (cursor < length && (value[cursor] == '+' || value[cursor] == '-')) {
            ++cursor;
        }
        const size_t exponent_start = cursor;
        while (cursor < length && value[cursor] >= '0' && value[cursor] <= '9') {
            ++cursor;
        }
        if (cursor == exponent_start) {
            return false;
        }
    }
    return cursor == length;
}

static int parse_primitive(json_parser_t *parser, int parent)
{
    const size_t start = parser->cursor;
    while (parser->cursor < parser->length &&
           !primitive_delimiter(parser->json[parser->cursor])) {
        const unsigned char value = (unsigned char)parser->json[parser->cursor];
        if (value < 0x20U || value == ':' || value == '[' || value == '{' ||
            value == '"' || value == '\\') {
            return -1;
        }
        ++parser->cursor;
    }
    const size_t length = parser->cursor - start;
    if (length == 0U ||
        !(number_syntax(parser->json + start, length) ||
          (length == 4U && memcmp(parser->json + start, "true", 4U) == 0) ||
          (length == 5U && memcmp(parser->json + start, "false", 5U) == 0) ||
          (length == 4U && memcmp(parser->json + start, "null", 4U) == 0))) {
        return -1;
    }
    const int token_index = allocate_token(parser, JSON_TOKEN_PRIMITIVE, parent, start);
    if (token_index < 0 || parser->cursor > UINT16_MAX) {
        return -1;
    }
    parser->tokens[token_index].end = (uint16_t)parser->cursor;
    return token_index;
}

static int parse_object(json_parser_t *parser, int parent, unsigned int depth)
{
    const int object_index =
        allocate_token(parser, JSON_TOKEN_OBJECT, parent, parser->cursor);
    if (object_index < 0) {
        return -1;
    }
    ++parser->cursor;
    skip_space(parser);
    if (parser->cursor < parser->length && parser->json[parser->cursor] == '}') {
        parser->tokens[object_index].end = (uint16_t)++parser->cursor;
        return object_index;
    }
    while (parser->cursor < parser->length) {
        if (parse_string(parser, object_index) < 0) {
            return -1;
        }
        ++parser->tokens[object_index].children;
        skip_space(parser);
        if (parser->cursor >= parser->length || parser->json[parser->cursor++] != ':') {
            return -1;
        }
        skip_space(parser);
        if (parse_value(parser, object_index, depth + 1U) < 0) {
            return -1;
        }
        ++parser->tokens[object_index].children;
        skip_space(parser);
        if (parser->cursor >= parser->length) {
            return -1;
        }
        const char separator = parser->json[parser->cursor++];
        if (separator == '}') {
            parser->tokens[object_index].end = (uint16_t)parser->cursor;
            return object_index;
        }
        if (separator != ',') {
            return -1;
        }
        skip_space(parser);
    }
    return -1;
}

static int parse_array(json_parser_t *parser, int parent, unsigned int depth)
{
    const int array_index = allocate_token(parser, JSON_TOKEN_ARRAY, parent, parser->cursor);
    if (array_index < 0) {
        return -1;
    }
    ++parser->cursor;
    skip_space(parser);
    if (parser->cursor < parser->length && parser->json[parser->cursor] == ']') {
        parser->tokens[array_index].end = (uint16_t)++parser->cursor;
        return array_index;
    }
    while (parser->cursor < parser->length) {
        if (parse_value(parser, array_index, depth + 1U) < 0) {
            return -1;
        }
        ++parser->tokens[array_index].children;
        skip_space(parser);
        if (parser->cursor >= parser->length) {
            return -1;
        }
        const char separator = parser->json[parser->cursor++];
        if (separator == ']') {
            parser->tokens[array_index].end = (uint16_t)parser->cursor;
            return array_index;
        }
        if (separator != ',') {
            return -1;
        }
        skip_space(parser);
    }
    return -1;
}

static int parse_value(json_parser_t *parser, int parent, unsigned int depth)
{
    if (depth > JSON_MAX_DEPTH) {
        return -1;
    }
    skip_space(parser);
    if (parser->cursor >= parser->length) {
        return -1;
    }
    const char value = parser->json[parser->cursor];
    if (value == '{') {
        return parse_object(parser, parent, depth);
    }
    if (value == '[') {
        return parse_array(parser, parent, depth);
    }
    if (value == '"') {
        return parse_string(parser, parent);
    }
    return parse_primitive(parser, parent);
}

static unsigned int hex_value(char value)
{
    if (value >= '0' && value <= '9') {
        return (unsigned int)(value - '0');
    }
    if (value >= 'a' && value <= 'f') {
        return (unsigned int)(value - 'a' + 10);
    }
    return (unsigned int)(value - 'A' + 10);
}

static bool append_utf8(unsigned int codepoint, char *output, size_t capacity, size_t *length)
{
    if (codepoint >= 0xD800U && codepoint <= 0xDFFFU) {
        return false;
    }
    if (codepoint <= 0x7FU) {
        if (*length + 1U >= capacity) {
            return false;
        }
        output[(*length)++] = (char)codepoint;
    } else if (codepoint <= 0x7FFU) {
        if (*length + 2U >= capacity) {
            return false;
        }
        output[(*length)++] = (char)(0xC0U | (codepoint >> 6U));
        output[(*length)++] = (char)(0x80U | (codepoint & 0x3FU));
    } else {
        if (*length + 3U >= capacity) {
            return false;
        }
        output[(*length)++] = (char)(0xE0U | (codepoint >> 12U));
        output[(*length)++] = (char)(0x80U | ((codepoint >> 6U) & 0x3FU));
        output[(*length)++] = (char)(0x80U | (codepoint & 0x3FU));
    }
    return true;
}

static bool token_string_copy(
    const json_parser_t *parser,
    int token_index,
    char *output,
    size_t capacity,
    size_t *decoded_length
)
{
    if (token_index < 0 || (uint16_t)token_index >= parser->count || capacity == 0U ||
        parser->tokens[token_index].type != JSON_TOKEN_STRING) {
        return false;
    }
    const json_token_t *token = &parser->tokens[token_index];
    size_t output_length = 0U;
    for (size_t cursor = token->start; cursor < token->end; ++cursor) {
        unsigned char value = (unsigned char)parser->json[cursor];
        if (value != '\\') {
            if (output_length + 1U >= capacity) {
                return false;
            }
            output[output_length++] = (char)value;
            continue;
        }
        if (++cursor >= token->end) {
            return false;
        }
        const char escape = parser->json[cursor];
        if (escape == 'u') {
            if (token->end - cursor < 5U) {
                return false;
            }
            unsigned int codepoint = 0U;
            for (size_t index = 1U; index <= 4U; ++index) {
                codepoint = (codepoint << 4U) | hex_value(parser->json[cursor + index]);
            }
            cursor += 4U;
            if (!append_utf8(codepoint, output, capacity, &output_length)) {
                return false;
            }
            continue;
        }
        const char decoded = escape == 'b'   ? '\b'
                             : escape == 'f' ? '\f'
                             : escape == 'n' ? '\n'
                             : escape == 'r' ? '\r'
                             : escape == 't' ? '\t'
                                             : escape;
        if (output_length + 1U >= capacity) {
            return false;
        }
        output[output_length++] = decoded;
    }
    output[output_length] = '\0';
    if (decoded_length != NULL) {
        *decoded_length = output_length;
    }
    return true;
}

static bool token_string_equal(
    const json_parser_t *parser,
    int token_index,
    const char *expected
)
{
    char value[JSON_STRING_BUFFER];
    return token_string_copy(parser, token_index, value, sizeof(value), NULL) &&
           strcmp(value, expected) == 0;
}

static bool object_keys_unique(const json_parser_t *parser)
{
    for (uint16_t object = 0U; object < parser->count; ++object) {
        if (parser->tokens[object].type != JSON_TOKEN_OBJECT) {
            continue;
        }
        int keys[JSON_MAX_TOKENS / 2U];
        size_t key_count = 0U;
        bool expecting_key = true;
        for (uint16_t index = object + 1U; index < parser->count; ++index) {
            if (parser->tokens[index].parent != (int16_t)object) {
                continue;
            }
            if (expecting_key) {
                if (parser->tokens[index].type != JSON_TOKEN_STRING) {
                    return false;
                }
                keys[key_count++] = (int)index;
            }
            expecting_key = !expecting_key;
        }
        if (!expecting_key) {
            return false;
        }
        for (size_t left = 0U; left < key_count; ++left) {
            char key[JSON_STRING_BUFFER];
            if (!token_string_copy(parser, keys[left], key, sizeof(key), NULL)) {
                return false;
            }
            for (size_t right = left + 1U; right < key_count; ++right) {
                if (token_string_equal(parser, keys[right], key)) {
                    return false;
                }
            }
        }
    }
    return true;
}

static int object_get(const json_parser_t *parser, int object, const char *name)
{
    bool expecting_key = true;
    bool matched = false;
    for (uint16_t index = (uint16_t)object + 1U; index < parser->count; ++index) {
        if (parser->tokens[index].parent != object) {
            continue;
        }
        if (expecting_key) {
            matched = token_string_equal(parser, index, name);
        } else if (matched) {
            return (int)index;
        }
        expecting_key = !expecting_key;
    }
    return -1;
}

static int array_get(const json_parser_t *parser, int array, size_t wanted)
{
    size_t current = 0U;
    for (uint16_t index = (uint16_t)array + 1U; index < parser->count; ++index) {
        if (parser->tokens[index].parent == array) {
            if (current == wanted) {
                return (int)index;
            }
            ++current;
        }
    }
    return -1;
}

static bool token_integer(const json_parser_t *parser, int token_index, int64_t *value)
{
    if (token_index < 0 || parser->tokens[token_index].type != JSON_TOKEN_PRIMITIVE) {
        return false;
    }
    const json_token_t *token = &parser->tokens[token_index];
    const size_t length = token->end - token->start;
    if (length == 0U || length >= 32U) {
        return false;
    }
    for (size_t index = token->start; index < token->end; ++index) {
        if (parser->json[index] == '.' || parser->json[index] == 'e' ||
            parser->json[index] == 'E') {
            return false;
        }
    }
    char buffer[32];
    memcpy(buffer, parser->json + token->start, length);
    buffer[length] = '\0';
    char *end = NULL;
    errno = 0;
    const long long parsed = strtoll(buffer, &end, 10);
    if (errno != 0 || end == NULL || *end != '\0') {
        return false;
    }
    *value = (int64_t)parsed;
    return true;
}

static bool token_number(const json_parser_t *parser, int token_index, float *value)
{
    if (token_index < 0 || parser->tokens[token_index].type != JSON_TOKEN_PRIMITIVE) {
        return false;
    }
    const json_token_t *token = &parser->tokens[token_index];
    const size_t length = token->end - token->start;
    if (length == 0U || length >= 64U ||
        !number_syntax(parser->json + token->start, length)) {
        return false;
    }
    char buffer[64];
    memcpy(buffer, parser->json + token->start, length);
    buffer[length] = '\0';
    char *end = NULL;
    errno = 0;
    const float parsed = strtof(buffer, &end);
    if (errno != 0 || end == NULL || *end != '\0' || !isfinite(parsed)) {
        return false;
    }
    *value = parsed;
    return true;
}

static bool token_boolean(const json_parser_t *parser, int token_index, bool *value)
{
    if (token_index < 0 || parser->tokens[token_index].type != JSON_TOKEN_PRIMITIVE) {
        return false;
    }
    const json_token_t *token = &parser->tokens[token_index];
    const size_t length = token->end - token->start;
    if (length == 4U && memcmp(parser->json + token->start, "true", 4U) == 0) {
        *value = true;
        return true;
    }
    if (length == 5U && memcmp(parser->json + token->start, "false", 5U) == 0) {
        *value = false;
        return true;
    }
    return false;
}

static ainekio_decode_result_t required_token(
    const json_parser_t *parser,
    int object,
    const char *name,
    int *token
)
{
    *token = object_get(parser, object, name);
    return *token < 0 ? AINEKIO_DECODE_MISSING : AINEKIO_DECODE_OK;
}

static ainekio_decode_result_t required_string(
    const json_parser_t *parser,
    int object,
    const char *name,
    char *output,
    size_t capacity,
    size_t minimum,
    size_t maximum
)
{
    int token = -1;
    if (required_token(parser, object, name, &token) != AINEKIO_DECODE_OK) {
        return AINEKIO_DECODE_MISSING;
    }
    size_t length = 0U;
    if (!token_string_copy(parser, token, output, capacity, &length)) {
        return AINEKIO_DECODE_TYPE;
    }
    return length >= minimum && length <= maximum ? AINEKIO_DECODE_OK
                                                   : AINEKIO_DECODE_RANGE;
}

static ainekio_decode_result_t required_integer(
    const json_parser_t *parser,
    int object,
    const char *name,
    int64_t minimum,
    int64_t maximum,
    int64_t *output
)
{
    int token = -1;
    if (required_token(parser, object, name, &token) != AINEKIO_DECODE_OK) {
        return AINEKIO_DECODE_MISSING;
    }
    if (!token_integer(parser, token, output)) {
        return AINEKIO_DECODE_TYPE;
    }
    return *output >= minimum && *output <= maximum ? AINEKIO_DECODE_OK
                                                     : AINEKIO_DECODE_RANGE;
}

static ainekio_decode_result_t required_number(
    const json_parser_t *parser,
    int object,
    const char *name,
    float *output
)
{
    int token = -1;
    if (required_token(parser, object, name, &token) != AINEKIO_DECODE_OK) {
        return AINEKIO_DECODE_MISSING;
    }
    return token_number(parser, token, output) ? AINEKIO_DECODE_OK : AINEKIO_DECODE_TYPE;
}

static ainekio_decode_result_t required_boolean(
    const json_parser_t *parser,
    int object,
    const char *name,
    bool *output
)
{
    int token = -1;
    if (required_token(parser, object, name, &token) != AINEKIO_DECODE_OK) {
        return AINEKIO_DECODE_MISSING;
    }
    return token_boolean(parser, token, output) ? AINEKIO_DECODE_OK : AINEKIO_DECODE_TYPE;
}

static bool string_in(const char *value, const char *const *allowed, size_t count)
{
    for (size_t index = 0U; index < count; ++index) {
        if (strcmp(value, allowed[index]) == 0) {
            return true;
        }
    }
    return false;
}

static ainekio_decode_result_t sequence(
    const json_parser_t *parser,
    int root,
    ainekio_control_message_t *message
)
{
    int64_t value = 0;
    const ainekio_decode_result_t result = required_integer(
        parser,
        root,
        "seq",
        1,
        AINEKIO_MAX_SEQUENCE,
        &value
    );
    if (result == AINEKIO_DECODE_OK) {
        message->has_sequence = true;
        message->sequence = (uint32_t)value;
        message->command.sequence = (uint32_t)value;
    }
    return result;
}

static ainekio_decode_result_t no_sequence(const json_parser_t *parser, int root)
{
    return object_get(parser, root, "seq") < 0 ? AINEKIO_DECODE_OK
                                                : AINEKIO_DECODE_VALUE;
}

static ainekio_decode_result_t asset_string(
    const json_parser_t *parser,
    int root,
    const char *field,
    char output[AINEKIO_ASSET_NAME_MAX + 1U]
)
{
    const ainekio_decode_result_t result = required_string(
        parser,
        root,
        field,
        output,
        AINEKIO_ASSET_NAME_MAX + 1U,
        1U,
        AINEKIO_ASSET_NAME_MAX
    );
    return result == AINEKIO_DECODE_OK && !ainekio_asset_name_valid(output)
               ? AINEKIO_DECODE_VALUE
               : result;
}

static ainekio_decode_result_t decode_intent(
    const json_parser_t *parser,
    int root,
    ainekio_control_message_t *message
)
{
    char name[16];
    ainekio_decode_result_t result = sequence(parser, root, message);
    if (result != AINEKIO_DECODE_OK) {
        return result;
    }
    result = required_string(parser, root, "name", name, sizeof(name), 1U, 15U);
    if (result != AINEKIO_DECODE_OK) {
        return result;
    }
    message->has_command = true;
    message->command.kind = AINEKIO_COMMAND_INTENT;
    ainekio_intent_t *intent = &message->command.data.intent;
    if (strcmp(name, "sit") == 0) {
        intent->kind = AINEKIO_INTENT_SIT;
    } else if (strcmp(name, "stand") == 0) {
        intent->kind = AINEKIO_INTENT_STAND;
    } else if (strcmp(name, "neutral") == 0) {
        intent->kind = AINEKIO_INTENT_NEUTRAL;
    } else if (strcmp(name, "look") == 0) {
        int64_t yaw = 0;
        int64_t pitch = 0;
        int64_t duration = 400;
        intent->kind = AINEKIO_INTENT_LOOK;
        result = required_integer(parser, root, "yaw", -90, 90, &yaw);
        if (result == AINEKIO_DECODE_OK) {
            result = required_integer(parser, root, "pitch", -45, 45, &pitch);
        }
        const int duration_token = object_get(parser, root, "ms");
        if (result == AINEKIO_DECODE_OK && duration_token >= 0) {
            if (!token_integer(parser, duration_token, &duration)) {
                result = AINEKIO_DECODE_TYPE;
            } else if (duration < 100 || duration > 5000) {
                result = AINEKIO_DECODE_RANGE;
            }
        }
        intent->data.look.yaw = (int16_t)yaw;
        intent->data.look.pitch = (int16_t)pitch;
        intent->data.look.duration_ms = (uint16_t)duration;
        return result;
    } else if (strcmp(name, "walk") == 0) {
        static const char *const directions[] = {"fwd", "back", "turn_l", "turn_r"};
        char direction[8];
        int64_t steps = 0;
        intent->kind = AINEKIO_INTENT_WALK;
        result = required_string(parser, root, "dir", direction, sizeof(direction), 1U, 7U);
        if (result == AINEKIO_DECODE_OK &&
            !string_in(direction, directions, sizeof(directions) / sizeof(directions[0]))) {
            result = AINEKIO_DECODE_VALUE;
        }
        if (result == AINEKIO_DECODE_OK) {
            result = required_integer(parser, root, "steps", 1, 10, &steps);
        }
        for (uint8_t index = 0U; index < 4U; ++index) {
            if (strcmp(direction, directions[index]) == 0) {
                intent->data.walk.direction = (ainekio_walk_direction_t)index;
            }
        }
        intent->data.walk.steps = (uint8_t)steps;
        return result;
    } else if (strcmp(name, "emote") == 0) {
        intent->kind = AINEKIO_INTENT_EMOTE;
        return asset_string(parser, root, "asset", intent->data.asset);
    } else if (strcmp(name, "face") == 0) {
        intent->kind = AINEKIO_INTENT_FACE;
        return asset_string(parser, root, "expr", intent->data.asset);
    } else if (strcmp(name, "say") == 0) {
        intent->kind = AINEKIO_INTENT_SAY;
        return asset_string(parser, root, "asset", intent->data.asset);
    } else {
        return AINEKIO_DECODE_UNKNOWN;
    }
    return AINEKIO_DECODE_OK;
}

static ainekio_decode_result_t decode_simple_command(
    const json_parser_t *parser,
    int root,
    ainekio_control_message_t *message,
    ainekio_command_kind_t kind
)
{
    const ainekio_decode_result_t result = sequence(parser, root, message);
    if (result == AINEKIO_DECODE_OK) {
        message->has_command = true;
        message->command.kind = kind;
    }
    return result;
}

static ainekio_decode_result_t decode_motion_plan(
    const json_parser_t *parser,
    int root,
    ainekio_control_message_t *message
)
{
    ainekio_decode_result_t result =
        decode_simple_command(parser, root, message, AINEKIO_COMMAND_MOTION_PLAN);
    int64_t joint_map = 0;
    if (result == AINEKIO_DECODE_OK) {
        result = required_integer(
            parser,
            root,
            "map",
            AINEKIO_JOINT_MAP_VERSION,
            AINEKIO_JOINT_MAP_VERSION,
            &joint_map
        );
    }
    int frames = -1;
    if (result == AINEKIO_DECODE_OK) {
        result = required_token(parser, root, "frames", &frames);
    }
    if (result != AINEKIO_DECODE_OK) {
        return result;
    }
    if (parser->tokens[frames].type != JSON_TOKEN_ARRAY ||
        parser->tokens[frames].children < 1U ||
        parser->tokens[frames].children > AINEKIO_MOTION_PLAN_MAX_FRAMES) {
        return AINEKIO_DECODE_RANGE;
    }

    ainekio_motion_plan_t *plan = &message->command.data.motion_plan;
    plan->joint_map_version = (uint8_t)joint_map;
    plan->frame_count = (uint8_t)parser->tokens[frames].children;
    uint32_t total_duration_ms = 0U;
    for (uint8_t frame_index = 0U; frame_index < plan->frame_count; ++frame_index) {
        const int frame = array_get(parser, frames, frame_index);
        if (frame < 0 || parser->tokens[frame].type != JSON_TOKEN_ARRAY ||
            parser->tokens[frame].children != 2U) {
            return AINEKIO_DECODE_TYPE;
        }
        int64_t duration_ms = 0;
        if (!token_integer(parser, array_get(parser, frame, 0U), &duration_ms)) {
            return AINEKIO_DECODE_TYPE;
        }
        if (duration_ms < AINEKIO_MOTION_PLAN_MIN_FRAME_MS ||
            duration_ms > AINEKIO_MOTION_PLAN_MAX_FRAME_MS) {
            return AINEKIO_DECODE_RANGE;
        }
        total_duration_ms += (uint32_t)duration_ms;
        if (total_duration_ms > AINEKIO_MOTION_PLAN_MAX_TOTAL_MS) {
            return AINEKIO_DECODE_RANGE;
        }

        const int targets = array_get(parser, frame, 1U);
        if (targets < 0 || parser->tokens[targets].type != JSON_TOKEN_ARRAY ||
            parser->tokens[targets].children != AINEKIO_SERVO_COUNT) {
            return AINEKIO_DECODE_RANGE;
        }
        ainekio_motion_plan_frame_t *output_frame = &plan->frames[frame_index];
        output_frame->duration_ms = (uint16_t)duration_ms;
        for (uint8_t joint_id = 0U; joint_id < AINEKIO_SERVO_COUNT; ++joint_id) {
            int64_t centidegrees = 0;
            if (!token_integer(parser, array_get(parser, targets, joint_id), &centidegrees)) {
                return AINEKIO_DECODE_TYPE;
            }
            if (centidegrees < 0 ||
                centidegrees > AINEKIO_MOTION_PLAN_MAX_CENTIDEGREES) {
                return AINEKIO_DECODE_RANGE;
            }
            output_frame->targets[joint_id] = (uint16_t)centidegrees;
        }
    }
    plan->total_duration_ms = (uint16_t)total_duration_ms;

    char end[8];
    result = required_string(parser, root, "end", end, sizeof(end), 4U, 7U);
    if (result != AINEKIO_DECODE_OK) {
        return result;
    }
    if (strcmp(end, "hold") == 0) {
        plan->end = AINEKIO_MOTION_PLAN_END_HOLD;
    } else if (strcmp(end, "stand") == 0) {
        plan->end = AINEKIO_MOTION_PLAN_END_STAND;
    } else if (strcmp(end, "neutral") == 0) {
        plan->end = AINEKIO_MOTION_PLAN_END_NEUTRAL;
    } else {
        return AINEKIO_DECODE_VALUE;
    }
    return AINEKIO_DECODE_OK;
}

static ainekio_decode_result_t decode_tts(
    const json_parser_t *parser,
    int root,
    ainekio_control_message_t *message
)
{
    char operation[8];
    ainekio_decode_result_t result =
        decode_simple_command(parser, root, message, AINEKIO_COMMAND_TTS);
    if (result == AINEKIO_DECODE_OK) {
        result = required_string(parser, root, "op", operation, sizeof(operation), 1U, 7U);
    }
    if (result != AINEKIO_DECODE_OK) {
        return result;
    }
    if (strcmp(operation, "start") == 0) {
        message->command.data.tts_operation = AINEKIO_TTS_START;
    } else if (strcmp(operation, "end") == 0) {
        message->command.data.tts_operation = AINEKIO_TTS_END;
    } else if (strcmp(operation, "cancel") == 0) {
        message->command.data.tts_operation = AINEKIO_TTS_CANCEL;
    } else {
        return AINEKIO_DECODE_VALUE;
    }
    return AINEKIO_DECODE_OK;
}

static ainekio_decode_result_t decode_camera(
    const json_parser_t *parser,
    int root,
    ainekio_control_message_t *message
)
{
    char resolution[8];
    int64_t fps = 0;
    ainekio_decode_result_t result =
        decode_simple_command(parser, root, message, AINEKIO_COMMAND_CAMERA);
    if (result == AINEKIO_DECODE_OK) {
        result = required_boolean(parser, root, "on", &message->command.data.camera.enabled);
    }
    if (result == AINEKIO_DECODE_OK) {
        result = required_integer(parser, root, "fps", 0, 15, &fps);
    }
    if (result == AINEKIO_DECODE_OK) {
        result = required_string(parser, root, "res", resolution, sizeof(resolution), 3U, 4U);
    }
    if (result != AINEKIO_DECODE_OK) {
        return result;
    }
    if (strcmp(resolution, "QVGA") == 0) {
        message->command.data.camera.resolution = AINEKIO_CAMERA_QVGA;
    } else if (strcmp(resolution, "VGA") == 0) {
        message->command.data.camera.resolution = AINEKIO_CAMERA_VGA;
    } else {
        return AINEKIO_DECODE_VALUE;
    }
    message->command.data.camera.fps = (uint8_t)fps;
    return AINEKIO_DECODE_OK;
}

static ainekio_decode_result_t decode_microphone(
    const json_parser_t *parser,
    int root,
    ainekio_control_message_t *message
)
{
    char gate[8];
    ainekio_decode_result_t result =
        decode_simple_command(parser, root, message, AINEKIO_COMMAND_MICROPHONE);
    if (result == AINEKIO_DECODE_OK) {
        result = required_boolean(parser, root, "on", &message->command.data.microphone.enabled);
    }
    if (result == AINEKIO_DECODE_OK) {
        result = required_string(parser, root, "gate", gate, sizeof(gate), 3U, 4U);
    }
    if (result != AINEKIO_DECODE_OK) {
        return result;
    }
    if (strcmp(gate, "open") == 0) {
        message->command.data.microphone.gate = AINEKIO_MIC_GATE_OPEN;
    } else if (strcmp(gate, "vad") == 0) {
        message->command.data.microphone.gate = AINEKIO_MIC_GATE_VAD;
    } else if (strcmp(gate, "wake") == 0) {
        message->command.data.microphone.gate = AINEKIO_MIC_GATE_WAKE;
    } else {
        return AINEKIO_DECODE_VALUE;
    }
    return AINEKIO_DECODE_OK;
}

static ainekio_decode_result_t decode_wake_config(
    const json_parser_t *parser,
    int root,
    ainekio_control_message_t *message
)
{
    ainekio_decode_result_t result =
        decode_simple_command(parser, root, message, AINEKIO_COMMAND_WAKE_CONFIG);
    if (result == AINEKIO_DECODE_OK) {
        result = required_boolean(parser, root, "enabled", &message->command.data.wake.enabled);
    }
    if (result == AINEKIO_DECODE_OK) {
        result = asset_string(parser, root, "model", message->command.data.wake.model);
    }
    return result;
}

static ainekio_decode_result_t decode_profile(
    const json_parser_t *parser,
    int root,
    ainekio_control_message_t *message
)
{
    char profile[8];
    ainekio_decode_result_t result =
        decode_simple_command(parser, root, message, AINEKIO_COMMAND_PROFILE);
    if (result == AINEKIO_DECODE_OK) {
        result = required_string(parser, root, "name", profile, sizeof(profile), 4U, 6U);
    }
    if (result != AINEKIO_DECODE_OK) {
        return result;
    }
    if (strcmp(profile, "home") == 0) {
        message->command.data.profile = AINEKIO_PROFILE_HOME;
    } else if (strcmp(profile, "tether") == 0) {
        message->command.data.profile = AINEKIO_PROFILE_TETHER;
    } else {
        return AINEKIO_DECODE_VALUE;
    }
    return AINEKIO_DECODE_OK;
}

static ainekio_decode_result_t decode_state(
    const json_parser_t *parser,
    int root,
    ainekio_control_message_t *message
)
{
    char state[8];
    ainekio_decode_result_t result =
        decode_simple_command(parser, root, message, AINEKIO_COMMAND_STATE);
    if (result == AINEKIO_DECODE_OK) {
        result = required_string(parser, root, "name", state, sizeof(state), 4U, 5U);
    }
    if (result != AINEKIO_DECODE_OK) {
        return result;
    }
    if (strcmp(state, "idle") == 0) {
        message->command.data.state.request = AINEKIO_STATE_REQUEST_IDLE;
    } else if (strcmp(state, "doze") == 0) {
        message->command.data.state.request = AINEKIO_STATE_REQUEST_DOZE;
    } else if (strcmp(state, "sleep") == 0) {
        int64_t sleep_seconds = 0;
        result = required_integer(parser, root, "sleep_s", 60, 86400, &sleep_seconds);
        message->command.data.state.request = AINEKIO_STATE_REQUEST_SLEEP;
        message->command.data.state.sleep_seconds = (uint32_t)sleep_seconds;
    } else {
        result = AINEKIO_DECODE_VALUE;
    }
    return result;
}

static ainekio_decode_result_t decode_mode(
    const json_parser_t *parser,
    int root,
    ainekio_control_message_t *message
)
{
    char mode[10];
    ainekio_decode_result_t result =
        decode_simple_command(parser, root, message, AINEKIO_COMMAND_MODE);
    if (result == AINEKIO_DECODE_OK) {
        result = required_string(parser, root, "name", mode, sizeof(mode), 6U, 9U);
    }
    if (result != AINEKIO_DECODE_OK) {
        return result;
    }
    if (strcmp(mode, "calibrate") == 0) {
        message->command.data.mode = AINEKIO_MODE_CALIBRATE;
    } else if (strcmp(mode, "normal") == 0) {
        message->command.data.mode = AINEKIO_MODE_NORMAL;
    } else {
        return AINEKIO_DECODE_VALUE;
    }
    return AINEKIO_DECODE_OK;
}

static ainekio_decode_result_t decode_servo(
    const json_parser_t *parser,
    int root,
    ainekio_control_message_t *message
)
{
    int64_t id = 0;
    int64_t duration = 0;
    ainekio_decode_result_t result =
        decode_simple_command(parser, root, message, AINEKIO_COMMAND_SERVO);
    if (result == AINEKIO_DECODE_OK) {
        result = required_integer(parser, root, "id", 0, 7, &id);
    }
    if (result == AINEKIO_DECODE_OK) {
        result = required_number(parser, root, "deg", &message->command.data.servo.degrees);
    }
    if (result == AINEKIO_DECODE_OK) {
        result = required_integer(parser, root, "ms", 0, 5000, &duration);
    }
    message->command.data.servo.id = (uint8_t)id;
    message->command.data.servo.duration_ms = (uint16_t)duration;
    return result;
}

static ainekio_decode_result_t decode_limits(
    const json_parser_t *parser,
    int root,
    ainekio_control_message_t *message
)
{
    int64_t id = 0;
    ainekio_decode_result_t result =
        decode_simple_command(parser, root, message, AINEKIO_COMMAND_LIMITS);
    if (result == AINEKIO_DECODE_OK) {
        result = required_integer(parser, root, "id", 0, 7, &id);
    }
    if (result == AINEKIO_DECODE_OK) {
        result = required_number(parser, root, "min", &message->command.data.limits.minimum);
    }
    if (result == AINEKIO_DECODE_OK) {
        result = required_number(parser, root, "max", &message->command.data.limits.maximum);
    }
    if (result == AINEKIO_DECODE_OK) {
        result = required_boolean(parser, root, "invert", &message->command.data.limits.invert);
    }
    if (result == AINEKIO_DECODE_OK) {
        result = required_number(parser, root, "center", &message->command.data.limits.center);
    }
    message->command.data.limits.id = (uint8_t)id;
    if (result == AINEKIO_DECODE_OK &&
        (message->command.data.limits.minimum > message->command.data.limits.maximum ||
         message->command.data.limits.center < message->command.data.limits.minimum ||
         message->command.data.limits.center > message->command.data.limits.maximum)) {
        result = AINEKIO_DECODE_RANGE;
    }
    return result;
}

static ainekio_decode_result_t decode_pose(
    const json_parser_t *parser,
    int root,
    ainekio_control_message_t *message
)
{
    ainekio_decode_result_t result =
        decode_simple_command(parser, root, message, AINEKIO_COMMAND_POSE_SAVE);
    if (result == AINEKIO_DECODE_OK) {
        result = asset_string(parser, root, "name", message->command.data.pose.name);
    }
    int servos = -1;
    if (result == AINEKIO_DECODE_OK) {
        result = required_token(parser, root, "servos", &servos);
    }
    if (result != AINEKIO_DECODE_OK) {
        return result;
    }
    if (parser->tokens[servos].type != JSON_TOKEN_ARRAY ||
        parser->tokens[servos].children < 1U ||
        parser->tokens[servos].children > AINEKIO_SERVO_COUNT) {
        return AINEKIO_DECODE_TYPE;
    }
    uint8_t seen = 0U;
    message->command.data.pose.count = (uint8_t)parser->tokens[servos].children;
    for (uint8_t index = 0U; index < message->command.data.pose.count; ++index) {
        const int pair = array_get(parser, servos, index);
        if (pair < 0 || parser->tokens[pair].type != JSON_TOKEN_ARRAY ||
            parser->tokens[pair].children != 2U) {
            return AINEKIO_DECODE_TYPE;
        }
        int64_t id = 0;
        float degrees = 0.0F;
        if (!token_integer(parser, array_get(parser, pair, 0U), &id)) {
            return AINEKIO_DECODE_TYPE;
        }
        if (id < 0 || id >= AINEKIO_SERVO_COUNT) {
            return AINEKIO_DECODE_RANGE;
        }
        if (!token_number(parser, array_get(parser, pair, 1U), &degrees)) {
            return AINEKIO_DECODE_TYPE;
        }
        if ((seen & (uint8_t)(1U << id)) != 0U) {
            return AINEKIO_DECODE_VALUE;
        }
        seen |= (uint8_t)(1U << id);
        message->command.data.pose.targets[index] = (ainekio_servo_target_t){
            .id = (uint8_t)id,
            .degrees = degrees,
        };
    }
    return AINEKIO_DECODE_OK;
}

static ainekio_decode_result_t validate_string_enum(
    const json_parser_t *parser,
    int root,
    const char *field,
    const char *const *allowed,
    size_t count
)
{
    char value[JSON_STRING_BUFFER];
    const ainekio_decode_result_t result = required_string(
        parser,
        root,
        field,
        value,
        sizeof(value),
        1U,
        sizeof(value) - 1U
    );
    return result == AINEKIO_DECODE_OK && !string_in(value, allowed, count)
               ? AINEKIO_DECODE_VALUE
               : result;
}

static ainekio_decode_result_t validate_outbound(
    const json_parser_t *parser,
    int root,
    ainekio_control_message_t *message
)
{
    int64_t integer = 0;
    float number = 0.0F;
    bool boolean = false;
    char string[JSON_STRING_BUFFER];
    ainekio_decode_result_t result = AINEKIO_DECODE_OK;
    if (message->kind == AINEKIO_MESSAGE_HELLO) {
        result = no_sequence(parser, root);
        if (result == AINEKIO_DECODE_OK) {
            result = required_integer(parser, root, "ver", 1, 1, &integer);
        }
        if (result == AINEKIO_DECODE_OK) {
            result = required_string(parser, root, "fw", string, sizeof(string), 1U, 32U);
        }
        if (result == AINEKIO_DECODE_OK) {
            result = required_string(parser, root, "id", string, sizeof(string), 1U, 64U);
        }
        if (result == AINEKIO_DECODE_OK) {
            result = required_string(parser, root, "auth", string, sizeof(string), 1U, 128U);
        }
        const int features = object_get(parser, root, "features");
        if (result == AINEKIO_DECODE_OK && features >= 0) {
            if (parser->tokens[features].type != JSON_TOKEN_ARRAY ||
                parser->tokens[features].children > 16U) {
                return AINEKIO_DECODE_RANGE;
            }
            for (uint16_t index = 0U; index < parser->tokens[features].children; ++index) {
                const int feature = array_get(parser, features, index);
                size_t feature_length = 0U;
                char feature_name[33];
                if (!token_string_copy(
                        parser,
                        feature,
                        feature_name,
                        sizeof(feature_name),
                        &feature_length
                    ) ||
                    feature_length < 1U || feature_length > 32U) {
                    return AINEKIO_DECODE_TYPE;
                }
                for (size_t character = 0U; character < feature_length; ++character) {
                    const char value = feature_name[character];
                    if (!((value >= 'a' && value <= 'z') ||
                          (value >= '0' && value <= '9') || value == '_')) {
                        return AINEKIO_DECODE_VALUE;
                    }
                }
                for (uint16_t previous = 0U; previous < index; ++previous) {
                    if (token_string_equal(
                            parser,
                            array_get(parser, features, previous),
                            feature_name
                        )) {
                        return AINEKIO_DECODE_VALUE;
                    }
                }
            }
        }
    } else if (message->kind == AINEKIO_MESSAGE_ACK ||
               message->kind == AINEKIO_MESSAGE_DONE) {
        result = sequence(parser, root, message);
        const int sleep_token = object_get(parser, root, "sleep_s");
        if (result == AINEKIO_DECODE_OK && message->kind == AINEKIO_MESSAGE_ACK &&
            sleep_token >= 0 &&
            (!token_integer(parser, sleep_token, &integer) || integer < 60 || integer > 86400)) {
            result = AINEKIO_DECODE_RANGE;
        }
    } else if (message->kind == AINEKIO_MESSAGE_NAK) {
        static const char *const codes[] = {
            "stale", "mode", "unsafe", "limit", "unknown", "busy",
            "profile", "malformed", "asset_missing",
        };
        result = validate_string_enum(parser, root, "code", codes, sizeof(codes) / sizeof(codes[0]));
        const int code_token = object_get(parser, root, "code");
        const bool malformed = code_token >= 0 && token_string_equal(parser, code_token, "malformed");
        if (result == AINEKIO_DECODE_OK && object_get(parser, root, "seq") >= 0) {
            result = sequence(parser, root, message);
        } else if (result == AINEKIO_DECODE_OK && !malformed) {
            result = AINEKIO_DECODE_MISSING;
        }
        const int msg_token = object_get(parser, root, "msg");
        size_t length = 0U;
        if (result == AINEKIO_DECODE_OK && msg_token >= 0 &&
            (!token_string_copy(parser, msg_token, string, sizeof(string), &length) ||
             length < 1U || length > 160U)) {
            result = AINEKIO_DECODE_RANGE;
        }
    } else if (message->kind == AINEKIO_MESSAGE_CANCELLED) {
        static const char *const codes[] = {"stop", "disconnect", "reconnect", "overflow"};
        result = sequence(parser, root, message);
        if (result == AINEKIO_DECODE_OK) {
            result = validate_string_enum(parser, root, "code", codes, sizeof(codes) / sizeof(codes[0]));
        }
    } else if (message->kind == AINEKIO_MESSAGE_STATUS) {
        static const char *const states[] = {"active", "idle", "dozing", "deep-sleep", "failsafe"};
        result = required_number(parser, root, "vbat", &number);
        if (result == AINEKIO_DECODE_OK) result = required_integer(parser, root, "rssi", -127, 0, &integer);
        if (result == AINEKIO_DECODE_OK) result = validate_string_enum(parser, root, "state", states, 5U);
        if (result == AINEKIO_DECODE_OK) result = required_integer(parser, root, "uptime", 0, INT64_MAX, &integer);
        if (result == AINEKIO_DECODE_OK) result = required_integer(parser, root, "heap", 0, INT64_MAX, &integer);
        if (result == AINEKIO_DECODE_OK) result = required_boolean(parser, root, "sd", &boolean);
        if (result == AINEKIO_DECODE_OK) result = required_integer(parser, root, "cam_drops", 0, INT64_MAX, &integer);
        if (result == AINEKIO_DECODE_OK) result = required_integer(parser, root, "spk_underruns", 0, INT64_MAX, &integer);
        if (result == AINEKIO_DECODE_OK) result = required_integer(parser, root, "mic_drops", 0, INT64_MAX, &integer);
    } else if (message->kind == AINEKIO_MESSAGE_EVENT) {
        static const char *const events[] = {
            "vad_open", "vad_close", "wake_word", "battery_warn", "battery_cutoff",
            "brownout_recovered", "boot", "sd_fail", "sd_corrupt", "littlefs_fail",
            "asset_missing", "tts_orphan", "tts_overflow",
        };
        result = validate_string_enum(parser, root, "name", events, sizeof(events) / sizeof(events[0]));
    } else if (message->kind == AINEKIO_MESSAGE_CAMERA_META) {
        static const char *const resolutions[] = {"QVGA", "VGA"};
        result = validate_string_enum(parser, root, "res", resolutions, 2U);
        if (result == AINEKIO_DECODE_OK) result = required_integer(parser, root, "fps", 0, 15, &integer);
        if (result == AINEKIO_DECODE_OK) result = required_integer(parser, root, "counter_base", 0, UINT32_MAX, &integer);
    }
    return result;
}

ainekio_decode_result_t ainekio_control_decode(
    const char *json,
    size_t length,
    ainekio_control_message_t *message
)
{
    if (json == NULL || message == NULL) {
        return AINEKIO_DECODE_TYPE;
    }
    if (length == 0U || length > AINEKIO_CONTROL_MAX_BYTES || length > UINT16_MAX) {
        return AINEKIO_DECODE_OVERSIZE;
    }
    json_parser_t parser = {.json = json, .length = length};
    skip_space(&parser);
    const int root = parse_value(&parser, -1, 0U);
    skip_space(&parser);
    if (root < 0 || parser.cursor != parser.length) {
        return parser.token_overflow ? AINEKIO_DECODE_TOKENS : AINEKIO_DECODE_JSON;
    }
    if (parser.tokens[root].type != JSON_TOKEN_OBJECT) {
        return AINEKIO_DECODE_TYPE;
    }
    if (!object_keys_unique(&parser)) {
        return AINEKIO_DECODE_JSON;
    }
    memset(message, 0, sizeof(*message));
    char type[24];
    ainekio_decode_result_t result =
        required_string(&parser, root, "t", type, sizeof(type), 1U, 23U);
    if (result != AINEKIO_DECODE_OK) {
        return result;
    }
    static const char *const types[] = {
        "hello", "err", "welcome", "intent", "stop", "motion_plan", "tts", "cam", "snap",
        "mic", "wake", "profile", "state", "ping", "mode", "servo", "limits",
        "pose_save", "cal_save", "ack", "nak", "done", "cancelled", "status",
        "event", "cam_meta", "pong",
    };
    size_t kind = sizeof(types) / sizeof(types[0]);
    for (size_t index = 0U; index < sizeof(types) / sizeof(types[0]); ++index) {
        if (strcmp(type, types[index]) == 0) {
            kind = index;
            break;
        }
    }
    if (kind == sizeof(types) / sizeof(types[0])) {
        return AINEKIO_DECODE_VALUE;
    }
    message->kind = (ainekio_message_kind_t)kind;
    switch (message->kind) {
    case AINEKIO_MESSAGE_ERROR: {
        static const char *const codes[] = {"auth", "ver"};
        result = no_sequence(&parser, root);
        if (result == AINEKIO_DECODE_OK) {
            result = validate_string_enum(&parser, root, "code", codes, 2U);
        }
        const int code = object_get(&parser, root, "code");
        if (result == AINEKIO_DECODE_OK) {
            message->data.session_error = token_string_equal(&parser, code, "auth")
                                              ? AINEKIO_SESSION_ERROR_AUTH
                                              : AINEKIO_SESSION_ERROR_VERSION;
        }
        return result;
    }
    case AINEKIO_MESSAGE_WELCOME: {
        int64_t version = 0;
        int64_t epoch = 0;
        char profile[8];
        result = no_sequence(&parser, root);
        if (result == AINEKIO_DECODE_OK) result = required_integer(&parser, root, "ver", 1, 1, &version);
        if (result == AINEKIO_DECODE_OK) result = required_integer(&parser, root, "epoch", 0, UINT32_MAX, &epoch);
        if (result == AINEKIO_DECODE_OK) result = required_string(&parser, root, "profile", profile, sizeof(profile), 4U, 6U);
        if (result == AINEKIO_DECODE_OK && strcmp(profile, "home") != 0 && strcmp(profile, "tether") != 0) result = AINEKIO_DECODE_VALUE;
        if (result == AINEKIO_DECODE_OK) {
            message->data.welcome.epoch = (uint32_t)epoch;
            message->data.welcome.profile = strcmp(profile, "home") == 0 ? AINEKIO_PROFILE_HOME : AINEKIO_PROFILE_TETHER;
        }
        return result;
    }
    case AINEKIO_MESSAGE_INTENT:
        return decode_intent(&parser, root, message);
    case AINEKIO_MESSAGE_STOP:
        return decode_simple_command(&parser, root, message, AINEKIO_COMMAND_STOP);
    case AINEKIO_MESSAGE_MOTION_PLAN:
        return decode_motion_plan(&parser, root, message);
    case AINEKIO_MESSAGE_TTS:
        return decode_tts(&parser, root, message);
    case AINEKIO_MESSAGE_CAMERA:
        return decode_camera(&parser, root, message);
    case AINEKIO_MESSAGE_SNAPSHOT:
        return decode_simple_command(&parser, root, message, AINEKIO_COMMAND_SNAPSHOT);
    case AINEKIO_MESSAGE_MICROPHONE:
        return decode_microphone(&parser, root, message);
    case AINEKIO_MESSAGE_WAKE_CONFIG:
        return decode_wake_config(&parser, root, message);
    case AINEKIO_MESSAGE_PROFILE:
        return decode_profile(&parser, root, message);
    case AINEKIO_MESSAGE_STATE:
        return decode_state(&parser, root, message);
    case AINEKIO_MESSAGE_PING:
    case AINEKIO_MESSAGE_PONG:
        return no_sequence(&parser, root);
    case AINEKIO_MESSAGE_MODE:
        return decode_mode(&parser, root, message);
    case AINEKIO_MESSAGE_SERVO:
        return decode_servo(&parser, root, message);
    case AINEKIO_MESSAGE_LIMITS:
        return decode_limits(&parser, root, message);
    case AINEKIO_MESSAGE_POSE_SAVE:
        return decode_pose(&parser, root, message);
    case AINEKIO_MESSAGE_CALIBRATION_SAVE:
        return decode_simple_command(&parser, root, message, AINEKIO_COMMAND_CALIBRATION_SAVE);
    default:
        return validate_outbound(&parser, root, message);
    }
}

const char *ainekio_decode_result_name(ainekio_decode_result_t result)
{
    static const char *const names[] = {
        "ok", "oversize", "json", "tokens", "type", "missing", "range", "value",
        "unknown",
    };
    return (unsigned int)result < sizeof(names) / sizeof(names[0]) ? names[result]
                                                                   : "unknown";
}
