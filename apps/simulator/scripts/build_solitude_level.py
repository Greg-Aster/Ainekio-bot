#!/usr/bin/env python3
"""
Procedural low-poly Solitude — Ancient Glowing Stonehenge & Rolling Grassy Plain
Robot Training Ground builder (`solitude.level.json` + `solitude.hfield.bin`).

Design ethos:
  - A beautiful, lonely ancient place of rest and reflection, tailored as an
    open wander-and-discover training ground for Ainekio V2!
  - Real rolling grassy plain topography (111x111 MuJoCo <hfield> + exact 1:1
    vertex-colored faceted grass mesh with procedural grass-grain micro-texture,
    0 heavy GLBs, ~48 KB heightfield).
  - Calm, completely flat walkable meadow & flush weathered flagstones at spawn
    and in the heart of the Stonehenge sanctuary (eliminating the old awkward
    center plate!).
  - 12 distinct, individually characterized ancient Stonehenge monoliths &
    trilithons (unique heights, tapers, weathered leans, cap lintels, moss
    cushions, broken/fallen stone, and glowing carved rune fissures).
  - A Single Glowing Firefly hovering and gently breathing warm golden light
    in the exact center of the ancient stone ring.
  - 6 discoverable robot training landmarks placed at exact h(x, z):
      1. Flush weathered flagstone sanctuary path & firefly hearth
      2. East Fallen Lintel Ramp (6.5 deg) & Solstice Cairn Terrace (+0.16 m)
      3. West Whispering Cairn Grove & Mossy Slalom Boulders
      4. North Broken Ring Observatory Knoll (+0.34 m climbable grassy hill)
      5. South-East Sunken Dew Pond & Narrow Stone Footbridge (0.50 m wide)
      6. South-West Lonely Stone Bench, Flagstone Steps & Stone Lantern Shrine

Coordinate convention (Three.js, local-origin centered at robot spawn):
  - Robot spawns at (0, 0, 0) facing +Z (MuJoCo +X forward, +Y left, +Z up)
  - Ground surface at spawn is strictly y = 0.000 m
  - Stonehenge Sanctuary & Single Glowing Firefly sit ahead at (0, 0, +5.4 m)
"""

from __future__ import annotations

import math
import struct
from typing import Any

import numpy as np

from build_yggdrasil_level import _SceneBuilder


# Center of the Stonehenge sanctuary & rolling plain
RING_X = 0.0
RING_Z = 5.4


def terrain_height(x: float, z: float) -> float:
    """
    Smooth, walkable rolling grassy plain height function y = h(x, z) in Three.js meters.
    Strictly 0.000 m at spawn (0, 0) and across the central Stonehenge sanctuary hearth,
    with gentle climbable undulations (<= 6.5 deg) across the inner training plain,
    a recessed SE dew pond hollow, a climbable North Broken Ring knoll, and poetic
    outer highland hills framing the lonely valley.
    """
    # Distance from spawn clearing (0, 0) and sanctuary center (0, 5.4)
    d_spawn = math.hypot(x, z)
    d_center = math.hypot(x - RING_X, z - RING_Z)

    # Smooth plateau blend: 0 inside spawn & center hearth so Ainekio spawns & rests cleanly
    flat_spawn = 1.0 - math.exp(-((max(0.0, d_spawn - 1.15) / 1.55) ** 2))
    flat_center = 1.0 - math.exp(-((max(0.0, d_center - 2.35) / 1.85) ** 2))
    # Keep the South approach corridor (x ~ 0, z in [0, 5.4]) gently level
    corridor_t = max(0.0, min(1.0, z / RING_Z))
    d_corridor = math.hypot(x, z - corridor_t * RING_Z)
    flat_corridor = 1.0 - math.exp(-((max(0.0, d_corridor - 0.85) / 1.15) ** 2))
    flat_mask = flat_spawn * flat_center * flat_corridor

    # Keep East terrace & West shrine pads gently settled
    d_east_pad = math.hypot(x - 7.8, z - 5.4)
    d_sw_pad = math.hypot(x + 6.4, z - 1.6)
    pad_mask = (1.0 - 0.85 * math.exp(-((d_east_pad / 2.2) ** 2))) * (
        1.0 - 0.85 * math.exp(-((d_sw_pad / 1.8) ** 2))
    )

    # Multi-frequency rolling grassy meadow bumps & swells (gentle <= 6 deg!)
    undulation = (
        0.085 * math.sin(x * 0.38 + 0.4) * math.cos(z * 0.34 - 0.2)
        + 0.055 * math.sin((x * 0.62 - z * 0.48) + 1.1)
        + 0.032 * math.cos(x * 1.05 + z * 0.92)
    )
    h = undulation * flat_mask * pad_mask

    # North Broken Ring Observatory Knoll at (0, 11.8): smooth climbable grassy hill (+0.34 m)
    d_north_hill = math.hypot(x - 0.0, z - 11.8)
    h += 0.34 * math.exp(-((d_north_hill / 3.4) ** 2))

    # Gentle grassy mound in NW (-6.2, 9.6) & NE (6.4, 9.8) for wandering exploration
    h += 0.22 * math.exp(-((math.hypot(x + 6.2, z - 9.6) / 2.9) ** 2))
    h += 0.20 * math.exp(-((math.hypot(x - 6.4, z - 9.8) / 2.8) ** 2))

    # SE Sunken Dew Pond hollow at (6.0, 1.4): dips cleanly to -0.15 m
    d_pond = math.hypot((x - 6.0) / 1.55, (z - 1.4) / 1.15)
    h -= 0.16 * math.exp(-(d_pond ** 2))

    # Outer highland basin rim (r > 11.5 m from ring center) rising into lonely framing hills
    if d_center > 11.2:
        t = (d_center - 11.2) / 5.8
        ang = math.atan2(x - RING_X, z - RING_Z)
        ridge_var = 0.72 + 0.38 * math.sin(ang * 3.0 + 0.7) + 0.22 * math.cos(ang * 5.0 - 0.4)
        # Keep a lower scenic view gap in the far South-West so twilight stars shine low
        h += (t * t) * 1.85 * ridge_var

    return float(h)


