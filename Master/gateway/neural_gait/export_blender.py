"""Read-only Wireless assembly export, executed inside Blender.

Call export(directory). Evaluated mesh copies are triangulated for transport;
the active scene, source polygons, pose, visibility and file are never changed.
"""
import json
import math
from pathlib import Path


def export(directory):
    import bpy
    import numpy as np

    scene = bpy.context.scene
    if scene.name != "Wireless":
        raise ValueError("Export the installed Wireless assembly")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    dg = bpy.context.evaluated_depsgraph_get()
    legs = dict(FL="rear_left", FR="rear_right", RL="front_left", RR="front_right")
    roles = {"h alpha theta": "shoulder_body", "mechanism frame": "mechanism",
             "mount frame": "shoulder_body", "primary": "carrier_body",
             "input": "crank_body", "foot": "pickup_body", "rod": "rod_body"}
    frames, angles = {}, []
    for cad, leg in legs.items():
        control = scene.objects[f"REFINED | {cad} | h alpha theta"]
        angles.extend(float(control[k]) for k in ("h_deg", "alpha_deg", "theta_deg"))
        for role in roles:
            obj = scene.objects[f"REFINED | {cad} | {role}"]
            frames[obj.name] = np.asarray(obj.evaluated_get(dg).matrix_world).tolist()
    collections = ["ROBOT - Body and electronics", "ROBOT - Legs", "ROBOT - Shell",
                   "CARAPACE | Fitted extracted plates"]
    candidates = {o.name: o for c in collections for o in bpy.data.collections[c].all_objects}
    candidates.update({o.name: o for c in bpy.data.collections if c.name.startswith("BOOT |") for o in c.all_objects})
    candidates.update({o.name: o for o in scene.objects if "CD74HC4067" in o.name})
    # These are detached studies/replaced parts in the live file, verified by
    # their assembly identity and evaluated placement, not discarded merely
    # because they are hidden in the user's current inspection view.
    detached = {
        "CARAPACE | Front helmet - extracted 014.001": "detached old shell at X -1218 mm; current three-piece helmet retained",
        "REFERENCE | FR outer boot - before clean rebuild": "detached replaced boot at X -270 mm; installed rebuilt boot retained",
        "STRUCTURAL | Battery bracket - Front paired": "detached old bracket at X -696 / Y -332 mm; current cradle retained",
        "STRUCTURAL | Battery bracket - Rear paired": "detached old bracket at X -613 / Y -332 mm; current cradle retained",
        "Face.Rail.L.001": "detached face rail at Y -169 mm",
        "Face.Rail.R.001": "detached face rail at Y -143 mm",
        "STRUCTURAL | Rear panel brace - Right": "detached brace at Y -209 mm",
        "_bezel_closefit": "temporary bezel study; installed MASK recessed bezel retained",
        "CARAPACE | Rear helmet - extracted 014.002": "detached source at X 1849..1911 mm; current three shells explicitly derived from it retained",
        "Crown.Center.001": "detached previous crown below body Z -2.61..-0.12 mm; current joined visor/crown retained",
        "Anker Slim": "detached old battery X -734..-579 / Y -368..-296 mm; current battery retained",
        "front mask shell": "explicit Replacement property: replaced by MASK fitted panel assembly",
        "front mask - Chin": "explicit Replacement property: replaced by MASK fitted panel assembly",
        "TESTS | B0066 - adjacent circuit reference": "explicit Reference status: hidden oversized adjacent circuit estimate, not installed ribbon passage",
    }
    for side in ("Left", "Right"):
        for end in ("front", "rear"):
            detached[f"STRUCTURAL | Battery clip - {side} {end} - underside mount"] = "detached with old brackets at X -703..-606 / Y -370..-295 mm; current battery cradle retained"
    arrays, objects, excluded = {}, [], []
    horns = {"TESTS | Part_001_9g": "FL", "TESTS | FR - Part_001_9g": "FR",
             "TESTS | RL - Part_001_9g": "RL", "TESTS | RR - Part_001_9g": "RR"}
    for name, obj in sorted(candidates.items()):
        if obj.type != "MESH" or obj.hide_render or "Radxa" in name or "PCA9685 - 1x6" in name or name in detached:
            reason = detached.get(name)
            if reason is None:
                if obj.type != "MESH":
                    reason = "non-mesh assembly/group/rig object"
                elif "Radxa" in name:
                    reason = "offboard Q6A hardware"
                elif name.startswith("FIT REF"):
                    reason = "fit-envelope reference, not an installed solid component"
                elif "Part_020" in name or "Part_022" in name:
                    reason = "render-hidden previous boot design; current rebuilt boot components retained"
                else:
                    reason = "render-hidden source reference; retained in CAD, not active render assembly"
            excluded.append(dict(name=name, reason=reason))
            continue
        owner = "torso"
        parent = obj
        while parent:
            parts = parent.name.split(" | ")
            if len(parts) == 3 and parts[0] == "REFINED" and parts[2] in roles:
                owner = legs[parts[1]] + "_" + roles[parts[2]]
                break
            parent = parent.parent
        # The current boot design is assembled on the rear-right foot but is
        # unparented in CAD. Keep that installed placement, not a torso weld.
        if any(c.name.startswith("BOOT |") for c in obj.users_collection):
            owner = "rear_right_pickup_body"
        evaluated = obj.evaluated_get(dg)
        mesh = evaluated.to_mesh()
        try:
            mesh.calc_loop_triangles()
            vertices = np.array([evaluated.matrix_world @ v.co for v in mesh.vertices], dtype=np.float64)
            faces = np.array([t.vertices for t in mesh.loop_triangles], dtype=np.int32)
            if not len(faces):
                continue
            if evaluated.matrix_world.determinant() < 0:
                faces = faces[:, ::-1]
            attachment_basis = "evaluated CAD parent hierarchy"
            if name in horns:
                # These purchased horns are explicitly bolted inside Part_003,
                # but remain statically parented in CAD at neutral. Express
                # that neutral fit in the moving shoulder frame; do not weld
                # the horn to the torso or preserve a stale posed mismatch.
                cad = horns[name]
                control = scene.objects[f"REFINED | {cad} | h alpha theta"]
                current = np.asarray(control.evaluated_get(dg).matrix_world)
                angle = math.radians(float(control["h_deg"]))
                undo = np.eye(4)
                c, s = math.cos(-angle), math.sin(-angle)
                undo[1:3, 1:3] = [[c, -s], [s, c]]
                neutral = current @ undo
                transform = current @ np.linalg.inv(neutral)
                vertices = vertices @ transform[:3, :3].T + transform[:3, 3]
                owner = legs[cad] + "_shoulder_body"
                attachment_basis = "MG90T horn Assembly role: bolted inside moving Part_003; static CAD reference fitted at neutral shoulder"
            key = f"mesh_{len(objects):03d}"
            arrays[key + "_vertices"] = vertices
            arrays[key + "_faces"] = faces
            color = list(obj.active_material.diffuse_color) if obj.active_material else [.4, .4, .4, 1]
            material = obj.active_material
            if material and material.use_nodes:
                node = next((n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None)
                if node:
                    color = list(node.inputs['Base Color'].default_value)
            objects.append(dict(key=key, name=name, body=owner, rgba=color,
                                attachment_basis=attachment_basis,
                                vertices=len(vertices), triangles=len(faces)))
        finally:
            evaluated.to_mesh_clear()
    np.savez_compressed(directory / "assembly.npz", **arrays)
    sensor_objects = {}
    for name in ("Purple_PCB_13x18_two_holes_ESTIMATED", "TESTS | Face - Arducam B0066 - camera mock-up"):
        obj = scene.objects[name].evaluated_get(dg)
        mesh = obj.to_mesh()
        try:
            v = np.array([obj.matrix_world @ vertex.co for vertex in mesh.vertices])
            sensor_objects[name] = dict(bounds_mm=[v.min(0).tolist(), v.max(0).tolist()],
                matrix_world=np.asarray(obj.matrix_world).tolist())
        finally:
            obj.to_mesh_clear()
    imu_bounds = np.array(sensor_objects["Purple_PCB_13x18_two_holes_ESTIMATED"]["bounds_mm"])
    camera_bounds = np.array(sensor_objects["TESTS | Face - Arducam B0066 - camera mock-up"]["bounds_mm"])
    manifest = dict(source_file=bpy.data.filepath, scene=scene.name, frame=scene.frame_current,
                    units="mm", mass_kg=.650, angles_deg=angles, frames=frames,
                    objects=objects, excluded=excluded,
                    sensor_references=sensor_objects,
                    imu_site=dict(position_mm=imu_bounds.mean(0).tolist(),
                        basis="CAD PCB envelope center; chip center not separately identified",
                        position_measured=False, axes="body axes after existing sensor-to-body calibration"),
                    camera_site=dict(position_mm=camera_bounds.mean(0).tolist(),
                        forward_body=[1, 0, 0], up_body=[0, 0, 1],
                        basis="CAD camera envelope center, not calibrated optical center; forward +X and upright from CAD mounting. Intrinsics unqualified.",
                        position_measured=False),
                    scope="Installed assembly collections; excludes render-hidden studies, offboard Q6A and tools")
    (directory / "assembly.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(dict(directory=str(directory), meshes=len(objects), triangles=sum(o['triangles'] for o in objects))))
