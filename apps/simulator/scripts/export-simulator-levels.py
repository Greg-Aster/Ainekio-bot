#!/usr/bin/env python3
"""
Export the 5 canonical game levels from apps/game into lazy-loadable,
Megameal-detached static scene bundles + exact MuJoCo collision geometry
for apps/simulator.ainek.io:

  1. observatory   - Real 16 chunked terrain GLBs + 112x112 MuJoCo <hfield>
  2. yggdrasil     - Rebuilt low-poly Norse Tree-of-Life Island & Robot Obstacle Course (0 heavy GLBs)
  3. miranda       - Rebuilt derelict cosmic-horror starship (Bridge stairs, Crew Quarters, Mess Hall, Asteroid Field & Dying Star)
  4. solitude      - Rebuilt rolling grassy Stonehenge plain & single firefly (111x111 hfield, 0 heavy GLBs)
  5. sci-fi-room   - Rebuilt surreal far-future Astral House (Chronos-Orrery, Escher stairs, crystal garden & portals)

All levels are re-centered around their authored walkable spawn point so
MuJoCo contact physics and WebGL depth/shadow precision stay centered at (0,0,0)
with the robot's feet resting flush on y = 0 (MuJoCo z = 0).
"""

from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

MERKIN_ROOT = Path("/home/greggles/Merkin")
GAME_SCENES_DIR = MERKIN_ROOT / "apps/game/src/threlte/editor/scenes"
PREFAB_CATALOG_PATH = MERKIN_ROOT / "apps/game/src/threlte/engine/runtimePrefabCatalog.json"
MEGAMEAL_PUBLIC = MERKIN_ROOT / "apps/megameal/public"

SIM_ROOT = Path("/home/greggles/Ainekio/apps/simulator")
OUT_LEVELS_DIR = SIM_ROOT / "public/sim/levels"
OUT_ASSETS_DIR = SIM_ROOT / "public/assets/levels"

from build_miranda_level import build_miranda_level
from build_robotics_lab_level import build_robotics_lab_level
from build_scifi_room_level import build_scifi_room_level
from build_solitude_level import build_solitude_level
from build_yggdrasil_level import build_yggdrasil_level

