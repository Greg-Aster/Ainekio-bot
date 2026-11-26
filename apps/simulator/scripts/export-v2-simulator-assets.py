#!/usr/bin/env python3
"""
Export self-contained static-web GLB for Ainekio V2 (12-Servo Study A 28-16-31-37 + Crimson Scout Shell)
from Slave/hardware/v2-12servo/v3-2.blend (Scene 'v2 - Concept Shell') into:
  public/assets/robots/ainekio-v2.glb

Preserves the exact ThreeVirtualRobotV2Rig scene-graph contract:
  - RobotRoot (local translation [0, -0.0141526, 0.00348363] m)
    - Ext_RobotRoot          (exterior Crimson Scout carapace, visor, hatches, rails & raised ivory badges)
    - Ext_Tex_RobotRoot_01   (exterior UV-marked prow cowl & tail fairing with baked ivory livery)
    - Int_RobotRoot          (interior chassis, modular power carrier, battery & boards)
    - Int_Tex_RobotRoot_00   (Mat_Tex_000 320x170 ST7789 live face display quad in visor bezel)
    - {FL,FR,RL,RR}_Shoulder
      - Ext_{leg}_Shoulder   (concept-fitted side protector carapace fairing)
      - Int_{leg}_Shoulder   (Part_003 mount, Part_005/006 servos, bolted Part_001_9g horn, Part_004)
      - {leg}_Primary -> Int_{leg}_Primary (Part_023 crimson carrier + inside collar + Horn_023)
      - {leg}_Input   -> Int_{leg}_Input   (Part_009 graphite recessed horn crank + Horn_009)
      - {leg}_Rod     -> Int_{leg}_Rod     (Part_026 satin-black direct styled rod + bearings)
      - {leg}_Foot    -> Int_{leg}_Foot    (Part_027 charcoal pickup + Part_022 crimson/charcoal boot + Part_021)

Read-only on v3-2.blend: runs in --background mode and never saves or modifies .blend files.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile

AINEKIO_ROOT = Path("/home/greggles/Ainekio")
SIM_ROOT = Path("/home/greggles/Ainekio/apps/simulator")
BLENDER_BIN = Path("/home/greggles/blender-5.2.2-linux-x64/blender")
BLEND_FILE = AINEKIO_ROOT / "Slave/hardware/v2-12servo/v3-2.blend"
GLTF_TRANSFORM = Path("/home/greggles/Merkin/node_modules/.bin/gltf-transform")
OUT_GLB = SIM_ROOT / "public/assets/robots/ainekio-v2.glb"


BLENDER_EXPORT_V2_SCRIPT = r"""
import json, math, os, sys, tempfile
from pathlib import Path
import bpy, bmesh, mathutils

raw_glb_path = Path(sys.argv[sys.argv.index("--") + 1])
report_path = Path(sys.argv[sys.argv.index("--") + 2])

sc = bpy.data.scenes.get("v2 - Concept Shell") or bpy.data.scenes["v2"]
src_scene_name = sc.name
if bpy.context.window is not None:
    bpy.context.window.scene = sc
vl = sc.view_layers[0]

# Exact V2 Study A 28-16-31-37 four-bar linkage neutral constants (matches virtualRobotRig.ts)
V2_A0 = -2.589563330529253
V2_T0 = -3.7982594562326515
V2_OLD_T0 = 2.129298947791696
L_CAR = 28.0
L_CRK = 16.0
L_PK = 37.0
L_ROD = 31.0

def wrap_pi(rad: float) -> float:
    return math.atan2(math.sin(rad), math.cos(rad))

def solve_v2_at(ox: float, oz: float, cx: float, cz: float, a_rad: float, t_rad: float):
    dx = ox + L_CAR * math.cos(a_rad)
    dz = oz + L_CAR * math.sin(a_rad)
    px = cx + L_CRK * math.cos(t_rad)
    pz = cz + L_CRK * math.sin(t_rad)
    wx = px - dx
    wz = pz - dz
    d = math.hypot(wx, wz)
    along = max(-L_PK, min(L_PK, (L_PK * L_PK - L_ROD * L_ROD + d * d) / (2.0 * max(d, 1e-9))))
    h = math.sqrt(max(0.0, L_PK * L_PK - along * along))
    ex = dx + (along * wx - h * wz) / d
    ez = dz + (along * wz + h * wx) / d
    beta = math.atan2(ez - dz, ex - dx)
    phi = math.atan2(ez - pz, ex - px)
    return dx, dz, px, pz, beta, phi

