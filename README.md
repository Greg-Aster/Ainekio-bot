# Ainekio the Robot Familiar

  Ainekio the Robot Familiar is a hardware and software project for building a small robot companion powered by MetaHuman OS. The robot uses a physical body,
  onboard sensors, and a network connection to let MetaHuman OS see, listen, speak, move, and interact through a physical chassis.

- Progress blog and current status: [ainek.io](https://ainek.io)
- MetaHuman OS development repo: [Greg-Aster/metahuman-os](https://github.com/Greg-Aster/metahuman-os)
- Retained V1 reference body: based on the Sesame robot: [dorianborian/sesame-robot](https://github.com/dorianborian/sesame-robot)

## Start here for robot development

Read the shared [robot design core](../metahuman/docs/robot/ROBOT_BIBLE.md)
for the companion's purpose, architecture, ownership and maintenance approach.
For processes, interfaces, source owners and execution paths, read the shared
[Robot software architecture](../metahuman/docs/robot/SYSTEM_ARCHITECTURE.md).
Then follow the contract and qualification scenario relevant to your task.
The canonical file lives at `docs/robot/ROBOT_BIBLE.md` in the MetaHuman repository
linked above; local cross-repository links assume sibling checkouts. Both humans
and agents use the same core. [AGENTS.md](AGENTS.md) governs repository work, and
[documentation authority](docs/README.md) identifies the specific system and
hardware references.

## Robot Models

- **V1 / eight servos:** the existing Freenove ESP32-S3 robot, with direct
  MCPWM servo outputs. [Wiring and hardware records](docs/v1-8servo/PINOUT_DIAGNOSTICS.md).
- **V2 / twelve servos:** ESP32-P4-WIFI6 with PCA9685 servo output,
  [P4 firmware](Slave/firmware/esp32p4-wifi6/README.md) and a
  [V2 motion model](Slave/software/models/v2-12servo/README.md).
  [Hardware records](docs/v2-12servo/README.md) and dated qualification remain
  separate from source implementation.

Both models use the same gateway and Body Control interface.
Current development targets V2; V1 work is paused.
[Robot Models](docs/ROBOT_MODELS.md) records their distinct body contracts. Use the selected device and current firmware/model
owners for available capabilities; older bring-up descriptions do not establish
the present implementation or installed physical performance.

## Repository Layout

- `Master/` - Body Control gateway, environment adapter and manual interface;
  MetaHuman owns the companion brain and higher functions.
- `Slave/hardware/v1-8servo/` - V1 CAD and physical-body assets.
- `Slave/hardware/v2-12servo/` - V2 CAD, source assemblies, and printable parts.
- `Slave/software/` - portable slave-brain core, protocol, and tests.
- `Slave/firmware/esp32s3/` - current V1 firmware that runs on the robot.
- `Slave/firmware/esp32p4-wifi6/` - V2 P4 firmware, motion and peripheral control.
- `Emulator/` - host body emulator, Sesame visual simulator, and tests.
- `docs/` - specifications, progress records, repository map, and the ignored
  Sesame reference clone.

The V2 physical robot entrypoint is
`Slave/firmware/esp32p4-wifi6/main/app_main.c`; V1 retains
`Slave/firmware/esp32s3/main/app_main.c`. Freestyle generation and host execution
currently live in `experiments/freestyle/` and are loaded by Body Control.
See [the repository map](docs/REPOSITORY_MAP.md) for source ownership and
[startup](docs/STARTUP.md) for an existing physical installation.

Run the V1 simulator inspection stack with:

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
