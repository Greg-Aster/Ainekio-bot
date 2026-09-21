# Cute — twelve-servo motion source

> Geometry snapshot note (2026-09-17): The 2026-09-17 final comparison found later front-panel, camera and display changes relative to the preserved integration baseline; those current edits are retained. No leg meshes appear in the changed/missing list, and earlier actuator/body curves match all 19 recorded baseline frames. All twelve new actuator/body tracks also match every exported source sample (see `current-curve-source-review.json`). Body-contact points and complete-body floor results below describe the earlier measured geometry snapshot and have not been requalified for the later front changes. Completed preview frames span the saved model revisions; visor work remains deferred.

## Gesture and eight-servo reference

V1 full-body lying pose, then five alternating rear R4/L4 distal waves. V2 lowers into the measured nose-up resting pose, splays mirrored shoulders 90 degrees, alternates only rear CAD FL/FR cranks while front pair stays posed, then stands.

V1 signature: Lower into the full-body lying pose; alternate only the rear R4/L4 distal joints five times; stand.

The exact reference is `reference-v1-cute.json`, with its joint labels in `reference-v1-joints.json` and unmodified face bitmaps under `faces/`. Electrical servo targets are retained as source evidence; V2 uses measured geometric joint coordinates. V1 frame-duration sum is 4.28 seconds; V2 smooth research timing is independently configurable.

## Sequence

1. Lower from standing into the measured nose-up body resting plane, keeping four sole contacts.
2. Splay mirrored shoulder joints to ±90 degrees and arrange the lying leg pose.
3. Alternate only the rear left/right distal crank motions five times; front legs remain posed.
4. Settle the limbs, reverse the solved entry motions, and return to exact standing.

Total duration **13.5 seconds** includes a 0.5-second final standing hold; 1621 samples at 120 Hz, preview 24 fps. Final timeline frames are assigned by batch integration. All twelve angles are recorded even when some remain constant during a phase.

## Ground contact and balance

The full current model requires a resting pitch of **-5.713782395 degrees about body Y** and body origin height **33.537235409 mm**. This places the rear cover edge and forward visor low point on the floor. `body-rest-plane.json` records the measured support points. `current-body-provenance.json` records the evaluated current body objects; no removed 2.4-inch LCD is restored.

The support polygon is the convex hull of these current contact points. The resting body supports the robot while all four feet are airborne. The animation explicitly records `body_contact_active`, `body_contact_polygon_world_mm`, foot contact flags, actual rotated sole geometry, and assumed COM. Four grounded soles support the lowering and recovery phases.

**Visor contact load capacity is unverified.** This nonpenetrating contact model is provisional and does not establish a physically qualified maneuver. Battery and optional Q6A mass/placement remain configurable, and COM is explicitly assumed at the body datum.

## Numerical checks

- Current complete rigid-body floor check: **passes**, minimum clearance 0.000000 mm.
- Minimum sole clearance: -4.63e-09 mm (floating-point zero).
- Minimum assumed support margin: 22.755 mm.
- Maximum material contact vertex error: 1.15e-13 mm.
- Maximum rolling normal correction: 0.000404 mm.
- Maximum adjacent actuator step: 1.561 degrees.
- Peak source joint speed: 187.33 degrees/s; peak finite-difference acceleration: 1276.23 degrees/s².
- Coupler-length residual at every sample and linear midpoint: 2.13e-14 mm.
- Exact geometric standing return: 0 degrees maximum error.

Actual mechanism collision checking, calibrated servo travel, mass distribution, torque/current, dynamics, and body contact strength remain unverified. The generator rejects linkage infeasibility, angle-bound violations, sole penetration, and body floor penetration rather than clamping angles.

## Source and reproduction

`source.json` contains timestamps, body pose, all four foot positions/contact states, twelve actuator angles, passive beta, and diagnostics. Leg order is CAD `FL, FR, RL, RR` = physical rear-left, rear-right, front-left, front-right. Each triplet is `h / Part_002` shoulder, `alpha / Part_006` upper carrier, `theta / Part_005` crank. Positions are millimeters, angles radians, time seconds; body X forward, Y left, Z up; quaternion WXYZ.

Edit `config.json`, then regenerate using Python with NumPy:

```bash
/home/greggles/blender-5.0.0-linux-x64/5.0/python/bin/python3.11 generate_cute.py
/home/greggles/blender-5.0.0-linux-x64/5.0/python/bin/python3.11 check_source.py
```

Every dependency and measured source file is included in this directory. `validation.json` and `source-check.json` contain the numerical reports; `reference-adaptation.json` records V1/V2 gesture mapping. `body-samples.npz` is the current complete rigid body used for floor checks; `belly-cover-samples.npz` retains the independently measured cover reference. Source choreography is coordinated; hardware pulse staggering is a separate execution-policy concern. No firmware or V1 assets are modified.

## Integrated Blender and handoff

Saved library: `Ainekio-Motion-Library.blend`, frames **3109–3433** at 24 fps. [Preview](preview.mp4). The library selector is `select_motion("cute", play=True)`.

`source.csv`, `schema.json`, `manifest.json` and `execution-contract.json` are the independent firmware research handoff. Positions are mm and actuator angles are geometric radians; electrical calibration is not supplied. Run `python3 export_command.py` after regeneration. `timing.py` shares one clock across all joints and excludes optional demonstration recovery by default; add `--include-demo-recovery` to inspect that path. Operating timing remains unset.

The reviewed source and saved poses are reported in `source-review.json`, `interpolation-validation.json`, and `blender-validation.json`. Visor and inter-part collision checks are deferred at the owner’s request.
