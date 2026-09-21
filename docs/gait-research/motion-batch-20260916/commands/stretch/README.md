# Stretch — twelve-servo source

> Geometry snapshot note (2026-09-17): The 2026-09-17 final comparison found later front-panel, camera and display changes relative to the preserved integration baseline; those current edits are retained. No leg meshes appear in the changed/missing list, and earlier actuator/body curves match all 19 recorded baseline frames. All twelve new actuator/body tracks also match every exported source sample (see `current-curve-source-review.json`). Body-contact points and complete-body floor results below describe the earlier measured geometry snapshot and have not been requalified for the later front changes. Completed preview frames span the saved model revisions; visor work remains deferred.

Rear brace, both front legs reach forward, held stretch, deeper pulse, then standing.

## Reference and adaptation

Read exact current `/home/greggles/Ainekio/Slave/software/assets/seed/motions-v1.json` asset `stretch`. Original JSON is preserved in `reference-v1-stretch.json`; `reference-v1-joints.json` preserves its electrical labels. Original face bitmaps and face metadata are included under `faces/` and `reference-v1-faces.json`. Source owner adjustments are already applied; older converter defaults do not override them.

V1 frames1 rear brace; frames2-3 front R1/L1 extend and R3/L3 reach90/90; frames4-5 front lower pair72/108 deepens stretch; frames6-7 soften and stand.

The electrical angles are not copied into the new linkage. Source angles are geometric radians ordered `[h/Part_002 shoulder, alpha/Part_006 carrier, theta/Part_005 crank]`; passive orientation follows measured four-bar closure on the original assembly branch. CAD order is FL rear-left, FR rear-right, RL front-left, RR front-right. World/body X is forward, Y left, Z up. Positions are millimetres and timestamps seconds.

## Motion

- Duration **6.7s**, 805 samples at **120Hz**, preview24fps.
- Start and finish are exactly the same standing pose; this matches V1 final standing semantics.
- Quintic transition profiles keep pose transitions smooth. The integration export defines interpolation and execution timing.
- Front soles deliberately slide17mm on entry plus2mm during the deeper pulse, then reverse exactly. Friction and traction are unverified.

## Numerical results

| Check | Result |
|---|---:|
| Minimum evaluated-source sole Z | -0.000000007mm |
| Minimum assumed-COM support margin | 29.477mm |
| Current complete-body sample floor clearance | 6.343942mm |
| Largest adjacent actuator step | 0.604983° |
| Peak source speed | 72.578°/s |
| Peak source acceleration | 257.789°/s² |
| Final joint return error | 0.000000° |

`validation.json` reports per-joint ranges, speeds and accelerations. `source-validation.json` independently recomputes every foot position, minimum sole height, passive branch, coupler length and timestamp interval. Blender evaluated-pose review belongs to the root integration report.

COM remains explicitly assumed at the configured body datum; battery and Q6A masses/positions remain configurable. Source kinematics do not establish physical balance, torque/current capacity, calibrated servo travel or full collision freedom. Scripts contain no PWM or hardware transport.

## Reproduce

Run from this command folder using Python with NumPy:

```bash
/home/greggles/blender-5.0.0-linux-x64/5.0/python/bin/python3.11 generator.py
/home/greggles/blender-5.0.0-linux-x64/5.0/python/bin/python3.11 check_source.py
```

`config.json` controls timing, amplitudes, body poses and assumptions. The local generator/solver/geometry/sole files require no sibling command folder. Root integration appends the scene animation, validates evaluated poses, generates previews and exports the firmware handoff contract.

## Integrated Blender and handoff

Saved library: `Ainekio-Motion-Library.blend`, frames **5900–6061** at 24 fps. [Preview](preview.mp4). The library selector is `select_motion("stretch", play=True)`.

`source.csv`, `schema.json`, `manifest.json` and `execution-contract.json` are the independent firmware research handoff. Positions are mm and actuator angles are geometric radians; electrical calibration is not supplied. Run `python3 export_command.py` after regeneration. `timing.py` shares one clock across all joints and excludes optional demonstration recovery by default; add `--include-demo-recovery` to inspect that path. Operating timing remains unset.

The reviewed source and saved poses are reported in `source-review.json`, `interpolation-validation.json`, and `blender-validation.json`. Visor and inter-part collision checks are deferred at the owner’s request.