def build_solitude_hfield() -> tuple[dict[str, Any], bytes]:
    """
    Build the exact 111x111 MuJoCo heightfield binary for Solitude.
    Covers Three.js x in [-17, +17] (34 m), z in [-11.6, +22.4] (34 m) centered on (0, 5.4).
    """
    nrow = 111  # MuJoCo +Y (= Three +X)
    ncol = 111  # MuJoCo +X (= Three +Z)
    half_x = 17.0
    half_z = 17.0
    cx = RING_X
    cz = RING_Z

    xs = np.linspace(cx - half_x, cx + half_x, nrow, dtype=np.float64)
    zs = np.linspace(cz - half_z, cz + half_z, ncol, dtype=np.float64)

    grid = np.zeros((nrow, ncol), dtype=np.float64)
    for r, xv in enumerate(xs):
        for c, zv in enumerate(zs):
            grid[r, c] = terrain_height(float(xv), float(zv))

    # Exact calibration so spawn (x=0, z=0) sits at y = 0.0000 m
    spawn_h = terrain_height(0.0, 0.0)
    grid -= spawn_h

    y_min = float(grid.min())
    y_max = float(grid.max())
    elev = max(0.5, y_max - y_min)
    norm = np.clip((grid - y_min) / elev, 0.0, 1.0).astype("<f4")
    hfield_bytes = struct.pack("<2i", nrow, ncol) + np.ascontiguousarray(norm).tobytes()

    hfield_spec = {
        "url": "/sim/levels/solitude.hfield.bin",
        "posMj": [round(cz, 5), round(cx, 5), round(y_min, 5)],
        "sizeMj": [round(half_z, 5), round(half_x, 5), round(elev, 5), 2.5],
    }
    return hfield_spec, hfield_bytes


