# Robot Hardware Assets

| Robot model | Printable Original Assets | Hardware documentation |
| --- | --- | --- |
| V1 / eight servos | [v1-8servo/](v1-8servo/) — `3d-print/STL/` (`frame/`, `left-legs/`, `right-legs/`, `enclosures-mounts/`) and `Parts/OBJ/` | [V1 wiring](../../docs/v1-8servo/PINOUT_DIAGNOSTICS.md) |
| V2 / twelve servos | [v2-12servo/](v2-12servo/) — checkpoint log ([CHECKPOINTS.md](v2-12servo/CHECKPOINTS.md)) and printable original exports under `STL/` (`Red/` subsystem folders `chassis-panels/`, `electronics-bridge/`, `head-carapace/`, `lcd-camera-audio/`, `legs-linkages/`, `power-battery/`, `q6a-slots/`, `servo-housings/`, plus `newlink/`, `q6a/`, `revision/`, `Training Stand/`) | [V2 hardware record](../../docs/v2-12servo/README.md) |

## Provenance and Third-Party Separation

- **100% original printable robot meshes**: Every printable robot frame, shell, linkage, carrier, bracket, foot, and enclosure mesh across V1, V2, and V3 was independently modeled from scratch by Gregory Aster on this workstation (`0` vertices retained from any external robot CAD). Legacy part-slot prefixes in V2 filenames (`Part_003`, `Part_009`, `Part_022`, `Part_023`, `Part_027`) are historical linkage slot identifiers retained for continuity across kinematics/Blender scripts, not imported meshes.
- **Non-printable off-the-shelf component references**: Fitment reference models for off-the-shelf servos and breakout boards live outside `Slave/hardware/` under [`third_party/cad-references/`](../../third_party/cad-references/) under their respective permissive upstream licenses (`MIT` / clean-room datasheet reconstructions) and are excluded from printable robot hardware claims.
- Local `.blend` scene snapshots are gitignored; printable STL/OBJ exports are tracked in Git. A WIP or review filename is not a declaration of print readiness or physical validation.

All original 3D printable robot meshes and hardware documentation in this directory are copyright Gregory Aster and publicly licensed for **non-commercial use only** under [CC BY-NC-SA 4.0](../../LICENSE-HARDWARE) (commercial distribution reserved to Gregory Aster; see [NOTICE](../../NOTICE) and [COMMERCIAL_MANIFEST.json](../../COMMERCIAL_MANIFEST.json)).
