#include "ainekio/platform/mcpwm_adapter.h"

#include <string.h>

#include "ainekio/platform/pin_map.h"
#include "driver/gpio.h"
#include "esp_check.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define AINEKIO_MCPWM_RESOLUTION_HZ UINT32_C(1000000)
#define AINEKIO_MCPWM_PERIOD_TICKS UINT32_C(20000)

static const char *TAG = "ainekio_mcpwm";

static bool physical_motion_enabled(void)
{
#ifdef CONFIG_AINEKIO_PHYSICAL_MOTION_ENABLED
    return true;
#else
    return false;
#endif
}

static bool servo_pin_map_safe_for_motion(void)
{
    for (uint8_t joint_id = 0U; joint_id < AINEKIO_SERVO_COUNT; ++joint_id) {
        const int gpio = ainekio_servo_pins[joint_id].gpio;
        if (ainekio_pin_is_reserved_for_psram(gpio)) {
            return false;
        }
    }
    return true;
}

static esp_err_t enable_output(
    ainekio_mcpwm_adapter_t *adapter,
    uint8_t joint_id,
    float physical_degrees
)
{
    ESP_RETURN_ON_ERROR(
        mcpwm_comparator_set_compare_value(
            adapter->comparators[joint_id],
            ainekio_servo_degrees_to_pulse(physical_degrees)
        ),
        TAG,
        "compare update failed"
    );
    if (adapter->output_enabled[joint_id]) {
        return ESP_OK;
    }
    ESP_RETURN_ON_ERROR(
        gpio_set_direction(ainekio_servo_pins[joint_id].gpio, GPIO_MODE_OUTPUT),
        TAG,
        "output attach failed"
    );
    ESP_RETURN_ON_ERROR(
        mcpwm_generator_set_force_level(adapter->generators[joint_id], -1, true),
        TAG,
        "output release failed"
    );
    adapter->output_enabled[joint_id] = true;
    return ESP_OK;
}

static size_t operator_slot(uint8_t group, uint8_t operator_index)
{
    return group == 0U ? operator_index : (size_t)(3U + operator_index);
}

static esp_err_t configure_timer(
    ainekio_mcpwm_adapter_t *adapter,
    uint8_t group
)
{
    const mcpwm_timer_config_t config = {
        .group_id = group,
        .clk_src = MCPWM_TIMER_CLK_SRC_DEFAULT,
        .resolution_hz = AINEKIO_MCPWM_RESOLUTION_HZ,
        .period_ticks = AINEKIO_MCPWM_PERIOD_TICKS,
        .count_mode = MCPWM_TIMER_COUNT_MODE_UP,
    };
    ESP_RETURN_ON_ERROR(mcpwm_new_timer(&config, &adapter->timers[group]), TAG,
                        "timer allocation failed");
    return ESP_OK;
}

static esp_err_t configure_operator(
    ainekio_mcpwm_adapter_t *adapter,
    uint8_t group,
    uint8_t operator_index
)
{
    const size_t slot = operator_slot(group, operator_index);
    const mcpwm_operator_config_t config = {.group_id = group};
    ESP_RETURN_ON_ERROR(mcpwm_new_operator(&config, &adapter->operators[slot]), TAG,
                        "operator allocation failed");
    ESP_RETURN_ON_ERROR(
        mcpwm_operator_connect_timer(adapter->operators[slot], adapter->timers[group]),
        TAG,
        "operator timer connection failed"
    );
    return ESP_OK;
}