def build_solitude_level() -> tuple[dict[str, Any], bytes]:
    b = _SceneBuilder()
    hfield_spec, hfield_bytes = build_solitude_hfield()
    spawn_offset = terrain_height(0.0, 0.0)

    def gy(x: float, z: float) -> float:
        return terrain_height(x, z) - spawn_offset

    # =========================================================================
    # 1. FLUSH WEATHERED FLAGSTONE PATH & CALM SANCTUARY HEARTH (NO UNEVEN PLATE!)
    #    Completely flat y = 0.000 m walkable ground at spawn & sanctuary center.
    # =========================================================================
    # Subtle inlaid weathered flagstones leading from spawn (0, 0) into the Stonehenge ring
    stepping_stones = [
        (0.00, 0.00, 0.68, 0.56, 0.04),
        (0.06, 0.85, 0.54, 0.44, -0.08),
        (-0.08, 1.62, 0.58, 0.46, 0.11),
        (0.04, 2.40, 0.52, 0.44, -0.05),
        (-0.05, 3.18, 0.56, 0.46, 0.09),
        (0.03, 3.98, 0.62, 0.50, -0.04),
        # Continuing north out of the sanctuary toward the Broken Ring Knoll
        (-0.04, 6.95, 0.56, 0.44, 0.07),
        (0.07, 7.80, 0.52, 0.44, -0.10),
        (-0.05, 8.65, 0.54, 0.42, 0.06),
        (0.04, 9.50, 0.50, 0.42, -0.08),
    ]
    for idx, (sx, sz, sw, sl, yaw) in enumerate(stepping_stones):
        y0 = gy(sx, sz)
        # Visual flush stone inset (+3 mm above grass, non-colliding so feet glide seamlessly!)
        b.add_box(
            f"flagstone_{idx + 1}",
            [sx, y0 - 0.006, sz],
            [sw, 0.018, sl],
            rot=[0.0, yaw, 0.0],
            color="#6e7782" if idx % 2 == 0 else "#636c77",
            emissive="#1e293b",
            emissive_intensity=0.1,
            roughness=0.92,
            metalness=0.06,
            flat_shading=True,
            solid=False,
        )

    # Flush mossy sanctuary hearth ring around the Single Firefly (visual ring inset at y = +0.003 m)
    b.add_poly(
        "sanctuary_hearth_ring",
        "torus",
        [RING_X, gy(RING_X, RING_Z) + 0.006, RING_Z],
        [1.55, 0.028, 6, 32],
        rot=[math.pi / 2.0, 0.0, 0.0],
        color="#fcd34d",
        emissive="#f59e0b",
        emissive_intensity=0.42,
        roughness=0.4,
    )
    # 8 small weathered flush hearth paving stones arranged peacefully in a ring around the firefly
    for idx in range(8):
        ang = idx * (math.pi / 4.0) + math.pi / 8.0
        px = RING_X + math.sin(ang) * 1.15
        pz = RING_Z + math.cos(ang) * 1.15
        b.add_box(
            f"hearth_flag_{idx}",
            [px, gy(px, pz) - 0.005, pz],
            [0.44, 0.016, 0.34],
            rot=[0.0, ang, 0.0],
            color="#737d89" if idx % 2 == 0 else "#65707b",
            emissive="#1e293b",
            emissive_intensity=0.1,
            roughness=0.9,
            flat_shading=True,
            solid=False,
        )

    # =========================================================================
    # 2. THE SINGLE GLOWING FIREFLY (Heart of Solitude, animated in viewport!)
    # =========================================================================
    ff_y = gy(RING_X, RING_Z) + 0.56
    b.add_poly(
        "firefly_core",
        "octahedron",
        [RING_X, ff_y, RING_Z],
        [0.055, 1],
        color="#fef9c3",
        emissive="#facc15",
        emissive_intensity=1.0,
        roughness=0.1,
        metalness=0.0,
    )
    b.add_poly(
        "firefly_aura",
        "sphere",
        [RING_X, ff_y, RING_Z],
        [0.20, 12, 10],
        color="#fde68a",
        emissive="#f59e0b",
        emissive_intensity=0.95,
        opacity=0.26,
        roughness=0.2,
        flat_shading=False,
    )
    b.add_box(
        "firefly_wing_l",
        [RING_X + 0.055, ff_y + 0.025, RING_Z],
        [0.09, 0.006, 0.045],
        rot=[0.2, 0.15, 0.42],
        color="#fef3c7",
        emissive="#fde68a",
        emissive_intensity=0.8,
        opacity=0.72,
        solid=False,
    )
    b.add_box(
        "firefly_wing_r",
        [RING_X - 0.055, ff_y + 0.025, RING_Z],
        [0.09, 0.006, 0.045],
        rot=[0.2, -0.15, -0.42],
        color="#fef3c7",
        emissive="#fde68a",
        emissive_intensity=0.8,
        opacity=0.72,
        solid=False,
    )

    # =========================================================================
    # 3. ANCIENT GLOWING STONEHENGE RING (Unique Pillars, Trilithons, Lintels,
    #    Broken Fallen Monolith, Moss Caps & Glowing Carved Runes!)
    # =========================================================================
    def add_megalith(
        name: str,
        x: float,
        z: float,
        w: float,
        h: float,
        d: float,
        yaw: float,
        *,
        lean_x: float = 0.0,
        lean_z: float = 0.0,
        stone_col: str = "#6d7682",
        rune_col: str = "#7dd3fc",
        rune_em: str = "#0ea5e9",
        has_moss: bool = True,
        has_shoulder: bool = True,
    ) -> None:
        base_y = gy(x, z) - 0.14
        # Main ancient carved megalith block (embedded 14 cm into earth so zero floating!)
        b.add_box(
            name,
            [x, base_y + h / 2.0, z],
            [w, h, d],
            rot=[lean_x, yaw, lean_z],
            color=stone_col,
            emissive="#1e293b",
            emissive_intensity=0.14,
            roughness=0.92,
            metalness=0.08,
            flat_shading=True,
            solid=True,
        )
        # Stepped/chipped upper shoulder cap for rich Stonehenge silhouette
        if has_shoulder:
            sh_h = h * 0.16
            b.add_box(
                f"{name}_cap",
                [x, base_y + h + sh_h * 0.35, z],
                [w * 0.84, sh_h, d * 0.86],
                rot=[lean_x, yaw + 0.06, lean_z],
                color="#7c8591",
                emissive="#1e293b",
                emissive_intensity=0.12,
                roughness=0.9,
                flat_shading=True,
                solid=False,
            )
        # Glowing ancient megalithic chevron/diamond rune carving facing inward toward the Firefly
        in_x = RING_X - x
        in_z = RING_Z - z
        in_len = math.hypot(in_x, in_z) or 1.0
        nx, nz = in_x / in_len, in_z / in_len
        rune_yaw = math.atan2(nx, nz)
        face_dist = max(w, d) * 0.51
        b.add_box(
            f"{name}_rune_main",
            [x + nx * face_dist, base_y + h * 0.54, z + nz * face_dist],
            [0.062, h * 0.44, 0.028],
            rot=[0.0, rune_yaw, 0.0],
            color=rune_col,
            emissive=rune_em,
            emissive_intensity=0.95,
            roughness=0.22,
            solid=False,
        )
        # Glowing diamond core & upper/lower rune dots (archaic megalithic glyph motif)
        b.add_poly(
            f"{name}_rune_diamond",
            "octahedron",
            [x + nx * (face_dist + 0.008), base_y + h * 0.56, z + nz * (face_dist + 0.008)],
            [min(w, 0.55) * 0.24, 0],
            scale=[0.85, 1.35, 0.32],
            rot=[0.0, rune_yaw, 0.0],
            color=rune_col,
            emissive=rune_em,
            emissive_intensity=0.98,
            roughness=0.18,
        )
        b.add_poly(
            f"{name}_rune_pip",
            "octahedron",
            [x + nx * (face_dist + 0.006), base_y + h * 0.80, z + nz * (face_dist + 0.006)],
            [0.055, 0],
            scale=[1.0, 1.0, 0.4],
            rot=[0.0, rune_yaw, 0.0],
            color=rune_col,
            emissive=rune_em,
            emissive_intensity=0.92,
            roughness=0.2,
        )
        # Mossy weathering patch on base or shoulder
        if has_moss:
            b.add_poly(
                f"{name}_moss",
                "dodecahedron",
                [x - nx * (w * 0.25), base_y + 0.24, z - nz * (d * 0.25)],
                [0.24, 0],
                scale=[1.3, 0.48, 1.15],
                color="#3b6e3c",
                emissive="#14381a",
                emissive_intensity=0.18,
                roughness=0.92,
            )

    def add_trilithon(
        name: str,
        center_ang: float,
        radius: float,
        span_rad: float,
        h_left: float,
        h_right: float,
        *,
        lintel_tilt: float = 0.0,
        stone_col: str = "#707a87",
        rune_col: str = "#7dd3fc",
        rune_em: str = "#0ea5e9",
    ) -> None:
        a1 = center_ang - span_rad / 2.0
        a2 = center_ang + span_rad / 2.0
        x1, z1 = RING_X + math.sin(a1) * radius, RING_Z + math.cos(a1) * radius
        x2, z2 = RING_X + math.sin(a2) * radius, RING_Z + math.cos(a2) * radius
        add_megalith(
            f"{name}_p1",
            x1,
            z1,
            0.54,
            h_left,
            0.46,
            a1,
            lean_z=0.03,
            stone_col=stone_col,
            rune_col=rune_col,
            rune_em=rune_em,
            has_shoulder=False,
        )
        add_megalith(
            f"{name}_p2",
            x2,
            z2,
            0.52,
            h_right,
            0.46,
            a2,
            lean_z=-0.025,
            stone_col="#656f7c",
            rune_col=rune_col,
            rune_em=rune_em,
            has_shoulder=False,
        )
        # Massive weathered Stonehenge lintel beam spanning across both uprights!
        mx, mz = 0.5 * (x1 + x2), 0.5 * (z1 + z2)
        span_dist = math.hypot(x2 - x1, z2 - z1)
        top_y = max(gy(x1, z1) - 0.14 + h_left, gy(x2, z2) - 0.14 + h_right)
        b.add_box(
            f"{name}_lintel",
            [mx, top_y + 0.18, mz],
            [span_dist + 0.85, 0.44, 0.62],
            rot=[0.0, center_ang, lintel_tilt],
            color="#7d8794",
            emissive="#1e293b",
            emissive_intensity=0.14,
            roughness=0.91,
            flat_shading=True,
            solid=False,
        )
        # Moss blanket resting atop the ancient lintel
        b.add_poly(
            f"{name}_lintel_moss",
            "dodecahedron",
            [mx, top_y + 0.42, mz],
            [0.34, 0],
            rot=[0.1, center_ang, 0.0],
            scale=[1.8, 0.34, 0.85],
            color="#3e6e3c",
            emissive="#14381a",
            emissive_intensity=0.16,
            roughness=0.92,
        )

    ring_r = 4.65
    # 1. SOUTH GATEWAY TRILITHON (frames spawn view at z ~ 0.9 m, wide 1.85 m opening!)
    add_trilithon(
        "trilithon_south_gate",
        math.pi,
        ring_r,
        0.44,
        2.35,
        2.42,
        lintel_tilt=0.02,
        stone_col="#76808d",
        rune_col="#fde68a",
        rune_em="#f59e0b",
    )
    # 2. NORTH GRAND TRILITHON (tallest 3.55 m sovereign arch directly behind the Firefly!)
    add_trilithon(
        "trilithon_north_crown",
        0.0,
        ring_r + 0.25,
        0.46,
        3.55,
        3.42,
        lintel_tilt=-0.03,
        stone_col="#727c8a",
        rune_col="#7dd3fc",
        rune_em="#0ea5e9",
    )
    # 3. EAST SOLSTICE TRILITHON (warm amber runes, slight centuries-old settle)
    add_trilithon(
        "trilithon_east",
        math.pi / 2.0,
        ring_r + 0.1,
        0.40,
        2.95,
        2.82,
        lintel_tilt=0.04,
        stone_col="#6b7480",
        rune_col="#fcd34d",
        rune_em="#f59e0b",
    )
    # 4. WEST TWILIGHT TRILITHON (cool cyan-violet runes)
    add_trilithon(
        "trilithon_west",
        -math.pi / 2.0,
        ring_r + 0.1,
        0.40,
        2.85,
        3.02,
        lintel_tilt=-0.035,
        stone_col="#697380",
        rune_col="#a5f3fc",
        rune_em="#06b6d4",
    )

    # 5. FOUR INTERCARDINAL STANDING & BROKEN MONOLITHS (each uniquely sculpted!)
    # NE: Tall leaning monolith with turquoise rune fissure
    ne_ang = math.pi / 4.0
    add_megalith(
        "monolith_ne_leaning",
        RING_X + math.sin(ne_ang) * (ring_r + 0.15),
        RING_Z + math.cos(ne_ang) * (ring_r + 0.15),
        0.64,
        3.15,
        0.48,
        ne_ang + 0.15,
        lean_x=0.11,
        lean_z=-0.06,
        stone_col="#6c7684",
        rune_col="#6ee7b7",
        rune_em="#10b981",
    )
    # NW: Broken stump (1.35 m) + its fallen upper half resting organically in the meadow!
    nw_ang = -math.pi / 4.0
    nwx = RING_X + math.sin(nw_ang) * (ring_r + 0.10)
    nwz = RING_Z + math.cos(nw_ang) * (ring_r + 0.10)
    add_megalith(
        "monolith_nw_stump",
        nwx,
        nwz,
        0.62,
        1.38,
        0.52,
        nw_ang,
        lean_z=0.05,
        stone_col="#66707d",
        rune_col="#7dd3fc",
        rune_em="#0284c7",
        has_shoulder=False,
    )
    fx, fz = nwx - 1.15, nwz + 0.72
    b.add_box(
        "monolith_nw_fallen_half",
        [fx, gy(fx, fz) + 0.18, fz],
        [0.54, 0.44, 1.65],
        rot=[0.08, nw_ang + 0.75, 0.12],
        color="#646e7a",
        emissive="#1e293b",
        emissive_intensity=0.14,
        roughness=0.92,
        flat_shading=True,
        solid=True,
    )
    # SE: Weathered double-stepped obelisk with warm amber glyph
    se_ang = 3.0 * math.pi / 4.0
    add_megalith(
        "monolith_se_obelisk",
        RING_X + math.sin(se_ang) * (ring_r + 0.05),
        RING_Z + math.cos(se_ang) * (ring_r + 0.05),
        0.58,
        2.65,
        0.50,
        se_ang - 0.12,
        lean_x=-0.08,
        stone_col="#727c88",
        rune_col="#fde68a",
        rune_em="#f59e0b",
    )
    # SW: Tall slender sentinel pillar tilted slightly inward
    sw_ang = -3.0 * math.pi / 4.0
    add_megalith(
        "monolith_sw_sentinel",
        RING_X + math.sin(sw_ang) * (ring_r + 0.05),
        RING_Z + math.cos(sw_ang) * (ring_r + 0.05),
        0.50,
        2.95,
        0.44,
        sw_ang + 0.18,
        lean_x=-0.09,
        lean_z=0.07,
        stone_col="#6a7482",
        rune_col="#c4b5fd",
        rune_em="#7c3aed",
    )

    # 6 low knee-high inner runic marker stones (gentle slalom / visual rhythm inside ring)
    for idx in range(6):
        ang = idx * (math.pi / 3.0) + math.pi / 6.0
        rx = RING_X + math.sin(ang) * 2.75
        rz = RING_Z + math.cos(ang) * 2.75
        sh = 0.42 + (idx % 3) * 0.14
        b.add_box(
            f"inner_marker_{idx}",
            [rx, gy(rx, rz) + sh / 2.0 - 0.05, rz],
            [0.20, sh, 0.18],
            rot=[0.04, ang, -0.03],
            color="#757f8c",
            emissive="#1e293b",
            emissive_intensity=0.12,
            roughness=0.9,
            flat_shading=True,
            solid=True,
        )
        b.add_box(
            f"inner_marker_glow_{idx}",
            [rx - math.sin(ang) * 0.095, gy(rx, rz) + sh * 0.56, rz - math.cos(ang) * 0.095],
            [0.045, sh * 0.36, 0.02],
            rot=[0.0, ang, 0.0],
            color="#fde68a" if idx % 2 == 0 else "#7dd3fc",
            emissive="#f59e0b" if idx % 2 == 0 else "#0ea5e9",
            emissive_intensity=0.88,
            solid=False,
        )

    # =========================================================================
    # 4. DISCOVERY LANDMARK A (East): FALLEN LINTEL RAMP & SOLSTICE CAIRN TERRACE
    # =========================================================================
    ey0 = gy(7.2, 3.3)
    ey_top = gy(7.8, 5.4) + 0.16
    b.add_ramp("solstice_ramp_up", 7.2, ey0, 3.3, 7.2, ey_top, 4.6, width=0.86, color="#737e8c")
    b.add_box(
        "solstice_terrace_deck",
        [7.95, ey_top - 0.12, 5.50],
        [2.25, 0.24, 1.85],
        color="#7b8694",
        emissive="#1e293b",
        emissive_intensity=0.12,
        flat_shading=True,
        solid=True,
    )
    ey1 = gy(8.4, 7.7)
    b.add_ramp("solstice_ramp_down", 8.4, ey_top, 6.4, 8.4, ey1, 7.7, width=0.86, color="#737e8c")
    # Glowing Solstice Sun-Dial Ring Cairn atop the East terrace
    b.add_cylinder(
        "solstice_cairn_base",
        [8.45, ey_top + 0.18, 5.45],
        0.24,
        0.34,
        0.36,
        segments=10,
        color="#6c7582",
        solid=True,
    )
    b.add_poly(
        "solstice_cairn_ring",
        "torus",
        [8.45, ey_top + 0.68, 5.45],
        [0.34, 0.048, 8, 22],
        rot=[0.18, 0.5, 0.0],
        color="#fde68a",
        emissive="#f59e0b",
        emissive_intensity=0.85,
        roughness=0.28,
    )

    # =========================================================================
    # 5. DISCOVERY LANDMARK B (West): WHISPERING CAIRN GROVE & SLALOM BOULDERS
    # =========================================================================
    west_boulders = [
        (-6.6, 3.8, 0.42),
        (-7.7, 4.7, 0.56),
        (-6.5, 5.7, 0.48),
        (-7.8, 6.6, 0.62),
        (-6.8, 7.5, 0.44),
    ]
    for idx, (bx, bz, br) in enumerate(west_boulders):
        by = gy(bx, bz)
        b.add_poly(
            f"meadow_boulder_{idx + 1}",
            "dodecahedron",
            [bx, by + br * 0.48, bz],
            [br, 0],
            rot=[idx * 0.5, idx * 0.8, 0.2],
            scale=[1.25, 0.78, 1.1],
            color="#5c6672" if idx % 2 == 0 else "#68737f",
            roughness=0.92,
        )
        # Matching MuJoCo cylinder collider so Ainekio weaves cleanly around boulders
        b.add_cylinder(
            f"meadow_boulder_col_{idx + 1}",
            [bx, by + br * 0.4, bz],
            br * 0.92,
            br * 1.0,
            br * 0.9,
            segments=8,
            color="#5c6672",
            opacity=0.0,
            solid=True,
        )
    # Hidden Spirit Crystal Cairn tucked inside the West grove at (-8.6, 5.6)
    cx_w, cz_w = -8.6, 5.6
    cy_w = gy(cx_w, cz_w)
    b.add_cylinder(
        "whisper_cairn_pedestal",
        [cx_w, cy_w + 0.22, cz_w],
        0.22,
        0.34,
        0.44,
        segments=9,
        color="#66707d",
        solid=True,
    )
    b.add_poly(
        "whisper_spirit_crystal",
        "octahedron",
        [cx_w, cy_w + 0.72, cz_w],
        [0.20, 0],
        scale=[0.8, 1.6, 0.8],
        color="#a5f3fc",
        emissive="#22d3ee",
        emissive_intensity=0.95,
        roughness=0.18,
    )

    # =========================================================================
    # 6. DISCOVERY LANDMARK C (North): BROKEN RING OBSERVATORY KNOLL (+0.34 m hill!)
    # =========================================================================
    nkx, nkz = 0.0, 11.8
    nky = gy(nkx, nkz)
    # Iconic tilted Ancient Broken Stone Ring crowning the climbable north grassy hill
    b.add_poly(
        "solitude_broken_ring",
        "torus",
        [nkx, nky + 1.45, nkz + 0.35],
        [1.55, 0.20, 8, 28],
        rot=[0.32, 0.25, -0.18],
        color="#7a8594",
        emissive="#38bdf8",
        emissive_intensity=0.22,
        roughness=0.82,
        metalness=0.18,
    )
    b.add_poly(
        "solitude_ring_beacon",
        "octahedron",
        [nkx, nky + 1.45, nkz + 0.35],
        [0.24, 0],
        scale=[0.85, 1.4, 0.85],
        color="#e0f2fe",
        emissive="#38bdf8",
        emissive_intensity=0.92,
        roughness=0.18,
    )

    # =========================================================================
    # 7. DISCOVERY LANDMARK D (SE): SUNKEN DEW POND & NARROW STONE FOOTBRIDGE
    # =========================================================================
    px, pz = 6.0, 1.4
    # Tranquil glassy moonlit dew pond surface sitting inside the recessed terrain hollow
    b.add_cylinder(
        "dew_pond_water",
        [px, -0.068, pz],
        1.48,
        1.48,
        0.014,
        segments=24,
        color="#1d5f7a",
        emissive="#0c4a6e",
        emissive_intensity=0.62,
        roughness=0.12,
        metalness=0.45,
        opacity=0.88,
        flat_shading=False,
        solid=False,
    )
    # Walkable narrow 0.50 m weathered stone slab footbridge spanning across the dew pond!
    br_y = 0.015
    b.add_ramp("dew_bridge_ramp_w", 4.35, gy(4.35, pz), pz, 4.95, br_y, pz, width=0.50, color="#7d8691")
    b.add_box(
        "dew_bridge_span",
        [px, br_y - 0.03, pz],
        [2.14, 0.06, 0.50],
        color="#848e9a",
        emissive="#1e293b",
        emissive_intensity=0.12,
        flat_shading=True,
        solid=True,
    )
    b.add_ramp("dew_bridge_ramp_e", 7.05, br_y, pz, 7.65, gy(7.65, pz), pz, width=0.50, color="#7d8691")

    # =========================================================================
    # 8. DISCOVERY LANDMARK E (SW): LONELY REST BENCH, FLAGSTONE STEPS & LANTERN
    # =========================================================================
    bx, bz = -6.4, 1.6
    by = gy(bx, bz)
    # Ancient weathered stone bench for rest & reflection
    b.add_box(
        "rest_bench_seat",
        [bx, by + 0.34, bz],
        [1.25, 0.12, 0.42],
        rot=[0.0, 0.55, 0.0],
        color="#7a8491",
        roughness=0.9,
        flat_shading=True,
        solid=True,
    )
    for side, off in (("l", -0.44), ("r", 0.44)):
        lx = bx + math.cos(0.55) * off
        lz = bz - math.sin(0.55) * off
        b.add_box(
            f"rest_bench_leg_{side}",
            [lx, by + 0.15, lz],
            [0.18, 0.30, 0.36],
            rot=[0.0, 0.55, 0.0],
            color="#66707c",
            roughness=0.92,
            flat_shading=True,
            solid=True,
        )
    # Two gentle robot-scale weathered threshold slabs (10 mm & 13 mm) in front of the rest shrine
    b.add_box(
        "rest_step_1",
        [bx + 0.72, gy(bx + 0.72, bz + 0.85) + 0.005, bz + 0.85],
        [0.95, 0.010, 0.08],
        rot=[0.0, 0.55, 0.0],
        color="#7c8794",
        solid=True,
    )
    b.add_box(
        "rest_step_2",
        [bx + 1.05, gy(bx + 1.05, bz + 1.32) + 0.0065, bz + 1.32],
        [0.95, 0.013, 0.08],
        rot=[0.0, 0.55, 0.0],
        color="#7c8794",
        solid=True,
    )
    # Warm ancient stone lantern beside the bench
    lx_s, lz_s = bx - 0.95, bz + 0.65
    ly_s = gy(lx_s, lz_s)
    b.add_cylinder(
        "rest_lantern_post",
        [lx_s, ly_s + 0.42, lz_s],
        0.10,
        0.15,
        0.84,
        segments=8,
        color="#68727f",
        solid=True,
    )
    b.add_poly(
        "rest_lantern_flame",
        "octahedron",
        [lx_s, ly_s + 0.94, lz_s],
        [0.11, 0],
        color="#fef08a",
        emissive="#f59e0b",
        emissive_intensity=0.96,
    )

    # =========================================================================
    # 9. ORGANIC LOW-POLY GRASS TUFTS, WILDFLOWERS & DISTANT STANDING STONES
    #    Every tuft is placed at exact gy(x, z) so ZERO float or clip!
    # =========================================================================
    tuft_colors = ["#3c6e3b", "#4c8244", "#5b914c", "#356136", "#669952"]
    for idx in range(44):
        ang = idx * 2.39996  # golden angle natural scatter
        rad = 2.0 + (idx % 11) * 0.95
        tx = RING_X + math.sin(ang) * rad
        tz = RING_Z + math.cos(ang) * rad
        # Keep spawn clearing, path corridor, and pond water clear
        if math.hypot(tx, tz) < 1.1 or (abs(tx) < 0.75 and -0.4 < tz < 4.5):
            continue
        if math.hypot(tx - 6.0, tz - 1.4) < 1.75:
            continue
        ty = gy(tx, tz)
        h_tuft = 0.10 + (idx % 4) * 0.045
        b.add_poly(
            f"grass_tuft_{idx}",
            "cone",
            [tx, ty + h_tuft * 0.45, tz],
            [0.065 + (idx % 3) * 0.02, h_tuft, 5],
            rot=[0.12 * math.sin(idx), idx * 0.7, 0.12 * math.cos(idx)],
            color=tuft_colors[idx % len(tuft_colors)],
            emissive="#142d16",
            emissive_intensity=0.14,
            roughness=0.9,
        )
        # Occasional tiny moonlit wildflower bud on meadow tufts
        if idx % 5 == 0:
            b.add_poly(
                f"wildflower_{idx}",
                "octahedron",
                [tx + 0.05, ty + h_tuft + 0.02, tz - 0.03],
                [0.028, 0],
                color="#fef08a" if idx % 10 == 0 else "#bae6fd",
                emissive="#f59e0b" if idx % 10 == 0 else "#38bdf8",
                emissive_intensity=0.75,
            )

    # 8 Distant lonely outer hilltop monoliths on the highland basin rim
    for idx in range(8):
        ang = idx * (math.pi / 4.0) + 0.35
        ox = RING_X + math.sin(ang) * 14.2
        oz = RING_Z + math.cos(ang) * 14.2
        oy = gy(ox, oz)
        oh = 2.6 + (idx % 3) * 0.8
        b.add_box(
            f"distant_rim_stone_{idx}",
            [ox, oy + oh / 2.0 - 0.25, oz],
            [0.65, oh, 0.55],
            rot=[0.08 * math.sin(idx), ang, 0.06 * math.cos(idx)],
            color="#586270",
            emissive="#1e293b",
            emissive_intensity=0.12,
            roughness=0.92,
            flat_shading=True,
            solid=False,
        )

    # =========================================================================
    # 10. SERENE TWILIGHT LIGHTING (Centered on the Single Glowing Firefly!)
    # =========================================================================
    b.add_light("light_firefly", [RING_X, ff_y + 0.15, RING_Z], "#fde68a", 3.6, 13.0)
    b.add_light("light_south_gate", [0.0, 1.5, 0.9], "#fcd34d", 1.8, 8.0)
    b.add_light("light_north_ring", [nkx, nky + 1.8, nkz], "#7dd3fc", 2.4, 11.0)
    b.add_light("light_east_solstice", [8.4, ey_top + 1.1, 5.4], "#fbbf24", 1.8, 8.0)
    b.add_light("light_west_whisper", [cx_w, cy_w + 1.1, cz_w], "#38bdf8", 1.8, 8.0)
    b.add_light("light_sw_lantern", [lx_s, ly_s + 1.2, lz_s], "#fdba74", 1.8, 7.5)

    payload: dict[str, Any] = {
        "schemaVersion": 2,
        "id": "solitude",
        "name": "Solitude (Stonehenge Plain)",
        "subtitle": "Glowing ancient Stonehenge, rolling grassy plain & the single firefly",
        "worldOriginThree": [0.0, 0.0, 0.0],
        "skyboxDir": "/assets/skyboxes/observatory",
        "backgroundHex": "#121b2d",
        "fogHex": "#1c2a42",
        "fogDensity": 0.0052,
        "useDefaultFloorPlane": False,
        "terrainStyle": "grassy-plain",
        "robotSpawnMj": [0.0, 0.0, 0.066],
        "primitives": b.primitives,
        "glbInstances": [],
        "colliders": b.colliders,
        "hfield": hfield_spec,
        "lights": b.lights,
    }
    return payload, hfield_bytes
