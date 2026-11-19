#!/usr/bin/env python3
"""Derive Ainekio V1 128x64 1-bit OLED face assets from the V2 C face renderer.

`Slave/software/faces/faces.def` and `Slave/software/faces/face.c` own all
expression definitions, geometry, accents, and animation trajectories. This
tool samples the compiled native `face_preview` executable and writes:
  - `Slave/software/assets/seed/faces/<name>/<frame>.bin` (1024-byte MSB-first)
  - `Slave/software/assets/seed/faces-v1.json`
  - `Slave/firmware/esp32s3/components/ainekio_platform/src/default_face_bitmap.h`

No external or hand-drawn bitmaps are used.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OLED_WIDTH = 128
OLED_HEIGHT = 64
OLED_ROW_BYTES = OLED_WIDTH // 8
OLED_FRAME_BYTES = OLED_ROW_BYTES * OLED_HEIGHT
MAX_V1_FRAMES = 6

# Exact 2.5x isotropic crop from 320x170 (where AINEKIO_FACE_OFFSET_Y = 10 shifts
# the wide layout to y=46..146): [0..320) x [12..172) -> 128 x 64, centering the
# eyes at y=32 with symmetric top/bottom margin for question marks and voice bars.
CROP_Y_OFFSET = 12.0
SCALE = 2.5
CORE_THRESHOLD = 145.0

ROOT = Path(__file__).resolve().parents[4]
FACES_DEF = Path(__file__).resolve().parents[1] / "faces.def"
DEFAULT_SEED_DIR = ROOT / "Slave" / "software" / "assets" / "seed"
DEFAULT_HEADER_PATH = (
    ROOT
    / "Slave"
    / "firmware"
    / "esp32s3"
    / "components"
    / "ainekio_platform"
    / "src"
    / "default_face_bitmap.h"
)

FACE_RE = re.compile(
    r"^FACE\(\s*([a-z0-9_]+)\s*,\s*([A-Z_]+)\s*,\s*([A-Z_]+)\s*,\s*"
    r"([A-Z_]+)\s*,\s*([A-Z_]+)\s*,\s*([A-Z_]+)\s*,\s*"
    r"([-+0-9.]+)\s*,\s*([-+0-9.]+)\s*,\s*([0-9]+)\s*\)$"
)


@dataclass(frozen=True)
class FaceRecipe:
    name: str
    left_eye: str
    right_eye: str
    color: str
    animation: str
    accent: str
    gaze_x: float
    gaze_y: float
    period_ms: int


def parse_faces_def(path: Path) -> list[FaceRecipe]:
    recipes: list[FaceRecipe] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("/*") or line.startswith("*") or line.startswith("//"):
            continue
        match = FACE_RE.match(line)
        if not match:
            raise ValueError(f"Unrecognized line in {path}: {raw_line!r}")
        recipes.append(
            FaceRecipe(
                name=match.group(1),
                left_eye=match.group(2),
                right_eye=match.group(3),
                color=match.group(4),
                animation=match.group(5),
                accent=match.group(6),
                gaze_x=float(match.group(7)),
                gaze_y=float(match.group(8)),
                period_ms=int(match.group(9)),
            )
        )
    if not recipes:
        raise ValueError(f"No FACE(...) entries found in {path}")
    return recipes


def verify_renderer_matches_defs(renderer: Path, recipes: list[FaceRecipe]) -> None:
    lines = subprocess.check_output([renderer, "--list"], text=True).splitlines()
    listed = [(parts[0], int(parts[1])) for parts in (line.split() for line in lines)]
    expected = [(r.name, r.period_ms) for r in recipes]
    if listed != expected:
        raise RuntimeError(
            "Renderer expression table does not match faces.def; rebuild face_preview."
        )


def core_score(r: int, g: int, b: int) -> float:
    if r == 0 and g == 0 and b == 0:
        return 0.0
    mx = max(r, g, b)
    mn = min(r, g, b)
    return mx * 0.65 + mn * 0.85


def rgb_to_oled_bytes(rgb_img: Image.Image) -> bytes:
    w, h = rgb_img.size
    px = rgb_img.load()
    scores = [[0.0] * w for _ in range(h)]
    for y in range(h):
        row = scores[y]
        for x in range(w):
            r, g, b = px[x, y]
            if r or g or b:
                row[x] = core_score(r, g, b)

    def bilerp(fx: float, fy: float) -> float:
        if fx < 0.0 or fy < 0.0 or fx >= w - 1 or fy >= h - 1:
            if 0.0 <= fx < w and 0.0 <= fy < h:
                ix = min(max(int(round(fx)), 0), w - 1)
                iy = min(max(int(round(fy)), 0), h - 1)
                return scores[iy][ix]
            return 0.0
        x0, y0 = int(fx), int(fy)
        tx, ty = fx - x0, fy - y0
        v00 = scores[y0][x0]
        v10 = scores[y0][x0 + 1]
        v01 = scores[y0 + 1][x0]
        v11 = scores[y0 + 1][x0 + 1]
        return (v00 * (1.0 - tx) + v10 * tx) * (1.0 - ty) + (
            v01 * (1.0 - tx) + v11 * tx
        ) * ty

    buf = bytearray(OLED_FRAME_BYTES)
    for oy in range(OLED_HEIGHT):
        cy = CROP_Y_OFFSET + oy * SCALE + SCALE * 0.5
        row_base = oy * OLED_ROW_BYTES
        for ox in range(OLED_WIDTH):
            cx = ox * SCALE + SCALE * 0.5
            center_v = bilerp(cx, cy)
            near_v = max(
                bilerp(cx - 0.65, cy),
                bilerp(cx + 0.65, cy),
                bilerp(cx, cy - 0.65),
                bilerp(cx, cy + 0.65),
            )
            if max(center_v, near_v * 0.82) >= CORE_THRESHOLD:
                buf[row_base + (ox >> 3)] |= 0x80 >> (ox & 7)
    return bytes(buf)


def render_frame_bytes(renderer: Path, name: str, elapsed_ms: int) -> bytes:
    png_data = subprocess.check_output([renderer, name, str(elapsed_ms)])
    rgb = Image.open(io.BytesIO(png_data)).convert("RGB")
    return rgb_to_oled_bytes(rgb)


def sample_plan(recipe: FaceRecipe) -> tuple[list[int], int, str]:
    """Return (sample_times_ms, fps, mode) within V1's 6-frame limit.

    Every sequence keeps open/expressive keyframes at both index 0 and index -1
    so `loop`, `boomerang`, and `.amot` `once` hold modes all display cleanly.
    """
    p = recipe.period_ms
    anim = recipe.animation
    acc = recipe.accent

    if anim == "STILL":
        return [0], 1, "once"

    if anim == "BLINK":
        # Smooth 5-frame blink finishing open at frame 4 (455 ms @ 11 fps).
        fracs = [0.22, 0.50, 0.72, 0.86, 0.0]
        return [int(round(f * p)) for f in fracs], 11, "once"

    if anim == "SPEAK":
        # `face.c` drives the 5-bar equalizer from `(elapsed_ms % 1500) * 0.025F`.
        times = [0, 55, 110, 165, 220, 275]
        return times, 8, "loop"

    if anim == "WINK":
        # Wink spans t in (0.30, 0.60) with peak closure at t = 0.45; end open.
        fracs = [0.0, 0.34, 0.45, 0.56, 0.74, 0.90]
        fps = max(3, min(8, int(round(6000.0 / p))))
        return [int(round(f * p)) for f in fracs], fps, "loop"

    if anim == "THINK":
        # Capture upward-right glance, left glance, thoughtful right-eye squint,
        # and traveling ellipsis while avoiding the brief blink at 0.84..0.89.
        fracs = [0.0, 0.20, 0.47, 0.64, 0.78, 0.94]
        return [int(round(f * p)) for f in fracs], 2, "loop"

    if anim == "INQUIRE":
        # Lean in, hold the questioning widen, and settle (avoiding 0.84..0.90 blink).
        fracs = [0.0, 0.16, 0.36, 0.52, 0.68, 0.95]
        return [int(round(f * p)) for f in fracs], 2, "loop"

    if anim == "ATTEND":
        fracs = [i / 6.0 for i in range(6)]
        return [int(round(f * p)) for f in fracs], 3, "loop"

    if anim == "BREATHE":
        if acc in ("TEAR",):
            # Continuous teardrop descent while staying outside the 0.89..0.96 blink.
            fracs = [0.08, 0.24, 0.40, 0.56, 0.72, 0.86]
            return [int(round(f * p)) for f in fracs], 3, "loop"
        if acc in ("SLEEP",):
            # Floating Z/z breath cycle (eyes are already FLAT).
            fracs = [i / 6.0 for i in range(6)]
            return [int(round(f * p)) for f in fracs], 2, "loop"
        # Pure resting BREATHE faces (default, idle, stand, neutral, bow, stretch,
        # lay_down, crouch, upright): V1 `service_idle()` schedules `idle_blink`
        # separately, so keep steady open eyes without closed-blink frames.
        return [0], 1, "once"

    if anim == "PULSE":
        # Check across cycle; deduplication below collapses identical 1-bit frames.
        fracs = [i / 6.0 for i in range(6)]
        fps = max(2, min(8, int(round(6000.0 / p))))
        return [int(round(f * p)) for f in fracs], fps, "loop"

    # BOB, SWAY, LOOK, TILT
    fracs = [i / 6.0 for i in range(6)]
    fps = max(2, min(10, int(round(6000.0 / p))))
    return [int(round(f * p)) for f in fracs], fps, "loop"


def deduplicate_frames(frames: list[bytes], fps: int, mode: str) -> tuple[list[bytes], int, str]:
    if not frames:
        raise ValueError("Empty frame list")
    if all(f == frames[0] for f in frames):
        return [frames[0]], 1, "once"
    # Collapse consecutive identical frames only if all frames collapsed to <= MAX_V1_FRAMES.
    compact: list[bytes] = [frames[0]]
    for frame in frames[1:]:
        if frame != compact[-1]:
            compact.append(frame)
    if len(compact) == 1:
        return compact, 1, "once"
    return frames[:MAX_V1_FRAMES], fps, mode


def format_default_header(default_bytes: bytes) -> str:
    if len(default_bytes) != OLED_FRAME_BYTES:
        raise ValueError(f"Expected {OLED_FRAME_BYTES} bytes")
    lines = [
        "/* Generated by Slave/software/faces/tools/derive_v1_oled.py from",
        " * Slave/software/faces/faces.def (`default`). Do not hand-edit. */",
        "#ifndef AINEKIO_PLATFORM_DEFAULT_FACE_BITMAP_H",
        "#define AINEKIO_PLATFORM_DEFAULT_FACE_BITMAP_H",
        "",
        "#include <stdint.h>",
        "",
        "static const uint8_t ainekio_default_face_bitmap[1024] = {",
    ]
    for offset in range(0, len(default_bytes), 16):
        chunk = ", ".join(f"0x{b:02x}U" for b in default_bytes[offset : offset + 16])
        lines.append(f"    {chunk},")
    lines.extend(["};", "", "#endif", ""])
    return "\n".join(lines)


def build_v1_library(
    renderer: Path, recipes: list[FaceRecipe]
) -> tuple[dict[str, object], dict[str, list[bytes]]]:
    manifest_faces: list[dict[str, object]] = []
    binaries: dict[str, list[bytes]] = {}
    for recipe in recipes:
        times, fps, mode = sample_plan(recipe)
        raw_frames = [render_frame_bytes(renderer, recipe.name, t) for t in times]
        frames, fps, mode = deduplicate_frames(raw_frames, fps, mode)
        binaries[recipe.name] = frames
        manifest_faces.append(
            {
                "fps": fps,
                "frames": [f"faces/{recipe.name}/{idx}.bin" for idx in range(len(frames))],
                "height": OLED_HEIGHT,
                "mode": mode,
                "name": recipe.name,
                "width": OLED_WIDTH,
            }
        )
    manifest: dict[str, object] = {
        "derived_from": "Slave/software/faces/faces.def",
        "faces": manifest_faces,
        "schema_version": 1,
    }
    return manifest, binaries


def oled_bytes_to_rgb(frame: bytes, fg: tuple[int, int, int] = (90, 230, 255)) -> Image.Image:
    img = Image.new("RGB", (OLED_WIDTH, OLED_HEIGHT), (0, 0, 0))
    px = img.load()
    for y in range(OLED_HEIGHT):
        row = y * OLED_ROW_BYTES
        for x in range(OLED_WIDTH):
            if frame[row + (x >> 3)] & (0x80 >> (x & 7)):
                px[x, y] = fg
    return img


def write_contact_sheet(
    out_path: Path,
    manifest: dict[str, object],
    binaries: dict[str, list[bytes]],
) -> None:
    faces = manifest["faces"]
    assert isinstance(faces, list)
    cols = 6
    rows = (len(faces) + cols - 1) // cols
    cell_w, cell_h = OLED_WIDTH * 2 + 16, OLED_HEIGHT * 2 + 28
    sheet = Image.new("RGB", (cols * cell_w + 16, rows * cell_h + 52), (11, 16, 20))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 13)
    draw.text(
        (16, 16),
        f"Ainekio V1 128x64 OLED Library Derived from V2 ({len(faces)} owner expressions, 2x pixel zoom)",
        fill=(234, 242, 247),
        font=font,
    )
    for idx, entry in enumerate(faces):
        assert isinstance(entry, dict)
        name = str(entry["name"])
        frames = binaries[name]
        # Display the middle/expressive frame for multi-frame animations (e.g. wink, blink, tear, speak)
        rep_idx = 1 if name == "idle_blink" else (2 if len(frames) >= 4 else len(frames) // 2)
        vis = oled_bytes_to_rgb(frames[rep_idx]).resize(
            (OLED_WIDTH * 2, OLED_HEIGHT * 2), Image.Resampling.NEAREST
        )
        gx = (idx % cols) * cell_w + 12
        gy = (idx // cols) * cell_h + 46
        draw.rectangle(
            [gx - 1, gy - 1, gx + OLED_WIDTH * 2, gy + OLED_HEIGHT * 2],
            outline=(38, 54, 64),
        )
        sheet.paste(vis, (gx, gy))
        tag = f"{name} ({len(frames)}f@{entry['fps']}fps)"
        draw.text((gx + 2, gy + OLED_HEIGHT * 2 + 4), tag, fill=(168, 194, 208), font=font)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)


def check_outputs(
    seed_dir: Path,
    header_path: Path,
    manifest_text: str,
    binaries: dict[str, list[bytes]],
    header_text: str,
) -> int:
    manifest_path = seed_dir / "faces-v1.json"
    if not manifest_path.is_file() or manifest_path.read_text(encoding="utf-8") != manifest_text:
        print(f"Mismatch: {manifest_path}", file=sys.stderr)
        return 1
    if not header_path.is_file() or header_path.read_text(encoding="utf-8") != header_text:
        print(f"Mismatch: {header_path}", file=sys.stderr)
        return 1
    faces_root = seed_dir / "faces"
    expected_rel: set[Path] = set()
    for name, frames in binaries.items():
        for idx, data in enumerate(frames):
            rel = Path(name) / f"{idx}.bin"
            expected_rel.add(rel)
            target = faces_root / rel
            if not target.is_file() or target.read_bytes() != data:
                print(f"Mismatch: {target}", file=sys.stderr)
                return 1
    actual_rel = (
        {p.relative_to(faces_root) for p in faces_root.rglob("*") if p.is_file()}
        if faces_root.exists()
        else set()
    )
    extra = sorted(actual_rel - expected_rel)
    if extra:
        print(f"Unexpected extra face files under {faces_root}: {extra}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--renderer", type=Path, required=True, help="Compiled native face_preview binary")
    parser.add_argument("--seed-dir", type=Path, default=DEFAULT_SEED_DIR)
    parser.add_argument("--default-header", type=Path, default=DEFAULT_HEADER_PATH)
    parser.add_argument("--contact-sheet", type=Path, default=None)
    parser.add_argument("--check", action="store_true", help="Verify checked-in V1 face assets match V2")
    args = parser.parse_args()

    recipes = parse_faces_def(FACES_DEF)
    verify_renderer_matches_defs(args.renderer, recipes)
    manifest, binaries = build_v1_library(args.renderer, recipes)
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    header_text = format_default_header(binaries["default"][0])

    if args.check:
        rc = check_outputs(args.seed_dir, args.default_header, manifest_text, binaries, header_text)
        if rc == 0:
            print(
                f"Verified {len(recipes)} V1 OLED expressions ({sum(len(v) for v in binaries.values())} frames) match V2."
            )
        return rc

    faces_root = args.seed_dir / "faces"
    if faces_root.exists():
        shutil.rmtree(faces_root)
    for name, frames in binaries.items():
        face_dir = faces_root / name
        face_dir.mkdir(parents=True, exist_ok=True)
        for idx, data in enumerate(frames):
            (face_dir / f"{idx}.bin").write_bytes(data)

    (args.seed_dir / "faces-v1.json").write_text(manifest_text, encoding="utf-8")
    args.default_header.parent.mkdir(parents=True, exist_ok=True)
    args.default_header.write_text(header_text, encoding="utf-8")

    if args.contact_sheet is not None:
        write_contact_sheet(args.contact_sheet, manifest, binaries)

    total_frames = sum(len(v) for v in binaries.values())
    print(
        f"Derived {len(recipes)} V1 OLED expressions ({total_frames} frames, "
        f"{len(manifest_text)} B index) from {FACES_DEF}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
