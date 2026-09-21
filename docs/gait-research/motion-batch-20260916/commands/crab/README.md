# Crab — twelve-servo motion source

> Geometry snapshot note (2026-09-17): The 2026-09-17 final comparison found later front-panel, camera and display changes relative to the preserved integration baseline; those current edits are retained. No leg meshes appear in the changed/missing list, and earlier actuator/body curves match all 19 recorded baseline frames. All twelve new actuator/body tracks also match every exported source sample (see `current-curve-source-review.json`). Body-contact points and complete-body floor results below describe the earlier measured geometry snapshot and have not been requalified for the later front changes. Completed preview frames span the saved model revisions; visor work remains deferred.

## Eight-servo reference

Upper joints reach 90 degrees, then five alternating left/right lower-pair strokes. V2 preserves the side-pair pattern with individually staggered ground steps.

The exact source entry is `reference-v1-crab.json`. `reference-v1-joints.json` preserves electrical joint IDs; `reference-adaptation.json` resolves sparse target frames. Faces are original seed bitmaps. V1 electrical angles and sequential frame timing are reference evidence, not a twelve-servo calibration.

## Twelve-servo adaptation

V1 rotates the upper joints to 90 degrees and alternates left/right lower pairs for five cycles. V2 widens a lowered stance, then alternates left and right side shuffles for five cycles. Each side pair is staggered into individual steps so three soles remain supporting; the body sways laterally with the steps.

Total source duration is **30.60s**, with 3673 samples at120Hz.

## Crab contact and timing choices

Five alternating left/right side-pair strokes are split into individual swings, retaining three supporting soles. Feet first widen10mm outward; working strokes add7mm outward and return. Each swing lasts0.6s and each body shift0.375s, slowed1.5× from the initial candidate. Actual sole lift target is5mm. The robot sways across its supports, then returns to the original body position; this is a Crab gesture rather than a calibrated travel-distance command.

The minimum support margin is **1.010mm**, although lift preparation requests5mm. The smaller measured margin occurs elsewhere in the complete trajectory and remains provisional. The final0.8s settle intentionally slides grounded contacts, with maximum bolt XY correction **1.577mm**, to restore exact standing before the next command. Friction is unverified and that phase is explicitly tagged `intentional_contact_settle`.

## Coordinates and mechanics

CAD ordering is FL rear-left, FR rear-right, RL front-left, RR front-right. Every triplet is h/Part002 shoulder, alpha/Part006 carrier, theta/Part005 input crank. Angles are geometric **radians**, positions **millimeters**, and times **seconds**; body axes Xforward, Yleft, Zup. Four-bar passive beta comes from fixed-branch closure. These are not electrical servo targets.

Measured rolling stance soles and 5 mm airborne shuffles. Final 0.8 second settle intentionally slides four grounded contacts to restore exact standing; sliding friction unverified.

## Numerical review

- Minimum assumed COM support margin: 1.010224mm.
- Minimum sole height: -0.000000018mm.
- Minimum body sample clearance: 20.573752mm.
- Maximum coupler closure error: 1.42e-14mm.
- Maximum adjacent actuator change: 0.826934degrees.
- Peak actuator speed: 99.177degrees/s.
- Peak sampled acceleration: 880.326degrees/s².
- Final standing angle error: 0.000000000degrees.

COM is explicitly assumed at the body datum. Battery/Q6A mass and position remain configurable. Joint envelopes are research ranges, not calibrated stops. Inter-part collisions, electrical timing, servo load, friction, and physical stability remain unverified. Runtime timing and PWM staggering belong to the shared execution contract.

## Reproduce

Run inside this command folder with Blender's Python (NumPy required):

```sh
/home/greggles/blender-5.0.0-linux-x64/5.0/python/bin/python3.11 generate_crab.py
```

This writes `source.json`, `config.json`, and `validation.json`. Dependencies are copied locally: `motion_common.py`, `plan_crawl.py`, `gait_kinematics.py`, measured geometry/sole/body files, and base COM configuration. Dead additionally uses `current-body-samples.npz` and `body-rest-plane.json` from the current saved scene. `gait_start_frame` is assigned by the parent playlist exporter. The root agent owns Blender append, preview, execution export, and saved-scene review.

## Integrated Blender and handoff

Saved library: `Ainekio-Motion-Library.blend`, frames **4818–5552** at 24 fps. [Preview](preview.mp4). The library selector is `select_motion("crab", play=True)`.

`source.csv`, `schema.json`, `manifest.json` and `execution-contract.json` are the independent firmware research handoff. Positions are mm and actuator angles are geometric radians; electrical calibration is not supplied. Run `python3 export_command.py` after regeneration. `timing.py` shares one clock across all joints and excludes optional demonstration recovery by default; add `--include-demo-recovery` to inspect that path. Operating timing remains unset.

The reviewed source and saved poses are reported in `source-review.json`, `interpolation-validation.json`, and `blender-validation.json`. Visor and inter-part collision checks are deferred at the owner’s request.
