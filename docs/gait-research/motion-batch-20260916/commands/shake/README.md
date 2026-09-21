# Shake — twelve-servo motion source

> Geometry snapshot note (2026-09-17): The 2026-09-17 final comparison found later front-panel, camera and display changes relative to the preserved integration baseline; those current edits are retained. No leg meshes appear in the changed/missing list, and earlier actuator/body curves match all 19 recorded baseline frames. All twelve new actuator/body tracks also match every exported source sample (see `current-curve-source-review.json`). Body-contact points and complete-body floor results below describe the earlier measured geometry snapshot and have not been requalified for the later front changes. Completed preview frames span the saved model revisions; visor work remains deferred.

## What the motion does

V1 front distal pair R3/L3 folds while rear R4/L4 pulses synchronously five times. V2 lowers the front, preserves four measured sole contacts, then rocks the rear pair up/down five times with coordinated carrier/crank closure.

V1 signature: Fold the front R3/L3 distal pair and reposition rear carriers; pulse rear R4/L4 together five times; stand.

The exact eight-servo entry is retained in `reference-v1-shake.json`; original face bitmaps are in `faces/`. Electrical target degrees are reference material, not a calibration for the twelve-servo robot. V1 nominal frame durations sum to 4.24 seconds and sequential-servo timing is true; this V2 research motion uses its own coordinated smooth timing.

## Playback and source

- Duration: **7 seconds**; 841 timestamped samples at 120 Hz; Blender preview 24 fps.
- Entry and exit: exact geometric standing. Final standing hold is 0.5 seconds.
- Geometric joint ordering per leg: `h / Part_002` shoulder, `alpha / Part_006` upper carrier, `theta / Part_005` input crank; passive beta follows four-bar closure.
- Leg order: CAD `FL, FR, RL, RR` = physical rear-left, rear-right, front-left, front-right.
- Positions are millimeters; angles radians; timestamps seconds. Body axes X forward, Y left, Z up; quaternions WXYZ.
- `source.json` is the canonical geometric trajectory; `config.json` contains editable timing and pose targets. Batch integration assigns final timeline frames and exports execution data.

## Contact and measured results

Four grounded measured convex soles. Ground-fixed material vertices between discrete rolling transfers; solved outbound paths are reversed exactly. Foot yaw scrub and friction unverified.

Grounded outbound primitives use quintic body interpolation and measured sole inverse kinematics. Returning through exact recorded reverses prevents accumulated contact drift. Finite-step supporting-feature transfers retain tangential contact position and log their small vertical correction. Airborne waves, where used, interpolate geometric actuator angles smoothly and solve passive four-bar closure at every sample.

- Minimum support margin: **37.823 mm**, using explicitly assumed body COM and the stated intended contact model.
- Minimum measured sole height in source geometry: **-1.37e-08 mm**.
- Minimum current sampled rigid body clearance: **4.278 mm**.
- Maximum fixed-material-vertex constraint error: 1.28e-13 mm.
- Maximum rolling normal correction: 0.000903 mm.
- Maximum adjacent joint step: 0.707 degrees.
- Peak source joint speed: 84.80 degrees/s; peak finite-difference acceleration: 685.52 degrees/s².
- Exact standing angle return error: 0 degrees.
- Four-bar coupler error across every sample and every linear midpoint: 2.13e-14 mm. Passive angles are continuous.

## Reproduce

Use Python with NumPy, or Blender's bundled Python:

```bash
/home/greggles/blender-5.0.0-linux-x64/5.0/python/bin/python3.11 generate_shake.py
/home/greggles/blender-5.0.0-linux-x64/5.0/python/bin/python3.11 check_source.py
```

Run from this directory, or pass the script's full path. All imported modules and measured geometry are included locally. `reference-adaptation.json` records the V1/V2 comparison; `validation.json` and `source-check.json` report reproducible numerical evidence.

## Limits and hardware handoff

COM is explicitly assumed. Battery and optional Q6A masses/placement remain configurable. Combined-pose physical collisions, calibrated servo stops, torque/current capability, sole friction, and dynamics remain unverified. Numerical closure and balance proxies are not physical qualification. Existing geometry is preserved. Source timing is geometric choreography; electrical pulse staggering belongs in the execution policy and must not replace coordinated trajectory sampling. No firmware or eight-servo assets are changed.

## Integrated Blender and handoff

Saved library: `Ainekio-Motion-Library.blend`, frames **4038–4206** at 24 fps. [Preview](preview.mp4). The library selector is `select_motion("shake", play=True)`.

`source.csv`, `schema.json`, `manifest.json` and `execution-contract.json` are the independent firmware research handoff. Positions are mm and actuator angles are geometric radians; electrical calibration is not supplied. Run `python3 export_command.py` after regeneration. `timing.py` shares one clock across all joints and excludes optional demonstration recovery by default; add `--include-demo-recovery` to inspect that path. Operating timing remains unset.

The reviewed source and saved poses are reported in `source-review.json`, `interpolation-validation.json`, and `blender-validation.json`. Visor and inter-part collision checks are deferred at the owner’s request.
