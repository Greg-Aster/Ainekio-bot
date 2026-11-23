#!/usr/bin/env python3
"""
Procedural low-poly Sci Fi Room — Far-Future Surreal Fantasy House
("Astral Pavilion") Robot Exploration & Obstacle Course builder
(`sci-fi-room.level.json`).

A dreamlike, incomprehensible residence 10,000 years in the future floating above
a mirrored astral sea — blending Moebius/Monument-Valley impossible architecture
with playful robot-scale obstacle courses for Ainekio V2:
  - Pearl-ivory & indigo inlaid Atrium Deck (y = 0.000 m) with glowing sacred
    golden circuit paths and 10mm / 13mm prismatic glass thresholds.
  - 8 Cantilevered Ivory-Gold Vault Arches opening onto a suspended rotating
    Tesseractic Prism & triple Gyroscopic Astrolabe Rings overhead!
  - Central Chronos-Orrery Hearth: stepped 11mm octagonal pearl dais with a
    levitating liquid-gold orb & 3 counter-rotating rings (walk-under arches!).
  - East Wing — Escher Mezzanine & Levitation Lounge: 6.5 deg climbable aqua-glass
    ramp -> +0.18 m floating mezzanine -> hovering sofa & table over cyan anti-grav
    emitters -> impossible floating Monument-Valley staircase leading into a
    midair glowing rose-gold portal doorway!
  - West Wing — Biomechanical Astral Garden: 3 helical crystal-botanical spiral
    plants with floating glowing lotus blossoms (slalom weave), 9/12/15 mm quartz
    bars, and a levitating glass terrarium dome!
  - North Balcony — Infinity Mirror Bridge (0.50 m narrow prismatic span with
    5 deg ramps over a glowing reflection pool) out to a floating Starlight
    Portal Gazebo overlooking levitating inverted crystal pyramids in the sky!
  - Zero heavy GLBs, 100% crisp faceted simple polygons, exact MuJoCo colliders.

Coordinate convention (Three.js, local-origin centered at robot spawn):
  - Robot spawns at (0, 0, 0) on the Pearl Atrium Walkway facing +Z toward
    the Chronos-Orrery Hearth & Starlight Portal Gazebo.
"""

from __future__ import annotations

import math
from typing import Any

from build_yggdrasil_level import _SceneBuilder


