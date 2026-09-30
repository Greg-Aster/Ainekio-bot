# Upright (experimental)

`upright` is a separate V2 command. `stand` keeps its four-foot meaning.
Send `{"t":"intent","name":"emote","asset":"upright"}` with the normal transport fields; the gateway accepts the name only when the body declares it.

The 22-second clip replays the exact first three seconds of Sit, moves each front foot backward, shifts the body rearward with all four feet supporting it, then rises to a vertical chassis. The rear lower legs retain their flat Sit contact throughout. It holds Upright until another command; automatic recovery is not included.

| Phase | Time |
| --- | --- |
| Accepted Sit | 0–3 s |
| Left front foot backward | 3–5 s |
| Rearward support shift | 5–6 s |
| Right front foot backward | 6–8 s |
| Supported push | 8–12 s |
| Rise and finish rearward arm extension | 12–20 s |
| Upright hold | 20–22 s, then held by the controller |

The supported push reaches about 88.48 mm of front-arm extension. The final backward reach is 92.93 mm, compared with 95.02 mm theoretical straight reach. A direct interpolation to the backward near-straight pose crosses an unreachable four-bar region; the recorded route goes around it and retains at least 2.38 mm of closure-triangle height. This is not a measured force or torque margin. Front feet lift before the final arm extension, once the assumed center of mass is above the rear support area.

The full source has 2,641 knots at 120 Hz. Rear sole poses remain anchored within 0.000043 mm in the reference solution, minimum complete-body floor clearance is 0.54 mm, and the assumed center of mass remains at least 0.737 mm inside the support polygon after Sit. This assumes the center of mass is the model pivot `[0,0,65]` mm and counts sole vertices within 0.5 mm of the floor. Real mass distribution, contact compliance, traction, balancing and loaded servo tracking are unknown.

The 2026-09-29 remap translates the front braces into the current footprint and changes the intermediate support pitch from −27.5° to −22.954° to retain front-foot reach on the longer chassis. The support shift moves 1.5 mm farther rearward to keep the assumed COM inside the support polygon. During 14–16 seconds the carrier clears the unreachable linkage region before the crank follows; the original waypoint, final 92.93 mm arm reach, full −90° body pitch and all phase times remain intact. The rear boot poses stay anchored. `temp_mesh.ply` is an owner-identified temporary reference and is excluded from robot clearance and playback geometry.

Current pulse demands use 1650 µs at the existing matchmarks. The mounting audit reports the resulting ranges and historical mechanical-envelope conflicts without clipping the movement. Complete-body collision and loaded balance remain unqualified for the changed assembly; older mesh-separation numbers do not qualify this remap.

`../../../tools/generate_upright.py` generates this source with NumPy and SciPy. Run `python tools/generate_upright.py` from the model directory, then build the native tests and P4 firmware. The compiler binds Sit, geometry and contact-hull hashes so stale dependencies fail instead of being silently accepted. Append the source to Blender with `append_blender_locomotion.append(['upright'])` only after verifying the current rolling recovery.