sc.frame_set(1)
for cad in ("FL", "FR", "RL", "RR"):
    ctrl = sc.objects[f"REFINED | {cad} | h alpha theta"]
    ctrl.animation_data_clear()
    ctrl["h_deg"] = 0.0
    ctrl["alpha_deg"] = 0.0
    ctrl["theta_deg"] = 0.0
    ctrl.rotation_euler = (0.0, 0.0, 0.0)
    ctrl.update_tag()

vl.update()

# Align all 4 legs in temporary memory to bolted Part_006/005 spline centers and exact firmware neutral
SPLINE_OX, SPLINE_OZ = 62.58781342006688, 69.71182170125783
SPLINE_CX, SPLINE_CZ = 50.08774121717073, 81.21184816811960
for cad in ("FL", "FR", "RL", "RR"):
    pr = sc.objects[f"REFINED | {cad} | primary"]
    inp = sc.objects[f"REFINED | {cad} | input"]
    rod = sc.objects[f"REFINED | {cad} | rod"]
    ft = sc.objects[f"REFINED | {cad} | foot"]
    for o in (pr, inp, rod, ft):
        o.animation_data_clear()
    pr.location = (SPLINE_OX, float(pr.location.y), SPLINE_OZ)
    inp.location = (SPLINE_CX, float(inp.location.y), SPLINE_CZ)
    _, _, _, _, old_beta0, old_phi0 = solve_v2_at(SPLINE_OX, SPLINE_OZ, SPLINE_CX, SPLINE_CZ, V2_A0, V2_OLD_T0)
    dx, dz, px, pz, beta, phi = solve_v2_at(SPLINE_OX, SPLINE_OZ, SPLINE_CX, SPLINE_CZ, V2_A0, V2_T0)

    pr.rotation_euler = (0.0, 0.0, 0.0)
    inp.rotation_euler = (0.0, -wrap_pi(V2_T0 - V2_OLD_T0), 0.0)
    rod.location = (px, float(rod.location.y), pz)
    rod.rotation_euler = (0.0, -wrap_pi(phi - old_phi0), 0.0)
    ft.location = (dx, float(ft.location.y), dz)
    ft.rotation_euler = (0.0, -wrap_pi(beta - old_beta0), 0.0)
    for o in (pr, inp, rod, ft):
        o.update_tag()

vl.update()
dg = bpy.context.evaluated_depsgraph_get()

detached = {
    "CARAPACE | Front helmet - extracted 014.001",
    "REFERENCE | FR outer boot - before clean rebuild",
    "STRUCTURAL | Battery bracket - Front paired",
    "STRUCTURAL | Battery bracket - Rear paired",
    "Face.Rail.L.001",
    "Face.Rail.R.001",
    "STRUCTURAL | Rear panel brace - Right",
    "_bezel_closefit",
    "CARAPACE | Rear helmet - extracted 014.002",
    "Crown.Center.001",
    "Anker Slim",
    "front mask shell",
    "front mask - Chin",
    "TESTS | B0066 - adjacent circuit reference",
    "REFERENCE | LCD default face - centered preview",
    "REFERENCE | LCD default face - centered preview | Concept fit",
    "Active_area_22p695x42p72",
    "Concept LCD | Active_area_22p695x42p72",
    "Concept LCD | Viewing_window_23p695x43p72",
    "Concept LCD | Glass_border",
    "Concept LCD | LCD_package_base_representative_25p8x49p72",
}
for side in ("Left", "Right"):
    for end in ("front", "rear"):
        detached.add(f"STRUCTURAL | Battery clip - {side} {end} - underside mount")

excluded_collections = {
    "HUNYUAN 3D 2.1 | Full Robot",
}

horns = {
    "TESTS | Part_001_9g": "FL",
    "TESTS | FR - Part_001_9g": "FR",
    "TESTS | RL - Part_001_9g": "RL",
    "TESTS | RR - Part_001_9g": "RR",
}

SHELL_COLLECTION_NAMES = {
    "CS5 | Crimson Scout Shell",
    "ROBOT - Shell",
    "CARAPACE | Fitted extracted plates",
    "HUNYUAN 3D 2.1 | Generated Cowl",
}

