"""Attach the read-only Wireless CAD export to the existing four-bar model.

CAD surfaces are retained for rendering, with documented attachment corrections.
Collision copies use CoACD mechanical solids and named coarse envelopes for
fixed modules/fittings, never one hull replacing the articulated robot.
The owner's 650 g total is measured; CAD-volume mass distribution is an estimate.
Run ``python -m Master.gateway.neural_gait.assembly --package`` after a Blender
export/conversion to publish the frozen derived meshes. Normal preparation
restores that package, without rerunning a native decomposition algorithm.
"""
from concurrent.futures import ProcessPoolExecutor
import fcntl
import hashlib
import json
from pathlib import Path
import struct
import os
import shutil
import zipfile
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import mujoco
import numpy as np
import trimesh

SOURCE = Path(__file__).resolve().parents[3] / "Slave/software/models/v2-12servo/simulation"
VERSION = 2
MODULE_ENVELOPES = frozenset((
    "PCB_29x62_holes_ESTIMATED", "Purple_PCB_13x18_two_holes_ESTIMATED",
    "REFERENCE | Battery pack - 73.6 x 46 x 22 mm",
    "REFERENCE | HiLetgo 2S USB-C charger - rear",
    "REFERENCE | HiLetgo CD74HC4067 - estimated mounting dimensions",
    "REFERENCE | Mini560 buck converter - rear",
    "TESTS | Board - Adafruit PCA9685", "TESTS | Board - ESP32-P4-WIFI6",
    "TESTS | Face - Arducam B0066 - camera mock-up",
))
PREPROCESS_REQUIRED = frozenset((
    # These closed imports trigger CoACD's native "Wrong MCTS clip proposal"
    # on direct decomposition; preprocess the collision copy, not the CAD.
    "STRUCTURAL | Front panel brace - Left",
))
# Coarse first-trial contacts for fixed fittings whose detailed decomposition
# blocked assembly preparation. Each disconnected source solid keeps its own
# envelope: this does not close the entire chassis or replace moving links.
FIXED_COMPONENT_ENVELOPES = frozenset((
    "STRUCTURAL | Battery carrier - rear power module cradle",
    "STRUCTURAL | Rear power carrier - open two-level frame",
    "STRUCTURAL | Tray mount plate - Front",
    "STRUCTURAL | Wireless keeper bridge - battery mounted",
    "Side.Guard.L.001", "Side.Guard.R.002",
    "TESTS | Body - Front End Panel - Compact",
    "TESTS | Body - Left Center Mount.001",
    "TESTS | Body - Rear End Panel - Q6A Ports",
    "TESTS | Body - Right Center Mount.001",
    "TESTS | FR - Part_002_SG90", "TESTS | Part_002_SG90",
    "TESTS | RL - Part_002_SG90", "TESTS | RR - Part_002_SG90",
    "TESTS | Face - Black LCD Carrier",
    "Temple.L.001", "Temple.R.001", "Viewing_window_23p695x43p72",
))


def _text(value):
    return " ".join(format(float(x), ".12g") for x in np.asarray(value).ravel())


def _msh(path, vertices, faces):
    with path.open("wb") as f:
        f.write(struct.pack("4i", len(vertices), 0, 0, len(faces)))
        f.write(np.asarray(vertices, dtype=np.float32).tobytes())
        f.write(np.asarray(faces, dtype=np.int32).tobytes())


def _fingerprint():
    # VERSION owns CAD-to-body-frame conversion. RL action/observation schemas
    # do not change these meshes and must not invalidate prepared assets.
    h = hashlib.sha256(str(VERSION).encode())
    h.update(json.dumps([sorted(MODULE_ENVELOPES), sorted(PREPROCESS_REQUIRED), sorted(FIXED_COMPONENT_ENVELOPES)]).encode())
    for name in ("assembly.json", "assembly.npz"):
        h.update((SOURCE / name).read_bytes())
    # Geometry owns the body frames used to make the exported vertices local.
    h.update((SOURCE.parent / "geometry.json").read_bytes())
    return h.hexdigest()