static esp_err_t configure_channel(
    ainekio_mcpwm_adapter_t *adapter,
    uint8_t joint_id
)
{
    const ainekio_servo_pin_t *pin = &ainekio_servo_pins[joint_id];
    const mcpwm_oper_handle_t oper =
        adapter->operators[operator_slot(pin->mcpwm_group, pin->mcpwm_operator)];
    const mcpwm_comparator_config_t comparator_config = {
        .flags.update_cmp_on_tez = true,
    };
    ESP_RETURN_ON_ERROR(
        mcpwm_new_comparator(oper, &comparator_config, &adapter->comparators[joint_id]),
        TAG,
        "comparator allocation failed"
    );
    const mcpwm_generator_config_t generator_config = {.gen_gpio_num = pin->gpio};
    ESP_RETURN_ON_ERROR(
        mcpwm_new_generator(oper, &generator_config, &adapter->generators[joint_id]),
        TAG,
        "generator allocation failed"
    );
    ESP_RETURN_ON_ERROR(
        mcpwm_generator_set_force_level(adapter->generators[joint_id], 0, true),
        TAG,
        "initial output disable failed"
    );
    ESP_RETURN_ON_ERROR(
        mcpwm_comparator_set_compare_value(
            adapter->comparators[joint_id],
            ainekio_servo_degrees_to_pulse(90.0F)
        ),
        TAG,
        "initial comparator failed"
    );
    ESP_RETURN_ON_ERROR(
        mcpwm_generator_set_action_on_timer_event(
            adapter->generators[joint_id],
            MCPWM_GEN_TIMER_EVENT_ACTION(
                MCPWM_TIMER_DIRECTION_UP,
                MCPWM_TIMER_EVENT_EMPTY,
                MCPWM_GEN_ACTION_HIGH
            )
        ),
        TAG,
        "timer action failed"
    );
    ESP_RETURN_ON_ERROR(
        mcpwm_generator_set_action_on_compare_event(
            adapter->generators[joint_id],
            MCPWM_GEN_COMPARE_EVENT_ACTION(
                MCPWM_TIMER_DIRECTION_UP,
                adapter->comparators[joint_id],
                MCPWM_GEN_ACTION_LOW
            )
        ),
        TAG,
        "compare action failed"
    );
    ESP_RETURN_ON_ERROR(gpio_set_direction(pin->gpio, GPIO_MODE_DISABLE), TAG,
                        "initial high impedance failed");
    ESP_LOGI(TAG,
             "joint=%u label=%s group=%u operator=%u generator=%u gpio=%d detached=high-z",
             (unsigned int)pin->joint_id,
             pin->label,
             (unsigned int)pin->mcpwm_group,
             (unsigned int)pin->mcpwm_operator,
             (unsigned int)pin->mcpwm_generator,
             pin->gpio);
    return ESP_OK;
}