SHELL_NAME_PREFIXES = (
    "01 •",
    "02 •",
    "03 •",
    "04 •",
    "05 •",
    "06 •",
    "07 •",
    "07 |",
    "08 •",
    "09 •",
    "10 •",
    "14 •",
    "LCD | Faceted visor bezel",
    "Forked visor cowl",
)

def material_has_image_tex(mat) -> bool:
    if mat is None or not mat.use_nodes or not mat.node_tree:
        return False
    pnode = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if pnode is None or not pnode.inputs["Base Color"].is_linked:
        return False
    return any(n.type == "TEX_IMAGE" and getattr(n, "image", None) is not None for n in mat.node_tree.nodes)

def is_exterior_shell_obj(obj) -> bool:
    col_names = {c.name for c in obj.users_collection}
    if col_names & SHELL_COLLECTION_NAMES:
        return True
    if obj.name.startswith(SHELL_NAME_PREFIXES):
        return True
    if obj.name.startswith("Carapace - ") and "Side Protector" in obj.name:
        return True
    return False

M_CAD_TO_BL = mathutils.Matrix((
    ( 0.0,    0.001, 0.0,   0.0),
    (-0.001,  0.0,   0.0,   0.0),
    ( 0.0,    0.0,   0.001, 0.0),
    ( 0.0,    0.0,   0.0,   1.0),
))

def cad_pt_to_bl_m(pt_mm) -> mathutils.Vector:
    return mathutils.Vector((float(pt_mm[1]) * 1e-3, -float(pt_mm[0]) * 1e-3, float(pt_mm[2]) * 1e-3))

exp_sc = bpy.data.scenes.new("V2_GLTF_Export")
exp_col = exp_sc.collection

def make_empty(name: str, loc_bl, parent=None):
    e = bpy.data.objects.new(name, None)
    e.empty_display_type = "PLAIN_AXES"
    e.empty_display_size = 0.01
    e.location = loc_bl
    if parent is not None:
        e.parent = parent
    exp_col.objects.link(e)
    return e

ROOT_LOC_BL = mathutils.Vector((0.0, -0.0034836269915103912, -0.01415259763598442))
robot_root = make_empty("RobotRoot", ROOT_LOC_BL, None)

pivot_nodes = {"RobotRoot": (robot_root, mathutils.Vector((0.0, 0.0, 0.0)))}
leg_roles = {
    "h alpha theta": "Shoulder",
    "mechanism frame": "Shoulder",
    "mount frame": "Shoulder",
    "primary": "Primary",
    "input": "Input",
    "rod": "Rod",
    "foot": "Foot",
}

for cad in ("FL", "FR", "RL", "RR"):
    sh_cad = sc.objects[f"REFINED | {cad} | h alpha theta"].evaluated_get(dg).matrix_world.translation.copy()
    sh_bl = cad_pt_to_bl_m(sh_cad)
    sh_empty = make_empty(f"{cad}_Shoulder", sh_bl, robot_root)
    pivot_nodes[f"{cad}_Shoulder"] = (sh_empty, sh_cad)

    for src_role, dst_suffix in (("primary", "Primary"), ("input", "Input"), ("rod", "Rod"), ("foot", "Foot")):
        p_cad = sc.objects[f"REFINED | {cad} | {src_role}"].evaluated_get(dg).matrix_world.translation.copy()
        rel_bl = cad_pt_to_bl_m(p_cad - sh_cad)
        p_empty = make_empty(f"{cad}_{dst_suffix}", rel_bl, sh_empty)
        pivot_nodes[f"{cad}_{dst_suffix}"] = (p_empty, p_cad)

mat_cache = {}
solid_counter = 0
tex_counter = 0

def bake_mix_rgb_image(name_tag: str, src_img, color1, color2) -> bpy.types.Image:
    # Composite MIX_RGB(Color1, Color2, Factor=src_img) into a glTF-ready sRGB texture.
    w, h = int(src_img.size[0]), int(src_img.size[1])
    src_px = list(src_img.pixels[:])
    out_px = [1.0] * (w * h * 4)
    c1r, c1g, c1b = float(color1[0]), float(color1[1]), float(color1[2])
    c2r, c2g, c2b = float(color2[0]), float(color2[1]), float(color2[2])
    for i in range(0, w * h * 4, 4):
        # Luminance of mask pixel drives MIX_RGB Factor socket
        fac = max(0.0, min(1.0, 0.2126 * src_px[i] + 0.7152 * src_px[i + 1] + 0.0722 * src_px[i + 2]))
        inv = 1.0 - fac
        # bpy.types.Image.pixels stores scene-linear floats and encodes sRGB on pack/save
        out_px[i] = c1r * inv + c2r * fac
        out_px[i + 1] = c1g * inv + c2g * fac
        out_px[i + 2] = c1b * inv + c2b * fac
        out_px[i + 3] = 1.0

    baked = bpy.data.images.new(name=f"Baked_{name_tag}", width=w, height=h, alpha=False, float_buffer=False)
    baked.colorspace_settings.name = "sRGB"
    baked.pixels[:] = out_px
    tmp_png = Path(tempfile.gettempdir()) / f"ainekio_v2_baked_{name_tag}_{os.getpid()}.png"
    baked.filepath_raw = str(tmp_png)
    baked.file_format = "PNG"
    baked.save()
    baked.pack()
    try:
        tmp_png.unlink()
    except OSError:
        pass
    return baked