# Prefab simple-polygon fallback specs (for Legacy Yggdrasil / Legacy Solitude)
# Each part is (shape, offset_xyz, args, color, emissive, metalness, roughness)
PREFAB_SIMPLE_POLYS: dict[str, list[dict[str, Any]]] = {
    "wasteland-monolith": [
        {
            "shape": "box",
            "pos": [0, 0, 0],
            "args": [1.3, 4.6, 1.3],
            "color": "#6e7785",
            "emissive": "#1e293b",
            "emissiveIntensity": 0.12,
            "metalness": 0.14,
            "roughness": 0.88,
            "solid": True,
        }
    ],
    "broken-ring": [
        {
            "shape": "torus",
            "pos": [0, 1.6, 0],
            "args": [2.4, 0.36, 10, 24],
            "color": "#8a95a6",
            "emissive": "#334155",
            "emissiveIntensity": 0.18,
            "metalness": 0.25,
            "roughness": 0.72,
            "solid": False,
        }
    ],
    "portal-apparatus": [
        {
            "shape": "torus",
            "pos": [0, 2.8, 0],
            "args": [2.2, 0.28, 12, 28],
            "color": "#475569",
            "emissive": "#38bdf8",
            "emissiveIntensity": 0.45,
            "metalness": 0.55,
            "roughness": 0.35,
            "solid": False,
        },
        {
            "shape": "box",
            "pos": [0, 0.2, 0],
            "args": [4.8, 0.4, 1.6],
            "color": "#334155",
            "emissive": "#0f172a",
            "emissiveIntensity": 0.1,
            "metalness": 0.5,
            "roughness": 0.5,
            "solid": True,
        },
    ],
    "observation-rig": [
        {
            "shape": "cylinder",
            "pos": [0, 1.4, 0],
            "args": [0.45, 0.65, 2.8, 10],
            "color": "#64748b",
            "emissive": "#0ea5e9",
            "emissiveIntensity": 0.22,
            "metalness": 0.45,
            "roughness": 0.55,
            "solid": True,
        }
    ],
    "wasteland-archway": [
        {
            "shape": "box",
            "pos": [-2.2, 2.5, 0],
            "args": [0.9, 5.0, 1.1],
            "color": "#7b8494",
            "emissive": "#1e293b",
            "emissiveIntensity": 0.08,
            "metalness": 0.15,
            "roughness": 0.88,
            "solid": True,
        },
        {
            "shape": "box",
            "pos": [2.2, 2.5, 0],
            "args": [0.9, 5.0, 1.1],
            "color": "#7b8494",
            "emissive": "#1e293b",
            "emissiveIntensity": 0.08,
            "metalness": 0.15,
            "roughness": 0.88,
            "solid": True,
        },
        {
            "shape": "box",
            "pos": [0, 5.2, 0],
            "args": [5.6, 0.9, 1.2],
            "color": "#8994a6",
            "emissive": "#273549",
            "emissiveIntensity": 0.1,
            "metalness": 0.18,
            "roughness": 0.85,
            "solid": False,
        },
    ],
    "interior-archway": [
        {
            "shape": "box",
            "pos": [-1.8, 2.1, 0],
            "args": [0.6, 4.2, 0.8],
            "color": "#475569",
            "emissive": "#0f172a",
            "emissiveIntensity": 0.12,
            "metalness": 0.5,
            "roughness": 0.45,
            "solid": True,
        },
        {
            "shape": "box",
            "pos": [1.8, 2.1, 0],
            "args": [0.6, 4.2, 0.8],
            "color": "#475569",
            "emissive": "#0f172a",
            "emissiveIntensity": 0.12,
            "metalness": 0.5,
            "roughness": 0.45,
            "solid": True,
        },
        {
            "shape": "box",
            "pos": [0, 4.3, 0],
            "args": [4.4, 0.6, 0.8],
            "color": "#64748b",
            "emissive": "#1e293b",
            "emissiveIntensity": 0.15,
            "metalness": 0.55,
            "roughness": 0.4,
            "solid": False,
        },
    ],
    "courtyard-pylon": [
        {
            "shape": "cylinder",
            "pos": [0, 2.2, 0],
            "args": [0.45, 0.7, 4.4, 8],
            "color": "#6d7889",
            "emissive": "#38bdf8",
            "emissiveIntensity": 0.22,
            "metalness": 0.32,
            "roughness": 0.62,
            "solid": True,
        }
    ],
    "support-column": [
        {
            "shape": "cylinder",
            "pos": [0, 2.5, 0],
            "args": [0.5, 0.6, 5.0, 10],
            "color": "#556270",
            "emissive": "#1e293b",
            "emissiveIntensity": 0.08,
            "metalness": 0.4,
            "roughness": 0.65,
            "solid": True,
        }
    ],
    "bench-growth": [
        {
            "shape": "box",
            "pos": [0, 0.4, 0],
            "args": [2.2, 0.7, 0.85],
            "color": "#4f6344",
            "emissive": "#1c2d19",
            "emissiveIntensity": 0.12,
            "metalness": 0.1,
            "roughness": 0.9,
            "solid": True,
        }
    ],
    "growth-planter": [
        {
            "shape": "cylinder",
            "pos": [0, 0.6, 0],
            "args": [0.9, 1.0, 1.2, 10],
            "color": "#475c3e",
            "emissive": "#1d3118",
            "emissiveIntensity": 0.15,
            "metalness": 0.12,
            "roughness": 0.88,
            "solid": True,
        }
    ],
    "anomaly-cluster": [
        {
            "shape": "octahedron",
            "pos": [0, 1.6, 0],
            "args": [0.85],
            "color": "#e879f9",
            "emissive": "#c026d3",
            "emissiveIntensity": 0.65,
            "metalness": 0.35,
            "roughness": 0.25,
            "solid": False,
        }
    ],
}


def euler_xyz_to_matrix(rx: float, ry: float, rz: float) -> np.ndarray:
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    mx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]], dtype=np.float64)
    my = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], dtype=np.float64)
    mz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]], dtype=np.float64)
    # Three.js default Euler order 'XYZ': R = Rx * Ry * Rz
    return mx @ my @ mz


def trs_matrix(pos: list[float], rot: list[float], scale: list[float]) -> np.ndarray:
    m = np.eye(4, dtype=np.float64)
    r = euler_xyz_to_matrix(rot[0], rot[1], rot[2])
    m[:3, :3] = r * np.array(scale, dtype=np.float64)[None, :]
    m[:3, 3] = np.array(pos, dtype=np.float64)
    return m


