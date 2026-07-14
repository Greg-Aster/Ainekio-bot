# Slave Software Core

This directory contains portable C logic compiled for both the ESP32-S3 slave
firmware and host tests. It must not include ESP-IDF, FreeRTOS, socket, GPIO, or
filesystem headers.

## Owners

- `core.c` owns command acceptance, lifecycle, state, and movement safety.
- `protocol.c` owns bounded C protocol normalization used by the body core.
- `provisioning.c` owns WiFi/provisioning transitions and emits platform actions.
- `config_schema.h` defines the versioned NVS namespace and key contract.

## Provisioning Storage

Configuration uses bounded A/B slots. The inactive slot is written and marked
complete first. WiFi is validated against that staged slot, then one metadata
commit bumps `schema_ver` and switches `active_slot`. A failed validation or
commit leaves the previous active slot selected. Repeated replacements alternate
the two slots, so network records do not accumulate.

Calibration, named poses, default profile, and ADC settings use separate
namespaces so a network-only reset does not erase them.

## Validation

From the repository root:

```sh
cmake -S Slave/software/core -B /tmp/ainekio-core
cmake --build /tmp/ainekio-core
/usr/bin/ctest --test-dir /tmp/ainekio-core --output-on-failure
```