def build_scifi_room_level() -> dict[str, Any]:
    b = _SceneBuilder()
    cx, cz = 0.0, 4.4

    # =========================================================================
    # 1. FLOATING PEARL-IVORY ATRIUM PAVILION DECK (y = 0.000 m)
    # =========================================================================
    # Main octagonal pearl-ivory floating house platform (radius 8.4 m centered at (0, 4.4))
    # Top strictly at y = 0.000 m so spawn (0, 0, 0) rests cleanly flush!
    b.add_cylinder(
        "pavilion_main_deck",
        [cx, -0.18, cz],
        8.4,
        7.4,
        0.36,
        segments=8,
        rot=[0.0, math.pi / 8.0, 0.0],
        color="#d8dee9",
        emissive="#1e1b4b",
        emissive_intensity=0.12,
        metalness=0.22,
        roughness=0.45,
        flat_shading=True,
        solid=True,
    )
    # Dark indigo-gold floating substructure hull beneath the pearl floor
    b.add_cylinder(
        "pavilion_under_hull",
        [cx, -0.52, cz],
        6.8,
        3.2,
        0.42,
        segments=8,
        rot=[0.0, math.pi / 8.0, 0.0],
        color="#1e1b4b",
        emissive="#312e81",
        emissive_intensity=0.35,
        metalness=0.55,
        roughness=0.35,
        solid=False,
    )
    # South cantilevered pearl arrival porch extending smoothly under spawn (z = -2.2 .. +0.8)
    b.add_box(
        "pavilion_entry_porch",
        [0.0, -0.14, -1.6],
        [2.6, 0.28, 3.2],
        color="#cfd8e6",
        emissive="#1e1b4b",
        emissive_intensity=0.12,
        metalness=0.22,
        roughness=0.46,
        flat_shading=True,
        solid=True,
    )
    # Deep indigo obsidian runner & glowing golden sacred-geometry floor circuit inlays
    b.add_box(
        "atrium_indigo_runner",
        [0.0, 0.002, 1.3],
        [1.15, 0.004, 6.2],
        color="#1e1b4b",
        emissive="#312e81",
        emissive_intensity=0.32,
        metalness=0.45,
        roughness=0.28,
        solid=False,
    )
    for side, sx in (("l", 0.60), ("r", -0.60)):
        b.add_box(
            f"atrium_gold_circuit_{side}",
            [sx, 0.003, 1.3],
            [0.04, 0.005, 6.2],
            color="#fde68a",
            emissive="#f59e0b",
            emissive_intensity=0.88,
            metalness=0.75,
            roughness=0.2,
            solid=False,
        )
    # Two luminous prismatic threshold bars (10 mm aqua & 13 mm rose-gold) along entry walkway!
    b.add_box(
        "atrium_threshold_1",
        [0.0, 0.005, 0.92],
        [1.08, 0.010, 0.045],
        color="#67e8f9",
        emissive="#06b6d4",
        emissive_intensity=0.72,
        metalness=0.35,
        roughness=0.22,
        solid=True,
    )
    b.add_box(
        "atrium_threshold_2",
        [0.0, 0.0065, 1.78],
        [1.08, 0.013, 0.050],
        color="#f9a8d4",
        emissive="#ec4899",
        emissive_intensity=0.75,
        metalness=0.35,
        roughness=0.22,
        solid=True,
    )

    # =========================================================================
    # 2. 8 IMPOSSIBLE CANTILEVERED IVORY-GOLD VAULT ARCHES & SUSPENDED ASTROLABE
    #    Ribs curve skyward to y = 8.4 m and float apart around a central
    #    rotating Tesseractic Prism & triple Gyroscopic Astrolabe Rings!
    # =========================================================================
    for idx in range(8):
        ang = idx * (math.pi / 4.0) + math.pi / 8.0
        sa, ca = math.sin(ang), math.cos(ang)
        p0 = [cx + sa * 7.55, 0.0, cz + ca * 7.55]
        p1 = [cx + sa * 7.95, 3.6, cz + ca * 7.95]
        p2 = [cx + sa * 5.80, 6.8, cz + ca * 5.80]
        p3 = [cx + sa * 2.90, 8.3, cz + ca * 2.90]
        b.add_segment(
            f"vault_arch_{idx}_a",
            p0,
            p1,
            0.28,
            0.22,
            segments=8,
            color="#e2e8f0",
            emissive="#312e81",
            emissive_intensity=0.14,
            metalness=0.3,
            roughness=0.4,
            solid=True,
        )
        b.add_segment(
            f"vault_arch_{idx}_b",
            p1,
            p2,
            0.22,
            0.16,
            segments=7,
            color="#f1f5f9",
            emissive="#4c1d95",
            emissive_intensity=0.16,
            metalness=0.35,
            roughness=0.38,
            solid=False,
        )
        b.add_segment(
            f"vault_arch_{idx}_c",
            p2,
            p3,
            0.16,
            0.09,
            segments=6,
            color="#fde68a",
            emissive="#f59e0b",
            emissive_intensity=0.65,
            metalness=0.72,
            roughness=0.25,
            solid=False,
        )
        # Floating glowing crystal finial hovering past the open tip of each cantilevered arch!
        b.add_poly(
            f"surreal_float_finial_{idx}",
            "octahedron",
            [cx + sa * 2.25, 8.55, cz + ca * 2.25],
            [0.18, 0],
            scale=[0.8, 1.5, 0.8],
            color="#a5f3fc" if idx % 2 == 0 else "#f9a8d4",
            emissive="#22d3ee" if idx % 2 == 0 else "#ec4899",
            emissive_intensity=0.95,
            roughness=0.15,
        )

    # Suspended Impossible Tesseractic Prism & Triple Gyroscopic Astrolabe high in the oculus (y = 6.2 m)
    b.add_poly(
        "surreal_spin_tesseract_outer",
        "octahedron",
        [cx, 6.2, cz],
        [1.15, 0],
        color="#c4b5fd",
        emissive="#8b5cf6",
        emissive_intensity=0.85,
        opacity=0.42,
        roughness=0.14,
    )
    b.add_poly(
        "surreal_spin_tesseract_core",
        "icosahedron",
        [cx, 6.2, cz],
        [0.58, 0],
        color="#fef08a",
        emissive="#f59e0b",
        emissive_intensity=1.0,
        roughness=0.12,
    )
    for r_idx, (rad, col, em, rot) in enumerate(
        [
            (2.05, "#fde68a", "#f59e0b", [0.45, 0.2, 0.1]),
            (2.65, "#67e8f9", "#06b6d4", [1.15, -0.3, 0.4]),
            (3.25, "#f9a8d4", "#db2777", [0.25, 0.8, 0.9]),
        ]
    ):
        b.add_poly(
            f"surreal_spin_astrolabe_{r_idx}",
            "torus",
            [cx, 6.2, cz],
            [rad, 0.055, 6, 36],
            rot=rot,
            color=col,
            emissive=em,
            emissive_intensity=0.88,
            metalness=0.65,
            roughness=0.22,
        )

    # =========================================================================
    # 3. CENTERPIECE: CHRONOS-ORRERY HEARTH (x = 0, z = +4.4 m)
    #    11 mm stepped octagonal pearl dais with walk-under cantilevered arches
    #    supporting a levitating liquid-gold orb & 3 counter-rotating rings!
    # =========================================================================
    b.add_cylinder(
        "chronos_hearth_dais",
        [cx, 0.0055, cz],
        1.85,
        1.95,
        0.011,
        segments=8,
        rot=[0.0, math.pi / 8.0, 0.0],
        color="#e2e8f0",
        emissive="#312e81",
        emissive_intensity=0.16,
        metalness=0.28,
        roughness=0.38,
        solid=True,
    )
    b.add_poly(
        "chronos_hearth_ring_inlay",
        "torus",
        [cx, 0.013, cz],
        [1.52, 0.024, 6, 32],
        rot=[math.pi / 2.0, 0.0, 0.0],
        color="#67e8f9",
        emissive="#06b6d4",
        emissive_intensity=0.9,
        roughness=0.2,
    )
    # 4 graceful cantilevered ivory-gold legs leaving 0.42 m walk-under clearance right through center!
    for idx in range(4):
        ang = idx * (math.pi / 2.0) + math.pi / 4.0
        sa, ca = math.sin(ang), math.cos(ang)
        p_foot = [cx + sa * 1.48, 0.01, cz + ca * 1.48]
        p_knee = [cx + sa * 1.12, 0.62, cz + ca * 1.12]
        p_tip = [cx + sa * 0.56, 1.05, cz + ca * 0.56]
        b.add_segment(f"orrery_leg_{idx}_a", p_foot, p_knee, 0.09, 0.06, segments=6, color="#cbd5e1", solid=True)
        b.add_segment(
            f"orrery_leg_{idx}_b",
            p_knee,
            p_tip,
            0.06,
            0.03,
            segments=6,
            color="#fde68a",
            emissive="#f59e0b",
            emissive_intensity=0.5,
            solid=False,
        )
    # Levitating Liquid-Gold Core & 3 Miniature Counter-Rotating Harmonic Rings
    b.add_poly(
        "surreal_float_orrery_core",
        "icosahedron",
        [cx, 1.25, cz],
        [0.34, 1],
        color="#fef08a",
        emissive="#f59e0b",
        emissive_intensity=1.0,
        metalness=0.45,
        roughness=0.14,
    )
    for r_i, (rad, col, em, rot) in enumerate(
        [
            (0.62, "#67e8f9", "#06b6d4", [0.6, 0.0, 0.25]),
            (0.84, "#f9a8d4", "#ec4899", [1.3, 0.5, -0.3]),
            (1.05, "#fde68a", "#f59e0b", [0.2, -0.8, 1.1]),
        ]
    ):
        b.add_poly(
            f"surreal_spin_orrery_ring_{r_i}",
            "torus",
            [cx, 1.25, cz],
            [rad, 0.022, 6, 28],
            rot=rot,
            color=col,
            emissive=em,
            emissive_intensity=0.92,
            roughness=0.2,
        )

    # =========================================================================
    # 4. EAST WING (+X): ESCHER MEZZANINE, LEVITATION LOUNGE & FLOATING STAIRS
    # =========================================================================
    mez_y = 0.18
    # Seamless 6.5 deg aqua-glass climbable ramp UP (x = 3.2, z = 1.4 -> 3.0)
    b.add_ramp(
        "escher_ramp_up",
        3.2,
        0.0,
        1.4,
        3.2,
        mez_y,
        3.0,
        width=0.86,
        color="#bae6fd",
        emissive="#0284c7",
        emissive_intensity=0.35,
    )
    # Floating Mezzanine Pearl Deck (x = 2.6..5.6, z = 3.0..5.6, top strictly at y = +0.180 m!)
    b.add_box(
        "escher_mezzanine_deck",
        [4.15, mez_y / 2.0, 4.30],
        [3.0, mez_y, 2.60],
        color="#e2e8f0",
        emissive="#312e81",
        emissive_intensity=0.16,
        metalness=0.25,
        roughness=0.42,
        flat_shading=True,
        solid=True,
    )
    # Seamless 6.5 deg return ramp DOWN heading North (x = 3.2, z = 5.6 -> 7.2)
    b.add_ramp(
        "escher_ramp_down",
        3.2,
        mez_y,
        5.6,
        3.2,
        0.0,
        7.2,
        width=0.86,
        color="#bae6fd",
        emissive="#0284c7",
        emissive_intensity=0.35,
    )
    # Levitating Sculptural Lounge Sofa & Floating Orb Table hovering over cyan anti-grav pads!
    b.add_cylinder(
        "antigrav_pad_sofa",
        [4.85, mez_y + 0.004, 4.35],
        0.72,
        0.76,
        0.008,
        segments=16,
        color="#67e8f9",
        emissive="#06b6d4",
        emissive_intensity=0.9,
        solid=False,
    )
    b.add_box(
        "surreal_float_sofa_seat",
        [4.85, mez_y + 0.36, 4.35],
        [0.62, 0.14, 1.55],
        color="#f5d0fe",
        emissive="#a21caf",
        emissive_intensity=0.22,
        roughness=0.55,
        solid=False,
    )
    b.add_box(
        "surreal_float_sofa_back",
        [5.12, mez_y + 0.62, 4.35],
        [0.14, 0.44, 1.55],
        color="#f0abfc",
        emissive="#86198f",
        emissive_intensity=0.22,
        roughness=0.55,
        solid=False,
    )
    b.add_poly(
        "surreal_float_coffee_orb",
        "dodecahedron",
        [4.05, mez_y + 0.44, 4.35],
        [0.26, 0],
        scale=[1.15, 0.45, 1.15],
        color="#fde68a",
        emissive="#f59e0b",
        emissive_intensity=0.62,
        metalness=0.55,
        roughness=0.2,
    )

    # IMPOSSIBLE MONUMENT-VALLEY FLOATING STAIRCASE spiraling up into a midair Rose-Gold Doorway!
    for step_i in range(11):
        ang = -0.3 + step_i * 0.26
        sx = 5.3 + math.sin(ang) * 1.45
        sz = 5.2 + math.cos(ang) * 1.45
        sy = 0.85 + step_i * 0.36
        b.add_box(
            f"surreal_float_escher_step_{step_i}",
            [sx, sy, sz],
            [0.72, 0.08, 0.34],
            rot=[0.0, ang, 0.0],
            color="#e2e8f0" if step_i % 2 == 0 else "#bae6fd",
            emissive="#6366f1",
            emissive_intensity=0.28,
            metalness=0.35,
            roughness=0.35,
            solid=False,
        )
    # Floating Midair Rose-Gold Dimensional Doorway at the top of the impossible stairs!
    dx_door, dy_door, dz_door = 5.85, 5.25, 3.85
    for side, off in (("l", -0.58), ("r", 0.58)):
        b.add_box(
            f"escher_door_jamb_{side}",
            [dx_door, dy_door, dz_door + off],
            [0.16, 2.05, 0.16],
            color="#fde68a",
            emissive="#f59e0b",
            emissive_intensity=0.75,
            solid=False,
        )
    b.add_box(
        "escher_door_lintel",
        [dx_door, dy_door + 1.02, dz_door],
        [0.18, 0.16, 1.36],
        color="#fde68a",
        emissive="#f59e0b",
        emissive_intensity=0.75,
        solid=False,
    )
    b.add_box(
        "escher_door_veil",
        [dx_door, dy_door, dz_door],
        [0.04, 1.90, 1.04],
        color="#f472b6",
        emissive="#db2777",
        emissive_intensity=0.95,
        opacity=0.58,
        solid=False,
    )

    # =========================================================================
    # 5. WEST WING (-X): BIOMECHANICAL ASTRAL GARDEN & CRYSTAL BONSAI SLALOM
    # =========================================================================
    planter_spots = [
        (-3.2, 2.2, "#34d399", "#10b981"),
        (-4.5, 3.6, "#67e8f9", "#06b6d4"),
        (-3.3, 5.2, "#f9a8d4", "#ec4899"),
    ]
    for idx, (px, pz, b_col, b_em) in enumerate(planter_spots):
        # Sculpted pearl-and-indigo hexagonal planter basin (slalom obstacle!)
        b.add_cylinder(
            f"astral_planter_{idx + 1}",
            [px, 0.18, pz],
            0.46,
            0.34,
            0.36,
            segments=6,
            color="#312e81",
            emissive="#1e1b4b",
            emissive_intensity=0.35,
            metalness=0.45,
            roughness=0.4,
            solid=True,
        )
        # Helical twisting golden-emerald biomechanical stem rising from the planter
        prev = [px, 0.34, pz]
        for s_i in range(1, 6):
            sa = idx * 1.4 + s_i * 0.95
            rr = 0.12 + s_i * 0.055
            nxt = [px + math.sin(sa) * rr, 0.34 + s_i * 0.34, pz + math.cos(sa) * rr]
            b.add_segment(
                f"spiral_stem_{idx}_{s_i}",
                prev,
                nxt,
                0.055 - s_i * 0.007,
                0.048 - s_i * 0.007,
                segments=6,
                color="#34d399" if s_i % 2 == 0 else "#fcd34d",
                emissive="#059669",
                emissive_intensity=0.45,
                solid=False,
            )
            prev = nxt
        # Floating glowing crystal lotus blossom hovering above the spiral stem!
        b.add_poly(
            f"surreal_spin_blossom_{idx + 1}",
            "octahedron",
            [prev[0], prev[1] + 0.24, prev[2]],
            [0.24, 0],
            scale=[1.15, 0.85, 1.15],
            color=b_col,
            emissive=b_em,
            emissive_intensity=0.95,
            roughness=0.16,
        )

    # 3 Progressive Luminous Quartz Stepping Bars (9 mm, 12 mm, 15 mm) across the Garden!
    for idx, (rz, rh, q_col, q_em) in enumerate(
        [
            (2.85, 0.009, "#6ee7b7", "#10b981"),
            (3.95, 0.012, "#67e8f9", "#06b6d4"),
            (5.15, 0.015, "#c4b5fd", "#7c3aed"),
        ]
    ):
        b.add_box(
            f"quartz_ridge_{idx + 1}",
            [-3.85, rh / 2.0, rz],
            [1.15, rh, 0.052],
            rot=[0.0, (idx - 1) * 0.16, 0.0],
            color=q_col,
            emissive=q_em,
            emissive_intensity=0.65,
            solid=True,
        )

    # Levitating Glass Terrarium Dome hovering on the far West garden edge!
    b.add_poly(
        "surreal_float_terrarium_glass",
        "icosahedron",
        [-5.6, 1.45, 4.4],
        [0.88, 1],
        color="#a5f3fc",
        emissive="#0891b2",
        emissive_intensity=0.42,
        opacity=0.26,
        roughness=0.12,
    )
    b.add_poly(
        "surreal_float_terrarium_island",
        "dodecahedron",
        [-5.6, 1.38, 4.4],
        [0.44, 0],
        scale=[1.15, 0.52, 1.15],
        color="#34d399",
        emissive="#059669",
        emissive_intensity=0.65,
        roughness=0.55,
    )

    # =========================================================================
    # 6. NORTH BALCONY (+Z): INFINITY MIRROR BRIDGE & STARLIGHT PORTAL GAZEBO
    # =========================================================================
    # Narrow 0.50 m prismatic bridge (5 deg entry/exit ramps, span at +0.045 m)
    # crossing the astral mirror sea from the main pavilion (z=8.4) to the Floating Gazebo (z=11.6)!
    b.add_ramp("mirror_bridge_ramp_s", 0.0, 0.0, 7.65, 0.0, 0.045, 8.20, width=0.52, color="#c7d2fe")
    b.add_box(
        "mirror_bridge_span",
        [0.0, 0.015, 9.50],
        [0.52, 0.06, 2.65],
        color="#c7d2fe",
        emissive="#6366f1",
        emissive_intensity=0.45,
        metalness=0.45,
        roughness=0.25,
        solid=True,
    )
    b.add_ramp("mirror_bridge_ramp_n", 0.0, 0.045, 10.80, 0.0, 0.0, 11.35, width=0.52, color="#c7d2fe")

    # Detached Floating Starlight Gazebo Platform (centered at (0, 13.0), top strictly y = 0.000 m!)
    b.add_cylinder(
        "gazebo_floating_deck",
        [0.0, -0.14, 13.0],
        2.15,
        1.55,
        0.28,
        segments=16,
        color="#e2e8f0",
        emissive="#312e81",
        emissive_intensity=0.22,
        metalness=0.35,
        roughness=0.38,
        solid=True,
    )
    # 3 Nested Rotating Surreal Portal Rings framing a Shimmering Turquoise Dimensional Window!
    for p_i, (rad, col, em, rot) in enumerate(
        [
            (1.42, "#fde68a", "#f59e0b", [0.0, 0.0, 0.0]),
            (1.14, "#c4b5fd", "#7c3aed", [0.18, 0.22, 0.0]),
            (0.86, "#67e8f9", "#06b6d4", [-0.15, -0.25, 0.0]),
        ]
    ):
        b.add_poly(
            f"surreal_spin_portal_ring_{p_i}",
            "torus",
            [0.0, 1.75, 13.85],
            [rad, 0.06, 6, 32],
            rot=rot,
            color=col,
            emissive=em,
            emissive_intensity=0.92,
            roughness=0.18,
        )
    b.add_poly(
        "portal_window_veil",
        "cylinder",
        [0.0, 1.75, 13.85],
        [0.78, 0.78, 0.04, 24],
        rot=[math.pi / 2.0, 0.0, 0.0],
        color="#5eead4",
        emissive="#14b8a6",
        emissive_intensity=0.95,
        opacity=0.45,
        roughness=0.12,
    )

    # =========================================================================
    # 7. SURREAL FAR-FUTURE SKY & FLOATING CITADEL HORIZON (PURE WONDER!)
    # =========================================================================
    # 6 Distant Levitating Inverted Crystal Pyramids hovering above the mirror sea!
    for idx, (ox, oy, oz, rad, h, col, em) in enumerate(
        [
            (-16.0, 5.2, 16.0, 2.2, 5.6, "#c4b5fd", "#6d28d9"),
            (17.5, 6.4, 15.0, 2.5, 6.2, "#fde68a", "#d97706"),
            (-18.5, 3.8, -2.5, 1.8, 4.4, "#67e8f9", "#0284c7"),
            (18.0, 4.5, -3.5, 2.0, 4.8, "#f9a8d4", "#be185d"),
            (-8.5, 8.2, 26.5, 2.8, 7.2, "#a5f3fc", "#0891b2"),
            (9.5, 7.8, 27.0, 2.6, 6.8, "#ddd6fe", "#7c3aed"),
        ]
    ):
        b.add_poly(
            f"surreal_float_pyramid_{idx}",
            "cone",
            [ox, oy, oz],
            [rad, h, 4],
            rot=[math.pi, idx * 0.6, 0.0],  # inverted floating pyramid!
            color=col,
            emissive=em,
            emissive_intensity=0.42,
            metalness=0.45,
            roughness=0.35,
        )

    # Twin Colossal Celestial Planetary Rings arcing across the distant sky!
    b.add_poly(
        "celestial_sky_ring_1",
        "torus",
        [cx, 12.0, cz + 8.0],
        [30.0, 0.24, 6, 60],
        rot=[1.12, 0.25, -0.18],
        color="#fde68a",
        emissive="#f59e0b",
        emissive_intensity=0.72,
        opacity=0.65,
    )
    b.add_poly(
        "celestial_sky_ring_2",
        "torus",
        [cx, 14.0, cz + 8.0],
        [36.0, 0.18, 6, 60],
        rot=[1.35, -0.22, 0.28],
        color="#a5f3fc",
        emissive="#06b6d4",
        emissive_intensity=0.68,
        opacity=0.52,
    )

    # 22 Drifting Prismatic Luminescence Motes hovering throughout the house
    mote_colors = [
        ("#fef08a", "#f59e0b"),
        ("#67e8f9", "#06b6d4"),
        ("#f9a8d4", "#ec4899"),
        ("#c4b5fd", "#8b5cf6"),
    ]
    for idx in range(22):
        ang = idx * 2.39996
        rad = 2.0 + (idx % 6) * 1.15
        my = 0.9 + (idx % 7) * 0.95
        mc, mem = mote_colors[idx % len(mote_colors)]
        b.add_poly(
            f"surreal_float_mote_{idx}",
            "octahedron",
            [cx + math.sin(ang) * rad, my, cz + math.cos(ang) * rad],
            [0.055 + (idx % 3) * 0.02, 0],
            color=mc,
            emissive=mem,
            emissive_intensity=1.0,
            roughness=0.14,
        )

    # =========================================================================
    # 8. ETHEREAL FAR-FUTURE PRISMATIC LIGHTING (8 Atmospheric Point Lights!)
    # =========================================================================
    b.add_light("light_orrery_gold", [cx, 1.8, cz], "#fde68a", 3.6, 14.0)
    b.add_light("light_astrolabe_sky", [cx, 6.4, cz], "#c4b5fd", 4.2, 22.0)
    b.add_light("light_escher_door", [5.2, 4.6, 3.8], "#f472b6", 3.0, 14.0)
    b.add_light("light_lounge_cyan", [4.2, 1.5, 4.3], "#38bdf8", 2.4, 10.0)
    b.add_light("light_garden_mint", [-4.0, 1.6, 3.8], "#2dd4bf", 2.8, 11.0)
    b.add_light("light_gazebo_portal", [0.0, 2.0, 13.0], "#c084fc", 3.2, 14.0)
    b.add_light("light_entry_champagne", [0.0, 1.6, 0.8], "#fef08a", 2.0, 9.0)
    b.add_light("light_mirror_bridge", [0.0, 1.2, 9.5], "#60a5fa", 2.2, 10.0)

    return {
        "schemaVersion": 2,
        "id": "sci-fi-room",
        "name": "Sci Fi Room (Astral House)",
        "subtitle": "Surreal far-future house · Chronos-Orrery, Escher stairs, crystal garden & portals",
        "worldOriginThree": [0.0, 0.0, 0.0],
        "skyboxDir": "/assets/skyboxes/observatory",
        "backgroundHex": "#0d1026",
        "fogHex": "#1b1f42",
        "fogDensity": 0.0044,
        "useDefaultFloorPlane": False,
        "robotSpawnMj": [0.0, 0.0, 0.066],
        "primitives": b.primitives,
        "glbInstances": [],
        "colliders": b.colliders,
        "lights": b.lights,
        "water": {
            "y": -0.65,
            "size": 640,
            "color": "#111938",
            "opacity": 0.90,
        },
    }
