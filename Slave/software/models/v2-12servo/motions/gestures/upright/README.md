# Upright

`upright` is an experimental V2 named motion, distinct from four-foot Stand. Send `{"t":"intent","name":"emote","asset":"upright"}` through the normal body-control transport.

The 22-second clip preserves the exact first three seconds of Sit, steps the front feet backward one at a time, transfers support rearward, then rises to a vertical chassis. It holds the endpoint until another command.

| Phase | Source interval |
| --- | --- |
| Accepted Sit prefix | 0–3 s |
| First front foot steps backward; brace pitch adjusts | 3–5 s |
| Second front foot steps backward | 6–8 s |
| Grounded rearward support transfer | 8–12 s |
| Withdraw forelimbs and rise to −90° | 12–20 s |
| Hold Upright | 20–22 s |

The mounted-calibration correction moves the front brace targets 15 mm forward of the previous targets. The chassis briefly levels to about −14.15° during the first step, then returns to about −22.75° before the final rise. Rear boot orientation and rear foot reference positions remain anchored; body translation and the final forelimb pose change to fit the requested 400–2900 µs span. Phase times and the full vertical rise are retained.

The 2,641 source knots at 120 Hz require approximately 405–2895 µs with the mapping recorded in `source.json` metadata. After Sit, the maximum planted target error is 0.000047 mm, minimum body floor clearance is 0.5435 mm, and the provisional center of mass stays at least 1.5626 mm inside the supporting sole polygon. Final forelimb reach is 90.3394 mm; minimum closure-triangle height is 2.0001 mm.

These are geometry calculations using an assumed center of mass at the model pivot `[0,0,65]` mm and sole vertices within 0.5 mm of ground. Real mass distribution, traction, compliance, dynamic balance, loaded servo tracking and robot collision clearance remain unqualified.

The corrected `source.json` is the canonical trajectory. `tools/generate_upright.py` and historical Blender reports describe earlier paths and do not regenerate or validate this calibration fit. `tests/test_upright.py` independently recomputes contact geometry, body clearance and support, and checks the exact Sit prefix and vertical hold. The firmware-native `clip_calibration` test checks compiled pulse extrema and entry interpolation using the mounted calibration. The source metadata records that calibration and the prior source hash.
