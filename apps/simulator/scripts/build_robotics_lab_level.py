#!/usr/bin/env python3
"""
Procedural 19m x 19m Robotics Lab & Multi-Zone Autonomous Proving Ground builder
(`v2-lab.level.json`).

Expansive flagship default arena for Ainekio V1 / V2 / V3 quadrupeds — built for
both direct user driving and autonomous robot navigation, SLAM mapping, terrain
locomotion, and chin-camera visual object recognition:

  Zone 0 — Home Calibration & Dual Charging Bay (spawn at (0, 0, 0), clear r >= 0.80m):
    - Glowing cyan Home Calibration Pad & forward runway chevron.
    - Dual-bay rear charging station (`TAG-00`), wheeled tool chest, spare battery rack.
  Zone 1 — Center Agility & Slalom Speedway (z = +1.0 .. +6.4m):
    - Cyan Start Gate Arch, graduated 10 / 14 / 18 mm cable thresholds, 4 reflective
      orange/white slalom agility cones, and Emerald Goal Portal (`TAG-04`) with a
      spinning holographic ring.
  Zone 2 — East Wing: Ramp Bridge, Balance Beam, Terraced Steps & Traction Strip
           (x = +1.5 .. +8.8m, z = +0.4 .. +7.4m):
    - Walkable 6.5 deg Ramp -> +0.145 m Elevated Observation Bridge -> Exit Ramp (`TAG-02`
      + floating golden trophy).
    - Raised 0.54 m wide Precision Balance Beam (+0.09 m height, 3.0 m span with ramps!).
    - Multi-tiered Terraced Step Trainer (16 / 32 / 48 mm climbable steps + beacon).
    - Precision Stepping-Stone Pad Grid & Cobble/Rumble Traction Test Strip.
  Zone 3 — West Wing: Autonomous Vision, Fiducial & Everyday Object Garden
           (x = -8.8 .. -1.5m, z = +0.2 .. +7.4m):
    - Double-sided 24-patch Macbeth ColorChecker, 9x6 SLAM Checkerboard panel,
      and eye-level AprilTags (`TAG-01`, `TAG-03`).
    - Geometric & benchmark targets: crimson ball, cobalt cube, emerald cylinder,
      golden companion rubber duck, cardboard cargo box, red/white hazard barrel,
      holographic sensor orb plinth, and walk-through magenta inspection tunnel.
    - Everyday Household / Indoor Recognition Alcove: walk-under coffee table with
      ceramic mug & red apple, colorful stacked toy blocks, yellow CAUTION A-frame sign,
      red STOP sign post, teal watering can, potted ficus plants, and a stainless
      robot-dog water bowl!
  Zone 4 — North-Center: Autonomous Waypoint Maze & Prize Plaza (z = +7.2 .. +14.0m):
    - Wide 1.2 m robot-scale navigation maze with low windowed baffle walls (clear
      aerial visibility!), amber checkpoint arch, `TAG-05`, `TAG-06`, `TAG-07`, and
      a glowing Central Prize Plaza with a rotating Holographic Core Monument (`TAG-08`).
  Zone 5 — North-West: Dynamic Terrain & Hill Mound Proving Pit
           (x = -8.6 .. -4.4m, z = +7.8 .. +13.6m):
    - Walkable 3-ramp trapezoidal test hill (+0.18 m summit), scattered low traction
      boulders / rubble pads (12-26 mm), crawl-under overhead gantry bridge, and `TAG-09`.
  Zone 6 — North-East: Robotics Engineering Workshop & Server Bay
           (x = +4.6 .. +8.8m, z = +7.8 .. +13.6m):
    - Dual engineering workbenches, articulated yellow industrial robot arm, glowing
      server rack towers, spare quadruped display stand, battery carousel, and 3 giant
      procedural diagnostic screens (500 Hz Telemetry, Autonomous Vision, SLAM Map).
  Lab Enclosure:
    - 19.2 m x 19.2 m architectural hall (`x in [-9.6, +9.6]`, `z in [-4.4, +14.8]`,
      height 5.2 m) with solid perimeter bulkhead walls, panoramic observation glass,
      6 overhead steel gantry trusses with LED light bars, and a rolling yellow bridge
      crane + hoist spanning the entire lab!
"""

from __future__ import annotations

import math
from typing import Any

from build_yggdrasil_level import _SceneBuilder


def _add_apriltag_stand(
    b: _SceneBuilder,
    tag_id: str,
    x: float,
    z: float,
    yaw: float = 0.0,
    base_y: float = 0.0,
    solid: bool = True,
) -> None:
    """Eye-level AprilTag fiducial stand (~0.25 m center height for quadruped chin cameras)."""
    b.add_box(
        f"tag_stand_base_{tag_id}",
        [x, base_y + 0.015, z],
        [0.24, 0.03, 0.16],
        rot=[0.0, yaw, 0.0],
        color="#1e293b",
        metalness=0.55,
        roughness=0.4,
        solid=solid,
    )
    for side, ox in (("l", -0.095), ("r", 0.095)):
        px = x + ox * math.cos(yaw)
        pz = z - ox * math.sin(yaw)
        b.add_cylinder(
            f"tag_stand_post_{tag_id}_{side}",
            [px, base_y + 0.19, pz],
            0.012,
            0.014,
            0.34,
            segments=8,
            color="#64748b",
            metalness=0.72,
            roughness=0.3,
            solid=False,
        )
    b.add_box(
        f"tag_frame_{tag_id}",
        [x, base_y + 0.25, z],
        [0.29, 0.29, 0.024],
        rot=[0.0, yaw, 0.0],
        color="#334155",
        metalness=0.45,
        roughness=0.38,
        solid=solid,
    )
    for face_side, dz_local in (("front", -0.014), ("back", 0.014)):
        fx = x + dz_local * math.sin(yaw)
        fz = z + dz_local * math.cos(yaw)
        b.add_box(
            f"lab_apriltag_{tag_id}" if face_side == "front" else f"lab_apriltag_{tag_id}_back",
            [fx, base_y + 0.25, fz],
            [0.26, 0.26, 0.004],
            rot=[0.0, yaw, 0.0],
            color="#ffffff",
            emissive="#ffffff",
            emissive_intensity=0.22,
            metalness=0.05,
            roughness=0.6,
            solid=False,
        )


def _add_slalom_cone(b: _SceneBuilder, idx: int, x: float, z: float) -> None:
    """High-visibility orange & reflective white agility slalom cone with exact collider."""
    b.add_box(
        f"cone_base_{idx}",
        [x, 0.012, z],
        [0.18, 0.024, 0.18],
        color="#1e293b",
        metalness=0.2,
        roughness=0.72,
        solid=True,
    )
    b.add_poly(
        f"cone_body_{idx}",
        "cone",
        [x, 0.16, z],
        [0.072, 0.28, 12],
        color="#f97316",
        emissive="#ea580c",
        emissive_intensity=0.24,
        metalness=0.1,
        roughness=0.45,
        flat_shading=False,
    )
    b.add_box(
        f"cone_col_{idx}",
        [x, 0.15, z],
        [0.11, 0.26, 0.11],
        solid=True,
        visual=False,
    )
    b.add_cylinder(
        f"cone_band_{idx}",
        [x, 0.19, z],
        0.036,
        0.052,
        0.065,
        segments=12,
        color="#f8fafc",
        emissive="#e2e8f0",
        emissive_intensity=0.35,
        metalness=0.1,
        roughness=0.3,
        flat_shading=False,
        solid=False,
    )


