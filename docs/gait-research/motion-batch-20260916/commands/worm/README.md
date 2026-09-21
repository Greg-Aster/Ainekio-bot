# Worm — twelve-servo motion source

> Geometry snapshot note (2026-09-17): The 2026-09-17 final comparison found later front-panel, camera and display changes relative to the preserved integration baseline; those current edits are retained. No leg meshes appear in the changed/missing list, and earlier actuator/body curves match all 19 recorded baseline frames. All twelve new actuator/body tracks also match every exported source sample (see `current-curve-source-review.json`). Body-contact points and complete-body floor results below describe the earlier measured geometry snapshot and have not been requalified for the later front changes. Completed preview frames span the saved model revisions; visor work remains deferred.

## Eight-servo reference

Low flat setup followed by five paired front/rear lower-joint undulation cycles. V1 lower target pairs alternate 45/135 and 135/45 degrees with mirrored mounting signs.

The exact source entry is `reference-v1-worm.json`. `reference-v1-joints.json` preserves electrical joint IDs; `reference-adaptation.json` resolves the sparse target frames. Faces are the original seed bitmaps.

## Twelve-servo adaptation

V1 lowers into a flat posture, then alternates mirrored front/rear lower-joint targets for five cycles. V2 performs five continuous low-body undulations: front dips as rear rises, then rear dips as front rises, with four grounded measured soles.

The animation lasts **12.50 seconds**, with 1501 samples at120Hz. Five front/rear undulations, then return to standing; rolling may accumulate a small sole contact displacement.

CAD ordering is FL rear-left, FR rear-right, RL front-left, RR front-right. Every triplet is h/Part002 shoulder, alpha/Part006 carrier, theta/Part005 input crank. Angles are geometric **radians**, positions **millimeters**, and times **seconds**; body axes are Xforward, Yleft, Zup. Four-bar passive beta comes from fixed-branch closure. These are not electrical servo angles.

## Contact and numerical review

Measured convex sole rolling: fixed material vertex between feature transfers. Belly support is explicit when selected; no friction or dynamics simulation.

- Minimum assumed COM support margin: 39.115587mm.
- Minimum evaluated sole height: -0.000000005mm.
- Minimum body sample clearance: 7.171442mm.
- Maximum coupler closure error: 1.42e-14mm.
- Maximum adjacent actuator change: 0.219935degrees.
- Peak actuator speed: 26.391degrees/s.
- Peak sampled acceleration: 73.693degrees/s².
- Final standing angle error: 0.000001568degrees.

COM is an explicitly assumed body datum. Battery/Q6A mass and position remain configurable in `config.json`. Joint envelopes are research ranges, not calibrated stops. Collisions, electrical timing, servo load, friction, and physical stability are unverified. Source speed is for choreography; runtime timing and PWM staggering belong to the shared execution contract.

## Reproduce

Run from this command folder with Blender's Python (NumPy required):

```sh
/home/greggles/blender-5.0.0-linux-x64/5.0/python/bin/python3.11 generate_worm.py
```

This writes `source.json`, `config.json`, and `validation.json`. The generator is self-contained with `motion_common.py`, `plan_crawl.py`, `gait_kinematics.py`, the measured geometry/sole/body files, and base COM configuration. `gait_start_frame` is assigned by the parent playlist exporter. Blender append, preview, final export contract, and saved-scene review are handled by the batch generator.

## Integrated Blender and handoff

Saved library: `Ainekio-Motion-Library.blend`, frames **3714–4014** at 24 fps. [Preview](preview.mp4). The library selector is `select_motion("worm", play=True)`.

`source.csv`, `schema.json`, `manifest.json` and `execution-contract.json` are the independent firmware research handoff. Positions are mm and actuator angles are geometric radians; electrical calibration is not supplied. Run `python3 export_command.py` after regeneration. `timing.py` shares one clock across all joints and excludes optional demonstration recovery by default; add `--include-demo-recovery` to inspect that path. Operating timing remains unset.

The reviewed source and saved poses are reported in `source-review.json`, `interpolation-validation.json`, and `blender-validation.json`. Visor and inter-part collision checks are deferred at the owner’s request.
