# Upright

`upright` is an experimental V2 emote, separate from ordinary four-foot Stand.
Send `{"t":"intent","name":"emote","asset":"upright"}` through the existing body-control owner.

The owner-approved calibration revision retains the 22-second source timeline:
Sit, front feet stepped backward one at a time, a grounded rearward transfer,
and a **60° rear-leg rise**. It holds that pose until another command. The prior
90° path exceeded the mounted pulse window; replacement full-vertical candidates
also failed continuity, modeled support or body-clearance checks. The 60° pose
is the current authored endpoint, not proof that every possible vertical path
is infeasible.

| Phase | Source interval |
| --- | --- |
| Exact revised Sit prefix | 0–3 s |
| First front foot steps backward | 3–5 s |
| Four-foot transfer | 5–6 s |
| Second front foot steps backward | 6–8 s |
| Grounded rearward support transfer | 8–12 s |
| Withdraw forelimbs and rise to −60° | 12–20 s |
| Hold | 20–22 s |

The offline authoring preserves planted foot-reference XY and broad rear-sole
orientation. It redistributes motion within each existing phase to remove the
abrupt changes found in the initial fitted candidates. Runtime joint-speed
retiming still determines actual execution duration.

The 2,641 source samples and compiled extrema fit **400–2900 µs** with the saved
mirrored calibration. After Sit, independent geometry checks find at least
**2.8699 mm modeled support margin**, **1.2450 mm body clearance**, and less than
**0.000115 mm rear anchor drift**. The largest source joint step is 1.1109°;
terminal forelimb reach is 71.0600 mm. Native monotone-cubic midpoint checks
find a maximum target discrepancy of 0.1224 mm, within the existing 0.5 mm
validation tolerance.

Support uses an assumed center of mass at the model pivot `[0,0,65]` mm and
sole vertices within 0.5 mm of ground. Actual mass distribution, traction,
compliance, dynamic balance, loaded tracking and collision clearance remain
unqualified. The pulse checks establish commanded travel only.

`source.json` is canonical. `tools/author_supported_upright.py` reconstructs the
contact fit, phase redistribution and supported rise using a retained baseline,
a candidate model containing the recorded `calibrated_transfer_seeds`, and a
local saved-calibration readback. `tools/author_calibrated_clips.py --refresh-only`
refreshes FK evidence and source bindings. The older `generate_upright.py` and
historical Blender reports describe previous trajectories.

`tests/test_upright.py` independently checks the Sit prefix, contacts, body
clearance, support and revised held pose. Firmware-native `clip_calibration`
checks compiled extrema and every Home/gesture-terminal entry interpolation.
Loaded motion remains a separate robot test.
