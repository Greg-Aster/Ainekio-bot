#ifndef AINEKIO_PLATFORM_SLEEP_SERVICE_H
#define AINEKIO_PLATFORM_SLEEP_SERVICE_H

#include <stdint.h>

void ainekio_sleep_enter(uint32_t seconds) __attribute__((noreturn));

#endif
