# Upright

`upright` is a separate experimental V2 command. `stand` retains its four-foot meaning. Send `{"t":"intent","name":"emote","asset":"upright"}` with the normal transport fields; the gateway accepts it only when the body declares this capability.

The 22-second clip preserves the exact first three seconds of Sit, levels the chassis while all four feet support it, shifts the body rearward with those foot reference positions fixed, then withdraws the front pair and rises to a vertical chassis. It holds Upright until another command; automatic recovery is not included.

| Phase | Source interval |
| --- | --- |
| Accepted Sit prefix | 0–3 s |
| Level seated chassis from −27.5° to −10° | 3–5 s |
| Grounded rearward support transfer | 5–12 s |
| Withdraw forelimbs and rise to −90° | 12–20 s |
| Hold Upright | 20–22 s |

Leveling before the rearward transfer keeps the grounded front-foot targets within the screw-aware linkage range. The previous simultaneous transfer at the seated pitch required unreachable front-foot placements; lifting the front pair early instead left the assumed center of mass outside the rear support. This route keeps all four contacts until the modeled support transfer is complete.

The source has 2,641 knots at 120 Hz. Rear foot reference XY positions stay fixed within 0.000018 mm; rear soles may roll as the chassis rises. Minimum complete-body floor clearance is 0.5435 mm, and the provisional center of mass stays at least 1.5626 mm inside the supporting sole polygon after Sit. The final constrained forelimb reach is 89.1123 mm, with at least 2.2703 mm of closure-triangle height. The earlier 92.93 mm forelimb endpoint exceeded the current screw-aware joint range.

These are geometric results using an assumed center of mass at the model pivot `[0,0,65]` mm and sole vertices within 0.5 mm of ground. Real mass distribution, traction, compliance, dynamic balance and loaded servo tracking remain unqualified. The complete robot has not been collision-qualified by this support calculation.

Pulse demands use the current per-joint matchmark references in `servo_profile.json`; these remain provisional until physical shaft mapping is verified. `tools/generate_upright.py` generates the source with NumPy and SciPy. `tests/test_upright.py` independently recomputes contact geometry and support, checks the exact Sit prefix and vertical hold, and proves interpolation remains inside the authored coupled joint envelope.