def make_solid_pbr(col, metal: float, rough: float) -> bpy.types.Material:
    global solid_counter
    m = bpy.data.materials.new(name=f"Mat_Solid_{solid_counter:03d}")
    solid_counter += 1
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out_n = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs["BSDF"], out_n.inputs["Surface"])
    bsdf.inputs["Base Color"].default_value = (float(col[0]), float(col[1]), float(col[2]), 1.0)
    bsdf.inputs["Metallic"].default_value = float(metal)
    bsdf.inputs["Roughness"].default_value = float(rough)
    m.diffuse_color = (float(col[0]), float(col[1]), float(col[2]), 1.0)
    m.metallic = float(metal)
    m.roughness = float(rough)
    return m

def get_fallback_material(obj) -> bpy.types.Material:
    # Assign accurate hardware PBR colors to CAD parts that have empty material slots.
    nm = obj.name
    oc = tuple(round(float(x), 3) for x in obj.color[:3])
    if "Horn_" in nm:
        role_key = "__fallback_horn__"
        spec = ([0.16, 0.18, 0.20], 0.20, 0.42)
    elif oc == (0.42, 0.46, 0.5) or any(k in nm for k in ("Bearing", "Shim", "Washer", "M3x6", "screw")):
        role_key = "__fallback_steel__"
        spec = ([0.45, 0.49, 0.53], 0.72, 0.30)
    elif nm.startswith("STRUCTURAL |"):
        role_key = "__fallback_structural_charcoal__"
        spec = ([0.075, 0.085, 0.105], 0.05, 0.52)
    elif oc != (1.0, 1.0, 1.0):
        role_key = f"__fallback_objcol_{oc[0]:.3f}_{oc[1]:.3f}_{oc[2]:.3f}__"
        spec = ([oc[0], oc[1], oc[2]], 0.08, 0.45)
    else:
        role_key = "__fallback_dark_graphite__"
        spec = ([0.20, 0.22, 0.24], 0.10, 0.45)

    if role_key not in mat_cache:
        mat_cache[role_key] = make_solid_pbr(*spec)
    return mat_cache[role_key]