def rot_matrix_to_quat_xyzw(r: np.ndarray) -> list[float]:
    # Normalize columns to strip scale
    r = r.copy()
    for c in range(3):
        n = float(np.linalg.norm(r[:, c]))
        if n > 1e-9:
            r[:, c] /= n
    tr = float(r[0, 0] + r[1, 1] + r[2, 2])
    if tr > 0.0:
        s = math.sqrt(tr + 1.0) * 2.0
        w = 0.25 * s
        x = (r[2, 1] - r[1, 2]) / s
        y = (r[0, 2] - r[2, 0]) / s
        z = (r[1, 0] - r[0, 1]) / s
    elif r[0, 0] > r[1, 1] and r[0, 0] > r[2, 2]:
        s = math.sqrt(1.0 + r[0, 0] - r[1, 1] - r[2, 2]) * 2.0
        w = (r[2, 1] - r[1, 2]) / s
        x = 0.25 * s
        y = (r[0, 1] + r[1, 0]) / s
        z = (r[0, 2] + r[2, 0]) / s
    elif r[1, 1] > r[2, 2]:
        s = math.sqrt(1.0 + r[1, 1] - r[0, 0] - r[2, 2]) * 2.0
        w = (r[0, 2] - r[2, 0]) / s
        x = (r[0, 1] + r[1, 0]) / s
        y = 0.25 * s
        z = (r[1, 2] + r[2, 1]) / s
    else:
        s = math.sqrt(1.0 + r[2, 2] - r[0, 0] - r[1, 1]) * 2.0
        w = (r[1, 0] - r[0, 1]) / s
        x = (r[0, 2] + r[2, 0]) / s
        y = (r[1, 2] + r[2, 1]) / s
        z = 0.25 * s
    norm = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    return [x / norm, y / norm, z / norm, w / norm]


def decompose_world_matrix(m: np.ndarray) -> tuple[list[float], list[float], list[float]]:
    pos = [float(m[0, 3]), float(m[1, 3]), float(m[2, 3])]
    sx = float(np.linalg.norm(m[:3, 0]))
    sy = float(np.linalg.norm(m[:3, 1]))
    sz = float(np.linalg.norm(m[:3, 2]))
    rot_m = m[:3, :3].copy()
    if sx > 1e-9:
        rot_m[:, 0] /= sx
    if sy > 1e-9:
        rot_m[:, 1] /= sy
    if sz > 1e-9:
        rot_m[:, 2] /= sz
    if np.linalg.det(rot_m) < 0:
        sx = -sx
        rot_m[:, 0] = -rot_m[:, 0]
    quat = rot_matrix_to_quat_xyzw(rot_m)
    return pos, quat, [abs(sx), abs(sy), abs(sz)]


def three_pos_to_mj(pos: list[float]) -> list[float]:
    # Three (+Z fwd, +X left, +Y up) -> MuJoCo (+X fwd, +Y left, +Z up)
    return [float(pos[2]), float(pos[0]), float(pos[1])]


def three_quat_xyzw_to_mj_wxyz(quat_xyzw: list[float]) -> list[float]:
    # Basis permutation P: v_mj = (v_t.z, v_t.x, v_t.y) has det = +1,
    # so rotation quaternion permutes identically: (qx, qy, qz, qw) -> (qw, qz, qx, qy)
    qx, qy, qz, qw = quat_xyzw
    return [float(qw), float(qz), float(qx), float(qy)]


def compute_world_transforms(nodes: list[dict[str, Any]]) -> dict[str, tuple[np.ndarray, bool]]:
    by_id = {n["id"]: n for n in nodes}
    cache: dict[str, tuple[np.ndarray, bool]] = {}

    def resolve(nid: str) -> tuple[np.ndarray, bool]:
        if nid in cache:
            return cache[nid]
        node = by_id[nid]
        pos = node.get("position") or [0, 0, 0]
        rot = node.get("rotation") or [0, 0, 0]
        scl = node.get("scale") or [1, 1, 1]
        local = trs_matrix(pos, rot, scl)
        vis = node.get("visible", True) is not False
        pid = node.get("parentId")
        if pid and pid in by_id:
            pm, pvis = resolve(pid)
            res = (pm @ local, pvis and vis)
        else:
            res = (local, vis)
        cache[nid] = res
        return res

    for n in nodes:
        resolve(n["id"])
    return cache


def copy_asset_to_simulator(src_rel_url: str, sub_folder: str) -> str:
    """Copy a GLB or GLTF (+ sidecar .bin/textures) into public/assets/levels/<sub_folder>/."""
    src = MEGAMEAL_PUBLIC / src_rel_url.lstrip("/")
    if not src.exists():
        raise FileNotFoundError(f"Missing source asset: {src}")
    if src.suffix.lower() == ".gltf":
        folder_name = src.parent.name
        dst_dir = OUT_ASSETS_DIR / sub_folder / folder_name
        dst_dir.mkdir(parents=True, exist_ok=True)
        for item in src.parent.rglob("*"):
            if item.is_file():
                rel = item.relative_to(src.parent)
                target = dst_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists() or target.stat().st_size != item.stat().st_size:
                    shutil.copy2(item, target)
        return f"/assets/levels/{sub_folder}/{folder_name}/{src.name}"

    dst_dir = OUT_ASSETS_DIR / sub_folder
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if not dst.exists() or dst.stat().st_size != src.stat().st_size:
        shutil.copy2(src, dst)
    return f"/assets/levels/{sub_folder}/{src.name}"


