# Ainekio the Robot Familiar

  Ainekio the Robot Familiar is a hardware and software project for building a small robot companion powered by MetaHuman OS. The robot uses a physical body,
  onboard sensors, and a network connection to let MetaHuman OS see, listen, speak, move, and interact through a physical chassis.

- Progress blog and current status: [ainek.io](https://ainek.io)
- MetaHuman OS development repo: [Greg-Aster/metahuman-os](https://github.com/Greg-Aster/metahuman-os)
- Current test body: based on the Sesame robot: [dorianborian/sesame-robot](https://github.com/dorianborian/sesame-robot)

## Repository Layout

- `Master/` - remote brain and gateway code.
- `Slave/hardware/` - CAD and physical-body assets.
- `Slave/software/` - portable slave-brain core, protocol, and tests.
- `Slave/firmware/` - ESP32-S3 firmware that runs on the robot.
- `Emulator/` - host body emulator, Sesame visual simulator, and tests.
- `docs/` - specifications, progress records, repository map, and the ignored
  Sesame reference clone.

The physical robot entry point is
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
