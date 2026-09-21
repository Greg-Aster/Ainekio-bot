# Ainekio the Robot Familiar

  Ainekio the Robot Familiar is a hardware and software project for building a small robot companion powered by MetaHuman OS. The robot uses a physical body,
  onboard sensors, and a network connection to let MetaHuman OS see, listen, speak, move, and interact through a physical chassis.

- Progress blog and current status: [ainek.io](https://ainek.io)
- MetaHuman OS development repo: [Greg-Aster/metahuman-os](https://github.com/Greg-Aster/metahuman-os)
- Current test body: based on the Sesame robot: [dorianborian/sesame-robot](https://github.com/dorianborian/sesame-robot)

## Robot Models

- **V1 / eight servos:** the existing Freenove ESP32-S3 robot, with direct
  MCPWM servo outputs. [Wiring and hardware records](docs/v1-8servo/PINOUT_DIAGNOSTICS.md).
- **V2 / twelve servos:** native ESP32-P4-WIFI6 bring-up with a PCA9685 driver;
  electrical acceptance and body motion remain pending. [V2 status](docs/v2-12servo/README.md).

Both models are intended to use the same gateway and Body Control interface.
V1 remains supported alongside V2. The complete motion runtime currently implements V1;
[Robot Models](docs/ROBOT_MODELS.md) records the separation boundaries and the
remaining code work for V2.

## Repository Layout

- `Master/` - remote brain and gateway code.
- `Slave/hardware/v1-8servo/` - V1 CAD and physical-body assets.
- `Slave/hardware/v2-12servo/` - V2 CAD, source assemblies, and printable parts.
- `Slave/software/` - portable slave-brain core, protocol, and tests.
- `Slave/firmware/esp32s3/` - current V1 firmware that runs on the robot.
- `Slave/firmware/esp32p4-wifi6/` - native V2 board/network/output-disable bring-up.
- `Emulator/` - host body emulator, Sesame visual simulator, and tests.
- `docs/` - specifications, progress records, repository map, and the ignored
  Sesame reference clone.

The V1 physical robot entry point is
`Slave/firmware/esp32s3/main/app_main.c`. See `docs/REPOSITORY_MAP.md` for the
complete ownership map.

Run the complete local software stack with:

```sh
cp .env.example .env
# Set AINEKIO_ENVIRONMENT_ADAPTER_TOKEN to the adapter token used by MetaHuman OS.
./start.sh
```

This one command starts the visual simulator, protocol-v1 body emulator, Master
gateway, operator dashboard, and authenticated environment adapter. The
launcher refuses to start when the shared bridge token is missing instead of
silently running a disconnected gateway. It prints the dashboard password and
local inspection URLs; pressing `Ctrl+C` stops the entire stack. Run all A1-A30
software acceptance gates with
`python3 Emulator/tools/run_acceptance.py`.