def r3(vals: list[float], ndigits: int = 4) -> list[float]:
    return [round(float(v), ndigits) for v in vals]


def add_primitive_visual_and_collider(
    *,
    pid: str,
    shape: str,
    args: list[float],
    world_pos: list[float],
    world_quat: list[float],
    world_scale: list[float],
    origin: list[float],
    color: str,
    emissive: str | None,
    emissive_intensity: float,
    metalness: float,
    roughness: float,
    opacity: float,
    solid: bool,
    primitives_out: list[dict[str, Any]],
    colliders_out: list[dict[str, Any]],
    max_collider_dist: float = 90.0,
) -> None:
    rel_pos = [world_pos[0] - origin[0], world_pos[1] - origin[1], world_pos[2] - origin[2]]
    if opacity > 0.01:
        primitives_out.append(
            {
                "id": pid,
                "shape": shape,
                "pos": r3(rel_pos),
                "quat": r3(world_quat, 5),
                "scale": r3(world_scale),
                "args": r3(args),
                "color": color,
                **({"emissive": emissive, "emissiveIntensity": round(emissive_intensity, 3)} if emissive else {}),
                "metalness": round(metalness, 3),
                "roughness": round(roughness, 3),
                **({"opacity": round(opacity, 3)} if opacity < 0.999 else {}),
            }
        )

    if not solid:
        return

    # Keep MuJoCo geoms within reasonable distance of spawn (or large floor slabs overlapping origin)
    if shape == "box" and len(args) >= 3:
        sx = abs(args[0] * world_scale[0])
        sy = abs(args[1] * world_scale[1])
        sz = abs(args[2] * world_scale[2])
        if sx < 0.02 or sy < 0.02 or sz < 0.02:
            return
        dist = math.hypot(rel_pos[0], rel_pos[2]) - 0.5 * math.hypot(sx, sz)
        if dist > max_collider_dist:
            return
        colliders_out.append(
            {
                "id": pid,
                "shape": "box",
                "posMj": r3(three_pos_to_mj(rel_pos)),
                "quatMj": r3(three_quat_xyzw_to_mj_wxyz(world_quat), 5),
                # Three (sx, sy, sz) -> MuJoCo half-size (sz/2, sx/2, sy/2)
                "sizeMj": r3([max(0.01, sz / 2), max(0.01, sx / 2), max(0.01, sy / 2)]),
            }
        )
    elif shape == "cylinder" and len(args) >= 3:
        r_top = abs(args[0]) * max(world_scale[0], world_scale[2])
        r_bot = abs(args[1]) * max(world_scale[0], world_scale[2])
        height = abs(args[2]) * world_scale[1]
        rad = max(r_top, r_bot)
        if rad < 0.02 or height < 0.02:
            return
        dist = math.hypot(rel_pos[0], rel_pos[2]) - rad
        if dist > max_collider_dist:
            return
        # Cylinder axis in Three.js is +Y -> which maps directly to MuJoCo +Z!
        # Wait: MuJoCo cylinder local axis is +Z, and our SO(3) mapping maps Three +Y -> MuJoCo +Z!
        # So three_quat_xyzw_to_mj_wxyz maps a Three +Y cylinder cleanly to a MuJoCo +Z cylinder!
        colliders_out.append(
            {
                "id": pid,
                "shape": "cylinder",
                "posMj": r3(three_pos_to_mj(rel_pos)),
                "quatMj": r3(three_quat_xyzw_to_mj_wxyz(world_quat), 5),
                "sizeMj": r3([max(0.02, rad), max(0.01, height / 2)]),
            }
        )