def _add_potted_plant(b: _SceneBuilder, tag: str, x: float, z: float, scale: float = 1.0) -> None:
    """Recognizable terracotta potted plant with faceted emerald foliage."""
    s = scale
    b.add_cylinder(
        f"plant_pot_{tag}",
        [x, 0.11 * s, z],
        0.13 * s,
        0.095 * s,
        0.22 * s,
        segments=10,
        color="#c2633a",
        metalness=0.05,
        roughness=0.82,
        flat_shading=True,
        solid=True,
    )
    b.add_cylinder(
        f"plant_rim_{tag}",
        [x, 0.215 * s, z],
        0.145 * s,
        0.135 * s,
        0.035 * s,
        segments=10,
        color="#d47247",
        roughness=0.78,
        flat_shading=True,
        solid=False,
    )
    b.add_cylinder(
        f"plant_soil_{tag}",
        [x, 0.21 * s, z],
        0.115 * s,
        0.115 * s,
        0.02 * s,
        segments=10,
        color="#3b281c",
        roughness=0.95,
        solid=False,
    )
    for i in range(6):
        ang = (i / 6.0) * math.tau + 0.3
        lx = x + math.cos(ang) * 0.08 * s
        lz = z + math.sin(ang) * 0.08 * s
        b.add_poly(
            f"plant_leaf_{tag}_{i}",
            "cone",
            [lx, (0.34 + (i % 2) * 0.04) * s, lz],
            [0.065 * s, 0.24 * s, 6],
            rot=[0.42 * math.sin(ang), -ang, -0.42 * math.cos(ang)],
            color="#22c55e" if i % 2 == 0 else "#16a34a",
            emissive="#14532d",
            emissive_intensity=0.15,
            roughness=0.65,
            flat_shading=True,
        )


def _add_companion_duck(b: _SceneBuilder, x: float, z: float, yaw: float = 0.72) -> None:
    """Classic robotics vision benchmark object: bright golden faceted companion rubber duck."""
    cy = math.cos(yaw)
    sy = math.sin(yaw)

    def pt(lx: float, ly: float, lz: float) -> list[float]:
        return [x + lx * cy + lz * sy, ly, z - lx * sy + lz * cy]

    b.add_cylinder(
        "duck_pad",
        [x, 0.006, z],
        0.18,
        0.19,
        0.012,
        segments=16,
        color="#1e293b",
        emissive="#0284c7",
        emissive_intensity=0.22,
        roughness=0.5,
        solid=False,
    )
    b.add_poly(
        "duck_body",
        "sphere",
        pt(0.0, 0.095, 0.0),
        [0.095, 14, 10],
        rot=[0.0, yaw, 0.0],
        scale=[1.05, 0.88, 1.32],
        color="#facc15",
        emissive="#ca8a04",
        emissive_intensity=0.18,
        roughness=0.35,
        flat_shading=True,
    )
    b.add_box(
        "duck_collider",
        [x, 0.11, z],
        [0.21, 0.22, 0.24],
        rot=[0.0, yaw, 0.0],
        solid=True,
        visual=False,
    )
    b.add_poly(
        "duck_head",
        "sphere",
        pt(0.0, 0.20, 0.075),
        [0.064, 12, 10],
        color="#fde047",
        emissive="#ca8a04",
        emissive_intensity=0.18,
        roughness=0.32,
        flat_shading=True,
    )
    b.add_box(
        "duck_beak",
        pt(0.0, 0.19, 0.145),
        [0.052, 0.024, 0.055],
        rot=[0.0, yaw, 0.0],
        color="#f97316",
        emissive="#ea580c",
        emissive_intensity=0.25,
        roughness=0.4,
        solid=False,
    )
    for side, ex in (("l", 0.044), ("r", -0.044)):
        b.add_poly(
            f"duck_eye_{side}",
            "sphere",
            pt(ex, 0.215, 0.118),
            [0.011, 8, 6],
            color="#0f172a",
            roughness=0.15,
            flat_shading=False,
        )
    b.add_poly(
        "duck_tail",
        "cone",
        pt(0.0, 0.135, -0.115),
        [0.04, 0.085, 6],
        rot=[-0.65, yaw, 0.0],
        color="#eab308",
        roughness=0.38,
        flat_shading=True,
    )


def _add_gate_arch(
    b: _SceneBuilder,
    tag: str,
    x: float,
    z: float,
    width: float,
    height: float,
    accent: str,
    yaw: float = 0.0,
) -> None:
    """Illuminated robotics test-course archway with exact side-pillar colliders."""
    half_w = width * 0.5
    post_w = 0.08
    cy = math.cos(yaw)
    sy = math.sin(yaw)

    for side, ox in (("l", -half_w), ("r", half_w)):
        px = x + ox * cy
        pz = z - ox * sy
        b.add_box(
            f"gate_{tag}_post_{side}",
            [px, height * 0.5, pz],
            [post_w, height, 0.10],
            rot=[0.0, yaw, 0.0],
            color="#334155",
            metalness=0.6,
            roughness=0.35,
            solid=True,
        )
        b.add_box(
            f"gate_{tag}_strip_{side}",
            [px, height * 0.5, pz],
            [post_w + 0.012, height * 0.78, 0.025],
            rot=[0.0, yaw, 0.0],
            color=accent,
            emissive=accent,
            emissive_intensity=0.95,
            roughness=0.2,
            solid=False,
        )

    b.add_box(
        f"gate_{tag}_header",
        [x, height + 0.045, z],
        [width + post_w + 0.08, 0.09, 0.12],
        rot=[0.0, yaw, 0.0],
        color="#1e293b",
        metalness=0.65,
        roughness=0.3,
        solid=False,
    )
    b.add_box(
        f"gate_{tag}_led_bar",
        [x, height - 0.005, z],
        [width - 0.06, 0.022, 0.04],
        rot=[0.0, yaw, 0.0],
        color=accent,
        emissive=accent,
        emissive_intensity=1.1,
        roughness=0.2,
        solid=False,
    )


def _add_maze_wall(
    b: _SceneBuilder,
    tag: str,
    x: float,
    z: float,
    w: float,
    d: float,
    accent: str = "#a855f7",
) -> None:
    """Low 0.42 m windowed maze baffle wall (blocks robots cleanly while staying visible from above!)."""
    b.add_box(
        f"maze_wall_{tag}",
        [x, 0.21, z],
        [w, 0.42, d],
        color="#273549",
        metalness=0.45,
        roughness=0.45,
        solid=True,
    )
    b.add_box(
        f"maze_cap_{tag}",
        [x, 0.43, z],
        [w + 0.015, 0.024, d + 0.015],
        color=accent,
        emissive=accent,
        emissive_intensity=0.72,
        roughness=0.25,
        solid=False,
    )


def _add_server_rack(b: _SceneBuilder, tag: str, x: float, z: float, yaw: float = 0.0) -> None:
    """Robotics compute & RL training server rack tower with glowing telemetry status LEDs."""
    b.add_box(
        f"rack_body_{tag}",
        [x, 0.92, z],
        [0.64, 1.84, 0.56],
        rot=[0.0, yaw, 0.0],
        color="#111827",
        metalness=0.62,
        roughness=0.36,
        solid=True,
    )
    cy = math.cos(yaw)
    sy = math.sin(yaw)
    for row in range(6):
        ry = 0.34 + row * 0.24
        col = "#22c55e" if row % 2 == 0 else "#38bdf8"
        fx = x - 0.285 * sy
        fz = z - 0.285 * cy
        b.add_box(
            f"rack_led_{tag}_{row}",
            [fx, ry, fz],
            [0.44, 0.032, 0.014],
            rot=[0.0, yaw, 0.0],
            color=col,
            emissive=col,
            emissive_intensity=0.95,
            solid=False,
        )


