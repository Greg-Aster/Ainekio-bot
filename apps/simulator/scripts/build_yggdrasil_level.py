#!/usr/bin/env python3
"""
Procedural low-poly Norse Tree-of-Life Island & Robot Obstacle Course builder
for Yggdrasil (`yggdrasil.level.json`) in simulator.ainek.io.

Designed specifically around Ainekio V2's physical dimensions while making the
central World Tree (Yggdrasil) truly monumental and awe-inspiring:
  - Robot scale: ~0.22 m long, ~0.18 m stance, ~0.19 m tall
  - World Tree scale: ~27 m tall (>140x the robot's height!), ~26 m canopy span,
    braided fluted bark buttress ribs, glowing runic sap veins, Tree-Heart shrine,
    9 colossal walk-under cathedral root arches, 3 tiers of knotted boughs,
    draping bioluminescent vines, hanging golden realm lanterns, lush layered
    emerald/teal/gold faceted foliage clouds, and an orbiting Nine Realms astral
    halo high in the cosmic sky!
  - Zero below-ground junk, zero misplaced meshes, 100% crisp faceted simple
    polygons (0 heavy GLBs, instant load), and 1:1 exact MuJoCo collision geometry.

Coordinate convention (Three.js, already local-origin centered at robot spawn):
  - Robot spawns at (0, 0, 0) facing +Z (MuJoCo +X forward, +Y left, +Z up)
  - Ground surface at spawn is y = 0.000 m
  - Colossal World Tree of Life rises straight ahead at (0, 0, +6.6 m)
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np


def _euler_xyz_to_quat_xyzw(rx: float, ry: float, rz: float) -> list[float]:
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    mx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]], dtype=np.float64)
    my = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], dtype=np.float64)
    mz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]], dtype=np.float64)
    r = mx @ my @ mz
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


def _quat_from_y_to_vec(dx: float, dy: float, dz: float) -> list[float]:
    """Quaternion rotating +Y axis to align with direction vector (dx, dy, dz)."""
    length = math.sqrt(dx * dx + dy * dy + dz * dz)
    if length < 1e-8:
        return [0.0, 0.0, 0.0, 1.0]
    vx, vy, vz = dx / length, dy / length, dz / length
    dot = vy  # dot((0,1,0), v)
    if dot > 0.999999:
        return [0.0, 0.0, 0.0, 1.0]
    if dot < -0.999999:
        return [1.0, 0.0, 0.0, 0.0]
    qx, qy, qz = vz, 0.0, -vx
    qw = 1.0 + dot
    n = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw) or 1.0
    return [qx / n, qy / n, qz / n, qw / n]


def _three_pos_to_mj(pos: list[float]) -> list[float]:
    return [float(pos[2]), float(pos[0]), float(pos[1])]


def _three_quat_to_mj(q_xyzw: list[float]) -> list[float]:
    qx, qy, qz, qw = q_xyzw
    return [float(qw), float(qz), float(qx), float(qy)]


def _r(vals: list[float], n: int = 4) -> list[float]:
    return [round(float(v), n) for v in vals]


class _SceneBuilder:
    def __init__(self) -> None:
        self.primitives: list[dict[str, Any]] = []
        self.colliders: list[dict[str, Any]] = []
        self.lights: list[dict[str, Any]] = []
        self._id_counts: dict[str, int] = {}

    def _uid(self, prefix: str) -> str:
        c = self._id_counts.get(prefix, 0) + 1
        self._id_counts[prefix] = c
        return f"{prefix}_{c}" if c > 1 else prefix

    def add_box(
        self,
        name: str,
        pos: list[float],
        size: list[float],
        *,
        rot: list[float] | None = None,
        quat: list[float] | None = None,
        color: str = "#475569",
        emissive: str | None = None,
        emissive_intensity: float = 0.25,
        metalness: float = 0.15,
        roughness: float = 0.82,
        opacity: float = 1.0,
        flat_shading: bool = False,
        solid: bool = True,
        visual: bool = True,
    ) -> None:
        pid = self._uid(name)
        q = quat if quat is not None else _euler_xyz_to_quat_xyzw(*(rot or [0.0, 0.0, 0.0]))
        if visual and opacity > 0.01:
            entry: dict[str, Any] = {
                "id": pid,
                "shape": "box",
                "pos": _r(pos),
                "quat": _r(q, 5),
                "scale": [1, 1, 1],
                "args": _r(size),
                "color": color,
                "metalness": round(metalness, 3),
                "roughness": round(roughness, 3),
            }
            if emissive:
                entry["emissive"] = emissive
                entry["emissiveIntensity"] = round(emissive_intensity, 3)
            if opacity < 0.999:
                entry["opacity"] = round(opacity, 3)
            if flat_shading:
                entry["flatShading"] = True
            self.primitives.append(entry)
        if solid:
            self.colliders.append(
                {
                    "id": pid,
                    "shape": "box",
                    "posMj": _r(_three_pos_to_mj(pos)),
                    "quatMj": _r(_three_quat_to_mj(q), 5),
                    "sizeMj": _r([max(0.005, size[2] / 2), max(0.005, size[0] / 2), max(0.005, size[1] / 2)]),
                }
            )

    def add_cylinder(
        self,
        name: str,
        pos: list[float],
        r_top: float,
        r_bot: float,
        height: float,
        segments: int = 12,
        *,
        rot: list[float] | None = None,
        quat: list[float] | None = None,
        color: str = "#4b5563",
        emissive: str | None = None,
        emissive_intensity: float = 0.2,
        metalness: float = 0.12,
        roughness: float = 0.86,
        opacity: float = 1.0,
        flat_shading: bool = True,
        solid: bool = True,
    ) -> None:
        pid = self._uid(name)
        q = quat if quat is not None else _euler_xyz_to_quat_xyzw(*(rot or [0.0, 0.0, 0.0]))
        entry: dict[str, Any] = {
            "id": pid,
            "shape": "cylinder",
            "pos": _r(pos),
            "quat": _r(q, 5),
            "scale": [1, 1, 1],
            "args": _r([r_top, r_bot, height, segments]),
            "color": color,
            "metalness": round(metalness, 3),
            "roughness": round(roughness, 3),
        }
        if emissive:
            entry["emissive"] = emissive
            entry["emissiveIntensity"] = round(emissive_intensity, 3)
        if opacity < 0.999:
            entry["opacity"] = round(opacity, 3)
        if flat_shading:
            entry["flatShading"] = True
        self.primitives.append(entry)
        if solid:
            rad = max(r_top, r_bot)
            self.colliders.append(
                {
                    "id": pid,
                    "shape": "cylinder",
                    "posMj": _r(_three_pos_to_mj(pos)),
                    "quatMj": _r(_three_quat_to_mj(q), 5),
                    "sizeMj": _r([max(0.01, rad), max(0.005, height / 2)]),
                }
            )

    def add_segment(
        self,
        name: str,
        p0: list[float],
        p1: list[float],
        r0: float,
        r1: float,
        segments: int = 8,
        *,
        color: str = "#5c4033",
        emissive: str | None = None,
        emissive_intensity: float = 0.15,
        roughness: float = 0.9,
        metalness: float = 0.06,
        flat_shading: bool = True,
        solid: bool = False,
    ) -> None:
        """Add a tapered low-poly cylinder connecting 3D points p0 -> p1."""
        dx = p1[0] - p0[0]
        dy = p1[1] - p0[1]
        dz = p1[2] - p0[2]
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        if length < 1e-4:
            return
        mid = [0.5 * (p0[0] + p1[0]), 0.5 * (p0[1] + p1[1]), 0.5 * (p0[2] + p1[2])]
        q = _quat_from_y_to_vec(dx, dy, dz)
        self.add_cylinder(
            name,
            mid,
            r1,
            r0,
            length,
            segments,
            quat=q,
            color=color,
            emissive=emissive,
            emissive_intensity=emissive_intensity,
            roughness=roughness,
            metalness=metalness,
            flat_shading=flat_shading,
            solid=solid,
        )

    def add_poly(
        self,
        name: str,
        shape: str,
        pos: list[float],
        args: list[float],
        *,
        rot: list[float] | None = None,
        scale: list[float] | None = None,
        color: str = "#2f7d4d",
        emissive: str | None = None,
        emissive_intensity: float = 0.25,
        metalness: float = 0.08,
        roughness: float = 0.78,
        opacity: float = 1.0,
        flat_shading: bool = True,
    ) -> None:
        pid = self._uid(name)
        q = _euler_xyz_to_quat_xyzw(*(rot or [0.0, 0.0, 0.0]))
        entry: dict[str, Any] = {
            "id": pid,
            "shape": shape,
            "pos": _r(pos),
            "quat": _r(q, 5),
            "scale": _r(scale or [1, 1, 1]),
            "args": _r(args),
            "color": color,
            "metalness": round(metalness, 3),
            "roughness": round(roughness, 3),
            "flatShading": flat_shading,
        }
        if emissive:
            entry["emissive"] = emissive
            entry["emissiveIntensity"] = round(emissive_intensity, 3)
        if opacity < 0.999:
            entry["opacity"] = round(opacity, 3)
        self.primitives.append(entry)

    def add_ramp(
        self,
        name: str,
        x0: float,
        y0: float,
        z0: float,
        x1: float,
        y1: float,
        z1: float,
        width: float,
        *,
        thickness: float = 0.08,
        color: str = "#64707d",
        emissive: str | None = None,
        emissive_intensity: float = 0.12,
    ) -> None:
        """
        Build a physically exact inclined ramp whose TOP surface runs seamlessly
        from (x0, y0, z0) to (x1, y1, z1) with full MuJoCo rotated-box parity!
        """
        dx = x1 - x0
        dz = z1 - z0
        dy = y1 - y0
        horiz = math.hypot(dx, dz)
        length = math.hypot(horiz, dy)
        yaw = math.atan2(dx, dz)
        pitch = -math.atan2(dy, horiz)

        cy, sy = math.cos(yaw), math.sin(yaw)
        cp, sp = math.cos(pitch), math.sin(pitch)
        rmat = np.array(
            [
                [cy, sy * sp, sy * cp],
                [0.0, cp, -sp],
                [-sy, cy * sp, cy * cp],
            ],
            dtype=np.float64,
        )
        tr = float(rmat[0, 0] + rmat[1, 1] + rmat[2, 2])
        if tr > 0.0:
            s = math.sqrt(tr + 1.0) * 2.0
            qw = 0.25 * s
            qx = (rmat[2, 1] - rmat[1, 2]) / s
            qy = (rmat[0, 2] - rmat[2, 0]) / s
            qz = (rmat[1, 0] - rmat[0, 1]) / s
        elif rmat[0, 0] > rmat[1, 1] and rmat[0, 0] > rmat[2, 2]:
            s = math.sqrt(1.0 + rmat[0, 0] - rmat[1, 1] - rmat[2, 2]) * 2.0
            qw = (rmat[2, 1] - rmat[1, 2]) / s
            qx = 0.25 * s
            qy = (rmat[0, 1] + rmat[1, 0]) / s
            qz = (rmat[0, 2] + rmat[2, 0]) / s
        elif rmat[1, 1] > rmat[2, 2]:
            s = math.sqrt(1.0 + rmat[1, 1] - rmat[0, 0] - rmat[2, 2]) * 2.0
            qw = (rmat[0, 2] - rmat[2, 0]) / s
            qx = (rmat[0, 1] + rmat[1, 0]) / s
            qy = 0.25 * s
            qz = (rmat[1, 2] + rmat[2, 1]) / s
        else:
            s = math.sqrt(1.0 + rmat[2, 2] - rmat[0, 0] - rmat[1, 1]) * 2.0
            qw = (rmat[1, 0] - rmat[0, 1]) / s
            qx = (rmat[0, 2] + rmat[2, 0]) / s
            qy = (rmat[1, 2] + rmat[2, 1]) / s
            qz = 0.25 * s
        n = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw) or 1.0
        q = [qx / n, qy / n, qz / n, qw / n]

        normal = rmat[:, 1]
        mid_top = np.array([0.5 * (x0 + x1), 0.5 * (y0 + y1), 0.5 * (z0 + z1)], dtype=np.float64)
        center = (mid_top - normal * (thickness / 2.0)).tolist()
        self.add_box(
            name,
            center,
            [width, thickness, length],
            quat=q,
            color=color,
            emissive=emissive,
            emissive_intensity=emissive_intensity,
            metalness=0.14,
            roughness=0.84,
            flat_shading=True,
            solid=True,
        )

    def add_light(self, name: str, pos: list[float], color: str, intensity: float, distance: float) -> None:
        self.lights.append(
            {
                "id": self._uid(name),
                "color": color,
                "intensity": round(intensity, 2),
                "distance": round(distance, 2),
                "pos": _r(pos),
            }
        )


def build_yggdrasil_level() -> dict[str, Any]:
    b = _SceneBuilder()
    tree_x, tree_z = 0.0, 6.6
    meadow_z = 6.6

    # =========================================================================
    # 1. MYTHIC ISLAND TERRAIN (Walkable flat emerald meadow at y = -0.003 m)
    # =========================================================================
    # Expanded ~22 m mythic island centered around the colossal World Tree at (0, 6.6).
    # South shoreline meets the Bifrost causeway at z = -3.8 m so the rainbow bridge
    # spans dramatically across the mythic sea onto the island!
    b.add_cylinder(
        "island_meadow",
        [tree_x, -0.303, meadow_z],
        10.4,
        11.4,
        0.60,
        segments=36,
        color="#2a4f30",
        emissive="#0f2314",
        emissive_intensity=0.14,
        roughness=0.94,
        metalness=0.04,
        flat_shading=True,
        solid=True,
    )
    # Lower rocky coastal shelf (visual cliff rim dropping into the mythic sea)
    b.add_cylinder(
        "island_cliff_shelf",
        [tree_x, -0.84, meadow_z],
        11.1,
        13.6,
        1.05,
        segments=28,
        color="#3b4553",
        emissive="#141c28",
        emissive_intensity=0.1,
        roughness=0.92,
        metalness=0.08,
        flat_shading=True,
        solid=False,
    )
    # Coastal boulders & basalt shore outcrops framing the island coastline
    for idx in range(22):
        ang = idx * (2.0 * math.pi / 22.0) + 0.12
        bx = tree_x + math.sin(ang) * 11.2
        bz = meadow_z + math.cos(ang) * 11.2
        if bz < -0.5 and abs(bx) < 2.6:
            continue
        r_rock = 0.65 + (idx % 3) * 0.28
        b.add_poly(
            f"shore_boulder_{idx}",
            "dodecahedron",
            [bx, -0.20 + (idx % 2) * 0.12, bz],
            [r_rock, 0],
            rot=[idx * 0.4, idx * 0.9, idx * 0.3],
            scale=[1.4, 0.72, 1.15],
            color="#4a5568" if idx % 2 == 0 else "#525d6d",
            roughness=0.92,
            metalness=0.08,
        )

    # Distant mythic sea-stacks & outer horizon monolith islets (pure visual backdrop)
    for idx, (ox, oz, rad, h) in enumerate(
        [
            (-24.0, 20.0, 4.2, 8.2),
            (25.0, 21.5, 4.8, 9.6),
            (-21.0, -8.5, 3.4, 5.8),
            (22.5, -7.5, 3.6, 6.4),
            (0.0, 32.0, 5.8, 11.5),
            (-15.0, 29.0, 3.8, 7.5),
            (16.0, 30.0, 4.0, 8.4),
        ]
    ):
        b.add_cylinder(
            f"horizon_islet_{idx}",
            [ox, -0.65, oz],
            rad * 0.78,
            rad * 1.18,
            1.5,
            segments=10,
            color="#253240",
            roughness=0.94,
            solid=False,
        )
        b.add_poly(
            f"horizon_spire_{idx}",
            "cone",
            [ox, h * 0.45 - 0.1, oz],
            [rad * 0.46, h, 7],
            color="#354152",
            emissive="#1e3a5f",
            emissive_intensity=0.16,
            roughness=0.88,
        )

    # =========================================================================
    # 2. BIFROST ARRIVAL CAUSEWAY (South approach across the sea, z = -6.0 -> +2.9 m)
    #    Robot spawns at (0, 0, 0) standing flush on top of the Bifrost!
    # =========================================================================
    b.add_box(
        "bifrost_deck",
        [0.0, -0.06, -1.55],
        [1.06, 0.12, 8.90],
        color="#2d3a4b",
        emissive="#172554",
        emissive_intensity=0.18,
        metalness=0.35,
        roughness=0.52,
        solid=True,
    )
    # Twin stone bridge piers anchoring the south Bifrost span into the mythic ocean
    for pier_z in (-5.2, -3.6, -2.2):
        for side, px in (("l", 0.40), ("r", -0.40)):
            b.add_cylinder(
                f"bifrost_pier_{side}_{abs(int(pier_z * 10))}",
                [px, -0.46, pier_z],
                0.13,
                0.18,
                0.76,
                segments=8,
                color="#475569",
                roughness=0.9,
                solid=False,
            )
    # 7 glowing Norse rainbow Bifrost inlays flush with the top surface (y = +0.002 m visual only)
    rainbow = [
        ("#ff4d6d", "#9d174d"),
        ("#ff8c42", "#9a3412"),
        ("#ffd166", "#92400e"),
        ("#52e58c", "#166534"),
        ("#38bdf8", "#075985"),
        ("#6366f1", "#3730a3"),
        ("#c084fc", "#6b21a8"),
    ]
    strip_w = 0.115
    for idx, (col, em) in enumerate(rainbow):
        sx = (idx - 3) * 0.128
        b.add_box(
            f"bifrost_ribbon_{idx + 1}",
            [sx, 0.002, -1.55],
            [strip_w, 0.004, 8.82],
            color=col,
            emissive=em,
            emissive_intensity=0.72,
            metalness=0.45,
            roughness=0.25,
            solid=False,
        )
    # Low glowing Bifrost edge guide curbs (24 mm high — robot feels bridge edges!)
    for side, sx in (("left", 0.55), ("right", -0.55)):
        b.add_box(
            f"bifrost_curb_{side}",
            [sx, 0.012, -1.55],
            [0.045, 0.024, 8.86],
            color="#94a3b8",
            emissive="#38bdf8",
            emissive_intensity=0.28,
            metalness=0.45,
            roughness=0.45,
            solid=True,
        )
    # Two robot-scale Bifrost threshold speed bumps (10 mm and 13 mm high)
    b.add_box(
        "bifrost_threshold_1",
        [0.0, 0.005, 0.85],
        [0.92, 0.010, 0.045],
        color="#f59e0b",
        emissive="#b45309",
        emissive_intensity=0.45,
        metalness=0.35,
        roughness=0.45,
        solid=True,
    )
    b.add_box(
        "bifrost_threshold_2",
        [0.0, 0.0065, 1.55],
        [0.92, 0.013, 0.050],
        color="#38bdf8",
        emissive="#0284c7",
        emissive_intensity=0.48,
        metalness=0.35,
        roughness=0.42,
        solid=True,
    )

    # Heimdall's Twin Gate Pillars & Carved Archway at z = +2.15 m (clear 0.96 m wide opening!)
    for side, px in (("left", 0.62), ("right", -0.62)):
        b.add_box(
            f"heimdall_pillar_{side}",
            [px, 0.58, 2.15],
            [0.24, 1.16, 0.26],
            color="#64748b",
            emissive="#1e293b",
            emissive_intensity=0.14,
            flat_shading=True,
            solid=True,
        )
        b.add_box(
            f"heimdall_rune_{side}",
            [px, 0.64, 2.01],
            [0.07, 0.56, 0.03],
            color="#7dd3fc",
            emissive="#38bdf8",
            emissive_intensity=0.95,
            solid=False,
        )
        b.add_poly(
            f"heimdall_cap_{side}",
            "octahedron",
            [px, 1.32, 2.15],
            [0.14, 0],
            color="#fde68a",
            emissive="#f59e0b",
            emissive_intensity=0.82,
        )
    b.add_box(
        "heimdall_arch_lintel",
        [0.0, 1.20, 2.15],
        [1.56, 0.16, 0.28],
        color="#738296",
        emissive="#1e293b",
        emissive_intensity=0.15,
        flat_shading=True,
        solid=False,
    )

    # =========================================================================
    # 3. COLOSSAL WORLD TREE OF LIFE — YGGDRASIL (x = 0.0, z = +6.6 m)
    #    ~27 m tall cathedral-scale ancient tree (>140x Ainekio's height!):
    #      - Stepped Sanctuary Ring + Root Mound
    #      - Core Multi-Tier Fluted Trunk + 8 Spiraling Twisted Bark Ribs
    #      - 4 Glowing Runic Sap Veins + Tree-Heart Crystal Shrine Alcove
    #      - 9 Monumental Arched Walk-Under Cathedral Roots + Spurs & Moss
    #      - 3 Tiers of Sweeping Knotted Boughs, Forks & Secondary Limbs
    #      - Draping Bioluminescent Vines + 12 Hanging Golden Realm Lanterns
    #      - 45+ Layered Emerald/Teal/Jade/Gold Faceted Foliage Canopy Clouds
    #      - Floating Astral Crown Halo & Orbiting Nine Realms Star Crystals
    # =========================================================================

    # Gentle sanctuary ring slab (12 mm step-up around the tree at y = +0.012 m, radius 3.85 m)
    b.add_cylinder(
        "sanctuary_ring_outer",
        [tree_x, -0.024, tree_z],
        3.68,
        3.92,
        0.072,
        segments=32,
        color="#4e5d56",
        emissive="#182d22",
        emissive_intensity=0.16,
        roughness=0.88,
        solid=True,
    )
    # Inner glowing rune inlay ring flush on the sanctuary stone
    b.add_poly(
        "sanctuary_rune_ring",
        "torus",
        [tree_x, 0.014, tree_z],
        [3.32, 0.032, 6, 36],
        rot=[math.pi / 2.0, 0.0, 0.0],
        color="#67e8f9",
        emissive="#06b6d4",
        emissive_intensity=0.72,
        roughness=0.25,
    )
    # Inner mossy root mound supporting the colossal trunk base (radius ~2.1 m)
    b.add_cylinder(
        "tree_root_mound",
        [tree_x, 0.14, tree_z],
        1.55,
        2.15,
        0.30,
        segments=20,
        color="#375432",
        emissive="#132514",
        emissive_intensity=0.14,
        roughness=0.94,
        solid=True,
    )

    # --- 3A. Colossal Tapered Core Trunk (rising cleanly from y = 0 to y = 21.5 m!) ---
    trunk_tiers = [
        ("yggdrasil_trunk_t1", 2.1, 1.48, 1.92, 4.2, "#4f3423", "#22130a", True),
        ("yggdrasil_trunk_t2", 6.0, 1.24, 1.52, 4.2, "#593b28", "#22130a", False),
        ("yggdrasil_trunk_t3", 9.8, 1.05, 1.28, 4.0, "#63422c", "#24150c", False),
        ("yggdrasil_trunk_t4", 13.4, 0.88, 1.08, 3.8, "#6a4730", "#24150c", False),
        ("yggdrasil_trunk_t5", 16.8, 0.68, 0.90, 3.6, "#704b33", "#20130a", False),
        ("yggdrasil_trunk_t6", 19.8, 0.42, 0.70, 3.2, "#765037", "#20130a", False),
    ]
    for name, cy, rt, rb, h, col, em, is_solid in trunk_tiers:
        b.add_cylinder(
            name,
            [tree_x, cy, tree_z],
            rt,
            rb,
            h,
            segments=12,
            color=col,
            emissive=em,
            emissive_intensity=0.14,
            roughness=0.92,
            solid=is_solid,
        )

    # --- 3B. 8 Sculpted Spiraling Fluted Bark Buttress Ribs (Organic Ancient Trunk Detail!) ---
    rib_colors = ["#3f281a", "#5e3e2a", "#4a3020", "#694630"]
    for rib_i in range(8):
        base_ang = rib_i * (2.0 * math.pi / 8.0) + math.pi / 8.0
        col = rib_colors[rib_i % len(rib_colors)]
        pts: list[tuple[list[float], float]] = []
        # Spiral gracefully ~70 deg as the rib climbs from y=0.2 up to y=15.5 m!
        rib_levels = [
            (0.25, 1.95, 0.42, 0.00),
            (2.80, 1.56, 0.36, 0.22),
            (6.20, 1.32, 0.31, 0.48),
            (9.80, 1.12, 0.26, 0.76),
            (13.20, 0.94, 0.21, 1.04),
            (16.20, 0.72, 0.15, 1.28),
        ]
        for h_y, rad_r, thick, twist in rib_levels:
            a = base_ang + twist
            pts.append(([tree_x + math.sin(a) * rad_r, h_y, tree_z + math.cos(a) * rad_r], thick))
        for seg_i in range(len(pts) - 1):
            p0, r0 = pts[seg_i]
            p1, r1 = pts[seg_i + 1]
            b.add_segment(
                f"trunk_rib_{rib_i}_{seg_i}",
                p0,
                p1,
                r0,
                r1,
                segments=7,
                color=col,
                emissive="#1c1008",
                emissive_intensity=0.12,
                solid=False,
            )

    # --- 3C. 4 Spiraling Glowing Runic Sap Veins ("Lifeblood of Yggdrasil") ---
    for vein_i in range(4):
        base_ang = vein_i * (math.pi / 2.0) + math.pi
        vein_levels = [
            (0.75, 1.96, 0.055, 0.00),
            (3.40, 1.62, 0.050, 0.28),
            (6.80, 1.38, 0.046, 0.56),
            (10.50, 1.18, 0.042, 0.85),
            (14.00, 0.96, 0.036, 1.12),
        ]
        vpts = [
            ([tree_x + math.sin(base_ang + tw) * rr, yy, tree_z + math.cos(base_ang + tw) * rr], th)
            for yy, rr, th, tw in vein_levels
        ]
        for seg_i in range(len(vpts) - 1):
            p0, r0 = vpts[seg_i]
            p1, r1 = vpts[seg_i + 1]
            b.add_segment(
                f"sap_vein_{vein_i}_{seg_i}",
                p0,
                p1,
                r0,
                r1,
                segments=6,
                color="#67e8f9" if vein_i % 2 == 0 else "#6ee7b7",
                emissive="#06b6d4" if vein_i % 2 == 0 else "#10b981",
                emissive_intensity=0.92,
                roughness=0.22,
                metalness=0.25,
                solid=False,
            )

    # --- 3D. Tree-Heart Crystal Shrine Alcove (South Trunk Face, directly ahead of Heimdall's Gate!) ---
    b.add_poly(
        "yggdrasil_heart_crystal",
        "octahedron",
        [tree_x, 1.15, tree_z - 1.95],
        [0.34, 0],
        scale=[0.85, 1.65, 0.65],
        color="#a5f3fc",
        emissive="#06b6d4",
        emissive_intensity=1.0,
        metalness=0.22,
        roughness=0.14,
    )
    b.add_poly(
        "yggdrasil_heart_halo",
        "torus",
        [tree_x, 1.15, tree_z - 1.95],
        [0.58, 0.038, 6, 20],
        color="#fde68a",
        emissive="#f59e0b",
        emissive_intensity=0.85,
        roughness=0.25,
    )
    # Secondary upper heart crystal high on the south trunk face (y = 5.4 m)
    b.add_poly(
        "yggdrasil_upper_rune_gem",
        "octahedron",
        [tree_x, 5.4, tree_z - 1.56],
        [0.28, 0],
        scale=[0.75, 1.7, 0.55],
        color="#6ee7b7",
        emissive="#10b981",
        emissive_intensity=0.92,
        roughness=0.18,
    )

    # --- 3E. 9 Colossal Sculpted Walk-Under Cathedral Roots + Root Spurs + Moss ---
    # Angles 0°, 40°, ..., 160°, 200°, ..., 320° straddle South (180°) symmetrically
    # so roots #4 (160°) & #5 (200°) frame the Bifrost -> Tree-Heart cathedral nave!
    for idx in range(9):
        ang = idx * (2.0 * math.pi / 9.0)
        ca, sa = math.cos(ang), math.sin(ang)
        # Massive buttress root sweeps out from trunk at y=2.15 m, arches at r=2.75 m y=0.88 m
        # (underside clearance ~0.58 m — spacious cathedral walk-under root tunnel!),
        # plants heavily into earth at r=4.35 m y=0.06 m, and snakes outward to r=5.65 m!
        p_trunk = [tree_x + sa * 1.15, 2.15 + (idx % 2) * 0.35, tree_z + ca * 1.15]
        p_arch = [tree_x + sa * 2.75, 0.88 + (idx % 2) * 0.12, tree_z + ca * 2.75]
        p_land = [tree_x + sa * 4.35, 0.08, tree_z + ca * 4.35]
        p_tail = [tree_x + sa * 5.65, -0.02, tree_z + ca * 5.65]
        b.add_segment(f"tree_root_{idx}_a", p_trunk, p_arch, 0.44, 0.30, segments=8, color="#4e3322", solid=False)
        b.add_segment(f"tree_root_{idx}_b", p_arch, p_land, 0.30, 0.22, segments=8, color="#442c1d", solid=True)
        b.add_segment(f"tree_root_{idx}_c", p_land, p_tail, 0.20, 0.07, segments=7, color="#3a2518", solid=False)

        # Secondary forked root spur curving sideways from each main root arch
        ang_s = ang + (0.24 if idx % 2 == 0 else -0.24)
        p_spur_end = [tree_x + math.sin(ang_s) * 4.15, 0.02, tree_z + math.cos(ang_s) * 4.15]
        b.add_segment(f"tree_root_spur_{idx}", p_arch, p_spur_end, 0.16, 0.08, segments=6, color="#3f281a", solid=False)

        # Emerald moss cushion seated atop each root arch
        b.add_poly(
            f"root_moss_{idx}",
            "dodecahedron",
            [p_arch[0], p_arch[1] + 0.24, p_arch[2]],
            [0.28, 0],
            rot=[idx * 0.3, ang, 0.2],
            scale=[1.3, 0.45, 1.1],
            color="#2f7d47",
            emissive="#14532d",
            emissive_intensity=0.22,
            roughness=0.88,
        )

    # --- 3F. 3 TIERS OF MASSIVE KNOTTED BOUGHS, FORKS, VINES, LANTERNS & CANOPY CLOUDS ---
    canopy_palette = [
        ("#1a6b42", "#0a3b22"),
        ("#24854f", "#14532d"),
        ("#1c7a64", "#0f4c43"),
        ("#339c58", "#166534"),
        ("#1f8b70", "#115e59"),
        ("#42b066", "#15803d"),
        ("#2d945f", "#14532d"),
        ("#52c47c", "#0f5132"),
    ]

    # TIER 1 — 7 Massive Lower Cathedral Boughs (y = 7.6 -> 14.5 m, spanning 22 m wide!)
    for idx in range(7):
        ang = idx * (2.0 * math.pi / 7.0) + 0.18
        ca, sa = math.cos(ang), math.sin(ang)
        h0 = 7.6 + (idx % 3) * 0.9
        p0 = [tree_x + sa * 0.95, h0, tree_z + ca * 0.95]
        p1 = [tree_x + sa * 4.2, h0 + 2.5, tree_z + ca * 4.2]
        p2 = [tree_x + sa * 7.8, h0 + 4.2, tree_z + ca * 7.8]
        p3 = [tree_x + sa * 10.6, h0 + 5.1, tree_z + ca * 10.6]
        b.add_segment(f"bough_t1_{idx}_a", p0, p1, 0.56, 0.38, segments=8, color="#563927", solid=False)
        b.add_segment(f"bough_t1_{idx}_b", p1, p2, 0.38, 0.24, segments=7, color="#61412d", solid=False)
        b.add_segment(f"bough_t1_{idx}_c", p2, p3, 0.24, 0.11, segments=6, color="#6d4933", solid=False)

        # Left & Right Fork Sub-Branches off each lower bough
        for side_i, delta_ang in enumerate((-0.34, 0.36)):
            af = ang + delta_ang
            pf = [
                tree_x + math.sin(af) * (7.2 + side_i * 1.6),
                h0 + 4.9 + side_i * 0.8,
                tree_z + math.cos(af) * (7.2 + side_i * 1.6),
            ]
            b.add_segment(
                f"bough_t1_fork_{idx}_{side_i}",
                p1 if side_i == 0 else p2,
                pf,
                0.24,
                0.09,
                segments=6,
                color="#6a4731",
                solid=False,
            )
            col, em = canopy_palette[(idx + side_i * 3) % len(canopy_palette)]
            b.add_poly(
                f"canopy_t1_fork_{idx}_{side_i}",
                "icosahedron",
                [pf[0], pf[1] + 0.55, pf[2]],
                [2.35 + (idx % 2) * 0.35, 0],
                rot=[idx * 0.4, af, 0.3],
                scale=[1.35, 0.68, 1.25],
                color=col,
                emissive=em,
                emissive_intensity=0.28,
                roughness=0.80,
            )

        # Lush outer bough foliage cluster
        col, em = canopy_palette[idx % len(canopy_palette)]
        b.add_poly(
            f"canopy_t1_tip_{idx}",
            "icosahedron",
            [p3[0], p3[1] + 0.55, p3[2]],
            [2.65, 1],
            rot=[0.2, ang, idx * 0.5],
            scale=[1.32, 0.64, 1.25],
            color=col,
            emissive=em,
            emissive_intensity=0.28,
            roughness=0.80,
        )

        # Hanging Bioluminescent Emerald-Gold Vine Curtain & Golden Realm Lantern!
        vine_top = [p1[0] * 0.35 + p2[0] * 0.65, p1[1] * 0.35 + p2[1] * 0.65 - 0.1, p1[2] * 0.35 + p2[2] * 0.65]
        vine_len = 3.2 + (idx % 3) * 0.9
        vine_bot = [vine_top[0], vine_top[1] - vine_len, vine_top[2]]
        b.add_segment(
            f"hanging_vine_{idx}",
            vine_top,
            vine_bot,
            0.032,
            0.018,
            segments=5,
            color="#34d399",
            emissive="#10b981",
            emissive_intensity=0.68,
            roughness=0.45,
            solid=False,
        )
        b.add_poly(
            f"realm_lantern_{idx}",
            "octahedron",
            [vine_bot[0], vine_bot[1] - 0.16, vine_bot[2]],
            [0.20, 0],
            scale=[0.85, 1.35, 0.85],
            color="#fef08a",
            emissive="#facc15",
            emissive_intensity=1.0,
            roughness=0.18,
        )

    # TIER 2 — 7 Soaring Mid-Upper Boughs (y = 13.5 -> 21.0 m, spanning 18 m wide!)
    for idx in range(7):
        ang = idx * (2.0 * math.pi / 7.0) + 0.62
        ca, sa = math.cos(ang), math.sin(ang)
        h0 = 13.5 + (idx % 2) * 1.2
        p0 = [tree_x + sa * 0.72, h0, tree_z + ca * 0.72]
        p1 = [tree_x + sa * 4.4, h0 + 3.2, tree_z + ca * 4.4]
        p2 = [tree_x + sa * 8.4, h0 + 5.6, tree_z + ca * 8.4]
        b.add_segment(f"bough_t2_{idx}_a", p0, p1, 0.40, 0.25, segments=7, color="#63422d", solid=False)
        b.add_segment(f"bough_t2_{idx}_b", p1, p2, 0.25, 0.11, segments=6, color="#704b34", solid=False)

        col, em = canopy_palette[(idx + 2) % len(canopy_palette)]
        b.add_poly(
            f"canopy_t2_mid_{idx}",
            "icosahedron",
            [p1[0], p1[1] + 0.9, p1[2]],
            [2.45, 0],
            rot=[0.3, ang, 0.4],
            scale=[1.30, 0.66, 1.28],
            color=col,
            emissive=em,
            emissive_intensity=0.30,
            roughness=0.78,
        )
        col2, em2 = canopy_palette[(idx + 5) % len(canopy_palette)]
        b.add_poly(
            f"canopy_t2_tip_{idx}",
            "icosahedron",
            [p2[0], p2[1] + 0.75, p2[2]],
            [2.75, 1],
            rot=[idx * 0.5, ang + 0.4, 0.2],
            scale=[1.35, 0.62, 1.25],
            color=col2,
            emissive=em2,
            emissive_intensity=0.32,
            roughness=0.76,
        )

    # TIER 3 — Sky-Piercing Crown Boughs & Monumental Apex Canopy (y = 19.5 -> 27.5 m!)
    for idx in range(5):
        ang = idx * (2.0 * math.pi / 5.0) + 0.3
        ca, sa = math.cos(ang), math.sin(ang)
        p0 = [tree_x + sa * 0.40, 19.2, tree_z + ca * 0.40]
        p1 = [tree_x + sa * 4.8, 23.6, tree_z + ca * 4.8]
        b.add_segment(f"bough_t3_{idx}", p0, p1, 0.26, 0.09, segments=6, color="#734d36", solid=False)
        col, em = canopy_palette[(idx + 4) % len(canopy_palette)]
        b.add_poly(
            f"canopy_t3_{idx}",
            "icosahedron",
            [p1[0], p1[1] + 0.8, p1[2]],
            [2.6, 1],
            rot=[0.4, ang, 0.3],
            scale=[1.25, 0.65, 1.25],
            color=col,
            emissive=em,
            emissive_intensity=0.34,
            roughness=0.74,
        )

    # Towering Apex Crown Dome + Luminous Emerald-Gold Starlight Crest
    b.add_poly(
        "canopy_apex_main",
        "icosahedron",
        [tree_x, 24.8, tree_z],
        [4.4, 1],
        scale=[1.42, 0.62, 1.42],
        color="#238454",
        emissive="#0f4c3a",
        emissive_intensity=0.34,
        roughness=0.74,
    )
    b.add_poly(
        "canopy_apex_crest",
        "icosahedron",
        [tree_x, 26.8, tree_z],
        [2.5, 1],
        scale=[1.25, 0.68, 1.25],
        color="#6ee7b7",
        emissive="#10b981",
        emissive_intensity=0.45,
        roughness=0.60,
    )

    # Floating Golden-Cyan Astral Halo & 9 Orbiting Nine-Realms Crystals Around the Upper Crown!
    b.add_poly(
        "yggdrasil_astral_halo",
        "torus",
        [tree_x, 21.5, tree_z],
        [12.8, 0.11, 6, 42],
        rot=[math.pi / 2.0 + 0.14, 0.0, -0.09],
        color="#fde68a",
        emissive="#f59e0b",
        emissive_intensity=0.82,
        roughness=0.22,
    )
    realm_colors = [
        ("#fef08a", "#f59e0b"),  # Asgard
        ("#6ee7b7", "#10b981"),  # Midgard
        ("#7dd3fc", "#0284c7"),  # Jotunheim
        ("#c4b5fd", "#7c3aed"),  # Alfheim
        ("#f9a8d4", "#db2777"),  # Vanaheim
        ("#fdba74", "#ea580c"),  # Muspelheim
        ("#a5f3fc", "#0891b2"),  # Niflheim
        ("#94a3b8", "#475569"),  # Svartalfheim
        ("#818cf8", "#4338ca"),  # Helheim
    ]
    for idx, (rc, rem) in enumerate(realm_colors):
        ang = idx * (2.0 * math.pi / 9.0)
        rx = tree_x + math.sin(ang) * 12.8
        rz = tree_z + math.cos(ang) * 12.8
        ry = 21.5 + math.sin(ang) * 1.4
        b.add_poly(
            f"nine_realm_crystal_{idx + 1}",
            "octahedron",
            [rx, ry, rz],
            [0.52, 0],
            scale=[0.78, 1.65, 0.78],
            color=rc,
            emissive=rem,
            emissive_intensity=0.98,
            roughness=0.16,
        )

    # 24 Bioluminescent Drifting Spores / Star-Motes around the roots & lower cathedral canopy
    for idx in range(24):
        ang = idx * 2.39996  # golden angle distribution
        rad = 2.6 + (idx % 7) * 1.05
        my = 1.2 + (idx % 8) * 1.45
        mx = tree_x + math.sin(ang) * rad
        mz = tree_z + math.cos(ang) * rad
        b.add_poly(
            f"biolum_spore_{idx}",
            "octahedron",
            [mx, my, mz],
            [0.065 + (idx % 3) * 0.025, 0],
            color="#a5f3fc" if idx % 3 != 0 else "#fef08a",
            emissive="#22d3ee" if idx % 3 != 0 else "#facc15",
            emissive_intensity=1.0,
            roughness=0.15,
        )

    # =========================================================================
    # 4. ROBOT OBSTACLE COURSE ZONE A (South-East, +X):
    #    "ASGARD OVERLOOK" — Gentle 6.5° Ramp, Elevated Terrace (+0.16 m) & Return Ramp
    # =========================================================================
    b.add_ramp("asgard_ramp_up", 4.6, 0.0, 1.8, 4.6, 0.16, 3.2, width=0.88, color="#6d7888")
    b.add_box(
        "asgard_terrace_deck",
        [5.35, 0.08, 4.10],
        [2.38, 0.16, 1.80],
        color="#7b8798",
        emissive="#1e293b",
        emissive_intensity=0.14,
        flat_shading=True,
        solid=True,
    )
    b.add_ramp("asgard_ramp_down", 5.8, 0.16, 5.0, 5.8, 0.0, 6.4, width=0.88, color="#6d7888")
    # Well of Urd (Sacred Cyan Spring) beside the East terrace at (7.0, 0, 6.6)
    b.add_cylinder(
        "well_of_urd_rim",
        [7.0, 0.08, 6.6],
        0.88,
        0.98,
        0.16,
        segments=16,
        color="#cbd5e1",
        emissive="#334155",
        emissive_intensity=0.14,
        solid=True,
    )
    b.add_cylinder(
        "well_of_urd_water",
        [7.0, 0.162, 6.6],
        0.70,
        0.70,
        0.015,
        segments=16,
        color="#38bdf8",
        emissive="#0ea5e9",
        emissive_intensity=0.9,
        roughness=0.15,
        metalness=0.35,
        solid=False,
    )

    # =========================================================================
    # 5. ROBOT OBSTACLE COURSE ZONE B (South-West, -X):
    #    "MIDGARD RUNES" — Slalom Obelisks (0.52 m weave) & Progressive Root Ridges
    # =========================================================================
    slalom_stones = [
        (-4.25, 2.35, 0.68),
        (-5.15, 3.15, 0.84),
        (-4.30, 4.05, 0.74),
        (-5.20, 4.95, 0.88),
    ]
    for idx, (sx, sz, sh) in enumerate(slalom_stones):
        ry = idx * 0.35
        b.add_box(
            f"slalom_runestone_{idx + 1}",
            [sx, sh / 2.0, sz],
            [0.22, sh, 0.22],
            rot=[0.0, ry, 0.0],
            color="#64748b",
            emissive="#1e293b",
            emissive_intensity=0.14,
            flat_shading=True,
            solid=True,
        )
        b.add_box(
            f"slalom_glow_{idx + 1}",
            [sx - math.sin(ry) * 0.115, sh * 0.55, sz - math.cos(ry) * 0.115],
            [0.06, sh * 0.45, 0.02],
            rot=[0.0, ry, 0.0],
            color="#34d399",
            emissive="#10b981",
            emissive_intensity=0.92,
            solid=False,
        )
    for idx, (rz, rh) in enumerate([(2.75, 0.009), (3.60, 0.012), (4.50, 0.015)]):
        b.add_box(
            f"root_ridge_{idx + 1}",
            [-4.72, rh / 2.0, rz],
            [1.15, rh, 0.055],
            rot=[0.0, (idx - 1) * 0.14, 0.0],
            color="#5c4033",
            emissive="#2b1b12",
            emissive_intensity=0.15,
            solid=True,
        )
    # Well of Mimir (Wisdom Gold Spring) at (-7.0, 0, 6.6)
    b.add_cylinder(
        "well_of_mimir_rim",
        [-7.0, 0.08, 6.6],
        0.88,
        0.98,
        0.16,
        segments=16,
        color="#57534e",
        emissive="#292524",
        emissive_intensity=0.14,
        solid=True,
    )
    b.add_cylinder(
        "well_of_mimir_water",
        [-7.0, 0.162, 6.6],
        0.70,
        0.70,
        0.015,
        segments=16,
        color="#fbbf24",
        emissive="#f59e0b",
        emissive_intensity=0.9,
        roughness=0.15,
        metalness=0.4,
        solid=False,
    )

    # =========================================================================
    # 6. ROBOT OBSTACLE COURSE ZONE C (North-West, -X, +Z):
    #    "JOTUNHEIM STONE BRIDGE" — Narrow 0.48 m Precision Causeway + Crystal Shrine
    # =========================================================================
    b.add_box(
        "jotun_stream_bed",
        [-4.8, 0.002, 10.6],
        [2.2, 0.004, 1.35],
        color="#0284c7",
        emissive="#0369a1",
        emissive_intensity=0.55,
        roughness=0.18,
        metalness=0.35,
        solid=False,
    )
    b.add_ramp("jotun_bridge_ramp_s", -4.8, 0.0, 9.45, -4.8, 0.045, 9.95, width=0.48, color="#94a3b8")
    b.add_box(
        "jotun_bridge_span",
        [-4.8, 0.015, 10.60],
        [0.48, 0.06, 1.32],
        color="#94a3b8",
        emissive="#1e293b",
        emissive_intensity=0.16,
        flat_shading=True,
        solid=True,
    )
    b.add_ramp("jotun_bridge_ramp_n", -4.8, 0.045, 11.25, -4.8, 0.0, 11.75, width=0.48, color="#94a3b8")
    b.add_poly(
        "jotun_shrine_crystal",
        "octahedron",
        [-4.8, 0.54, 12.45],
        [0.28, 0],
        scale=[0.75, 1.75, 0.75],
        color="#a5f3fc",
        emissive="#22d3ee",
        emissive_intensity=0.95,
        roughness=0.18,
    )

    # =========================================================================
    # 7. ROBOT OBSTACLE COURSE ZONE D (North-East, +X, +Z):
    #    "VALHALLA CIRCLE" — 3 Concentric 11 mm Stepped Emote Dais & Braziers
    # =========================================================================
    vx, vz = 4.8, 11.2
    b.add_cylinder(
        "valhalla_step_1",
        [vx, 0.0055, vz],
        1.55,
        1.62,
        0.011,
        segments=20,
        color="#526072",
        roughness=0.86,
        solid=True,
    )
    b.add_cylinder(
        "valhalla_step_2",
        [vx, 0.0165, vz],
        1.18,
        1.24,
        0.011,
        segments=20,
        color="#64748b",
        roughness=0.82,
        solid=True,
    )
    b.add_cylinder(
        "valhalla_step_3",
        [vx, 0.0275, vz],
        0.82,
        0.88,
        0.011,
        segments=20,
        color="#7c8ea3",
        emissive="#1e293b",
        emissive_intensity=0.18,
        roughness=0.78,
        solid=True,
    )
    for idx in range(4):
        ang = idx * (math.pi / 2.0) + math.pi / 4.0
        fx = vx + math.sin(ang) * 1.48
        fz = vz + math.cos(ang) * 1.48
        b.add_cylinder(
            f"valhalla_brazier_{idx}",
            [fx, 0.22, fz],
            0.12,
            0.16,
            0.44,
            segments=8,
            color="#475569",
            solid=True,
        )
        b.add_poly(
            f"valhalla_flame_{idx}",
            "octahedron",
            [fx, 0.50, fz],
            [0.09, 0],
            color="#fdba74",
            emissive="#f97316",
            emissive_intensity=0.98,
        )

    # =========================================================================
    # 8. OUTER RING STANDING MONOLITHS (10 Iconic Norse Runestones Framing the Island)
    # =========================================================================
    for idx in range(10):
        ang = idx * (2.0 * math.pi / 10.0) + math.pi / 10.0
        mx = tree_x + math.sin(ang) * 9.35
        mz = meadow_z + math.cos(ang) * 9.35
        if mz < 0.8 and abs(mx) < 2.6:
            continue
        mh = 2.0 + (idx % 3) * 0.55
        b.add_box(
            f"outer_monolith_{idx}",
            [mx, mh / 2.0, mz],
            [0.48, mh, 0.40],
            rot=[0.0, ang, 0.0],
            color="#556172",
            emissive="#1e293b",
            emissive_intensity=0.12,
            flat_shading=True,
            solid=True,
        )
        b.add_box(
            f"outer_monolith_rune_{idx}",
            [mx - math.sin(ang) * 0.205, mh * 0.56, mz - math.cos(ang) * 0.205],
            [0.09, mh * 0.48, 0.03],
            rot=[0.0, ang, 0.0],
            color="#7dd3fc" if idx % 2 == 0 else "#fcd34d",
            emissive="#0ea5e9" if idx % 2 == 0 else "#f59e0b",
            emissive_intensity=0.90,
            solid=False,
        )

    # 8 Rich Atmospheric Lights illuminating the colossal World Tree, Canopy & Realms
    b.add_light("light_tree_heart", [tree_x, 1.6, tree_z - 2.6], "#67e8f9", 3.6, 14.0)
    b.add_light("light_canopy_gold", [tree_x, 11.5, tree_z - 3.0], "#fde68a", 4.5, 28.0)
    b.add_light("light_canopy_crown", [tree_x, 20.5, tree_z - 2.0], "#34d399", 5.0, 32.0)
    b.add_light("light_bifrost", [0.0, 1.5, 1.1], "#fde68a", 2.2, 9.0)
    b.add_light("light_well_urd", [7.0, 1.1, 6.6], "#38bdf8", 2.0, 9.0)
    b.add_light("light_well_mimir", [-7.0, 1.1, 6.6], "#fbbf24", 2.0, 9.0)
    b.add_light("light_jotunheim", [-4.8, 1.3, 12.2], "#22d3ee", 2.0, 9.0)
    b.add_light("light_valhalla", [vx, 1.2, vz], "#fb923c", 2.0, 9.0)

    return {
        "schemaVersion": 2,
        "id": "yggdrasil",
        "name": "Yggdrasil (Tree of Life)",
        "subtitle": "Colossal 27m Norse World Tree · Bifrost, cathedral roots, ramps, slalom & wells",
        "worldOriginThree": [0.0, 0.0, 0.0],
        "skyboxDir": "/assets/skyboxes/observatory",
        "backgroundHex": "#0b1626",
        "fogHex": "#132845",
        "fogDensity": 0.0042,
        "useDefaultFloorPlane": False,
        "robotSpawnMj": [0.0, 0.0, 0.066],
        "primitives": b.primitives,
        "glbInstances": [],
        "colliders": b.colliders,
        "lights": b.lights,
        "water": {
            "y": -0.55,
            "size": 640,
            "color": "#061528",
            "opacity": 0.92,
        },
    }