def export_scene_level(
    *,
    level_id: str,
    name: str,
    subtitle: str,
    scene: dict[str, Any],
    world_origin_three: list[float],
    legacy_simple_polygons: bool,
    prefab_catalog: dict[str, Any],
    skybox_dir: str,
    background_hex: str,
    fog_hex: str,
    fog_density: float,
    water_y_world: float | None = None,
    water_color: str = "#050b14",
    extra_solid_ids: set[str] | None = None,
    skip_collider_ids: set[str] | None = None,
) -> dict[str, Any]:
    nodes = scene.get("nodes") or []
    world_map = compute_world_transforms(nodes)
    primitives: list[dict[str, Any]] = []
    colliders: list[dict[str, Any]] = []
    glb_instances: list[dict[str, Any]] = []
    lights: list[dict[str, Any]] = []

    asset_urls = prefab_catalog.get("assetUrls") or {}
    asset_variants = prefab_catalog.get("assetVariants") or {}
    extra_solid = extra_solid_ids or set()
    skip_colliders = skip_collider_ids or set()

    for node in nodes:
        nid = node["id"]
        kind = node.get("kind")
        world_m, visible = world_map[nid]
        if not visible:
            continue
        # Strip Megameal story markers / narrative triggers cleanly
        if kind == "prefab" and (node.get("prefab") or {}).get("type") == "story-marker":
            continue
        if "story" in nid.lower() and kind != "group":
            continue

        w_pos, w_quat, w_scale = decompose_world_matrix(world_m)
        col_cfg = node.get("collision") or {}
        has_collision = (
            nid not in skip_colliders
            and col_cfg.get("mode") != "none"
            and col_cfg.get("enabled") is not False
        )

        if kind == "primitive":
            prim = node.get("primitive") or {}
            geom = prim.get("geometry", "box")
            args = [float(v) for v in (prim.get("args") or [1, 1, 1])]
            opacity = float(prim.get("opacity", 1.0)) if prim.get("transparent") else 1.0
            # Skip invisible helper pads (opacity == 0) from both visuals & colliders unless explicitly solid
            if opacity <= 0.01 and nid not in extra_solid:
                continue
            solid = (has_collision or nid in extra_solid) and geom in ("box", "cylinder") and opacity > 0.01
            # Non-walkable translucent ribbons/beams should not interfere with foot contact
            if "ribbon" in nid.lower() or "mist" in nid.lower() or "canopy" in nid.lower() or "foliage" in nid.lower():
                solid = False
            add_primitive_visual_and_collider(
                pid=nid,
                shape=geom,
                args=args,
                world_pos=w_pos,
                world_quat=w_quat,
                world_scale=w_scale,
                origin=world_origin_three,
                color=str(prim.get("color", "#64748b")),
                emissive=prim.get("emissive"),
                emissive_intensity=float(prim.get("emissiveIntensity", 0.0)),
                metalness=float(prim.get("metalness", 0.25)),
                roughness=float(prim.get("roughness", 0.75)),
                opacity=opacity,
                solid=solid,
                primitives_out=primitives,
                colliders_out=colliders,
            )

        elif kind == "prefab":
            pf = node.get("prefab") or {}
            ptype = pf.get("type", "")
            if legacy_simple_polygons or ptype not in asset_urls:
                parts = PREFAB_SIMPLE_POLYS.get(ptype) or PREFAB_SIMPLE_POLYS["wasteland-monolith"]
                for idx, part in enumerate(parts):
                    local_m = trs_matrix(part["pos"], [0, 0, 0], [1, 1, 1])
                    pm = world_m @ local_m
                    pp, pq, ps = decompose_world_matrix(pm)
                    add_primitive_visual_and_collider(
                        pid=f"{nid}_p{idx}",
                        shape=part["shape"],
                        args=list(part["args"]),
                        world_pos=pp,
                        world_quat=pq,
                        world_scale=ps,
                        origin=world_origin_three,
                        color=part["color"],
                        emissive=part.get("emissive"),
                        emissive_intensity=float(part.get("emissiveIntensity", 0.0)),
                        metalness=float(part.get("metalness", 0.25)),
                        roughness=float(part.get("roughness", 0.75)),
                        opacity=1.0,
                        solid=bool(part.get("solid", False)) and has_collision,
                        primitives_out=primitives,
                        colliders_out=colliders,
                    )
            else:
                variant = pf.get("variant")
                src_url = (asset_variants.get(ptype) or {}).get(variant) or asset_urls[ptype]
                sim_url = copy_asset_to_simulator(src_url, "prefabs")
                rel_pos = [w_pos[0] - world_origin_three[0], w_pos[1] - world_origin_three[1], w_pos[2] - world_origin_three[2]]
                glb_instances.append(
                    {
                        "id": nid,
                        "url": sim_url,
                        "pos": r3(rel_pos),
                        "quat": r3(w_quat, 5),
                        "scale": r3(w_scale),
                    }
                )

        elif kind == "asset":
            url = (node.get("asset") or {}).get("url")
            if not url:
                continue
            if legacy_simple_polygons:
                # Render legacy scene monoliths/planters cleanly as simple polygons
                is_planter = "planter" in url.lower() or "planter" in nid.lower() or "growth" in nid.lower()
                add_primitive_visual_and_collider(
                    pid=nid,
                    shape="cylinder" if is_planter else "box",
                    args=[0.9, 1.1, 1.4, 10] if is_planter else [1.6, 5.2, 1.6],
                    world_pos=w_pos,
                    world_quat=w_quat,
                    world_scale=w_scale,
                    origin=world_origin_three,
                    color="#495f41" if is_planter else "#697380",
                    emissive="#1b2b18" if is_planter else "#1e293b",
                    emissive_intensity=0.14,
                    metalness=0.14,
                    roughness=0.88,
                    opacity=1.0,
                    solid=has_collision,
                    primitives_out=primitives,
                    colliders_out=colliders,
                )
            else:
                sim_url = copy_asset_to_simulator(url, level_id)
                rel_pos = [w_pos[0] - world_origin_three[0], w_pos[1] - world_origin_three[1], w_pos[2] - world_origin_three[2]]
                glb_instances.append(
                    {
                        "id": nid,
                        "url": sim_url,
                        "pos": r3(rel_pos),
                        "quat": r3(w_quat, 5),
                        "scale": r3(w_scale),
                    }
                )

        elif kind == "light":
            lt = node.get("light") or {}
            rel_pos = [w_pos[0] - world_origin_three[0], w_pos[1] - world_origin_three[1], w_pos[2] - world_origin_three[2]]
            lights.append(
                {
                    "id": nid,
                    "color": str(lt.get("color", "#cbe4ff")),
                    "intensity": min(4.0, float(lt.get("intensity", 1.5))),
                    "distance": float(lt.get("distance", 28.0)),
                    "pos": r3(rel_pos),
                }
            )

    payload: dict[str, Any] = {
        "schemaVersion": 2,
        "id": level_id,
        "name": name,
        "subtitle": subtitle,
        "worldOriginThree": r3(world_origin_three),
        "skyboxDir": skybox_dir,
        "backgroundHex": background_hex,
        "fogHex": fog_hex,
        "fogDensity": fog_density,
        "useDefaultFloorPlane": False,
        "robotSpawnMj": [0.0, 0.0, 0.066],
        "primitives": primitives,
        "glbInstances": glb_instances,
        "colliders": colliders,
        "lights": lights,
    }
    if water_y_world is not None:
        payload["water"] = {
            "y": round(water_y_world - world_origin_three[1], 4),
            "size": 1200,
            "color": water_color,
            "opacity": 0.88,
        }
    return payload