def build_robotics_lab_level() -> dict[str, Any]:
    b = _SceneBuilder()

    # =========================================================================
    # 0. HOME CALIBRATION PAD & DUAL CHARGING BAY (spawn (0,0,0) clear r >= 0.80m)
    # =========================================================================
    b.add_cylinder(
        "home_pad_disc",
        [0.0, 0.0015, 0.0],
        0.64,
        0.66,
        0.003,
        segments=28,
        color="#172336",
        metalness=0.35,
        roughness=0.45,
        flat_shading=False,
        solid=False,
    )
    b.add_poly(
        "home_pad_glow_ring",
        "torus",
        [0.0, 0.005, 0.0],
        [0.64, 0.012, 8, 36],
        rot=[math.pi / 2.0, 0.0, 0.0],
        color="#38bdf8",
        emissive="#0ea5e9",
        emissive_intensity=1.05,
        roughness=0.2,
        flat_shading=False,
    )
    b.add_poly(
        "home_pad_inner_ring",
        "torus",
        [0.0, 0.004, 0.0],
        [0.34, 0.006, 8, 28],
        rot=[math.pi / 2.0, 0.0, 0.0],
        color="#7dd3fc",
        emissive="#38bdf8",
        emissive_intensity=0.75,
        roughness=0.25,
        flat_shading=False,
    )
    b.add_box(
        "home_arrow_stem",
        [0.0, 0.003, 0.44],
        [0.04, 0.004, 0.24],
        color="#38bdf8",
        emissive="#0ea5e9",
        emissive_intensity=0.85,
        solid=False,
    )
    for side, ax, rot_y in (("l", -0.055, -0.7), ("r", 0.055, 0.7)):
        b.add_box(
            f"home_arrow_tip_{side}",
            [ax, 0.003, 0.55],
            [0.035, 0.004, 0.14],
            rot=[0.0, rot_y, 0.0],
            color="#38bdf8",
            emissive="#0ea5e9",
            emissive_intensity=0.85,
            solid=False,
        )

    # Rear Dual Charging Dock Station (z = -1.65 m)
    b.add_box(
        "home_dock_chassis",
        [0.0, 0.16, -1.65],
        [0.92, 0.32, 0.28],
        color="#1e293b",
        metalness=0.55,
        roughness=0.38,
        solid=True,
    )
    b.add_box(
        "home_dock_charge_bar",
        [0.0, 0.24, -1.505],
        [0.58, 0.045, 0.015],
        color="#4ade80",
        emissive="#22c55e",
        emissive_intensity=1.1,
        solid=False,
    )
    _add_apriltag_stand(b, "00", 0.0, -1.65, yaw=0.0, base_y=0.32, solid=False)

    # Rolling red mechanic tool chest & spare battery shelf in the South staging bay
    b.add_box(
        "south_tool_chest",
        [2.6, 0.42, -3.15],
        [0.92, 0.84, 0.52],
        color="#dc2626",
        metalness=0.45,
        roughness=0.36,
        solid=True,
    )
    for dr in range(4):
        b.add_box(
            f"south_tool_drawer_{dr}",
            [2.6, 0.18 + dr * 0.18, -2.885],
            [0.78, 0.025, 0.02],
            color="#cbd5e1",
            metalness=0.8,
            roughness=0.25,
            solid=False,
        )
    # Spare LiPo battery charging bank (south-west bay)
    b.add_box(
        "south_lipo_bench",
        [-2.8, 0.36, -3.15],
        [1.10, 0.72, 0.50],
        color="#334155",
        metalness=0.5,
        roughness=0.42,
        solid=True,
    )
    for bi in range(4):
        b.add_box(
            f"south_lipo_pack_{bi}",
            [-3.15 + bi * 0.23, 0.76, -3.12],
            [0.14, 0.07, 0.20],
            color="#1e293b",
            emissive="#22c55e" if bi % 2 == 0 else "#38bdf8",
            emissive_intensity=0.35,
            solid=False,
        )

    # =========================================================================
    # 1. FLOOR LANE MARKINGS & ZONE BORDERS (6 color-coded proving zones!)
    # =========================================================================
    # Zone 1 Center Agility Runway rails (cyan)
    for side, sx in (("l", -0.68), ("r", 0.68)):
        b.add_box(
            f"runway_lane_{side}",
            [sx, 0.002, 3.25],
            [0.035, 0.004, 5.1],
            color="#38bdf8",
            emissive="#0284c7",
            emissive_intensity=0.7,
            solid=False,
        )
    # Zone 2 East Ramp & Balance Zone border (amber)
    for tag, pos, size in (
        ("east_s", [5.15, 0.002, 0.35], [7.2, 0.004, 0.04]),
        ("east_n", [5.15, 0.002, 7.25], [7.2, 0.004, 0.04]),
        ("east_w", [1.55, 0.002, 3.80], [0.04, 0.004, 6.9]),
        ("east_e", [8.75, 0.002, 3.80], [0.04, 0.004, 6.9]),
    ):
        b.add_box(f"zone_tape_{tag}", pos, size, color="#f59e0b", emissive="#d97706", emissive_intensity=0.65, solid=False)

    # Zone 3 West Vision & Household Object Garden border (teal)
    for tag, pos, size in (
        ("west_s", [-5.15, 0.002, 0.15], [7.3, 0.004, 0.04]),
        ("west_n", [-5.15, 0.002, 7.15], [7.3, 0.004, 0.04]),
        ("west_e", [-1.50, 0.002, 3.65], [0.04, 0.004, 7.0]),
        ("west_w", [-8.80, 0.002, 3.65], [0.04, 0.004, 7.0]),
    ):
        b.add_box(f"zone_tape_{tag}", pos, size, color="#14b8a6", emissive="#0d9488", emissive_intensity=0.65, solid=False)

    # Zone 4 North-Center Autonomous Maze border (violet)
    for tag, pos, size in (
        ("maze_s", [0.0, 0.002, 7.25], [7.4, 0.004, 0.04]),
        ("maze_n", [0.0, 0.002, 13.75], [7.4, 0.004, 0.04]),
        ("maze_w", [-3.70, 0.002, 10.50], [0.04, 0.004, 6.5]),
        ("maze_e", [3.70, 0.002, 10.50], [0.04, 0.004, 6.5]),
    ):
        b.add_box(f"zone_tape_{tag}", pos, size, color="#a855f7", emissive="#9333ea", emissive_intensity=0.65, solid=False)

    # Zone 5 North-West Dynamic Terrain Pit border (emerald)
    for tag, pos, size in (
        ("terr_s", [-6.65, 0.002, 7.75], [4.3, 0.004, 0.04]),
        ("terr_n", [-6.65, 0.002, 13.75], [4.3, 0.004, 0.04]),
        ("terr_w", [-8.80, 0.002, 10.75], [0.04, 0.004, 6.0]),
        ("terr_e", [-4.50, 0.002, 10.75], [0.04, 0.004, 6.0]),
    ):
        b.add_box(f"zone_tape_{tag}", pos, size, color="#22c55e", emissive="#16a34a", emissive_intensity=0.65, solid=False)

    # =========================================================================
    # 2. ZONE 1 (CENTER): START GATE, THRESHOLDS, SLALOM CONES & GOAL PORTAL
    # =========================================================================
    _add_gate_arch(b, "start", 0.0, 1.05, width=1.22, height=0.72, accent="#38bdf8")

    for idx, (tz, height_m, width_z, color) in enumerate(
        (
            (1.55, 0.010, 0.038, "#f59e0b"),
            (2.05, 0.014, 0.042, "#fb923c"),
            (2.55, 0.018, 0.048, "#eab308"),
        ),
        start=1,
    ):
        b.add_box(
            f"threshold_strip_{idx}",
            [0.0, height_m * 0.5, tz],
            [1.16, height_m, width_z],
            color=color,
            emissive=color,
            emissive_intensity=0.22,
            metalness=0.25,
            roughness=0.5,
            solid=True,
        )

    for idx, (cx, cz) in enumerate(
        ((-0.34, 3.15), (0.34, 3.68), (-0.34, 4.22), (0.34, 4.75)),
        start=1,
    ):
        _add_slalom_cone(b, idx, cx, cz)

    _add_gate_arch(b, "goal", 0.0, 5.55, width=1.32, height=0.82, accent="#22c55e")
    b.add_poly(
        "surreal_spin_goal_ring",
        "torus",
        [0.0, 1.18, 5.55],
        [0.26, 0.025, 10, 28],
        color="#4ade80",
        emissive="#22c55e",
        emissive_intensity=1.05,
        roughness=0.2,
        flat_shading=False,
    )
    b.add_poly(
        "holo_projection_goal_orb",
        "octahedron",
        [0.0, 1.18, 5.55],
        [0.11, 0],
        color="#bbf7d0",
        emissive="#22c55e",
        emissive_intensity=1.15,
        opacity=0.88,
        flat_shading=True,
    )
    _add_apriltag_stand(b, "04", 0.85, 6.15, yaw=-0.45, solid=True)

    # =========================================================================
    # 3. ZONE 2 (EAST WING +X): RAMP BRIDGE, BALANCE BEAM, STEPS & TRACTION
    # =========================================================================
    # 2A. Walkable 6.5 deg Ramp -> +0.145 m Elevated Observation Bridge -> Exit Ramp
    ramp_x = 2.65
    ramp_w = 1.04
    deck_h = 0.145
    b.add_ramp("east_ramp_up", ramp_x, 0.0, 0.98, ramp_x, deck_h, 2.27, ramp_w, thickness=0.055, color="#475569")
    b.add_box("east_bridge_deck", [ramp_x, deck_h * 0.5, 2.86], [ramp_w, deck_h, 1.18], color="#334155", metalness=0.38, roughness=0.58, solid=True)
    for side, ox in (("l", -ramp_w * 0.5 + 0.025), ("r", ramp_w * 0.5 - 0.025)):
        b.add_box(f"east_bridge_curb_{side}", [ramp_x + ox, deck_h + 0.018, 2.86], [0.045, 0.036, 1.16], color="#38bdf8", emissive="#0284c7", emissive_intensity=0.72, roughness=0.3, solid=True)
    b.add_ramp("east_ramp_down", ramp_x, deck_h, 3.45, ramp_x, 0.0, 4.74, ramp_w, thickness=0.055, color="#475569")
    _add_apriltag_stand(b, "02", ramp_x + 0.72, 2.86, yaw=-math.pi * 0.42, solid=True)
    b.add_box("bridge_beacon_pedestal", [ramp_x + 0.72, 0.14, 1.95], [0.24, 0.28, 0.24], color="#1e293b", metalness=0.5, roughness=0.42, solid=True)
    b.add_poly("surreal_float_bridge_trophy", "octahedron", [ramp_x + 0.72, 0.44, 1.95], [0.10, 0], color="#fde047", emissive="#eab308", emissive_intensity=0.85, metalness=0.5, roughness=0.25, flat_shading=True)

    # 2B. Precision Balance Beam Runway (x = +5.15 m, +0.09 m height, 0.54 m wide, 2.6 m span!)
    beam_x = 5.15
    beam_h = 0.09
    beam_w = 0.54
    b.add_ramp("balance_ramp_up", beam_x, 0.0, 0.80, beam_x, beam_h, 1.58, beam_w, thickness=0.045, color="#64748b")
    b.add_box("balance_beam_span", [beam_x, beam_h * 0.5, 2.88], [beam_w, beam_h, 2.60], color="#334155", metalness=0.42, roughness=0.52, solid=True)
    for side, ox in (("l", -beam_w * 0.5 + 0.018), ("r", beam_w * 0.5 - 0.018)):
        b.add_box(f"balance_edge_{side}", [beam_x + ox, beam_h + 0.002, 2.88], [0.024, 0.004, 2.56], color="#f59e0b", emissive="#f59e0b", emissive_intensity=0.85, solid=False)
    b.add_ramp("balance_ramp_down", beam_x, beam_h, 4.18, beam_x, 0.0, 4.96, beam_w, thickness=0.045, color="#64748b")

    # 2C. Multi-Tiered Climbable Step Terrace (x = +7.35 m, z = 1.4 .. 4.6 m: 16mm -> 32mm -> 48mm!)
    terrace_x = 7.35
    for tier, (tz, td, th, col) in enumerate(
        (
            (3.00, 3.00, 0.016, "#38bdf8"),
            (3.00, 2.00, 0.032, "#f59e0b"),
            (3.00, 1.05, 0.048, "#22c55e"),
        ),
        start=1,
    ):
        b.add_box(
            f"terrace_step_{tier}",
            [terrace_x, th * 0.5, tz],
            [1.65 - (tier - 1) * 0.25, th, td],
            color="#334155" if tier % 2 else "#3f4e63",
            metalness=0.35,
            roughness=0.58,
            solid=True,
        )
        b.add_box(
            f"terrace_trim_{tier}",
            [terrace_x, th + 0.001, tz - td * 0.5 + 0.025],
            [1.60 - (tier - 1) * 0.25, 0.003, 0.03],
            color=col,
            emissive=col,
            emissive_intensity=0.75,
            solid=False,
        )
    # Glowing target orb perched above the top step
    b.add_poly("holo_projection_terrace_orb", "octahedron", [terrace_x, 0.36, 3.00], [0.085, 0], color="#38bdf8", emissive="#0ea5e9", emissive_intensity=1.0, opacity=0.9, flat_shading=True)

    # 2D. Precision Stepping-Stone Pad Grid (z = 5.1 .. 6.2 m)
    stepping_pads = (
        (2.05, 5.20, 0.015, "#0ea5e9"),
        (2.65, 5.42, 0.018, "#f59e0b"),
        (3.22, 5.18, 0.020, "#14b8a6"),
        (2.32, 5.95, 0.022, "#38bdf8"),
        (3.02, 5.98, 0.016, "#eab308"),
    )
    for idx, (px, pz, ph, col) in enumerate(stepping_pads, start=1):
        b.add_box(f"stepping_pad_{idx}", [px, ph * 0.5, pz], [0.44, ph, 0.44], color="#334155", metalness=0.35, roughness=0.58, solid=True)
        b.add_box(f"stepping_pad_trim_{idx}", [px, ph + 0.001, pz], [0.36, 0.002, 0.36], color=col, emissive=col, emissive_intensity=0.45, solid=False)

    # 2E. Rumble / Cobble Traction Test Strip (x = +4.6 .. +7.8 m, z = 5.6 .. 6.8 m)
    for ri in range(6):
        rx = 4.75 + ri * 0.52
        rh = 0.010 + (ri % 3) * 0.004
        b.add_box(
            f"traction_rib_{ri}",
            [rx, rh * 0.5, 6.25 + (0.14 if ri % 2 else -0.14)],
            [0.24, rh, 0.72],
            color="#475569",
            metalness=0.3,
            roughness=0.72,
            solid=True,
        )

    # =========================================================================
    # 4. ZONE 3 (WEST WING -X): AUTONOMOUS VISION & HOUSEHOLD OBJECT GARDEN
    # =========================================================================
    # Double-sided 24-Patch Macbeth ColorChecker Calibration Board
    cc_yaw = 0.48
    b.add_box("colorchecker_base", [-2.05, 0.02, 1.15], [0.54, 0.04, 0.22], rot=[0.0, cc_yaw, 0.0], color="#1e293b", metalness=0.5, roughness=0.45, solid=True)
    b.add_box("colorchecker_frame", [-2.05, 0.26, 1.15], [0.54, 0.36, 0.032], rot=[0.0, cc_yaw, 0.0], color="#334155", metalness=0.45, roughness=0.4, solid=True)
    for cc_side, dz_local in (("front", -0.018), ("back", 0.018)):
        b.add_box(
            "lab_colorchecker_board" if cc_side == "front" else "lab_colorchecker_board_back",
            [-2.05 + dz_local * math.sin(cc_yaw), 0.26, 1.15 + dz_local * math.cos(cc_yaw)],
            [0.50, 0.33, 0.004],
            rot=[0.0, cc_yaw, 0.0],
            color="#ffffff",
            emissive="#ffffff",
            emissive_intensity=0.22,
            roughness=0.65,
            solid=False,
        )

    # Double-sided 9x6 SLAM Checkerboard Calibration Stand (for visual odometry / intrinsics!)
    cb_yaw = 0.28
    b.add_box("checkerboard_base", [-4.65, 0.02, 1.15], [0.72, 0.04, 0.22], rot=[0.0, cb_yaw, 0.0], color="#1e293b", metalness=0.5, roughness=0.45, solid=True)
    b.add_box("checkerboard_frame", [-4.65, 0.32, 1.15], [0.72, 0.50, 0.034], rot=[0.0, cb_yaw, 0.0], color="#334155", metalness=0.45, roughness=0.4, solid=True)
    for cb_side, dz_local in (("front", -0.019), ("back", 0.019)):
        b.add_box(
            "lab_checkerboard_front" if cb_side == "front" else "lab_checkerboard_back",
            [-4.65 + dz_local * math.sin(cb_yaw), 0.32, 1.15 + dz_local * math.cos(cb_yaw)],
            [0.66, 0.44, 0.004],
            rot=[0.0, cb_yaw, 0.0],
            color="#ffffff",
            emissive="#ffffff",
            emissive_intensity=0.22,
            roughness=0.6,
            solid=False,
        )

    # Eye-level AprilTags in Zone 3
    _add_apriltag_stand(b, "01", -1.65, 2.55, yaw=0.55, solid=True)
    _add_apriltag_stand(b, "03", -3.85, 3.95, yaw=0.35, solid=True)

    # Benchmark Geometric & Vision Targets
    b.add_poly("target_ball_cradle", "torus", [-1.58, 0.025, 1.72], [0.10, 0.022, 8, 22], rot=[math.pi / 2.0, 0.0, 0.0], color="#1e293b", metalness=0.45, roughness=0.5, flat_shading=False)
    b.add_poly("target_red_ball", "sphere", [-1.58, 0.125, 1.72], [0.115, 18, 14], color="#ef4444", emissive="#b91c1c", emissive_intensity=0.22, roughness=0.32, flat_shading=False)
    b.add_box("target_red_ball_col", [-1.58, 0.12, 1.72], [0.22, 0.22, 0.22], solid=True, visual=False)

    b.add_box("target_blue_cube", [-2.58, 0.115, 2.28], [0.23, 0.23, 0.23], rot=[0.0, 0.35, 0.0], color="#2563eb", emissive="#1d4ed8", emissive_intensity=0.2, roughness=0.35, solid=True)

    b.add_cylinder("target_green_cylinder", [-1.82, 0.17, 3.35], 0.105, 0.105, 0.34, segments=16, color="#10b981", emissive="#059669", emissive_intensity=0.22, roughness=0.38, flat_shading=False, solid=True)
    b.add_poly("target_green_ring", "torus", [-1.82, 0.345, 3.35], [0.105, 0.015, 8, 22], rot=[math.pi / 2.0, 0.0, 0.0], color="#6ee7b7", emissive="#34d399", emissive_intensity=0.9, flat_shading=False)

    _add_companion_duck(b, -2.85, 1.52, yaw=0.72)

    b.add_box("target_cargo_box", [-3.38, 0.14, 2.75], [0.34, 0.28, 0.28], rot=[0.0, -0.25, 0.0], color="#b88952", roughness=0.88, solid=True)
    b.add_box("target_cargo_tape", [-3.38, 0.281, 2.75], [0.345, 0.004, 0.055], rot=[0.0, -0.25, 0.0], color="#d4a76a", roughness=0.55, solid=False)

    b.add_cylinder("target_hazard_barrel", [-2.52, 0.21, 3.65], 0.135, 0.145, 0.42, segments=14, color="#dc2626", emissive="#991b1b", emissive_intensity=0.16, roughness=0.45, flat_shading=False, solid=True)
    for bi, by in enumerate((0.14, 0.28)):
        b.add_cylinder(f"target_hazard_stripe_{bi}", [-2.52, by, 3.65], 0.142, 0.142, 0.055, segments=14, color="#f8fafc", emissive="#e2e8f0", emissive_intensity=0.25, roughness=0.35, flat_shading=False, solid=False)

    _add_potted_plant(b, "west_a", -3.75, 1.12, scale=1.0)
    _add_potted_plant(b, "west_b", -7.85, 1.25, scale=1.35)
    _add_potted_plant(b, "east_a", 4.15, 0.72, scale=1.05)

    # Floating Holographic Sensor Orb on Scan Plinth
    b.add_cylinder("vision_plinth", [-3.05, 0.09, 0.42], 0.24, 0.28, 0.18, segments=12, color="#1e293b", metalness=0.55, roughness=0.38, solid=True)
    b.add_poly("surreal_spin_vision_ring", "torus", [-3.05, 0.42, 0.42], [0.18, 0.016, 8, 24], color="#38bdf8", emissive="#0ea5e9", emissive_intensity=1.0, flat_shading=False)
    b.add_poly("holo_projection_vision_orb", "icosahedron", [-3.05, 0.42, 0.42], [0.09, 0], color="#c084fc", emissive="#a855f7", emissive_intensity=1.1, opacity=0.88, flat_shading=True)

    # Walk-Through Magenta Inspection Tunnel
    tx, tz = -2.65, 5.15
    for side, ox in (("l", -0.58), ("r", 0.58)):
        b.add_box(f"tunnel_wall_{side}", [tx + ox, 0.34, tz], [0.09, 0.68, 0.96], color="#334155", metalness=0.5, roughness=0.42, solid=True)
        b.add_box(f"tunnel_led_{side}", [tx + (ox * 0.91), 0.36, tz], [0.018, 0.035, 0.88], color="#e879f9", emissive="#d946ef", emissive_intensity=1.1, solid=False)
    b.add_box("tunnel_roof", [tx, 0.71, tz], [1.26, 0.075, 0.98], color="#1e293b", metalness=0.58, roughness=0.35, solid=False)
    b.add_box("tunnel_roof_accent", [tx, 0.752, tz], [1.20, 0.018, 0.14], color="#e879f9", emissive="#d946ef", emissive_intensity=0.95, solid=False)

    # --- NEW: Household & Everyday Indoor Recognition Alcove (x = -8.4 .. -4.8, z = 1.6 .. 6.4) ---
    # 1. Walk-under modern Coffee Table with Coffee Mug + Bright Red Apple on top + Area Rug!
    ct_x, ct_z = -6.45, 2.75
    b.add_box("household_rug", [ct_x, 0.002, ct_z], [2.10, 0.004, 1.50], color="#312e81", emissive="#1e1b4b", emissive_intensity=0.25, roughness=0.92, solid=False)
    b.add_box("coffee_table_top", [ct_x, 0.44, ct_z], [1.18, 0.045, 0.72], color="#c28d57", roughness=0.58, solid=False)
    for li, (lx, lz) in enumerate(((-0.52, -0.29), (0.52, -0.29), (-0.52, 0.29), (0.52, 0.29))):
        b.add_box(f"coffee_table_leg_{li}", [ct_x + lx, 0.21, ct_z + lz], [0.05, 0.42, 0.05], color="#1e293b", metalness=0.5, roughness=0.45, solid=True)
    # Ceramic white/cyan coffee mug & bright red apple on table
    b.add_cylinder("table_mug", [ct_x - 0.24, 0.515, ct_z - 0.08], 0.045, 0.042, 0.105, segments=12, color="#f8fafc", roughness=0.25, flat_shading=False, solid=False)
    b.add_poly("table_apple", "sphere", [ct_x + 0.18, 0.508, ct_z + 0.06], [0.048, 12, 10], color="#ef4444", emissive="#b91c1c", emissive_intensity=0.18, roughness=0.28, flat_shading=False)
    b.add_box("table_apple_stem", [ct_x + 0.18, 0.562, ct_z + 0.06], [0.008, 0.024, 0.008], color="#713f12", solid=False)

    # 2. Stacked Colorful Toy Blocks (primary color segmentation benchmark!)
    blk_x, blk_z = -5.45, 4.35
    b.add_box("toy_block_base_r", [blk_x - 0.11, 0.09, blk_z], [0.18, 0.18, 0.18], color="#ef4444", roughness=0.4, solid=True)
    b.add_box("toy_block_base_b", [blk_x + 0.11, 0.09, blk_z + 0.04], [0.18, 0.18, 0.18], rot=[0.0, 0.2, 0.0], color="#3b82f6", roughness=0.4, solid=True)
    b.add_box("toy_block_mid_y", [blk_x, 0.26, blk_z + 0.01], [0.16, 0.16, 0.16], rot=[0.0, -0.3, 0.0], color="#facc15", roughness=0.4, solid=False)
    b.add_poly("toy_block_top_g", "cone", [blk_x, 0.42, blk_z + 0.01], [0.085, 0.16, 4], color="#22c55e", roughness=0.4, flat_shading=True)

    # 3. Yellow CAUTION A-Frame Safety Sign (procedural texture!)
    cf_x, cf_z, cf_yaw = -5.15, 2.25, 0.52
    b.add_box("caution_aframe_col", [cf_x, 0.22, cf_z], [0.30, 0.44, 0.22], rot=[0.0, cf_yaw, 0.0], solid=True, visual=False)
    for side, tilt, dz_l in (("f", 0.22, -0.07), ("b", -0.22, 0.07)):
        b.add_box(
            f"lab_caution_{side}",
            [cf_x + dz_l * math.sin(cf_yaw), 0.24, cf_z + dz_l * math.cos(cf_yaw)],
            [0.32, 0.46, 0.018],
            rot=[tilt, cf_yaw, 0.0],
            color="#facc15",
            emissive="#facc15",
            emissive_intensity=0.18,
            roughness=0.45,
            solid=False,
        )

    # 4. Miniature Red STOP Sign Post (classic autonomous driving / navigation target!)
    st_x, st_z = -7.65, 4.35
    b.add_cylinder("stopsign_base", [st_x, 0.018, st_z], 0.14, 0.16, 0.036, segments=12, color="#1e293b", metalness=0.5, solid=True)
    b.add_cylinder("stopsign_post", [st_x, 0.36, st_z], 0.016, 0.018, 0.68, segments=8, color="#94a3b8", metalness=0.75, solid=True)
    b.add_box("lab_stopsign_face", [st_x, 0.68, st_z], [0.32, 0.32, 0.022], rot=[0.0, 0.62, 0.0], color="#dc2626", emissive="#ffffff", emissive_intensity=0.22, roughness=0.4, solid=False)

    # 5. Teal Watering Can next to the tall potted ficus plant
    wc_x, wc_z = -7.35, 1.85
    b.add_cylinder("watering_can_body", [wc_x, 0.11, wc_z], 0.09, 0.10, 0.22, segments=12, color="#14b8a6", metalness=0.35, roughness=0.38, solid=True)
    b.add_cylinder("watering_can_spout", [wc_x + 0.13, 0.16, wc_z], 0.018, 0.026, 0.22, segments=8, rot=[0.0, 0.0, -0.78], color="#0d9488", metalness=0.35, solid=False)

    # 6. Stainless Robot-Dog Water Bowl (adorable quadruped lab landmark!)
    bw_x, bw_z = -6.75, 5.45
    b.add_cylinder("dog_bowl_outer", [bw_x, 0.035, bw_z], 0.12, 0.145, 0.07, segments=16, color="#cbd5e1", metalness=0.82, roughness=0.22, flat_shading=False, solid=True)
    b.add_cylinder("dog_bowl_water", [bw_x, 0.062, bw_z], 0.108, 0.108, 0.012, segments=16, color="#38bdf8", emissive="#0284c7", emissive_intensity=0.55, roughness=0.1, flat_shading=False, solid=False)

    # 7. Second Stacked Crate Cluster (logistics / warehouse object test!)
    b.add_box("crate_large", [-7.55, 0.20, 6.05], [0.46, 0.40, 0.46], rot=[0.0, 0.18, 0.0], color="#a17445", roughness=0.88, solid=True)
    b.add_box("crate_small", [-7.52, 0.52, 6.05], [0.28, 0.24, 0.28], rot=[0.0, -0.35, 0.0], color="#c4955e", roughness=0.86, solid=False)

    # =========================================================================
    # 5. ZONE 4 (NORTH-CENTER): AUTONOMOUS WAYPOINT MAZE & PRIZE PLAZA
    #    x in [-3.7, +3.7], z in [7.25, 13.75] (generous >= 1.25 m corridors!)
    # =========================================================================
    # Outer maze perimeter with wide South entry (x in [-0.85, +0.85]), West & East side doors
    _add_maze_wall(b, "s_l", -2.30, 7.35, 2.75, 0.14, "#a855f7")
    _add_maze_wall(b, "s_r", 2.30, 7.35, 2.75, 0.14, "#a855f7")
    _add_maze_wall(b, "w_s", -3.62, 8.70, 0.14, 2.55, "#a855f7")
    _add_maze_wall(b, "w_n", -3.62, 12.40, 0.14, 2.55, "#a855f7")
    _add_maze_wall(b, "e_s", 3.62, 8.70, 0.14, 2.55, "#a855f7")
    _add_maze_wall(b, "e_n", 3.62, 12.40, 0.14, 2.55, "#a855f7")
    _add_maze_wall(b, "n_full", 0.0, 13.68, 7.35, 0.14, "#a855f7")

    # Interior chicane baffle walls creating two distinct branching routes to the Prize Plaza!
    _add_maze_wall(b, "mid_center_s", 0.0, 8.75, 2.55, 0.14, "#38bdf8")
    _add_maze_wall(b, "mid_left_arm", -1.95, 10.15, 0.14, 2.25, "#38bdf8")
    _add_maze_wall(b, "mid_right_arm", 1.95, 10.15, 0.14, 2.25, "#38bdf8")
    _add_maze_wall(b, "mid_north_l", -1.25, 11.45, 1.35, 0.14, "#f59e0b")
    _add_maze_wall(b, "mid_north_r", 1.25, 11.45, 1.35, 0.14, "#f59e0b")

    # Amber Checkpoint Arch spanning the Maze South entrance
    _add_gate_arch(b, "maze_entry", 0.0, 7.35, width=1.65, height=0.78, accent="#f59e0b")

    # Maze Waypoint AprilTags (`TAG-05`, `TAG-06`, `TAG-07`, `TAG-08`)
    _add_apriltag_stand(b, "05", 0.0, 8.50, yaw=0.0, solid=True)
    _add_apriltag_stand(b, "06", -2.75, 10.25, yaw=math.pi * 0.5, solid=True)
    _add_apriltag_stand(b, "07", 2.75, 10.25, yaw=-math.pi * 0.5, solid=True)
    _add_apriltag_stand(b, "08", 0.0, 13.35, yaw=0.0, solid=True)

    # Central Prize Plaza (0, 12.55): Glowing Sanctuary Ring + Rotating Holographic Core Monument
    b.add_poly("plaza_ring", "torus", [0.0, 0.005, 12.55], [0.78, 0.014, 8, 36], rot=[math.pi / 2.0, 0.0, 0.0], color="#facc15", emissive="#eab308", emissive_intensity=1.05, flat_shading=False)
    b.add_poly("surreal_spin_plaza_outer", "torus", [0.0, 1.15, 12.55], [0.42, 0.025, 10, 32], color="#38bdf8", emissive="#0ea5e9", emissive_intensity=1.0, flat_shading=False)
    b.add_poly("surreal_spin_plaza_inner", "torus", [0.0, 1.15, 12.55], [0.28, 0.02, 8, 24], rot=[0.9, 0.5, 0.0], color="#facc15", emissive="#eab308", emissive_intensity=1.1, flat_shading=False)
    b.add_poly("holo_projection_plaza_core", "dodecahedron", [0.0, 1.15, 12.55], [0.15, 0], color="#e0f2fe", emissive="#38bdf8", emissive_intensity=1.2, opacity=0.9, flat_shading=True)

    # =========================================================================
    # 6. ZONE 5 (NORTH-WEST): DYNAMIC TERRAIN & HILL MOUND PROVING PIT
    #    x in [-8.6, -4.5], z in [7.8, 13.6]
    # =========================================================================
    # Walkable 3-ramp Trapezoidal Test Hill (+0.18 m summit, gentle ~6.5 deg slopes!)
    hx, hz, hh = -6.65, 10.75, 0.18
    b.add_box("terrain_hill_summit", [hx, hh * 0.5, hz], [1.25, hh, 1.25], color="#3f5246", metalness=0.18, roughness=0.78, solid=True)
    # South, North, and East gentle climbable ramps onto the summit!
    b.add_ramp("terrain_hill_ramp_s", hx, 0.0, hz - 2.15, hx, hh, hz - 0.62, 1.18, thickness=0.06, color="#4a5f52")
    b.add_ramp("terrain_hill_ramp_n", hx, hh, hz + 0.62, hx, 0.0, hz + 2.15, 1.18, thickness=0.06, color="#4a5f52")
    b.add_ramp("terrain_hill_ramp_e", hx + 0.62, hh, hz, hx + 2.05, 0.0, hz, 1.18, thickness=0.06, color="#4a5f52")
    # Glowing emerald summit beacon ring
    b.add_poly("terrain_summit_ring", "torus", [hx, hh + 0.006, hz], [0.42, 0.012, 8, 28], rot=[math.pi / 2.0, 0.0, 0.0], color="#4ade80", emissive="#22c55e", emissive_intensity=0.95, flat_shading=False)
    _add_apriltag_stand(b, "09", -8.25, 10.75, yaw=math.pi * 0.5, solid=True)

    # Scattered low-profile geometric traction stones / rubble pads (12-24 mm walkable bumps!)
    rubble_stones = (
        (-5.25, 8.35, 0.36, 0.016, 0.32),
        (-6.05, 8.15, 0.42, 0.020, 0.28),
        (-7.75, 8.55, 0.38, 0.018, 0.38),
        (-5.15, 12.95, 0.44, 0.022, 0.34),
        (-7.85, 12.75, 0.40, 0.015, 0.36),
        (-8.15, 9.55, 0.34, 0.020, 0.30),
    )
    for idx, (rx, rz, rw, rh, rd) in enumerate(rubble_stones, start=1):
        b.add_box(
            f"terrain_stone_{idx}",
            [rx, rh * 0.5, rz],
            [rw, rh, rd],
            rot=[0.0, idx * 0.42, 0.0],
            color="#576370" if idx % 2 else "#4b5563",
            roughness=0.88,
            flat_shading=True,
            solid=True,
        )

    # =========================================================================
    # 7. ZONE 6 (NORTH-EAST): ENGINEERING WORKSHOP, SERVERS & TELEMETRY SCREENS
    #    x in [+4.6, +9.0], z in [7.8, 13.8]
    # =========================================================================
    # East Engineering Workbench + Articulated Bench Robot Arm + Telemetry Screen
    bx_e, bz_e = 8.75, 4.20
    b.add_box("east_bench_top", [bx_e, 0.78, bz_e], [0.85, 0.06, 3.20], color="#475569", metalness=0.45, roughness=0.45, solid=True)
    for leg_i, lz in enumerate((bz_e - 1.42, bz_e + 1.42)):
        b.add_box(f"east_bench_leg_{leg_i}", [bx_e, 0.38, lz], [0.74, 0.76, 0.10], color="#1e293b", metalness=0.6, roughness=0.4, solid=True)
    b.add_box("east_monitor_bezel", [9.22, 1.56, bz_e], [0.06, 0.96, 1.84], color="#0f172a", metalness=0.6, roughness=0.3, solid=False)
    b.add_box("lab_screen_telemetry", [9.185, 1.56, bz_e], [0.01, 0.86, 1.74], color="#ffffff", emissive="#ffffff", emissive_intensity=0.72, roughness=0.25, solid=False)

    # Articulated Industrial Yellow Robotic Arm on the East Bench
    b.add_cylinder("bench_arm_base", [bx_e - 0.12, 0.86, bz_e - 0.85], 0.11, 0.13, 0.10, segments=12, color="#1e293b", metalness=0.65, roughness=0.35, solid=False)
    b.add_box("bench_arm_lower", [bx_e - 0.16, 1.12, bz_e - 0.85], [0.08, 0.44, 0.08], rot=[0.0, 0.0, 0.22], color="#f59e0b", metalness=0.35, roughness=0.4, solid=False)
    b.add_box("bench_arm_upper", [bx_e - 0.38, 1.30, bz_e - 0.85], [0.38, 0.065, 0.065], rot=[0.0, 0.0, -0.18], color="#fbbf24", metalness=0.35, roughness=0.4, solid=False)

    # North-East Compute Server Rack Row (3 RL training servers!)
    for si, sx in enumerate((5.45, 6.30, 7.15)):
        _add_server_rack(b, f"ne_{si}", sx, 13.75, yaw=0.0)

    # North-East Diagnostic Inspection Bench + Spare Quadruped Display Pedestal + SLAM Screen
    b.add_box("ne_slam_bench", [8.75, 0.78, 10.65], [0.85, 0.06, 2.80], color="#475569", metalness=0.45, roughness=0.45, solid=True)
    for leg_i, lz in enumerate((9.45, 11.85)):
        b.add_box(f"ne_slam_leg_{leg_i}", [8.75, 0.38, lz], [0.74, 0.76, 0.10], color="#1e293b", metalness=0.6, roughness=0.4, solid=True)
    b.add_box("ne_slam_bezel", [9.22, 1.62, 10.65], [0.06, 1.02, 1.98], color="#0f172a", metalness=0.6, roughness=0.3, solid=False)
    b.add_box("lab_screen_slam", [9.185, 1.62, 10.65], [0.01, 0.92, 1.88], color="#ffffff", emissive="#ffffff", emissive_intensity=0.76, roughness=0.25, solid=False)

    # Central NE Display Pedestal with glowing miniature holo-robot sculpture
    b.add_cylinder("ne_pedestal", [6.35, 0.28, 10.45], 0.36, 0.42, 0.56, segments=12, color="#1e293b", metalness=0.55, roughness=0.38, solid=True)
    b.add_box("holo_projection_spare_bot", [6.35, 0.72, 10.45], [0.24, 0.10, 0.32], color="#38bdf8", emissive="#0ea5e9", emissive_intensity=0.95, opacity=0.82, solid=False)

    # West Vision & Autonomous Learning Workstation + Radar Screen
    bx_w, bz_w = -8.75, 4.20
    b.add_box("west_bench_top", [bx_w, 0.78, bz_w], [0.85, 0.06, 3.20], color="#475569", metalness=0.45, roughness=0.45, solid=True)
    for leg_i, lz in enumerate((bz_w - 1.42, bz_w + 1.42)):
        b.add_box(f"west_bench_leg_{leg_i}", [bx_w, 0.38, lz], [0.74, 0.76, 0.10], color="#1e293b", metalness=0.6, roughness=0.4, solid=True)
    b.add_box("west_monitor_bezel", [-9.22, 1.56, bz_w], [0.06, 0.96, 1.84], color="#0f172a", metalness=0.6, roughness=0.3, solid=False)
    b.add_box("lab_screen_vision", [-9.185, 1.56, bz_w], [0.01, 0.86, 1.74], color="#ffffff", emissive="#ffffff", emissive_intensity=0.72, roughness=0.25, solid=False)

    # =========================================================================
    # 8. ARCHITECTURAL 19.2m x 19.2m LAB HALL, OVERHEAD GANTRY & BRIDGE CRANE
    # =========================================================================
    x_min, x_max = -9.60, 9.60
    z_min, z_max = -4.40, 14.80
    wall_h_low = 1.28
    roof_y = 5.10

    for tag, pos, size in (
        ("north", [0.0, wall_h_low * 0.5, z_max], [x_max - x_min + 0.3, wall_h_low, 0.28]),
        ("south", [0.0, wall_h_low * 0.5, z_min], [x_max - x_min + 0.3, wall_h_low, 0.28]),
        ("west", [x_min, wall_h_low * 0.5, (z_min + z_max) * 0.5], [0.28, wall_h_low, z_max - z_min]),
        ("east", [x_max, wall_h_low * 0.5, (z_min + z_max) * 0.5], [0.28, wall_h_low, z_max - z_min]),
    ):
        b.add_box(f"lab_wall_low_{tag}", pos, size, color="#263345", metalness=0.35, roughness=0.62, solid=True)

    for tag, pos, size in (
        ("north", [0.0, wall_h_low + 0.03, z_max - 0.15], [x_max - x_min, 0.055, 0.04]),
        ("south", [0.0, wall_h_low + 0.03, z_min + 0.15], [x_max - x_min, 0.055, 0.04]),
        ("west", [x_min + 0.15, wall_h_low + 0.03, (z_min + z_max) * 0.5], [0.04, 0.055, z_max - z_min]),
        ("east", [x_max - 0.15, wall_h_low + 0.03, (z_min + z_max) * 0.5], [0.04, 0.055, z_max - z_min]),
    ):
        b.add_box(f"lab_wall_trim_{tag}", pos, size, color="#38bdf8", emissive="#0284c7", emissive_intensity=0.72, solid=False)

    b.add_box("lab_north_hazard_trim", [0.0, 0.06, z_max - 0.17], [x_max - x_min - 0.4, 0.12, 0.06], color="#f59e0b", emissive="#b45309", emissive_intensity=0.25, solid=False)

    # Giant Panoramic North Wall Telemetry & SLAM Command Displays!
    b.add_box("north_wall_screen_bezel", [0.0, 2.75, z_max - 0.20], [5.40, 2.15, 0.14], color="#0f172a", metalness=0.65, roughness=0.3, solid=False)
    b.add_box("lab_screen_telemetry_north", [0.0, 2.75, z_max - 0.28], [5.16, 1.96, 0.015], color="#ffffff", emissive="#ffffff", emissive_intensity=0.75, roughness=0.25, solid=False)

    b.add_box("north_wall_slam_bezel", [-5.45, 2.65, z_max - 0.20], [3.60, 1.72, 0.12], color="#0f172a", metalness=0.65, roughness=0.3, solid=False)
    b.add_box("lab_screen_slam_north", [-5.45, 2.65, z_max - 0.27], [3.42, 1.56, 0.015], color="#ffffff", emissive="#ffffff", emissive_intensity=0.75, roughness=0.25, solid=False)

    b.add_box("north_wall_vision_bezel", [5.45, 2.65, z_max - 0.20], [3.60, 1.72, 0.12], color="#0f172a", metalness=0.65, roughness=0.3, solid=False)
    b.add_box("lab_screen_vision_north", [5.45, 2.65, z_max - 0.27], [3.42, 1.56, 0.015], color="#ffffff", emissive="#ffffff", emissive_intensity=0.75, roughness=0.25, solid=False)

    # 6 Structural steel bay columns, overhead gantry trusses & LED ceiling light bars
    col_zs = (-4.0, -0.4, 3.2, 6.8, 10.4, 14.2)
    for ci, cz in enumerate(col_zs):
        for side, cx in (("w", x_min + 0.16), ("e", x_max - 0.16)):
            b.add_box(f"lab_col_{side}_{ci}", [cx, roof_y * 0.5, cz], [0.28, roof_y, 0.28], color="#475569", metalness=0.62, roughness=0.38, solid=False)
        b.add_box(f"lab_gantry_beam_{ci}", [0.0, roof_y, cz], [x_max - x_min, 0.22, 0.24], color="#334155", metalness=0.68, roughness=0.35, solid=False)
        b.add_box(f"lab_ceiling_led_{ci}", [0.0, roof_y - 0.13, cz], [14.2, 0.045, 0.12], color="#e0f2fe", emissive="#bae6fd", emissive_intensity=1.25, solid=False)

    # Overhead Longitudinal Crane Rails & Iconic Yellow Industrial Bridge Crane + Hoist!
    for side, rx in (("w", -6.2), ("e", 6.2)):
        b.add_box(f"lab_crane_rail_{side}", [rx, roof_y - 0.28, (z_min + z_max) * 0.5], [0.16, 0.18, z_max - z_min], color="#f59e0b", emissive="#b45309", emissive_intensity=0.18, metalness=0.55, roughness=0.38, solid=False)
    b.add_box("overhead_bridge_crane", [0.0, roof_y - 0.46, 5.20], [13.0, 0.24, 0.34], color="#eab308", emissive="#a16207", emissive_intensity=0.16, metalness=0.5, roughness=0.4, solid=False)
    b.add_box("overhead_crane_trolley", [1.4, roof_y - 0.68, 5.20], [0.68, 0.26, 0.46], color="#1e293b", metalness=0.65, roughness=0.35, solid=False)

    # Panoramic tinted upper observation glass along East & West walls
    for side, wx in (("w", x_min), ("e", x_max)):
        b.add_box(f"lab_glass_{side}", [wx, 3.15, (z_min + z_max) * 0.5], [0.04, 3.60, z_max - z_min - 0.4], color="#38bdf8", emissive="#0c4a6e", emissive_intensity=0.2, opacity=0.12, roughness=0.1, metalness=0.8, solid=False)

    # 8 balanced studio lights illuminating all 6 zones evenly!
    lights = [
        {"id": "light_lab_spawn", "color": "#e0f2fe", "intensity": 2.4, "distance": 13.0, "pos": [0.0, 3.2, 0.5]},
        {"id": "light_lab_runway", "color": "#f8fafc", "intensity": 2.6, "distance": 14.0, "pos": [0.0, 3.6, 4.2]},
        {"id": "light_lab_vision", "color": "#bae6fd", "intensity": 2.5, "distance": 13.0, "pos": [-5.2, 3.2, 3.2]},
        {"id": "light_lab_east", "color": "#fef3c7", "intensity": 2.5, "distance": 13.0, "pos": [5.2, 3.2, 3.2]},
        {"id": "light_lab_maze", "color": "#e9d5ff", "intensity": 2.5, "distance": 14.0, "pos": [0.0, 3.4, 10.6]},
        {"id": "light_lab_terrain", "color": "#bbf7d0", "intensity": 2.4, "distance": 12.0, "pos": [-6.5, 3.2, 10.6]},
        {"id": "light_lab_workshop", "color": "#bae6fd", "intensity": 2.4, "distance": 12.0, "pos": [6.5, 3.2, 10.6]},
        {"id": "light_lab_goal", "color": "#4ade80", "intensity": 2.1, "distance": 8.0, "pos": [0.0, 1.6, 5.6]},
    ]

    return {
        "id": "v2_lab",
        "name": "Robotics Lab (Obstacle Course)",
        "subtitle": (
            "19m multi-zone proving ground · agility runway, maze, ramp bridge, "
            "terrain pit, AprilTags & vision targets"
        ),
        "skyboxDir": "/assets/skyboxes/classic",
        "backgroundHex": "#101a2c",
        "fogHex": "#142238",
        "fogDensity": 0.0052,
        "useDefaultFloorPlane": True,
        "robotSpawnMj": [0.0, 0.0, 0.066],
        "primitives": b.primitives,
        "glbInstances": [],
        "colliders": b.colliders,
        "lights": lights,
    }


if __name__ == "__main__":
    import json
    from pathlib import Path

    out = Path("/home/greggles/Ainekio/apps/simulator/public/sim/levels/v2-lab.level.json")
    bundle = build_robotics_lab_level()
    out.write_text(json.dumps(bundle, separators=(",", ":")) + "\n", encoding="utf-8")
    print(
        f"Wrote {out} ({out.stat().st_size:,} bytes): "
        f"{len(bundle['primitives'])} primitives, {len(bundle['colliders'])} colliders"
    )
