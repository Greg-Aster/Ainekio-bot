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
- `Emulator/` - host body emulator, Sesame simulator, legacy adapter, and tests.
- `docs/` - specifications, progress records, repository map, and the ignored
  Sesame reference clone.

The physical robot entry point is
`Slave/firmware/esp32s3/main/app_main.c`. See `docs/REPOSITORY_MAP.md` for the
complete ownership map.

Run the complete local software stack with:

```sh
./Emulator/start-protocol-v1-stack.sh
```

The launcher prints the dashboard password and local inspection URLs. Run all
A1-A30 software acceptance gates with
`python3 Emulator/tools/run_acceptance.py`.