def export_observatory() -> tuple[dict[str, Any], bytes]:
    manifest = json.loads((MEGAMEAL_PUBLIC / "terrain/observatory-environment.manifest.json").read_text())
    collider_bin = (MEGAMEAL_PUBLIC / "terrain/collision/observatory-environment.collider.bin").read_bytes()
    magic, ver, vcnt, icnt, tcnt, sres, cres, step = struct.unpack_from("<8I", collider_bin, 0)
    assert magic == 0x4D4D5443 and vcnt == 112 * 112

    verts = np.frombuffer(collider_bin, dtype="<f4", count=vcnt * 3, offset=32).reshape(112, 112, 3).astype(np.float64)
    # Verify grid ordering: row = Z ascending (-195.10 -> 194.08), col = X ascending (-199.55 -> 194.00)
    x_coords = verts[0, :, 0]
    z_coords = verts[:, 0, 2]
    y_grid = verts[:, :, 1]  # shape (nz=112, nx=112) where [iz, ix] = height at (x[ix], z[iz])

    spawn_x, spawn_z = -137.2, -49.5
    # Bilinear interpolation of exact ground elevation at (spawn_x, spawn_z)
    ix_f = float(np.interp(spawn_x, x_coords, np.arange(len(x_coords))))
    iz_f = float(np.interp(spawn_z, z_coords, np.arange(len(z_coords))))
    ix0 = max(0, min(110, int(math.floor(ix_f))))
    iz0 = max(0, min(110, int(math.floor(iz_f))))
    tx = ix_f - ix0
    tz = iz_f - iz0
    y00 = y_grid[iz0, ix0]
    y10 = y_grid[iz0, ix0 + 1]
    y01 = y_grid[iz0 + 1, ix0]
    y11 = y_grid[iz0 + 1, ix0 + 1]
    collider_ground_y = float((1 - tx) * (1 - tz) * y00 + tx * (1 - tz) * y10 + (1 - tx) * tz * y01 + tx * tz * y11)
    # Exact visual chunk mesh triangle height at (-137.2, -49.5) in chunk_0_1_LOD0.glb is 0.3406 m.
    # Shift the coarse 112x112 collider vertically by (visual - collider) so visual feet contact matches MuJoCo to <1 mm.
    visual_ground_y = 0.3406
    origin = [spawn_x, visual_ground_y, spawn_z]

    # Build exact MuJoCo binary heightfield (<hfield>) centered around the terrain grid!
    # In MuJoCo, <hfield> has:
    #   size = [radius_x_mj, radius_y_mj, elevation_z_mj, base_z_mj]
    #   data[row * ncol + col] where row indexes MuJoCo +Y (= Three +X!) and col indexes MuJoCo +X (= Three +Z!)
    # Notice our y_grid has shape (nz=112, nx=112), so y_grid.T has shape (nx=112, nz=112) -> (nrow_mjY, ncol_mjX)!
    y_min = float(y_grid.min())
    y_max = float(y_grid.max())
    elev = max(1.0, y_max - y_min)
    hfield_mat = ((y_grid.T - y_min) / elev).astype("<f4")  # shape (nrow=112 [X_three=Y_mj], ncol=112 [Z_three=X_mj])
    hfield_bytes = struct.pack("<2i", 112, 112) + np.ascontiguousarray(hfield_mat).tobytes()

    # Center of terrain grid in Three.js world coordinates -> relative to origin -> MuJoCo coordinates
    cx_three = 0.5 * (float(x_coords[0]) + float(x_coords[-1]))
    cz_three = 0.5 * (float(z_coords[0]) + float(z_coords[-1]))
    rx_three = 0.5 * (float(x_coords[-1]) - float(x_coords[0]))
    rz_three = 0.5 * (float(z_coords[-1]) - float(z_coords[0]))

    # MuJoCo hfield geom pos is the bottom of the elevation band, aligned so (0, 0) lands at z = 0.000
    hfield_pos_mj = [
        round(cz_three - spawn_z, 5),
        round(cx_three - spawn_x, 5),
        round(y_min - collider_ground_y + 0.014, 5),
    ]
    hfield_size_mj = [
        round(rz_three, 5),  # MuJoCo +X half-extent (= Three Z)
        round(rx_three, 5),  # MuJoCo +Y half-extent (= Three X)
        round(elev, 5),      # MuJoCo +Z elevation scale (= Three Y)
        5.0,                 # MuJoCo base thickness below y_min
    ]

    # Copy all 16 Observatory terrain chunks (each 1.7-4.9 MB, lazy-loaded when Observatory is selected)
    glb_instances: list[dict[str, Any]] = []
    chunks = manifest["visualChunks"]["chunks"]
    # Sort chunks nearest to spawn first so spawn courtyard appears almost instantaneously!
    def chunk_dist(ch: dict[str, Any]) -> float:
        bmin = ch["bounds"]["min"]
        bmax = ch["bounds"]["max"]
        cx = 0.5 * (bmin[0] + bmax[0])
        cz = 0.5 * (bmin[2] + bmax[2])
        return math.hypot(cx - spawn_x, cz - spawn_z)

    for ch in sorted(chunks, key=chunk_dist):
        sim_url = copy_asset_to_simulator(ch["url"], "observatory")
        glb_instances.append(
            {
                "id": f"obs_chunk_{ch['x']}_{ch['z']}",
                "url": sim_url,
                "pos": r3([-spawn_x, -visual_ground_y, -spawn_z]),
                "quat": [0, 0, 0, 1],
                "scale": [1, 1, 1],
            }
        )

    payload = {
        "schemaVersion": 2,
        "id": "observatory",
        "name": "Observatory",
        "subtitle": "Chunked coastal stone observatory · 112×112 MuJoCo heightfield terrain",
        "worldOriginThree": r3(origin),
        "skyboxDir": "/assets/skyboxes/observatory",
        "backgroundHex": "#202c40",
        "fogHex": "#596784",
        "fogDensity": 0.0012,
        "useDefaultFloorPlane": False,
        "robotSpawnMj": [0.0, 0.0, 0.066],
        "primitives": [],
        "glbInstances": glb_instances,
        "colliders": [],
        "hfield": {
            "url": "/sim/levels/observatory.hfield.bin",
            "posMj": hfield_pos_mj,
            "sizeMj": hfield_size_mj,
        },
        "lights": [],
        "water": {
            "y": round(-2.0 - visual_ground_y, 4),
            "size": 1600,
            "color": "#050b14",
            "opacity": 0.9,
        },
    }
    return payload, hfield_bytes


