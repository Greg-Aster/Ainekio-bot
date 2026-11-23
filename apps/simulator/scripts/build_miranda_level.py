#!/usr/bin/env python3
"""
Procedural low-poly Miranda Wreck — Derelict Cosmic-Horror Starship Interior
& Deep-Space Asteroid Field / Dying Star Robot Obstacle Course builder
(`miranda.level.json`).

Features designed specifically for Ainekio V2 exploration & obstacle traversal:
  - Main Spine Corridor & Airlock Vestibule (y = 0.000 m) with 9mm & 12mm
    deck cable bundles, glowing emergency strips, structural hull ribs, and
    creeping dark-violet cosmic anomaly tendrils.
  - Twin Climbable Bridge Stairway Ramps (exact 6.5 deg MuJoCo ramp colliders
    with visual stair treads & amber handrails) rising smoothly to the elevated
    Command Bridge (+0.24 m)!
  - Command Bridge with Captain's Chair, 4 angled glowing consoles, central
    holographic star-map table, and a massive panoramic Forward Viewport looking
    straight out at a colossal bleeding crimson Dying Star, its warped burning
    accretion disk, and 35+ drifting jagged asteroids & sheared hull debris!
  - East Wing: Crew Quarters & Medbay (double-tier bunks, footlockers, cracked
    cyan cryo-stasis pod, obstacle weave, and starboard space porthole).
  - West Wing: Mess Hall & Galley (industrial tables, overturned table, bench
    obstacles, broken galley counter, and huge port-side asteroid porthole).
  - Aft Section: Cracked Singularity Reactor Core with pulsing crimson rings,
    cargo crates, and a 6.5 deg maintenance catwalk ramp (+0.14 m).
  - Ribbed open-frame ceiling trusses so Robot POV / Follow V2 feel deeply
    enclosed & claustrophobic while Orbit camera can inspect every deck freely!

Coordinate convention (Three.js, local-origin centered at robot spawn):
  - Robot spawns at (0, 0, 0) on the Main Spine Deck facing +Z toward the
    Bridge Stairways & Dying Star Viewport.
"""

from __future__ import annotations

import math
from typing import Any

from build_yggdrasil_level import _SceneBuilder


