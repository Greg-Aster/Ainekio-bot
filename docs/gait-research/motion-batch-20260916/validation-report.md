# Motion-library validation

All twelve command sources passed the independent source review and gesture cross-review. The saved Blender mechanism was evaluated at **336 poses**, including subframes.

| Command | Demo seconds | Min assumed margin mm | Peak speed deg/s | Peak acceleration deg/s² |
| --- | ---: | ---: | ---: | ---: |
| cute | 13.5 | 22.755 | 187.500 | 1532.064 |
| freaky | 9.7 | 17.557 | 161.440 | 689.126 |
| worm | 12.5 | 39.116 | 26.395 | 210.518 |
| shake | 7 | 37.823 | 84.888 | 850.923 |
| shrug | 10.2 | 22.755 | 168.750 | 572.627 |
| dead | 12.3 | 22.755 | 122.267 | 409.255 |
| crab | 30.6 | 1.010 | 99.359 | 1317.915 |
| celebrate | 12.5 | 22.755 | 168.750 | 1221.015 |
| stretch | 6.7 | 29.477 | 72.610 | 286.957 |
| surprised | 11.95 | 22.755 | 168.750 | 1100.312 |
| sad | 8.8 | 35.498 | 59.891 | 219.872 |
| curious | 9.75 | 39.116 | 31.860 | 169.957 |

Maximum evaluated joint-connection error: **0.00004179 mm**. Maximum foot-prediction error: **0.00003580 mm**. Lowest sampled sole Z: **-0.00029402 mm**, a small interpolation/numerical residue.

Every actuator source is continuous, bounded within its declared research envelope, and follows the measured four-bar branch. Every interpolation segment was checked at quarter points; peak speed and acceleration were calculated from the interpolant. Endpoint speeds are zero. These are demonstration demands, not loaded-servo capability measurements.

The 2026-09-17 final comparison found later front-panel, camera and display changes relative to the preserved integration baseline; those current edits are retained. No leg meshes appear in the changed/missing list, and earlier actuator/body curves match all 19 recorded baseline frames. All twelve new actuator/body tracks also match every exported source sample (see `current-curve-source-review.json`). Body-contact points and complete-body floor results below describe the earlier measured geometry snapshot and have not been requalified for the later front changes. Completed preview frames span the saved model revisions; visor work remains deferred.

Dead reaches its held semantic completion at **7.4 seconds**. Its full **12.3-second** demonstration includes optional standing recovery. The timing helper stops at semantic completion by default, and its explicit recovery flag enables the complete playlist path.

Crab retains a **1.01 mm** minimum assumed margin and a documented **1.577 mm** final contact slide. Treat its support/friction assumptions as provisional. Other deliberate contact slides and body supports are documented per command.

COM remains assumed. Actual servo travel calibration, loaded torque/current, brownouts, dynamics, contact load capacity and inter-part collisions remain unverified. Visor collision work is deferred at the owner’s request. A kinematic support margin does not establish physical stability.

Before hardware execution: calibrate signed geometric joints to electrical centers/directions/endpoints; measure mass and payload positions; establish loaded speed/current limits and coordinated timing; verify real contact friction and body-contact strength. Firmware and Body Control code were not modified.