def verify_level_spawn_in_mujoco(level_payload: dict[str, Any], hfield_bytes: bytes | None = None) -> None:
    """Drop a 0.05m test sphere at (0, 0, 0.12) in real MuJoCo and verify it settles on z ~= 0.00!"""
    import mujoco

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        asset_xml = ""
        geom_xml = []
        if level_payload.get("useDefaultFloorPlane"):
            geom_xml.append('<geom name="default_floor" type="plane" pos="0 0 0" size="50 50 0.1"/>')
        if level_payload.get("hfield") and hfield_bytes:
            hf = level_payload["hfield"]
            hf_path = tmp_dir / "terrain.hfield"
            hf_path.write_bytes(hfield_bytes)
            sx, sy, sz, sb = hf["sizeMj"]
            px, py, pz = hf["posMj"]
            asset_xml = f'<asset><hfield name="lvl_hf" file="{hf_path}" size="{sx} {sy} {sz} {sb}"/></asset>'
            geom_xml.append(f'<geom name="lvl_hf_geom" type="hfield" hfield="lvl_hf" pos="{px} {py} {pz}"/>')
        for idx, col in enumerate(level_payload.get("colliders") or []):
            px, py, pz = col["posMj"]
            qw, qx, qy, qz = col["quatMj"]
            if col["shape"] == "box":
                hx, hy, hz = col["sizeMj"]
                geom_xml.append(
                    f'<geom name="c_{idx}" type="box" pos="{px} {py} {pz}" quat="{qw} {qx} {qy} {qz}" size="{hx} {hy} {hz}"/>'
                )
            elif col["shape"] == "cylinder":
                rad, hh = col["sizeMj"]
                geom_xml.append(
                    f'<geom name="c_{idx}" type="cylinder" pos="{px} {py} {pz}" quat="{qw} {qx} {qy} {qz}" size="{rad} {hh}"/>'
                )

        xml = f"""
        <mujoco>
          <option timestep="0.002" gravity="0 0 -9.81"/>
          {asset_xml}
          <worldbody>
            <geom name="safety_floor" type="plane" pos="0 0 -200" size="500 500 0.1"/>
            {"".join(geom_xml)}
            <body name="probe" pos="0 0 0.12">
              <freejoint/>
              <geom type="sphere" size="0.02" mass="0.5"/>
            </body>
          </worldbody>
        </mujoco>
        """
        m = mujoco.MjModel.from_xml_string(xml)
        d = mujoco.MjData(m)
        for _ in range(400):
            mujoco.mj_step(m, d)
        z_surface = float(d.qpos[2]) - 0.02
        print(
            f"  [MuJoCo Drop Check] {level_payload['id']:12s}: surface_z={z_surface:+.4f}m "
            f"(ncon={d.ncon}, colliders={len(level_payload.get('colliders') or [])}, "
            f"prims={len(level_payload.get('primitives') or [])}, glbs={len(level_payload.get('glbInstances') or [])})"
        )
        if abs(z_surface) > 0.06:
            raise RuntimeError(
                f"Spawn surface check FAILED for {level_payload['id']}: landed at z={z_surface:+.4f}m (expected ~0.00m)!"
            )