def get_export_material(src_mat, owner_obj=None) -> bpy.types.Material:
    global tex_counter
    if src_mat is None:
        return get_fallback_material(owner_obj) if owner_obj is not None else make_solid_pbr([0.20, 0.22, 0.24], 0.10, 0.45)

    key = f"mat::{src_mat.name}"
    if key in mat_cache:
        return mat_cache[key]

    if material_has_image_tex(src_mat):
        tex_counter += 1
        m = bpy.data.materials.new(name=f"Mat_Tex_{tex_counter:03d}")
        m.use_nodes = True
        nt = m.node_tree
        nt.nodes.clear()
        out_n = nt.nodes.new("ShaderNodeOutputMaterial")
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        nt.links.new(bsdf.outputs["BSDF"], out_n.inputs["Surface"])

        src_pnode = next(n for n in src_mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        metal = float(src_pnode.inputs["Metallic"].default_value)
        rough = float(src_pnode.inputs["Roughness"].default_value)
        bsdf.inputs["Metallic"].default_value = metal
        bsdf.inputs["Roughness"].default_value = rough
        bsdf.inputs["Base Color"].default_value = (1.0, 1.0, 1.0, 1.0)

        from_node = src_pnode.inputs["Base Color"].links[0].from_node
        baked_img = None
        if from_node.type == "MIX_RGB":
            fac_inp = from_node.inputs["Factor"]
            c1 = from_node.inputs["Color1"].default_value
            c2 = from_node.inputs["Color2"].default_value
            tex_n = fac_inp.links[0].from_node if (fac_inp.is_linked and fac_inp.links[0].from_node.type == "TEX_IMAGE") else None
            if tex_n is not None and tex_n.image is not None:
                baked_img = bake_mix_rgb_image(f"tex_{tex_counter:03d}", tex_n.image, c1, c2)
        if baked_img is None:
            src_tex = next(n for n in src_mat.node_tree.nodes if n.type == "TEX_IMAGE" and n.image is not None)
            baked_img = src_tex.image

        tex_node = nt.nodes.new("ShaderNodeTexImage")
        tex_node.image = baked_img
        nt.links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
        mat_cache[key] = m
        return m

    diff = [float(c) for c in src_mat.diffuse_color[:3]]
    col = list(diff)
    metal = float(src_mat.metallic)
    rough = float(src_mat.roughness)

    if src_mat.use_nodes and src_mat.node_tree:
        pnode = next((n for n in src_mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if pnode is not None:
            bc = [float(c) for c in pnode.inputs["Base Color"].default_value[:3]]
            p_metal = float(pnode.inputs["Metallic"].default_value)
            p_rough = float(pnode.inputs["Roughness"].default_value)
            bc_is_default_grey = all(abs(c - 0.8) < 0.015 for c in bc)
            bc_is_step_white = all(abs(c - 1.0) < 0.015 for c in bc) and "255,255,255" not in src_mat.name
            diff_differs = sum(abs(bc[i] - diff[i]) for i in range(3)) > 0.05

            if (bc_is_default_grey or bc_is_step_white or src_mat.name == "STEP_393939") and diff_differs:
                # Preserve the Solid-view material color authored in Blender instead of untouched [0.8,0.8,0.8]/[1,1,1]
                col = list(diff)
                if src_mat.name == "STEP_FFFFFF.006":
                    # Crimson red upper leg carriers (Part_023)
                    metal, rough = 0.25, 0.32
                elif src_mat.name == "STEP_FFFFFF":
                    # Dark charcoal shoulder mounts & horns (Part_003 / Part_001_9g / Part_004)
                    metal, rough = 0.08, 0.42
                elif src_mat.name == "STEP_393939":
                    # Deep matte black servo housings (Part_005 / Part_006 / Part_002_SG90)
                    metal, rough = 0.05, 0.45
                elif max(col) < 0.012:
                    # Satin black chassis plates, braces & styled rods (Material.001..010)
                    col = [0.024, 0.026, 0.030]
                    metal, rough = 0.12, 0.40
                else:
                    metal, rough = 0.10, 0.44
            else:
                col = bc
                metal = p_metal
                rough = p_rough
                if src_mat.name.endswith(".002") and metal >= 0.99 and rough >= 0.99:
                    metal, rough = 0.15, 0.45

    m = make_solid_pbr(col, metal, rough)
    mat_cache[key] = m
    return m

def classify_v2_mesh(obj):
    if obj.name in horns:
        cad = horns[obj.name]
        return f"Int_{cad}_Shoulder", f"{cad}_Shoulder"
    if any(c.name.startswith("BOOT |") for c in obj.users_collection):
        return "Int_FR_Foot", "FR_Foot"
    cur = obj
    while cur is not None:
        parts = cur.name.split(" | ")
        if len(parts) == 3 and parts[0] == "REFINED" and parts[2] in leg_roles:
            cad = parts[1]
            role = leg_roles[parts[2]]
            prefix = "Ext" if (role == "Shoulder" and is_exterior_shell_obj(obj)) else "Int"
            return f"{prefix}_{cad}_{role}", f"{cad}_{role}"
        cur = cur.parent
    if is_exterior_shell_obj(obj):
        has_tex = any(material_has_image_tex(ms.material) for ms in obj.material_slots if ms.material)
        if has_tex:
            return "Ext_Tex_RobotRoot_01", "RobotRoot"
        return "Ext_RobotRoot", "RobotRoot"
    return "Int_RobotRoot", "RobotRoot"

buckets = {}
exported_parts = []
total_raw_tris = 0

for obj in sorted(sc.objects, key=lambda x: x.name):
    name = obj.name
    if obj.type != "MESH" or not obj.visible_get(view_layer=vl) or obj.hide_render:
        continue
    if any(c.name.startswith("BACKUP |") or c.name in excluded_collections for c in obj.users_collection):
        continue
    if name in detached or name.startswith(("ORIG_", "PRE_", "BACKUP", "HY21_", "FIT REF")):
        continue
    if "Radxa" in name or "PCA9685 - 1x6" in name or "Torsion Spring" in name:
        continue

    ev = obj.evaluated_get(dg)
    bbox_pts = [ev.matrix_world @ mathutils.Vector(c) for c in ev.bound_box]
    cx = 0.5 * (min(p.x for p in bbox_pts) + max(p.x for p in bbox_pts))
    cy = 0.5 * (min(p.y for p in bbox_pts) + max(p.y for p in bbox_pts))
    cz = 0.5 * (min(p.z for p in bbox_pts) + max(p.z for p in bbox_pts))
    if abs(cx) > 150.0 or abs(cy) > 100.0 or cz < -20.0 or cz > 160.0:
        continue

    group_name, pivot_key = classify_v2_mesh(obj)
    _, pivot_cad_mm = pivot_nodes[pivot_key]

    tmp_mesh = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=dg)
    if tmp_mesh is None or len(tmp_mesh.polygons) == 0:
        if tmp_mesh is not None:
            bpy.data.meshes.remove(tmp_mesh)
        continue

    T_shift = mathutils.Matrix.Translation(-pivot_cad_mm)
    M_full = M_CAD_TO_BL @ T_shift @ ev.matrix_world
    tmp_mesh.transform(M_full)
    if M_full.determinant() < 0:
        tmp_mesh.flip_normals()

    # Weld sub-millimetre internal PCB/servo reference vertices (>25k polys) directly in bmesh
    poly_cnt = len(tmp_mesh.polygons)
    if poly_cnt > 25000 and not group_name.startswith("Ext_"):
        bm_dec = bmesh.new()
        bm_dec.from_mesh(tmp_mesh)
        dist_m = 0.00055 if poly_cnt > 200000 else 0.00028
        bmesh.ops.remove_doubles(bm_dec, verts=bm_dec.verts[:], dist=dist_m)
        bm_dec.to_mesh(tmp_mesh)
        bm_dec.free()
        tmp_mesh.update()

    orig_slots = [ms.material for ms in obj.material_slots]
    mapped_mats = (
        [get_export_material(sm, obj) for sm in orig_slots]
        if orig_slots
        else [get_export_material(obj.active_material, obj)]
    )

    buckets.setdefault(group_name, {"pivot_key": pivot_key, "parts": []})["parts"].append((name, tmp_mesh, mapped_mats))
    total_raw_tris += len(tmp_mesh.polygons)
    exported_parts.append({"name": name, "group": group_name, "polys": len(tmp_mesh.polygons)})

# Merge parts per group cleanly using bmesh (preserving multi-slot material indices!)
for group_name, info in sorted(buckets.items()):
    parent_obj, _ = pivot_nodes[info["pivot_key"]]
    bm_merged = bmesh.new()
    uv_lay_merged = bm_merged.loops.layers.uv.new("UVMap")
    group_mats = []
    mat_to_slot = {}

    for orig_name, mdata, part_mats in info["parts"]:
        slot_remap = {}
        for i, emat in enumerate(part_mats):
            if emat.name not in mat_to_slot:
                mat_to_slot[emat.name] = len(group_mats)
                group_mats.append(emat)
            slot_remap[i] = mat_to_slot[emat.name]

        bm_part = bmesh.new()
        bm_part.from_mesh(mdata)
        uv_src = bm_part.loops.layers.uv.active
        if uv_src is None:
            uv_src = bm_part.loops.layers.uv.new("UVMap")
        elif uv_src.name != "UVMap":
            uv_dst = bm_part.loops.layers.uv.new("UVMap")
            for f in bm_part.faces:
                for l in f.loops:
                    l[uv_dst].uv = l[uv_src].uv
        for f in bm_part.faces:
            f.material_index = slot_remap.get(f.material_index, 0)

        tmp_part_mesh = bpy.data.meshes.new("_bm_xfer")
        for gm in group_mats:
            tmp_part_mesh.materials.append(gm)
        bm_part.to_mesh(tmp_part_mesh)
        bm_part.free()
        bm_merged.from_mesh(tmp_part_mesh)
        bpy.data.meshes.remove(tmp_part_mesh)
        bpy.data.meshes.remove(mdata)

    bmesh.ops.triangulate(bm_merged, faces=bm_merged.faces[:])
    out_mesh = bpy.data.meshes.new(group_name)
    for gm in group_mats:
        out_mesh.materials.append(gm)
    bm_merged.to_mesh(out_mesh)
    bm_merged.free()
    out_mesh.validate()
    out_mesh.update()

    g_obj = bpy.data.objects.new(group_name, out_mesh)
    g_obj.parent = parent_obj
    exp_col.objects.link(g_obj)

# Add exact Int_Tex_RobotRoot_00 (Mat_Tex_000) ST7789 320x170 live face display quad
face_mat = bpy.data.materials.new(name="Mat_Tex_000")
face_mat.use_nodes = True
face_mat.use_backface_culling = False
f_nt = face_mat.node_tree
f_bsdf = next(n for n in f_nt.nodes if n.type == "BSDF_PRINCIPLED")
f_bsdf.inputs["Base Color"].default_value = (0.02, 0.025, 0.035, 1.0)
f_bsdf.inputs["Metallic"].default_value = 0.0
f_bsdf.inputs["Roughness"].default_value = 0.75
def make_default_eye_image() -> bpy.types.Image:
    if Path("/tmp/ainekio-face-default.png").exists():
        img = bpy.data.images.load("/tmp/ainekio-face-default.png")
        img.pack()
        return img
    ref = bpy.data.images.get("REFERENCE | Default face - native Ainekio renderer")
    if ref is not None and int(ref.size[0]) > 0 and int(ref.size[1]) > 0:
        if not ref.packed_file:
            ref.pack()
        return ref
    w, h = 320, 170
    px = [0.0] * (w * h * 4)
    for y in range(h):
        for x in range(w):
            i = (y * w + x) * 4
            px[i : i + 4] = [0.008, 0.012, 0.020, 1.0]
            for cx in (96.0, 224.0):
                d_pupil = math.hypot(x - cx, y - 85.0)
                if d_pupil <= 11.5:
                    t = max(0.0, min(1.0, (11.5 - d_pupil) / 2.0))
                    px[i : i + 3] = [0.45 * t, 0.94 * t, 1.0 * t]
            dx_arc = abs(x - 160.0)
            r_arc = math.hypot((x - (62.0 if x < 160 else 258.0)) * 0.95, y - 85.0)
            if dx_arc > 112.0 and 46.0 <= r_arc <= 54.0 and 38 <= y <= 132:
                px[i : i + 3] = [0.35, 0.90, 1.0]
    gen = bpy.data.images.new(name="Default_Ainekio_Eyes", width=w, height=h, alpha=False, float_buffer=False)
    gen.colorspace_settings.name = "sRGB"
    gen.pixels[:] = px
    tmp_e = Path(tempfile.gettempdir()) / f"ainekio_v2_eyes_{os.getpid()}.png"
    gen.filepath_raw = str(tmp_e)
    gen.file_format = "PNG"
    gen.save()
    gen.pack()
    tmp_e.unlink(missing_ok=True)
    return gen

eye_img = make_default_eye_image()
if eye_img is not None:
    f_tex = f_nt.nodes.new("ShaderNodeTexImage")
    f_tex.image = eye_img
    f_nt.links.new(f_tex.outputs["Color"], f_bsdf.inputs["Emission Color"])
    f_bsdf.inputs["Emission Strength"].default_value = 1.0

lcd_ref = sc.objects.get("REFERENCE | LCD default face - centered preview | Concept fit")
if lcd_ref is not None:
    ev_lcd = lcd_ref.evaluated_get(dg)
    poly0 = ev_lcd.data.polygons[0]
    wnrm = (ev_lcd.matrix_world.to_3x3() @ poly0.normal).normalized()
    uv_src = ev_lcd.data.uv_layers.active.data
    f_verts_local = []
    f_uvs = {}
    for idx, li in enumerate(poly0.loop_indices):
        vi = ev_lcd.data.loops[li].vertex_index
        wco_mm = (ev_lcd.matrix_world @ ev_lcd.data.vertices[vi].co) + (0.45 * wnrm)
        v_bl = cad_pt_to_bl_m(wco_mm)
        f_verts_local.append(tuple(v_bl))
        f_uvs[idx] = (float(uv_src[li].uv[0]), float(uv_src[li].uv[1]))
    f_faces = [(0, 1, 2), (0, 2, 3)]
else:
    f_verts_local = [
        (-0.02136, -0.10681, 0.06844),
        ( 0.02136, -0.10681, 0.06844),
        ( 0.02136, -0.09758, 0.08917),
        (-0.02136, -0.09758, 0.08917),
    ]
    f_faces = [(0, 1, 2), (0, 2, 3)]
    f_uvs = {
        0: (0.0161, 0.1083),
        1: (0.8933, 0.1083),
        2: (0.8933, 0.9855),
        3: (0.0161, 0.9855),
    }

f_mesh = bpy.data.meshes.new("Int_TexMesh_00")
f_mesh.from_pydata(f_verts_local, [], f_faces)
f_mesh.materials.append(face_mat)
uv_layer = f_mesh.uv_layers.new(name="UVMap")
for poly in f_mesh.polygons:
    for li in poly.loop_indices:
        vi = f_mesh.loops[li].vertex_index
        uv_layer.data[li].uv = f_uvs[vi]
f_mesh.update()
f_obj = bpy.data.objects.new("Int_Tex_RobotRoot_00", f_mesh)
f_obj.parent = robot_root
exp_col.objects.link(f_obj)

# Remove other scenes in temporary background memory so export_scene.gltf exports ONLY V2_GLTF_Export
for other_sc in list(bpy.data.scenes):
    if other_sc != exp_sc:
        bpy.data.scenes.remove(other_sc)
exp_sc.view_layers[0].update()

raw_glb_path.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.export_scene.gltf(
    filepath=str(raw_glb_path),
    export_format="GLB",
    export_yup=True,
    export_apply=False,
    export_texcoords=True,
    export_normals=True,
    export_materials="EXPORT",
)

report_path.write_text(json.dumps({
    "scene": src_scene_name,
    "parts_count": len(exported_parts),
    "groups": sorted(buckets.keys()),
    "materials_count": len(mat_cache) + 1,
    "total_polys_after_pcb_decim": total_raw_tris,
    "parts": exported_parts,
}, indent=2), encoding="utf-8")
print(f"Exported raw V2 GLB ({len(exported_parts)} CAD parts across {len(buckets)} groups, {total_raw_tris:,} polys)")
"""


def main() -> None:
    if not BLENDER_BIN.exists():
        raise FileNotFoundError(f"Missing Blender binary: {BLENDER_BIN}")
    if not BLEND_FILE.exists():
        raise FileNotFoundError(f"Missing v3-2.blend: {BLEND_FILE}")
    if not GLTF_TRANSFORM.exists():
        raise FileNotFoundError(f"Missing gltf-transform CLI: {GLTF_TRANSFORM}")

    with tempfile.TemporaryDirectory(prefix="v2-export-") as td:
        td_path = Path(td)
        script_path = td_path / "export_v2.py"
        raw_glb = td_path / "ainekio-v2-raw.glb"
        webp_glb = td_path / "ainekio-v2-webp.glb"
        report_json = td_path / "v2_report.json"
        script_path.write_text(BLENDER_EXPORT_V2_SCRIPT, encoding="utf-8")

        print("Running read-only Blender background export for Scene 'v2 - Concept Shell'...")
        res = subprocess.run(
            [
                str(BLENDER_BIN),
                "--background",
                "--python-exit-code",
                "1",
                "-y",
                str(BLEND_FILE),
                "--python",
                str(script_path),
                "--",
                str(raw_glb),
                str(report_json),
            ],
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            print("=== BLENDER STDOUT ===\n", res.stdout[-4000:])
            print("=== BLENDER STDERR ===\n", res.stderr[-4000:])
            raise RuntimeError(f"Blender V2 export failed with exit code {res.returncode}")

        for line in res.stdout.splitlines():
            if "Exported raw V2 GLB" in line:
                print(f"  {line}")

        report = json.loads(report_json.read_text(encoding="utf-8"))
        print(f"  Raw GLB size: {raw_glb.stat().st_size / (1024 * 1024):.2f} MB; groups: {len(report['groups'])}")

        subprocess.run(
            [str(GLTF_TRANSFORM), "webp", str(raw_glb), str(webp_glb)],
            check=True,
        )
        OUT_GLB.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [str(GLTF_TRANSFORM), "meshopt", str(webp_glb), str(OUT_GLB)],
            check=True,
        )
        final_mb = OUT_GLB.stat().st_size / (1024 * 1024)
        print(f"Exported Meshopt-compressed {OUT_GLB} ({final_mb:.2f} MB)")


if __name__ == "__main__":
    main()