def _identity(obj, vertices, faces):
    method = "fixed-electronic-module-envelope-v1" if obj["name"] in MODULE_ENVELOPES else "coacd-1.0.7-normalized-0.03"
    if obj["name"] in PREPROCESS_REQUIRED:
        method += "-preprocessed"
    if obj["name"] in FIXED_COMPONENT_ENVELOPES:
        method = "fixed-fitting-per-connected-solid-envelope-v1"
    h = hashlib.sha256(method.encode())
    h.update(json.dumps(obj, sort_keys=True).encode())
    h.update(np.asarray(vertices, dtype=np.float64).tobytes())
    h.update(np.asarray(faces, dtype=np.int32).tobytes())
    return h.hexdigest(), method


def _atomic_json(path, value):
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def _asset_names(manifest):
    return sorted({name + ".msh" for obj in manifest["objects"]
                   for name in [obj["visual"], *obj["collision"]]})


def _restore_prepared(directory, fingerprint):
    """Restore the frozen derived geometry, not a fresh stochastic conversion."""
    descriptor = SOURCE / "prepared.json"
    if not descriptor.exists():
        return None
    package = json.loads(descriptor.read_text())
    if package["source_sha256"] != fingerprint:
        return None  # A new CAD snapshot needs its own explicit conversion.
    archive = SOURCE / "prepared.zip"
    if hashlib.sha256(archive.read_bytes()).hexdigest() != package["archive_sha256"]:
        raise ValueError("Prepared assembly archive checksum mismatch")
    with zipfile.ZipFile(archive) as source:
        manifest = json.loads(source.read("manifest.json"))
        if manifest["source_sha256"] != fingerprint:
            raise ValueError("Prepared assembly manifest does not match its source")
        for name in _asset_names(manifest):
            destination = directory / name
            temporary = destination.with_name(destination.name + f".{os.getpid()}.tmp")
            with source.open(name) as src, temporary.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            temporary.replace(destination)
    _atomic_json(directory / "manifest.json", manifest)
    return manifest