def main() -> int:
    OUT_LEVELS_DIR.mkdir(parents=True, exist_ok=True)
    OUT_ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    prefab_catalog = json.loads(PREFAB_CATALOG_PATH.read_text())

    # 0. Robotics Lab (Flagship default proving ground & autonomous vision obstacle course)
    lab_payload = build_robotics_lab_level()
    (OUT_LEVELS_DIR / "v2-lab.level.json").write_text(
        json.dumps(lab_payload, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    verify_level_spawn_in_mujoco(lab_payload)

    # 1. Observatory (real chunked terrain + 112x112 MuJoCo hfield)
    obs_payload, obs_hf_bytes = export_observatory()
    (OUT_LEVELS_DIR / "observatory.hfield.bin").write_bytes(obs_hf_bytes)
    (OUT_LEVELS_DIR / "observatory.level.json").write_text(
        json.dumps(obs_payload, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    verify_level_spawn_in_mujoco(obs_payload, obs_hf_bytes)

    # 2. Yggdrasil — Rebuilt low-poly Norse Tree-of-Life Island & Robot Obstacle Course
    ygg_payload = build_yggdrasil_level()
    (OUT_LEVELS_DIR / "yggdrasil.level.json").write_text(
        json.dumps(ygg_payload, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    verify_level_spawn_in_mujoco(ygg_payload)

    # 3. Miranda Wreck — Rebuilt Derelict Cosmic-Horror Starship & Dying Star Obstacle Course
    miranda_payload = build_miranda_level()
    (OUT_LEVELS_DIR / "miranda.level.json").write_text(
        json.dumps(miranda_payload, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    verify_level_spawn_in_mujoco(miranda_payload)

    # 4. Solitude — Rebuilt Rolling Grassy Stonehenge Plain & Single Firefly (0 heavy GLBs!)
    sol_payload, sol_hf_bytes = build_solitude_level()
    (OUT_LEVELS_DIR / "solitude.hfield.bin").write_bytes(sol_hf_bytes)
    (OUT_LEVELS_DIR / "solitude.level.json").write_text(
        json.dumps(sol_payload, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    verify_level_spawn_in_mujoco(sol_payload, sol_hf_bytes)

    # 5. Sci Fi Room — Rebuilt Surreal Far-Future Astral House (0 heavy GLBs!)
    sfr_payload = build_scifi_room_level()
    (OUT_LEVELS_DIR / "sci-fi-room.level.json").write_text(
        json.dumps(sfr_payload, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    verify_level_spawn_in_mujoco(sfr_payload)

    print("All 5 original levels exported & verified in MuJoCo!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
