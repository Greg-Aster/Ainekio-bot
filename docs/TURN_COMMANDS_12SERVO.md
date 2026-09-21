# Twelve-servo turn command sources

The eight commands are ready as independent Blender research sources: left/right 15°, 45°, 90° and 180°. The 15° semantic names are new.

- [Command index](gait-research/turn-commands-20260915/README.md)
- [Firmware and Body Control handoff](gait-research/turn-commands-20260915/FIRMWARE_HANDOFF.md)
- [Validation and assumptions](gait-research/turn-commands-20260915/VALIDATION.md)
- [Saved Blender files](gait-research/turn-commands-20260915/BLENDER_FILES.md)
- [Portable source archive](gait-research/turn-commands-20260915/ainekio-twelve-servo-turns-20260915.zip)

Every command has its own JSON/CSV body/foot/contact/twelve-joint source, config, schema, manifest and evaluated Blender report. The archive contains those sources and their generator; the full Blender files remain in `/home/greggles/blender-5.0.0-linux-x64/robot-turn-commands-20260915`.

These are geometric coordinates for integration, with unqualified physical balance and actuator capability. The original handoff supplies no electrical calibration or firmware registration. The handoff identifies the existing owners and the two new command names; subsequent integration is recorded below.

## Firmware integration

All eight complete sources are now imported into the [V2 motion model](../Slave/software/models/v2-12servo/motions/turns/README.md),
with semantic request mapping, compiled twelve-joint sampling and P4 console
diagnostics. Body Control includes the two new 15° buttons; command availability
comes from the selected body's declaration and readiness. Physical execution
remains disabled. The original handoff package above remains unchanged.

Firmware `0.3.0-p4-turns` has been built and application-flashed to the actual P4.
All eight clips passed read-only twelve-joint console checks; the P4 is connected
to Body Control and remains disarmed. See the [test, build and flash evidence](../Slave/software/models/v2-12servo/motions/turns/README.md#verification-and-application-flash-2026-09-15).

## Timing and engagement supplement — 2026-09-16

[Execution guide and all eight independent turn timing contracts](gait-research/execution-20260916/README.md#command-contracts)
add editable phase durations, joint coordination, contact-aware interruption and
firmware pulse/engagement scheduling requirements. The original sources remain
unchanged; operating timing requires loaded calibration.