esp_err_t ainekio_mcpwm_adapter_init(ainekio_mcpwm_adapter_t *adapter)
{
    if (adapter == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    memset(adapter, 0, sizeof(*adapter));
    if (!physical_motion_enabled()) {
        adapter->initialized = true;
        ESP_LOGW(TAG, "physical motion disabled; servo GPIO mux remains untouched");
        return ESP_OK;
    }
    if (!ainekio_pin_map_valid() || !servo_pin_map_safe_for_motion()) {
        ESP_LOGE(TAG, "physical motion blocked: servo pin map is unsafe");
        return ESP_ERR_INVALID_ARG;
    }
    ESP_RETURN_ON_ERROR(configure_timer(adapter, 0U), TAG, "group 0 timer failed");
    ESP_RETURN_ON_ERROR(configure_timer(adapter, 1U), TAG, "group 1 timer failed");
    for (uint8_t operator_index = 0U; operator_index < 3U; ++operator_index) {
        ESP_RETURN_ON_ERROR(configure_operator(adapter, 0U, operator_index), TAG,
                            "group 0 operator failed");
    }
    ESP_RETURN_ON_ERROR(configure_operator(adapter, 1U, 0U), TAG,
                        "group 1 operator failed");
    for (uint8_t joint_id = 0U; joint_id < AINEKIO_SERVO_COUNT; ++joint_id) {
        ESP_RETURN_ON_ERROR(configure_channel(adapter, joint_id), TAG,
                            "servo channel failed");
    }
    for (uint8_t group = 0U; group < 2U; ++group) {
        ESP_RETURN_ON_ERROR(mcpwm_timer_enable(adapter->timers[group]), TAG,
                            "timer enable failed");
        ESP_RETURN_ON_ERROR(
            mcpwm_timer_start_stop(adapter->timers[group], MCPWM_TIMER_START_NO_STOP),
            TAG,
            "timer start failed"
        );
    }
    adapter->initialized = true;
    return ESP_OK;
}

esp_err_t ainekio_mcpwm_adapter_enable_all(
    ainekio_mcpwm_adapter_t *adapter,
    ainekio_servo_bank_t *bank,
    uint16_t stagger_ms
)
{
    if (adapter == NULL || bank == NULL || !adapter->initialized) {
        return ESP_ERR_INVALID_ARG;
    }
    if (!physical_motion_enabled()) {
        return ESP_ERR_INVALID_STATE;
    }
    for (uint8_t joint_id = 0U; joint_id < AINEKIO_SERVO_COUNT; ++joint_id) {
        ainekio_servo_channel_t *channel = &bank->channels[joint_id];
        const float center = channel->calibration.center_degrees;
        channel->current_degrees = center;
        channel->target_degrees = center;
        channel->remaining_ticks = 0U;
        channel->attached = true;
        const esp_err_t result = enable_output(adapter, joint_id, center);
        if (result != ESP_OK) {
            ainekio_servo_detach_all(bank);
            (void)ainekio_mcpwm_adapter_detach_all(adapter);
            return result;
        }
        ESP_LOGI(
            TAG,
            "startup joint=%u label=%s gpio=%d center=%.1f enabled=true",
            (unsigned int)joint_id,
            ainekio_servo_pins[joint_id].label,
            ainekio_servo_pins[joint_id].gpio,
            (double)center
        );
        if (stagger_ms > 0U && joint_id + 1U < AINEKIO_SERVO_COUNT) {
            vTaskDelay(pdMS_TO_TICKS(stagger_ms));
        }
    }
    return ESP_OK;
}

esp_err_t ainekio_mcpwm_adapter_detach(
    ainekio_mcpwm_adapter_t *adapter,
    uint8_t joint_id
)
{
    if (adapter == NULL || !adapter->initialized || joint_id >= AINEKIO_SERVO_COUNT) {
        return ESP_ERR_INVALID_ARG;
    }
    if (!physical_motion_enabled()) {
        return ESP_OK;
    }
    ESP_RETURN_ON_ERROR(
        mcpwm_generator_set_force_level(adapter->generators[joint_id], 0, true),
        TAG,
        "force low before detach failed"
    );
    ESP_RETURN_ON_ERROR(
        gpio_set_direction(ainekio_servo_pins[joint_id].gpio, GPIO_MODE_DISABLE),
        TAG,
        "high impedance detach failed"
    );
    adapter->output_enabled[joint_id] = false;
    return ESP_OK;
}

esp_err_t ainekio_mcpwm_adapter_detach_all(ainekio_mcpwm_adapter_t *adapter)
{
    if (adapter == NULL || !adapter->initialized) {
        return ESP_ERR_INVALID_ARG;
    }
    if (!physical_motion_enabled()) {
        return ESP_OK;
    }
    for (uint8_t joint_id = 0U; joint_id < AINEKIO_SERVO_COUNT; ++joint_id) {
        ESP_RETURN_ON_ERROR(ainekio_mcpwm_adapter_detach(adapter, joint_id), TAG,
                            "channel detach failed");
    }
    return ESP_OK;
}

esp_err_t ainekio_mcpwm_adapter_sync(
    ainekio_mcpwm_adapter_t *adapter,
    ainekio_servo_bank_t *bank
)
{
    if (adapter == NULL || bank == NULL || !adapter->initialized) {
        return ESP_ERR_INVALID_ARG;
    }
    if (!physical_motion_enabled()) {
        return ESP_ERR_INVALID_STATE;
    }
    ainekio_servo_tick(bank);
    for (uint8_t joint_id = 0U; joint_id < AINEKIO_SERVO_COUNT; ++joint_id) {
        const ainekio_servo_channel_t *channel = &bank->channels[joint_id];
        if (!channel->attached) {
            if (adapter->output_enabled[joint_id]) {
                ESP_RETURN_ON_ERROR(ainekio_mcpwm_adapter_detach(adapter, joint_id), TAG,
                                    "channel detach failed");
            }
            continue;
        }
        ESP_RETURN_ON_ERROR(
            enable_output(adapter, joint_id, channel->current_degrees),
            TAG,
            "channel enable failed"
        );
    }
    return ESP_OK;
}