def build_miranda_level() -> dict[str, Any]:
    b = _SceneBuilder()

    # =========================================================================
    # 1. MAIN DECK STRUCTURAL FLOOR & BULKHEAD HULL (y = 0.000 m)
    # =========================================================================
    # Main continuous deck slab covering Spine + East Crew Quarters + West Mess Hall + Aft Reactor
    # x in [-6.0, +6.0], z in [-4.5, +9.6], top strictly at y = 0.000 m
    b.add_box(
        "miranda_main_deck",
        [0.0, -0.10, 2.55],
        [12.0, 0.20, 14.1],
        color="#232a35",
        emissive="#090d14",
        emissive_intensity=0.14,
        metalness=0.45,
        roughness=0.72,
        flat_shading=True,
        solid=True,
    )
    # Subtle contrasting grated deck runner down the Main Spine Corridor (y = +0.002 m visual)
    b.add_box(
        "spine_grate_runner",
        [0.0, 0.002, 1.4],
        [1.55, 0.004, 10.6],
        color="#313b4a",
        emissive="#0f172a",
        emissive_intensity=0.12,
        metalness=0.55,
        roughness=0.58,
        solid=False,
    )
    # Emergency deck guide light strips flanking the spine corridor
    for side, sx in (("l", 0.82), ("r", -0.82)):
        b.add_box(
            f"spine_guide_strip_{side}",
            [sx, 0.003, 1.1],
            [0.035, 0.005, 8.2],
            color="#f87171",
            emissive="#dc2626",
            emissive_intensity=0.88,
            roughness=0.25,
            solid=False,
        )

    # Industrial deck cable hazard bundles across the Main Spine (9 mm & 12 mm high!)
    b.add_box(
        "deck_cable_hazard_1",
        [0.0, 0.0045, 0.95],
        [1.42, 0.009, 0.048],
        color="#f59e0b",
        emissive="#92400e",
        emissive_intensity=0.35,
        metalness=0.35,
        roughness=0.55,
        solid=True,
    )
    b.add_box(
        "deck_cable_hazard_2",
        [0.0, 0.006, 2.45],
        [1.42, 0.012, 0.055],
        color="#ef4444",
        emissive="#991b1b",
        emissive_intensity=0.38,
        metalness=0.35,
        roughness=0.55,
        solid=True,
    )

    # Ribbed Starship Hull Structural Arch Frames along the Spine (open top for Orbit view!)
    for idx, rz in enumerate((-2.2, -0.5, 1.4, 3.2, 5.2, 7.4)):
        # Left & right angled hull ribs + overhead cross-truss
        for side, sx in (("l", 1.38), ("r", -1.38)):
            b.add_box(
                f"spine_rib_{idx}_{side}",
                [sx, 1.25, rz],
                [0.20, 2.50, 0.24],
                color="#333e4f",
                emissive="#0f172a",
                emissive_intensity=0.14,
                metalness=0.55,
                roughness=0.62,
                flat_shading=True,
                solid=True,
            )
            # Subtle glowing crimson emergency sconce on every second rib
            if idx % 2 == 1:
                b.add_box(
                    f"spine_sconce_{idx}_{side}",
                    [sx - (0.11 if sx > 0 else -0.11), 1.65, rz],
                    [0.03, 0.28, 0.08],
                    color="#fca5a5",
                    emissive="#dc2626",
                    emissive_intensity=0.95,
                    solid=False,
                )
        # Overhead girder truss beam (high at y = 2.52 m, open spacing between ribs)
        b.add_box(
            f"spine_beam_{idx}",
            [0.0, 2.52, rz],
            [3.0, 0.18, 0.24],
            color="#2b3544",
            metalness=0.55,
            roughness=0.65,
            flat_shading=True,
            solid=False,
        )

    # Interior Spine Partition Walls with Wide 1.25 m Doorways into Crew Quarters (+X) & Mess Hall (-X)
    for side, wx in (("east", 1.48), ("west", -1.48)):
        # South wall segment z = -1.6 .. +1.5
        b.add_box(
            f"spine_wall_{side}_s",
            [wx, 1.10, -0.05],
            [0.18, 2.20, 3.10],
            color="#2b3442",
            emissive="#0c1320",
            emissive_intensity=0.14,
            metalness=0.45,
            roughness=0.72,
            flat_shading=True,
            solid=True,
        )
        # North wall segment z = +2.85 .. +5.9
        b.add_box(
            f"spine_wall_{side}_n",
            [wx, 1.10, 4.38],
            [0.18, 2.20, 3.05],
            color="#2b3442",
            emissive="#0c1320",
            emissive_intensity=0.14,
            metalness=0.45,
            roughness=0.72,
            flat_shading=True,
            solid=True,
        )
        # Doorway header lintel over the 1.35 m wide doorway (z = 1.50 .. 2.85)
        b.add_box(
            f"spine_door_lintel_{side}",
            [wx, 1.95, 2.18],
            [0.24, 0.50, 1.45],
            color="#3d495b",
            metalness=0.5,
            roughness=0.6,
            solid=False,
        )
        # 10 mm steel bulkhead doorway threshold lip (authentic ship door coaming!)
        b.add_box(
            f"door_coaming_{side}",
            [wx, 0.005, 2.18],
            [0.14, 0.010, 1.28],
            color="#64748b",
            emissive="#f59e0b",
            emissive_intensity=0.22,
            metalness=0.55,
            roughness=0.45,
            solid=True,
        )

    # Outer Wing Perimeter Walls (East x=+5.9, West x=-5.9, Aft z=-4.4, Forward Bridge z=+9.5)
    # Each outer wing wall features a HUGE SPACE PORTHOLE WINDOW opening onto the asteroid field!
    def add_porthole_wall_x(name: str, wx: float, z_min: float, z_max: float, z_win_a: float, z_win_b: float) -> None:
        # Solid lower hull below porthole (y = 0 .. 0.58 m)
        b.add_box(
            f"{name}_lower",
            [wx, 0.29, 0.5 * (z_min + z_max)],
            [0.24, 0.58, z_max - z_min],
            color="#252d3a",
            metalness=0.52,
            roughness=0.68,
            flat_shading=True,
            solid=True,
        )
        # Upper hull header above porthole (y = 2.05 .. 2.55 m)
        b.add_box(
            f"{name}_upper",
            [wx, 2.30, 0.5 * (z_min + z_max)],
            [0.24, 0.50, z_max - z_min],
            color="#252d3a",
            metalness=0.52,
            roughness=0.68,
            flat_shading=True,
            solid=False,
        )
        # Solid wall piers flanking the viewport
        b.add_box(
            f"{name}_pier_s",
            [wx, 1.32, 0.5 * (z_min + z_win_a)],
            [0.24, 1.50, max(0.3, z_win_a - z_min)],
            color="#293240",
            metalness=0.5,
            roughness=0.68,
            solid=True,
        )
        b.add_box(
            f"{name}_pier_n",
            [wx, 1.32, 0.5 * (z_win_b + z_max)],
            [0.24, 1.50, max(0.3, z_max - z_win_b)],
            color="#293240",
            metalness=0.5,
            roughness=0.68,
            solid=True,
        )
        # Heavy metallic porthole frame mullions + translucent scratched space-glass pane
        b.add_box(
            f"{name}_glass",
            [wx, 1.32, 0.5 * (z_win_a + z_win_b)],
            [0.03, 1.44, z_win_b - z_win_a],
            color="#7dd3fc",
            emissive="#0c4a6e",
            emissive_intensity=0.22,
            opacity=0.14,
            roughness=0.12,
            metalness=0.35,
            solid=True,
        )
        # Center vertical mullion strut
        b.add_box(
            f"{name}_mullion",
            [wx, 1.32, 0.5 * (z_win_a + z_win_b)],
            [0.14, 1.48, 0.10],
            color="#475569",
            metalness=0.6,
            roughness=0.5,
            solid=False,
        )

    add_porthole_wall_x("hull_east_crew", 5.9, -0.6, 5.9, 1.1, 4.5)
    add_porthole_wall_x("hull_west_mess", -5.9, -0.6, 5.9, 0.9, 4.7)

    # South closing bulkheads for Crew Quarters & Mess Hall (z = -0.6)
    for side, cx in (("east", 3.7), ("west", -3.7)):
        b.add_box(
            f"wing_south_wall_{side}",
            [cx, 1.15, -0.6],
            [4.5, 2.30, 0.22],
            color="#262f3d",
            metalness=0.48,
            roughness=0.72,
            solid=True,
        )
        b.add_box(
            f"wing_north_wall_{side}",
            [cx, 1.15, 5.9],
            [4.5, 2.30, 0.22],
            color="#262f3d",
            metalness=0.48,
            roughness=0.72,
            solid=True,
        )

    # Cosmic-Horror Anomaly Tendrils erupting from a ruptured conduit along the Spine!
    anomaly_origin = [1.28, 0.55, 3.65]
    b.add_poly(
        "anomaly_core_mass",
        "dodecahedron",
        anomaly_origin,
        [0.22, 0],
        scale=[0.75, 1.25, 1.05],
        color="#1a0b24",
        emissive="#581c87",
        emissive_intensity=0.52,
        roughness=0.28,
    )
    b.add_poly(
        "anomaly_eye_node",
        "octahedron",
        [1.10, 0.58, 3.65],
        [0.065, 0],
        color="#fca5a5",
        emissive="#dc2626",
        emissive_intensity=0.95,
        roughness=0.15,
    )
    for idx, (tx, ty, tz) in enumerate(
        [
            (0.96, 0.04, 3.22),
            (0.90, 0.04, 4.08),
            (1.22, 1.38, 3.38),
            (1.18, 1.56, 4.12),
            (0.76, 0.03, 3.74),
        ]
    ):
        b.add_segment(
            f"anomaly_tendril_{idx}",
            anomaly_origin,
            [tx, ty, tz],
            0.052,
            0.016,
            segments=6,
            color="#1e102b",
            emissive="#4c1d95",
            emissive_intensity=0.42,
            solid=False,
        )

    # =========================================================================
    # 2. TWIN BRIDGE STAIRWAY RAMPS (y = 0.00 -> +0.24 m) & UPPER COMMAND BRIDGE!
    #    Exact 6.5 deg MuJoCo climbable ramps with stepped industrial visual risers
    #    and glowing amber handrails so Ainekio V2 climbs right onto the Bridge!
    # =========================================================================
    bridge_y = 0.24
    for side, sx in (("left", 0.62), ("right", -0.62)):
        # Smooth exact 6.5 deg climbable ramp (z = 3.90 -> 6.00 m, dy = +0.24 m -> 6.5 deg!)
        b.add_ramp(
            f"bridge_stair_ramp_{side}",
            sx,
            0.0,
            3.90,
            sx,
            bridge_y,
            6.00,
            width=0.76,
            color="#3b4759",
            emissive="#1e293b",
            emissive_intensity=0.16,
        )
        # Visual industrial stair tread nosing strips embedded flush along the ramp slope
        for step_i in range(1, 10):
            frac = step_i / 10.0
            sz = 3.90 + frac * 2.10
            sy = frac * bridge_y + 0.002
            b.add_box(
                f"stair_nosing_{side}_{step_i}",
                [sx, sy, sz],
                [0.72, 0.004, 0.028],
                color="#fbbf24",
                emissive="#d97706",
                emissive_intensity=0.55,
                solid=False,
            )
        # Glowing safety handrail along outer edge of each staircase
        rail_x = sx + (0.40 if sx > 0 else -0.40)
        b.add_segment(
            f"stair_handrail_{side}",
            [rail_x, 0.34, 3.95],
            [rail_x, bridge_y + 0.34, 6.00],
            0.025,
            0.025,
            segments=6,
            color="#94a3b8",
            emissive="#f59e0b",
            emissive_intensity=0.35,
            solid=False,
        )
        for post_z, post_y in ((3.95, 0.0), (5.00, 0.12), (6.00, bridge_y)):
            b.add_cylinder(
                f"stair_post_{side}_{int(post_z * 10)}",
                [rail_x, post_y + 0.17, post_z],
                0.022,
                0.024,
                0.34,
                segments=6,
                color="#64748b",
                solid=True,
            )

    # Central low divider curb between twin Bridge staircases
    b.add_box(
        "bridge_stair_divider",
        [0.0, 0.12, 4.95],
        [0.14, 0.24, 2.05],
        color="#2e3847",
        emissive="#dc2626",
        emissive_intensity=0.16,
        solid=True,
    )

    # UPPER COMMAND BRIDGE DECK (x in [-3.8, +3.8], z in [6.0, 9.5], top strictly y = +0.240 m!)
    b.add_box(
        "bridge_upper_deck",
        [0.0, bridge_y / 2.0, 7.75],
        [7.6, bridge_y, 3.50],
        color="#283242",
        emissive="#0f172a",
        emissive_intensity=0.15,
        metalness=0.5,
        roughness=0.65,
        flat_shading=True,
        solid=True,
    )
    # Bridge Side Walls (x = +-3.8, z = 6.0..9.5)
    for side, wx in (("l", 3.8), ("r", -3.8)):
        b.add_box(
            f"bridge_wall_{side}",
            [wx, bridge_y + 1.15, 7.75],
            [0.24, 2.30, 3.60],
            color="#242c38",
            metalness=0.5,
            roughness=0.7,
            solid=True,
        )

    # MASSIVE PANORAMIC FORWARD BRIDGE VIEWPORT (z = +9.5 m) LOOKING OUT AT THE DYING STAR!
    b.add_box(
        "bridge_viewport_lower",
        [0.0, bridge_y + 0.28, 9.52],
        [7.7, 0.56, 0.26],
        color="#232b38",
        metalness=0.55,
        roughness=0.65,
        solid=True,
    )
    b.add_box(
        "bridge_viewport_upper",
        [0.0, bridge_y + 2.24, 9.52],
        [7.7, 0.36, 0.26],
        color="#232b38",
        metalness=0.55,
        roughness=0.65,
        solid=False,
    )
    b.add_box(
        "bridge_viewport_glass",
        [0.0, bridge_y + 1.32, 9.52],
        [7.3, 1.54, 0.03],
        color="#fca5a5",
        emissive="#7f1d1d",
        emissive_intensity=0.22,
        opacity=0.12,
        roughness=0.10,
        metalness=0.35,
        solid=True,
    )
    # Angled metallic viewport mullions framing the colossal Dying Star
    for mx in (-2.4, -0.85, 0.85, 2.4):
        b.add_box(
            f"bridge_mullion_{int(mx * 10)}",
            [mx, bridge_y + 1.32, 9.50],
            [0.12, 1.60, 0.16],
            color="#3b4759",
            metalness=0.62,
            roughness=0.45,
            solid=False,
        )

    # Captain's Derelict Command Chair (centered on Bridge at z = 7.45 m, slightly swiveled)
    b.add_cylinder(
        "captain_chair_base",
        [0.0, bridge_y + 0.14, 7.45],
        0.22,
        0.28,
        0.28,
        segments=10,
        color="#334155",
        solid=True,
    )
    b.add_box(
        "captain_chair_seat",
        [0.0, bridge_y + 0.34, 7.45],
        [0.48, 0.10, 0.46],
        rot=[0.0, 0.28, 0.0],
        color="#475569",
        solid=True,
    )
    b.add_box(
        "captain_chair_back",
        [-0.06, bridge_y + 0.66, 7.26],
        [0.46, 0.56, 0.10],
        rot=[-0.12, 0.28, 0.0],
        color="#3b4759",
        solid=False,
    )

    # Central Holographic Tactical Star-Map Table (z = 8.45 m)
    b.add_cylinder(
        "holo_table_pedestal",
        [0.0, bridge_y + 0.26, 8.45],
        0.58,
        0.44,
        0.52,
        segments=12,
        color="#2e3a4c",
        emissive="#0c4a6e",
        emissive_intensity=0.28,
        solid=True,
    )
    b.add_poly(
        "holo_projection_star",
        "icosahedron",
        [0.0, bridge_y + 0.82, 8.45],
        [0.14, 0],
        color="#fca5a5",
        emissive="#ef4444",
        emissive_intensity=0.98,
        opacity=0.82,
    )
    b.add_poly(
        "holo_projection_ring",
        "torus",
        [0.0, bridge_y + 0.82, 8.45],
        [0.34, 0.015, 6, 24],
        rot=[math.pi / 2.0 + 0.22, 0.0, 0.15],
        color="#38bdf8",
        emissive="#0ea5e9",
        emissive_intensity=0.92,
        opacity=0.75,
    )

    # 4 Angled Bridge Helm / Nav / Weapons Consoles with Glowing Status Screens
    bridge_consoles = [
        (-2.15, 8.65, 0.35, "#38bdf8", "#0284c7"),
        (2.15, 8.65, -0.35, "#f87171", "#dc2626"),
        (-2.65, 7.15, 1.15, "#fbbf24", "#d97706"),
        (2.65, 7.15, -1.15, "#2dd4bf", "#0d9488"),
    ]
    for idx, (cx, cz, yaw, sc_col, sc_em) in enumerate(bridge_consoles):
        b.add_box(
            f"bridge_console_{idx + 1}",
            [cx, bridge_y + 0.34, cz],
            [1.05, 0.68, 0.48],
            rot=[0.0, yaw, 0.0],
            color="#334155",
            metalness=0.52,
            roughness=0.58,
            flat_shading=True,
            solid=True,
        )
        b.add_box(
            f"bridge_screen_{idx + 1}",
            [cx, bridge_y + 0.72, cz],
            [0.86, 0.24, 0.05],
            rot=[-0.42, yaw, 0.0],
            color=sc_col,
            emissive=sc_em,
            emissive_intensity=0.92,
            roughness=0.18,
            solid=False,
        )

    # =========================================================================
    # 3. EAST WING (+X): CREW QUARTERS & MEDBAY CRYO-POD
    # =========================================================================
    # 3 Double-Tier Crew Bunk Alcoves along the north/south walls of Crew Quarters
    for idx, (bx, bz, yaw) in enumerate([(3.4, 5.15, 0.0), (5.0, 5.15, 0.0), (3.6, 0.08, 0.0)]):
        # Bunk frame posts + lower bunk + upper bunk
        b.add_box(
            f"crew_bunk_low_{idx}",
            [bx, 0.26, bz],
            [1.35, 0.14, 0.72],
            rot=[0.0, yaw, 0.0],
            color="#3b4759",
            metalness=0.45,
            roughness=0.68,
            solid=True,
        )
        b.add_box(
            f"crew_mattress_low_{idx}",
            [bx, 0.36, bz],
            [1.26, 0.08, 0.64],
            color="#4c5566" if idx != 1 else "#5b3b3b",
            roughness=0.92,
            solid=False,
        )
        b.add_box(
            f"crew_bunk_high_{idx}",
            [bx, 1.05, bz],
            [1.35, 0.12, 0.72],
            color="#3b4759",
            metalness=0.45,
            roughness=0.68,
            solid=False,
        )
        # Warm amber bunk reading lamp strip
        b.add_box(
            f"crew_bunk_lamp_{idx}",
            [bx, 0.78, bz + (0.34 if bz > 2.5 else -0.34)],
            [0.42, 0.04, 0.04],
            color="#fde68a",
            emissive="#f59e0b",
            emissive_intensity=0.85,
            solid=False,
        )

    # Derelict Medbay Cryo-Stasis Pod (glowing eerie cyan stasis chamber in Crew Quarters!)
    b.add_cylinder(
        "cryo_pod_base",
        [4.85, 0.14, 1.35],
        0.52,
        0.58,
        0.28,
        segments=12,
        color="#334155",
        solid=True,
    )
    b.add_cylinder(
        "cryo_pod_glass",
        [4.85, 0.92, 1.35],
        0.44,
        0.44,
        1.32,
        segments=14,
        color="#5eead4",
        emissive="#0d9488",
        emissive_intensity=0.78,
        opacity=0.38,
        roughness=0.14,
        solid=True,
    )
    b.add_cylinder(
        "cryo_pod_cap",
        [4.85, 1.66, 1.35],
        0.56,
        0.48,
        0.22,
        segments=12,
        color="#334155",
        solid=False,
    )
    # Crew footlockers forming an indoor obstacle weave in Crew Quarters
    for idx, (lx, lz, yaw) in enumerate([(2.75, 2.85, 0.15), (3.85, 2.35, -0.45), (3.15, 1.35, 0.85)]):
        b.add_box(
            f"crew_footlocker_{idx + 1}",
            [lx, 0.16, lz],
            [0.52, 0.32, 0.32],
            rot=[0.0, yaw, 0.0],
            color="#475569",
            emissive="#1e293b",
            emissive_intensity=0.12,
            metalness=0.42,
            roughness=0.65,
            solid=True,
        )

    # =========================================================================
    # 4. WEST WING (-X): THE MESS HALL & GALLEY
    # =========================================================================
    # 2 Standing Industrial Mess Tables + Benches + 1 Overturned Table!
    for idx, (tx, tz) in enumerate([(-3.2, 3.65), (-4.6, 2.35)]):
        b.add_box(
            f"mess_table_top_{idx}",
            [tx, 0.44, tz],
            [1.15, 0.07, 0.62],
            color="#475569",
            metalness=0.5,
            roughness=0.58,
            solid=True,
        )
        b.add_box(
            f"mess_table_pedestal_{idx}",
            [tx, 0.21, tz],
            [0.32, 0.42, 0.32],
            color="#2b3544",
            solid=True,
        )
        # Flanking mess benches (robot can weave between tables & benches)
        for side, bz_off in (("n", 0.52), ("s", -0.52)):
            b.add_box(
                f"mess_bench_{idx}_{side}",
                [tx, 0.20, tz + bz_off],
                [1.05, 0.08, 0.24],
                color="#3b4759",
                solid=True,
            )
    # Overturned derelict mess table near the port porthole!
    b.add_box(
        "mess_table_overturned",
        [-4.55, 0.26, 4.45],
        [1.10, 0.08, 0.60],
        rot=[0.72, 0.45, 0.18],
        color="#475569",
        metalness=0.45,
        roughness=0.68,
        solid=True,
    )
    # Galley Serving Counter & Malfunctioning Replicator along South Mess Wall (z = 0.05)
    b.add_box(
        "galley_counter",
        [-3.65, 0.38, 0.12],
        [2.65, 0.76, 0.58],
        color="#334155",
        metalness=0.55,
        roughness=0.52,
        solid=True,
    )
    b.add_box(
        "galley_replicator_glow",
        [-3.65, 0.92, -0.05],
        [0.85, 0.38, 0.08],
        color="#5eead4",
        emissive="#14b8a6",
        emissive_intensity=0.82,
        solid=False,
    )

    # =========================================================================
    # 5. AFT SECTION (-Z): CRACKED SINGULARITY REACTOR & CARGO CATWALK RAMP
    # =========================================================================
    # Towering Cracked Singularity Reactor Core at (0, 0, -3.55 m)
    b.add_cylinder(
        "reactor_base_plinth",
        [0.0, 0.18, -3.55],
        0.92,
        1.05,
        0.36,
        segments=14,
        color="#2c3545",
        solid=True,
    )
    b.add_cylinder(
        "reactor_core_column",
        [0.0, 1.35, -3.55],
        0.46,
        0.54,
        2.10,
        segments=12,
        color="#fda4af",
        emissive="#e11d48",
        emissive_intensity=0.95,
        opacity=0.85,
        roughness=0.18,
        solid=True,
    )
    for ring_i, ry in enumerate((0.68, 1.25, 1.82)):
        b.add_poly(
            f"reactor_coil_{ring_i}",
            "torus",
            [0.0, ry, -3.55],
            [0.74, 0.065, 8, 24],
            rot=[math.pi / 2.0 + (ring_i - 1) * 0.14, 0.0, 0.08 * ring_i],
            color="#64748b",
            emissive="#f43f5e",
            emissive_intensity=0.55,
            metalness=0.65,
            roughness=0.35,
        )

    # Aft Cargo Catwalk Climbable Ramp (6.5 deg -> +0.14 m elevated maintenance bay!)
    b.add_ramp("aft_cargo_ramp", -2.35, 0.0, -1.65, -2.35, 0.14, -2.85, width=0.78, color="#3e4a5e")
    b.add_box(
        "aft_cargo_platform",
        [-3.15, 0.07, -3.55],
        [2.35, 0.14, 1.45],
        color="#334155",
        metalness=0.5,
        roughness=0.62,
        solid=True,
    )
    # Cargo crates on East Aft bay
    for idx, (cx, cz, ch) in enumerate([(2.45, -2.45, 0.42), (3.15, -3.15, 0.56), (2.25, -3.45, 0.36)]):
        b.add_box(
            f"aft_cargo_crate_{idx + 1}",
            [cx, ch / 2.0, cz],
            [0.54, ch, 0.54],
            rot=[0.0, idx * 0.32, 0.0],
            color="#4b5563",
            emissive="#1e293b",
            emissive_intensity=0.12,
            metalness=0.35,
            roughness=0.72,
            solid=True,
        )

    # =========================================================================
    # 6. DEEP SPACE COSMIC HORROR EXTERIOR:
    #    - COLOSSAL BLEEDING CRIMSON DYING STAR + WARPED ACCRETION DISK
    #    - 34 DRIFTING JAGGED ASTEROIDS & SHEARED FLOATING HULL DEBRIS
    #      (Animated gently in zero-G by levelSceneBuilder.ts!)
    # =========================================================================
    star_x, star_y, star_z = 0.8, 4.6, 36.0
    b.add_poly(
        "dying_star_core",
        "icosahedron",
        [star_x, star_y, star_z],
        [6.8, 2],
        color="#ef4444",
        emissive="#dc2626",
        emissive_intensity=1.0,
        roughness=0.35,
        metalness=0.05,
    )
    b.add_poly(
        "dying_star_corona",
        "icosahedron",
        [star_x, star_y, star_z],
        [8.4, 1],
        color="#fb923c",
        emissive="#ea580c",
        emissive_intensity=0.88,
        opacity=0.28,
        roughness=0.2,
    )
    b.add_poly(
        "dying_star_accretion",
        "torus",
        [star_x, star_y, star_z],
        [13.2, 0.55, 8, 44],
        rot=[math.pi / 2.0 + 0.34, 0.0, -0.22],
        color="#fdba74",
        emissive="#f97316",
        emissive_intensity=0.95,
        opacity=0.82,
        roughness=0.25,
    )
    b.add_poly(
        "dying_star_outer_ring",
        "torus",
        [star_x, star_y, star_z],
        [17.5, 0.28, 6, 44],
        rot=[math.pi / 2.0 + 0.34, 0.0, -0.22],
        color="#c084fc",
        emissive="#7e22ce",
        emissive_intensity=0.72,
        opacity=0.45,
        roughness=0.3,
    )

    # 28 Drifting Jagged Asteroids outside Forward Bridge, Port Mess Hall & Starboard Crew Portholes!
    asteroid_specs = [
        # Framed right outside the Forward Bridge Viewport (between ship & Dying Star!)
        (-4.5, 2.2, 16.5, 1.35),
        (4.8, 1.4, 15.2, 1.15),
        (-2.2, 5.2, 21.0, 1.85),
        (6.4, 4.8, 22.5, 2.25),
        (-8.2, 0.6, 18.0, 1.95),
        (1.4, -1.8, 14.5, 1.05),
        (-6.8, -2.4, 24.0, 2.40),
        (9.2, -1.2, 19.5, 2.10),
        # Outside Port-side Mess Hall Porthole (-X)
        (-10.2, 1.8, 3.2, 1.25),
        (-12.5, 0.5, 0.6, 1.65),
        (-9.4, 3.6, 5.8, 0.95),
        (-14.8, 2.8, 4.5, 2.35),
        (-11.2, -1.2, 2.1, 1.15),
        (-16.5, 4.2, -1.5, 2.60),
        (-8.8, 1.1, 7.6, 0.85),
        # Outside Starboard Crew Quarters Porthole (+X)
        (10.0, 1.9, 2.8, 1.30),
        (12.8, 0.7, 5.2, 1.75),
        (9.2, 3.8, 0.8, 0.92),
        (15.2, 3.2, 3.6, 2.45),
        (11.4, -1.4, 4.0, 1.20),
        (16.0, 4.6, -2.0, 2.50),
        # Aft & deep background asteroids
        (-5.5, 3.4, -10.5, 1.85),
        (6.2, 2.0, -11.5, 2.15),
        (0.5, 5.8, -14.0, 2.45),
        (-12.0, 6.2, 14.0, 2.75),
        (13.5, 6.5, 13.5, 2.65),
    ]
    for idx, (ax, ay, az, ar) in enumerate(asteroid_specs):
        b.add_poly(
            f"space_debris_ast_{idx}",
            "dodecahedron",
            [ax, ay, az],
            [ar, 0],
            rot=[idx * 0.6, idx * 1.1, idx * 0.4],
            scale=[1.28, 0.82, 1.12],
            color="#353d4a" if idx % 3 != 0 else "#4a3b3b",
            emissive="#1e1b2e" if idx % 2 == 0 else "#2a1414",
            emissive_intensity=0.22,
            roughness=0.92,
            metalness=0.14,
        )

    # 8 Sheared Floating Starship Hull Debris Plates & Broken Girders drifting outside the portholes!
    debris_plates = [
        (-8.6, 1.6, 2.2, [1.8, 0.10, 0.95], [0.4, 0.6, 0.25]),
        (-10.8, 2.8, 4.4, [2.4, 0.14, 0.22], [-0.3, 0.9, 0.5]),
        (8.8, 1.5, 3.4, [1.9, 0.10, 0.85], [-0.5, 0.4, -0.3]),
        (11.0, 3.1, 1.8, [2.2, 0.14, 0.22], [0.25, -0.7, 0.4]),
        (-3.2, 2.4, 12.8, [2.1, 0.12, 0.90], [0.35, 0.2, 0.6]),
        (3.6, 3.2, 13.6, [2.6, 0.14, 0.24], [-0.4, 0.5, -0.25]),
        (-1.4, -0.8, 11.8, [1.4, 0.10, 0.75], [0.6, -0.4, 0.2]),
        (7.5, -0.6, 9.8, [1.6, 0.10, 0.80], [-0.2, 0.8, 0.5]),
    ]
    for idx, (dx, dy, dz, sz, rot) in enumerate(debris_plates):
        b.add_box(
            f"space_debris_hull_{idx}",
            [dx, dy, dz],
            sz,
            rot=rot,
            color="#475569",
            emissive="#7f1d1d" if idx % 3 == 0 else "#1e293b",
            emissive_intensity=0.25,
            metalness=0.58,
            roughness=0.55,
            flat_shading=True,
            solid=False,
        )

    # =========================================================================
    # 7. COSMIC HORROR ATMOSPHERIC LIGHTING (8 Dramatic Point Lights!)
    # =========================================================================
    b.add_light("light_dying_star", [0.0, 2.2, 11.2], "#ef4444", 5.2, 24.0)
    b.add_light("light_bridge_holo", [0.0, 1.45, 8.2], "#38bdf8", 2.4, 9.0)
    b.add_light("light_spine_red", [0.0, 1.95, 1.6], "#dc2626", 2.0, 9.0)
    b.add_light("light_anomaly", [0.8, 0.9, 3.65], "#a855f7", 2.2, 7.5)
    b.add_light("light_crew_cryo", [4.4, 1.35, 1.8], "#2dd4bf", 2.9, 9.5)
    b.add_light("light_mess_hall", [-3.8, 1.85, 2.8], "#f59e0b", 2.8, 9.5)
    b.add_light("light_reactor", [0.0, 1.6, -3.1], "#f43f5e", 3.0, 10.0)
    b.add_light("light_spawn_airlock", [0.0, 1.85, -0.4], "#93c5fd", 1.8, 7.5)

    return {
        "schemaVersion": 2,
        "id": "miranda",
        "name": "Miranda Wreck",
        "subtitle": "Derelict starship · Bridge stairs, Crew Quarters, Mess Hall, Asteroid Field & Dying Star",
        "worldOriginThree": [0.0, 0.0, 0.0],
        "skyboxDir": "/assets/skyboxes/classic",
        "backgroundHex": "#04060c",
        "fogHex": "#080c16",
        "fogDensity": 0.0062,
        "useDefaultFloorPlane": False,
        "robotSpawnMj": [0.0, 0.0, 0.066],
        "primitives": b.primitives,
        "glbInstances": [],
        "colliders": b.colliders,
        "lights": b.lights,
    }