def package_prepared(config=None):
    """Publish exact prepared meshes so machines share one collision asset."""
    directory, manifest = prepare(config)
    archive = SOURCE / "prepared.zip"
    temporary = archive.with_name(archive.name + f".{os.getpid()}.tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6) as output:
        for name in ["manifest.json", *_asset_names(manifest)]:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            output.writestr(info, (directory / name).read_bytes())
    temporary.replace(archive)
    descriptor = dict(source_sha256=manifest["source_sha256"],
        archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        files=len(_asset_names(manifest)),
        basis="Frozen verified conversion; exact mesh bytes and per-object approximation provenance retained",
        rebuild_limit="Fresh CoACD 1.0.7 conversion can abort natively on some imported solids; this package avoids rerunning it for this unchanged geometry")
    _atomic_json(SOURCE / "prepared.json", descriptor)
    return descriptor


def _frames(config, manifest):
    from .environment import build_xml, GaitEnvironment
    from .contract import JOINTS
    model = mujoco.MjModel.from_xml_string(build_xml(config, include_assembly=False))
    data = mujoco.MjData(model)
    ids = [model.joint(name).id for name in JOINTS]
    state = SimpleNamespace(model=model, data=data, qadr=model.jnt_qposadr[ids])
    GaitEnvironment.set_pose(state, np.deg2rad(manifest["angles_deg"]))
    return {model.body(i).name: (data.xpos[i].copy(), data.xmat[i].reshape(3, 3).copy())
            for i in range(1, model.nbody)}


def _convert(job):
    """One independent CAD object; approximation affects collision copies only."""
    import coacd
    obj, vertices, faces, directory = job
    directory = Path(directory)
    name = obj["key"]
    record = directory / (name + ".json")
    identity, method = _identity(obj, vertices, faces)
    if record.exists():
        cached = json.loads(record.read_text())
        if cached.get("conversion_identity") == identity:
            return cached
    _msh(directory / (name + ".msh"), vertices, faces)
    mesh = trimesh.Trimesh(vertices, faces, process=True)
    collision = []
    coacd.set_log_level("error")
    components = [mesh.convex_hull] if obj["name"] in MODULE_ENVELOPES else mesh.split(only_watertight=False)
    for index, part in enumerate(components):
        if np.linalg.matrix_rank(part.vertices - part.vertices.mean(0), tol=1e-10) < 3:
            continue  # Surface-only decoration has no solid collision volume.
        hull = part.convex_hull
        if part.is_convex or obj["name"] in FIXED_COMPONENT_ENVELOPES:
            pieces = [(hull.vertices, hull.faces)]
        else:
            # CoACD 1.0.7 uses a normalized concavity tolerance. Record it;
            # this is not a claim of submillimetre physical clearance fidelity.
            pieces = coacd.run_coacd(coacd.Mesh(part.vertices * 1000, part.faces),
                threshold=.03, preprocess_mode="off" if part.is_volume and obj["name"] not in PREPROCESS_REQUIRED else "on", preprocess_resolution=100,
                resolution=1000, mcts_nodes=10,
                mcts_iterations=30, mcts_max_depth=3, seed=0)
            pieces = [(v / 1000, f) for v, f in pieces]
        for number, (v, f) in enumerate(pieces):
            key = f"{name}_c{index}_{number}"
            _msh(directory / (key + ".msh"), v, f)
            collision.append(key)
    # Open imported meshes cannot supply trustworthy signed volume/inertia.
    # Their convex volume is explicitly an estimate for mass allocation only.
    solid = mesh if mesh.is_volume else mesh.convex_hull
    props = solid.mass_properties
    result = dict(**obj, visual=name, collision=collision,
                conversion_identity=identity, collision_method=method,
                preprocessing=("none: fixed envelope" if "envelope" in method else
                    "on for documented native decomposition failure" if obj["name"] in PREPROCESS_REQUIRED else
                    "on for non-volume imports; off for closed solids"),
                volume=float(props.volume), center=np.asarray(props.center_mass).tolist(),
                inertia=np.asarray(props.inertia).tolist(),
                mass_basis="CAD solid volume" if mesh.is_volume else "CAD convex volume estimate")
    _atomic_json(record, result)
    return result


def prepare(config=None, workers=8):
    cache = SOURCE.parents[4] / "build/neural-gait/assembly"
    cache.mkdir(parents=True, exist_ok=True)
    with (cache / ".prepare.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _prepare(config, workers)


def _prepare(config=None, workers=8):
    from .environment import EnvironmentConfig
    manifest = json.loads((SOURCE / "assembly.json").read_text())
    fingerprint = _fingerprint()
    directory = SOURCE.parents[4] / "build/neural-gait/assembly" / fingerprint[:16]
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / "manifest.json"
    if output.exists():
        return directory, json.loads(output.read_text())
    packaged = _restore_prepared(directory, fingerprint)
    if packaged is not None:
        return directory, packaged
    config = config or EnvironmentConfig()
    frames = _frames(config, manifest)
    arrays = np.load(SOURCE / "assembly.npz")
    jobs, omitted = [], []
    for obj in manifest["objects"]:
        vertices = arrays[obj["key"] + "_vertices"] / 1000
        faces = arrays[obj["key"] + "_faces"]
        position, rotation = frames[obj["body"]]
        local = (vertices - position) @ rotation
        if np.linalg.matrix_rank(local - local.mean(0), tol=1e-10) < 3:
            omitted.append(dict(name=obj["name"], reason="flat reference preview; physical LCD geometry retained"))
            continue
        jobs.append((obj, local, faces, str(directory)))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        objects = list(pool.map(_convert, jobs))
    result = dict(source_sha256=fingerprint, version=VERSION, objects=objects,
        omitted=omitted, imu_site=manifest["imu_site"], camera_site=manifest["camera_site"],
        collision_method="CoACD 1.0.7 per connected moving/mechanical CAD solid, normalized threshold 0.03; named fixed electronics use module envelopes; named remaining fixed fittings use per-solid envelopes for first offline trial",
        qualification="CAD conversion; collision clearance and component mass distribution unmeasured")
    _atomic_json(output, result)
    return directory, result


def attach(root, config, *, visuals=True):
    directory, manifest = prepare(config)
    asset = root.find("asset")
    asset.clear()
    bodies = {b.get("name"): b for b in root.iter("body")}
    for body in bodies.values():
        for geom in list(body.findall("geom")):
            body.remove(geom)
    totals = {}
    for obj in manifest["objects"]:
        family = "torso" if obj["body"] == "torso" else "_".join(obj["body"].split("_")[:2])
        totals[family] = totals.get(family, 0) + obj["volume"]
    properties = {name: [] for name in bodies}
    for obj in manifest["objects"]:
        body = bodies[obj["body"]]
        family = "torso" if obj["body"] == "torso" else "_".join(obj["body"].split("_")[:2])
        budget = config.mass_kg - 4 * config.leg_mass_kg if family == "torso" else config.leg_mass_kg
        density = budget / totals[family]
        properties[obj["body"]].append((obj["volume"] * density, np.asarray(obj["center"]), np.asarray(obj["inertia"]) * density))
        for name in ([obj["visual"]] if visuals else []) + obj["collision"]:
            # Body inertias below are explicit; none is inferred from these
            # render/contact meshes. Shell processing supports thin CoACD
            # pieces without inventing a minimum collision volume.
            mesh = ET.SubElement(asset, "mesh", name=name,
                file=str(directory / (name + ".msh")), inertia="shell")
            if name == obj["visual"]:
                # MuJoCo computes an unused hull even for visual-only meshes.
                # This changes that unused hull, never the rendered triangles.
                mesh.set("maxhullvert", "32")
        if visuals:
            ET.SubElement(body, "geom", name=obj["visual"], type="mesh", mesh=obj["visual"],
                          mass="0", contype="0", conaffinity="0", group="2", rgba=_text(obj["rgba"]))
        for name in obj["collision"]:
            ET.SubElement(body, "geom", name=name, type="mesh", mesh=name,
                          mass="0", group="3", rgba="0 0 0 0")
    for name, items in properties.items():
        if not items:
            continue
        mass = sum(m for m, _, _ in items)
        center = sum(m * c for m, c, _ in items) / mass
        inertia = sum(i + m * (np.eye(3) * np.dot(c-center, c-center) - np.outer(c-center, c-center)) for m,c,i in items)
        ET.SubElement(bodies[name], "inertial", pos=_text(center), mass=str(mass),
            fullinertia=_text([inertia[0,0], inertia[1,1], inertia[2,2], inertia[0,1], inertia[0,2], inertia[1,2]]))
    bodies["torso"].find("site[@name='imu']").set("pos", _text((np.array(manifest["imu_site"]["position_mm"]) - [0,0,65]) / 1000))
    contact = root.find("contact")
    if contact is None:
        contact = ET.SubElement(root, "contact")
    # The fourth four-bar hinge closes a loop rather than a parent-child edge.
    # Its connected pickup and rod share the intentional bearing interface.
    for leg in ("rear_left", "rear_right", "front_left", "front_right"):
        ET.SubElement(contact, "exclude", body1=leg+"_pickup_body", body2=leg+"_rod_body")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", action="store_true", help="Publish frozen derived meshes for this CAD export")
    args = parser.parse_args()
    directory, manifest = prepare()
    if args.package:
        package_prepared()
    print(json.dumps(dict(directory=str(directory), objects=len(manifest["objects"]),
                         collision_pieces=sum(len(o["collision"]) for o in manifest["objects"]))))
