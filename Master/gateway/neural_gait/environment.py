"""MuJoCo dynamics generated from the maintained Ainekio four-bar geometry.

Real loop closure, twelve servo shafts, passive pickup/rod hinges, sole hulls.
Mass distribution and actuator dynamics are explicit experimental estimates.
This environment is not a physical qualification of an exported policy.
"""

from dataclasses import dataclass, field, replace
from copy import deepcopy
from collections import deque
import fcntl
import gzip
import hashlib
import importlib.util
import json
import math
import os
import shutil
from pathlib import Path
import xml.etree.ElementTree as ET

import gymnasium as gym
import mujoco
import numpy as np
from scipy.spatial.transform import Rotation

from .contract import JOINTS, LEGS, SCHEMA, HISTORY_SCHEMA, ObservationHistory, foot_offsets, vector, observation_size

GEOMETRY = (
    Path(__file__).resolve().parents[3]
    / "Slave/software/models/v2-12servo/geometry.json"
)
ENVIRONMENT_VERSION = 10
# Versions6/7/8 changed reward accounting. Version9 also repairs the existing
# native host-heading response. Input/action meanings and geometry are retained;
# PPO continues from saved weights with fresh rollouts, not old transitions.
# Version10 keeps the requested reward heading continuous through Walk updates.
POLICY_ENVIRONMENT_VERSIONS = frozenset((5, 6, 7, 8, 9, 10))
# Explicit objective normalization, not measured hardware limits. The linear
# scale is the current 30 mm/s training request; angular scale is independent
# so lowering requested travel speed cannot amplify yaw-noise penalties.
REWARD_VELOCITY_SCALE_M_S = .03
REWARD_YAW_SCALE_RAD_S = .5
REWARD_CROSS_TRACK_COST = .1
REWARD_OVERSPEED_COST = 2.
REWARD_SPEED_WINDOW_S = 1.
# Training objective in s²/m², not a runtime limit. Paired16s evaluations:
# clean stepping costs0.00210/step versus0.02586/step for the sliding policy.
# This retains positive clean progress while making the measured slider worse
# than rest under the corrected heading objective (see the gait journal).
CONTACT_SLIP_COST = 1.0
# Published locomotion terms: MuJoCo Playground Go1 joystick, with the
# measured-joint acceleration term from ETH legged_gym. Robot-scale units are
# explicit below; these are training weights, never servo/control restrictions.
LOCOMOTION_REWARD_WEIGHTS = dict(
    tracking_linear=1.0, tracking_yaw=.5, orientation=5.0,
    vertical_velocity=.5, roll_pitch_velocity=.05,
    joint_acceleration=2.5e-7, action_change=.01,
    effort=.05, energy=.001, slip=.1,
)
ASSEMBLY = GEOMETRY.parent / "simulation"

def representation_identity():
    """Identify both kinematic and CAD collision/inertia sources for a replay."""
    from .assembly import _fingerprint
    return dict(geometry_sha256=hashlib.sha256(GEOMETRY.read_bytes()).hexdigest(),
                assembly_sha256=_fingerprint())

def compiled_model(xml):
    # Training, evaluation and video workers share immutable compiled assets.
    # Source/collision identities are included in the XML mesh paths; physics
    # settings and MuJoCo version also participate in this cache key.
    identity = hashlib.sha256((mujoco.__version__+xml).encode()).hexdigest()
    directory = GEOMETRY.parents[4] / "build/neural-gait/compiled"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (identity+".mjb.gz")
    with (directory/(identity+".lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if path.exists():
            with gzip.open(path, "rb") as source:
                return mujoco.MjModel.from_binary_path("cached.mjb", {"cached.mjb": source.read()})
        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        legacy = directory/(identity+".mjb")
        raw = legacy if legacy.exists() else temporary.with_suffix(".mjb")
        model = (mujoco.MjModel.from_binary_path(str(raw)) if raw == legacy
                 else mujoco.MjModel.from_xml_string(xml))
        try:
            if raw != legacy:
                mujoco.mj_saveModel(model, str(raw))
            with raw.open("rb") as source, gzip.open(temporary, "wb", compresslevel=1) as target:
                shutil.copyfileobj(source, target)
            temporary.replace(path)
            raw.unlink()
        finally:
            if raw != legacy:
                raw.unlink(missing_ok=True)
            temporary.unlink(missing_ok=True)
        return model

def device_profile():
    return json.loads((GEOMETRY.parents[4] / "build/neural-gait/device.json").read_text())

def advertised_speed():
    return json.loads((GEOMETRY.parent / "servo_profile.json").read_text())["gait_max_joint_speed_degrees_s"]

def movement_reward(velocity_xy, yaw_rate, command, upright, height_ratio, *,
                    velocity_scale=REWARD_VELOCITY_SCALE_M_S,
                    yaw_scale=REWARD_YAW_SCALE_RAD_S,
                    cross_track_cost=REWARD_CROSS_TRACK_COST,
                    overspeed_cost=REWARD_OVERSPEED_COST, pace_twist=None, details=False):
    """Score this transition's travel, with zero for a stationary move request.

    Directed displacement earns credit immediately. Only the overspeed penalty
    uses measured recent pace, so periodic propulsion is not confused with a
    persistent speed error. All other terms subtract credit; zero-net rocking
    cannot beat rest, and stale pace can never pay credit after stopping.
    """
    scale = np.array([velocity_scale, velocity_scale, yaw_scale])
    measured = np.array([*velocity_xy, yaw_rate])/scale
    requested = np.asarray(command)/scale
    magnitude = float(np.linalg.norm(requested))
    if magnitude > 0:
        direction = requested/magnitude
        along = float(measured @ direction)
        ratio = along/magnitude
        pace = measured if pace_twist is None else np.asarray(pace_twist)/scale
        pace_ratio = float(pace @ direction)/magnitude
        overspeed = overspeed_cost*max(pace_ratio-1., 0.)
        cross_track = cross_track_cost*float(np.linalg.norm(measured-along*direction))
        tracking = ratio-overspeed-cross_track
    else:
        tracking = math.exp(-float(measured @ measured))
        ratio, overspeed, cross_track = tracking, 0., 0.
    support = float(np.clip(upright,0,1)*np.clip(height_ratio,0,1))
    multiplier = support if tracking > 0 else 1.
    value = tracking*multiplier
    return (value, dict(progress=ratio*multiplier, overspeed=overspeed*multiplier,
                        cross_track=cross_track*multiplier)) if details else value


def locomotion_reward(velocity_xy, yaw_rate, command, upright, height_ratio, *,
                      vertical_velocity, angular_velocity_xy, joint_velocity,
                      previous_joint_velocity, joint_torque, action, previous_action,
                      contact_slip_speed_squared, config):
    """Robot-scaled velocity tracking and physical movement quality per second.

    Reference terms: google-deepmind/mujoco_playground Go1 joystick and
    leggedrobotics/legged_gym joint acceleration. Tracking widths have SI units;
    unlike division by the request, they remain defined at zero commands.
    Acceleration uses measured servo-shaft qvel, not target acceleration.
    Signed costs remain visible rather than clipping every poor action to zero.
    """
    linear_error = (np.asarray(velocity_xy)-np.asarray(command[:2])) / config.locomotion_tracking_width_m_s
    yaw_error = (yaw_rate-command[2]) / config.locomotion_tracking_width_rad_s
    support = float(np.clip(upright, 0, 1)*np.clip(height_ratio, 0, 1))
    acceleration = (np.asarray(joint_velocity)-previous_joint_velocity)*config.control_hz
    terms = dict(
        tracking_linear=math.exp(-float(linear_error @ linear_error))*support,
        tracking_yaw=math.exp(-float(yaw_error*yaw_error))*support,
        orientation=max(0., 1.-float(upright)**2),
        vertical_velocity=float(vertical_velocity)**2,
        roll_pitch_velocity=float(np.sum(np.asarray(angular_velocity_xy)**2)),
        joint_acceleration=float(np.sum(acceleration**2)),
        action_change=float(np.sum((np.asarray(action)-previous_action)**2)),
        # Effort is a fraction of rated torque. Energy is mechanical watts;
        # contact speed is relative to this robot's tracking-speed unit.
        effort=float(np.mean((np.asarray(joint_torque)/config.torque_nm)**2)),
        energy=float(np.sum(np.abs(np.asarray(joint_torque)*joint_velocity))),
        slip=float(contact_slip_speed_squared)/config.locomotion_tracking_width_m_s**2,
    )
    components = {key: value*config.locomotion_reward_weights[key]/config.control_hz
                  for key, value in terms.items()}
    reward = sum(value if key.startswith("tracking_") else -value
                 for key, value in components.items())
    return float(reward), components


def command_limits(robot):
    limits=[]
    profile=json.loads((GEOMETRY.parent / "servo_profile.json").read_text())
    for j in sorted(robot["calibration"],key=lambda j:j["id"]):
        pulses=profile["pulse_range_us"] if j["id"]%3==0 else [500,2800]
        limits.append(sorted(j["home_cd"]/100+(-1 if j["invert"] else 1)*(p-j["home_us"])/j["us_per_degree"] for p in pulses))
    return limits


def validate_scenarios(scenarios):
    """Validate scenario descriptions, not robot admission or motion limits.

    Coordinates and force/torque are world-frame SI. Geometry sizes are positive
    half-extents; rock is an ellipsoid, block/wall/friction_patch are boxes.
    A friction patch has explicit physical thickness and a friction coefficient.
    It must not be a second coplanar floor pretending to be a material change.
    """
    def values(value, count):
        return isinstance(value, (list, tuple)) and len(value)==count and all(
            isinstance(x, (int, float)) and math.isfinite(x) for x in value)
    identities=set()
    for scenario in scenarios:
        identity=scenario.get("id")
        if not isinstance(identity,str) or not identity or identity in identities:
            raise ValueError("Scenarios require unique nonempty IDs")
        identities.add(identity)
        for key,count in (("slope_deg",2),("start_rpy_deg",3),("start_xy_m",2)):
            if key in scenario and not values(scenario[key],count):
                raise ValueError(f"Scenario {key} requires {count} finite values")
        if "slope_deg" in scenario:
            normal=Rotation.from_euler("xy",scenario["slope_deg"],degrees=True).as_matrix()[:,2]
            if normal[2]<=0:
                raise ValueError("Terrain plane must have an upward-facing surface")
        for geom in scenario.get("geoms",[]):
            if geom.get("kind") not in {"rock","block","wall","friction_patch"}:
                raise ValueError("Unknown scenario terrain shape")
            if not values(geom.get("position_m"),3) or not values(geom.get("size_m"),3) or min(geom["size_m"])<=0:
                raise ValueError("Terrain requires explicit position and positive half-extents in metres")
            if "rpy_deg" in geom and not values(geom["rpy_deg"],3):
                raise ValueError("Terrain rotation requires three finite degrees")
            if geom["kind"]=="friction_patch" and "friction" not in geom:
                raise ValueError("Friction patch requires its coefficient")
            if "friction" in geom and (not math.isfinite(geom["friction"]) or geom["friction"]<0):
                raise ValueError("Terrain friction must be finite and nonnegative")
        for push in scenario.get("pushes",[]):
            if not values([push.get("start_s"),push.get("duration_s")],2) or push["start_s"]<0 or push["duration_s"]<=0:
                raise ValueError("Push requires a finite nonnegative start and positive duration")
            if not values(push.get("force_n"),3) or ("torque_nm" in push and not values(push["torque_nm"],3)):
                raise ValueError("Push requires explicit world force N and optional torque Nm")


@dataclass
class EnvironmentConfig:
    # Missing in historical artifacts: retain their original replay semantics.
    # New training requests select body_control explicitly at their entrypoint.
    execution_backend: str = "direct"
    # Total mass is owner-measured; component distribution is estimated.
    mass_kg: float = 0.650
    leg_mass_kg: float = 0.055
    torque_nm: float = 0.18
    servo_kp: float = 2.0
    servo_kd: float = 0.04
    friction: float = 0.8
    control_hz: int = 50
    physics_hz: int = 500
    episode_seconds: float = 10.0
    command: list = field(default_factory=lambda: [0.08, 0.0, 0.0])
    robot: dict = field(default_factory=device_profile)
    target_limits_deg: list = field(default_factory=list)
    reference_joint_deg: list = field(default_factory=lambda: [0, 3.46, -21.63]*4)
    # Initial walking search extent, not a physical capability restriction.
    foot_action_scale_mm: list = field(default_factory=lambda: [30.0, 20.0, 30.0])
    joint_speed_deg_s: float = field(default_factory=advertised_speed)
    motor_no_load_speed_deg_s: float = field(default_factory=advertised_speed)
    # board.c nominal PCA9685 clock; actual installed oscillator is unmeasured.
    pwm_oscillator_hz: int = 25_000_000
    pwm_frequency_hz: int = 50
    feedback_noise_raw_std: float = 0.0  # Unmeasured; configurable, not fabricated evidence.
    imu_accel_noise_std: float = 0.0
    imu_gyro_noise_std: float = 0.0
    randomization: float = 0.0
    # Explicit simulation setting, not a claim about the saved robot setting.
    # Disabled reproduces historical neural-policy targets exactly.
    balance_enabled: bool = False
    balance_tuning: list = field(default_factory=lambda: [1.0, 1.0, 0.0, 0.0])
    heading_feedback_enabled: bool = True
    # Explicit experimental scenes, not measurements of the owner's room.
    # Empty preserves the original flat MJCF and RNG sequence.
    scenarios: list = field(default_factory=list)
    observation_schema: str = SCHEMA
    depth_camera: dict = field(default_factory=dict)
    reward_velocity_scale_m_s: float = REWARD_VELOCITY_SCALE_M_S
    reward_yaw_scale_rad_s: float = REWARD_YAW_SCALE_RAD_S
    reward_cross_track_cost: float = REWARD_CROSS_TRACK_COST
    reward_overspeed_cost: float = REWARD_OVERSPEED_COST
    reward_speed_window_s: float = REWARD_SPEED_WINDOW_S
    # An absent field means legacy reward so historical artifacts replay intact.
    # New recipe selection happens in the existing training owner.
    reward_profile: str = "legacy"
    locomotion_tracking_width_m_s: float = .03
    locomotion_tracking_width_rad_s: float = .5
    locomotion_reward_weights: dict = field(default_factory=lambda: dict(LOCOMOTION_REWARD_WEIGHTS))

    def __post_init__(self):
        observation_size(self.observation_schema)
        if self.depth_camera and self.observation_schema==SCHEMA:
            raise ValueError("Depth camera requires the depth observation schema")
        validate_scenarios(self.scenarios)
        if self.execution_backend not in {"direct", "body_control"}:
            raise ValueError("Unknown gait execution backend")
        if self.reward_profile not in {"legacy", "locomotion"}:
            raise ValueError("Unknown gait training reward profile")
        if (set(self.locomotion_reward_weights) != set(LOCOMOTION_REWARD_WEIGHTS)
                or any(not math.isfinite(value) or value < 0
                       for value in self.locomotion_reward_weights.values())):
            raise ValueError("Locomotion reward weights require all named finite nonnegative terms")
        if not self.target_limits_deg:
            self.target_limits_deg = command_limits(self.robot)
        for name in (
            "mass_kg",
            "leg_mass_kg",
            "torque_nm",
            "servo_kp",
            "servo_kd",
            "reward_velocity_scale_m_s",
            "reward_yaw_scale_rad_s",
            "reward_cross_track_cost",
            "reward_overspeed_cost",
            "reward_speed_window_s",
            "locomotion_tracking_width_m_s",
            "locomotion_tracking_width_rad_s",
            "friction",
            "control_hz",
            "physics_hz",
            "episode_seconds",
            "joint_speed_deg_s",
            "motor_no_load_speed_deg_s",
            "pwm_oscillator_hz",
            "pwm_frequency_hz",
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.mass_kg <= 4 * self.leg_mass_kg:
            raise ValueError("Total mass must exceed the four leg masses")
        if not 0 <= self.randomization < 1:
            raise ValueError("Mass randomization must be between zero and one")
        if len(self.command) != 3 or not all(math.isfinite(x) for x in self.command):
            raise ValueError("Command is forward m/s, lateral m/s, yaw rad/s")
        if len(self.target_limits_deg) != 12 or any(
            len(r) != 2 or not all(math.isfinite(v) for v in r) or r[0] >= r[1]
            for r in self.target_limits_deg
        ):
            raise ValueError("Expected twelve ordered finite exploration ranges")
        if self.physics_hz % self.control_hz:
            raise ValueError("Physics cadence must divide control cadence")
        foot_offsets([0]*12, self.foot_action_scale_mm)
        if len(self.reference_joint_deg) != 12 or not all(math.isfinite(v) for v in self.reference_joint_deg):
            raise ValueError("Expected twelve finite standing reference angles")
        if type(self.balance_enabled) is not bool or len(self.balance_tuning) != 4 or not all(
                math.isfinite(value) for value in self.balance_tuning):
            raise ValueError("Balance requires an enable flag and finite strength/damping/roll/pitch tuning")


def body_control_config(config):
    """Make the executor transition explicit and recover an omitted saved field.

    Older mathematical-simulator snapshots didn't use standing arrival. Read
    its value from that snapshot's named acquisition evidence, not a guessed
    default or the settings of a different robot.
    """
    robot = deepcopy(config.robot)
    if "stand_enabled" not in robot["feedback"]:
        source = robot.get("provenance", {}).get("feedback_source")
        if not source:
            raise ValueError("Connected execution needs the captured standing-feedback setting")
        path = Path(__file__).resolve().parents[3] / source
        raw = path.read_bytes()
        value = json.loads(raw)["stand_enabled"]
        if type(value) is not bool:
            raise ValueError("Captured stand_enabled must be boolean")
        robot["feedback"]["stand_enabled"] = value
        robot["provenance"]["execution_feedback_setting"] = dict(
            source=source, sha256=hashlib.sha256(raw).hexdigest(), stand_enabled=value)
    return replace(config, execution_backend="body_control", robot=robot)


def reference():
    path = GEOMETRY.parent / "motions/walk/reference.py"
    spec = importlib.util.spec_from_file_location("neural_gait_geometry", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Mechanism(json.loads(GEOMETRY.read_text()))


def text(values):
    return " ".join(format(float(x), ".12g") for x in values)


def quat(matrix):
    x, y, z, w = Rotation.from_matrix(matrix).as_quat()
    return text([w, x, y, z])


def yquat(angle):
    return text([math.cos(angle / 2), 0, math.sin(angle / 2), 0])


def build_xml(config, *, include_assembly=True, include_visuals=True):
    m = reference()
    root = ET.Element("mujoco", model="ainekio-v2-four-bar")
    ET.SubElement(root, "compiler", angle="radian", autolimits="true", discardvisual="false")
    ET.SubElement(
        root,
        "option",
        timestep=str(1 / config.physics_hz),
        integrator="implicitfast",
        iterations="50",
    )
    default = ET.SubElement(root, "default")
    ET.SubElement(default, "joint", damping="0.002", armature="0.000003")
    ET.SubElement(
        default, "geom", friction=f"{config.friction} 0.005 0.0001", condim="3"
    )
    asset = ET.SubElement(root, "asset")
    world = ET.SubElement(root, "worldbody")
    ET.SubElement(
        world, "geom", name="floor", type="plane", size="3 3 .05", rgba=".3 .35 .4 1"
    )
    # Compile every candidate into the static collision BVH. Reset disables
    # inactive candidates; enabling a compiled visual-only geom would not add
    # it to MuJoCo's collision tree.
    for index,scenario in enumerate(config.scenarios):
        for number,geom in enumerate(scenario.get("geoms",[])):
            ET.SubElement(world,"geom",name=f"terrain_{index}_{number}",
                type="ellipsoid" if geom["kind"]=="rock" else "box",
                pos=text(geom["position_m"]),size=text(geom["size_m"]),
                quat=quat(Rotation.from_euler("xyz",geom.get("rpy_deg",[0,0,0]),degrees=True).as_matrix()),
                contype="1",conaffinity="1",rgba=".4 .36 .27 0",priority="1")
    ET.SubElement(world, "light", pos="0 0 2")
    torso = ET.SubElement(world, "body", name="torso", pos="0 0 .065")
    ET.SubElement(torso, "freejoint", name="root")
    hull = (np.asarray(m.cfg["current_body_hull_local_mm"]) - [0, 0, 65]) / 1000
    ET.SubElement(asset, "mesh", name="body_hull", vertex=text(hull.ravel()))
    ET.SubElement(
        torso,
        "geom",
        name="chassis",
        type="mesh",
        mesh="body_hull",
        mass=str(config.mass_kg - 4 * config.leg_mass_kg),
        rgba=".8 .08 .05 1",
    )
    ET.SubElement(torso, "site", name="imu", size=".001")
    equality = ET.SubElement(root, "equality")
    actuators = ET.SubElement(root, "actuator")
    sensors = ET.SubElement(root, "sensor")
    ET.SubElement(sensors, "gyro", name="gyro", site="imu")
    ET.SubElement(sensors, "accelerometer", name="accel", site="imu")

    def rod(parent, name, length, mass):
        ET.SubElement(
            parent,
            "geom",
            name=name,
            type="capsule",
            fromto=text([0, 0, 0, length, 0, 0]),
            size=".002",
            mass=str(mass),
            contype="0",
            conaffinity="0",
            rgba=".5 .5 .5 1",
        )

    for index, (leg, cad) in enumerate(zip(LEGS, ("FL", "FR", "RL", "RR"))):
        g = m.geom[cad]
        S = np.array(g["shoulder_world"])
        M = np.array(g["mechanism_local"])
        shoulder_sign = -1.0 if np.linalg.det(S[:3, :3]) < 0 else 1.0
        shoulder_mirror = np.diag([1.0, shoulder_sign, 1.0])
        M[:3, :] = shoulder_mirror @ M[:3, :]
        shoulder = ET.SubElement(
            torso,
            "body",
            name=leg + "_shoulder_body",
            pos=text((S[:3, 3] - [0, 0, 65]) / 1000),
            quat=quat(S[:3, :3] @ shoulder_mirror),
        )
        ET.SubElement(
            shoulder, "joint", name=leg + "_shoulder", axis=text([shoulder_sign, 0, 0])
        )
        ET.SubElement(
            shoulder,
            "geom",
            type="box",
            size=".012 .006 .014",
            mass=str(config.leg_mass_kg * 0.36),
            contype="0",
            conaffinity="0",
        )
        # CAD exports mirrored mechanism frames. MJCF needs proper rotations;
        # move the reflection into local mesh/reference coordinates instead.
        mirror = np.diag([1.0, -1.0 if np.linalg.det(M[:3, :3]) < 0 else 1.0, 1.0])
        mech = ET.SubElement(
            shoulder, "body", name=leg+"_mechanism", pos=text(M[:3, 3] / 1000), quat=quat(M[:3, :3] @ mirror)
        )
        carrier = ET.SubElement(
            mech, "body", name=leg+"_carrier_body", pos=text([m.O[0] / 1000, 0, m.O[1] / 1000]), quat=yquat(-m.a0)
        )
        ET.SubElement(carrier, "joint", name=leg + "_carrier", axis="0 -1 0")
        rod(carrier, leg + "_carrier_link", m.A / 1000, config.leg_mass_kg * 0.15)
        pickup = ET.SubElement(
            carrier, "body", name=leg+"_pickup_body", pos=text([m.A / 1000, 0, 0]), quat=yquat(-(m.b0 - m.a0))
        )
        ET.SubElement(pickup, "joint", name=leg + "_pickup", axis="0 -1 0")
        rod(pickup, leg + "_pickup_link", m.b / 1000, config.leg_mass_kg * 0.08)
        ET.SubElement(
            pickup,
            "site",
            name=leg + "_pickup_end",
            pos=text([m.b / 1000, 0, 0]),
            size=".001",
        )
        # Hull/foot reference live in the reference lower-leg frame at beta0.
        hull = (
            Rotation.from_euler("y", m.b0).as_matrix() @ mirror @ m.hulls[cad].T
        ).T / 1000
        ET.SubElement(asset, "mesh", name=leg + "_sole", vertex=text(hull.ravel()))
        ET.SubElement(
            pickup,
            "geom",
            name=leg + "_foot",
            type="mesh",
            mesh=leg + "_sole",
            mass=str(config.leg_mass_kg * 0.27),
            rgba=".15 .15 .17 1",
        )
        foot = (
            Rotation.from_euler("y", m.b0).apply(
                mirror @ np.asarray(g["foot_reference_local_mm"])
            )
            / 1000
        )
        ET.SubElement(
            pickup, "site", name=leg + "_reference", pos=text(foot), size=".002"
        )
        crank = ET.SubElement(
            mech, "body", name=leg+"_crank_body", pos=text([m.C[0] / 1000, 0, m.C[1] / 1000]), quat=yquat(-m.t0)
        )
        ET.SubElement(crank, "joint", name=leg + "_crank", axis="0 -1 0")
        rod(crank, leg + "_crank_link", m.r / 1000, config.leg_mass_kg * 0.07)
        D, P, E, beta, height = m.planar([0, 0, 0])
        gamma = math.atan2(*(E - P)[::-1])
        link = ET.SubElement(
            crank, "body", name=leg+"_rod_body", pos=text([m.r / 1000, 0, 0]), quat=yquat(-(gamma - m.t0))
        )
        ET.SubElement(link, "joint", name=leg + "_rod", axis="0 -1 0")
        rod(link, leg + "_rod_link", m.L / 1000, config.leg_mass_kg * 0.07)
        ET.SubElement(
            link,
            "site",
            name=leg + "_rod_end",
            pos=text([m.L / 1000, 0, 0]),
            size=".001",
        )
        ET.SubElement(
            equality,
            "connect",
            site1=leg + "_pickup_end",
            site2=leg + "_rod_end",
            solref=".004 1",
        )
        for axis in ("shoulder", "carrier", "crank"):
            ET.SubElement(
                actuators,
                "position",
                name=leg + "_" + axis,
                joint=leg + "_" + axis,
                kp=str(config.servo_kp),
                kv=str(config.servo_kd),
                forcerange=text([-config.torque_nm, config.torque_nm]),
            )
    if include_assembly:
        from .assembly import attach
        attach(root, config, visuals=include_visuals)
    return ET.tostring(root, encoding="unicode")


class GaitEnvironment(gym.Env):
    metadata = {"render_modes": ["rgb_array"], "render_fps": 50}

    def __init__(self, config=None, render_mode=None, *, include_assembly=True, include_visuals=True,
                 commands=None):
        self.config = deepcopy(config or EnvironmentConfig())
        self.reward_twists = deque(maxlen=max(1,round(
            self.config.reward_speed_window_s*self.config.control_hz)))
        self.commands = deepcopy(commands)
        if commands is not None and (not commands or any(
                len(command) != 3 or not all(math.isfinite(value) for value in command)
                for command in commands)):
            raise ValueError("Commands must contain finite forward/lateral m/s and yaw rad/s")
        if self.config.physics_hz % self.config.control_hz:
            raise ValueError("Physics cadence must divide control cadence")
        self.model = compiled_model(build_xml(
            self.config, include_assembly=include_assembly, include_visuals=include_visuals))
        self.data = mujoco.MjData(self.model)
        self.joint_ids = [self.model.joint(n).id for n in JOINTS]
        self.qadr = self.model.jnt_qposadr[self.joint_ids]
        self.vadr = self.model.jnt_dofadr[self.joint_ids]
        self.action_space = gym.spaces.Box(-1.0, 1.0, (12,), dtype=np.float32)
        self.observation_space = gym.spaces.Box(
            -np.inf, np.inf, (observation_size(self.config.observation_schema),), dtype=np.float32
        )
        self.render_mode = render_mode
        self.renderer = None
        from .native import BodyModel
        self.body_model = BodyModel(self.config.robot)
        self.imu_sample = np.zeros(14)
        self.feedback_angles = np.zeros(12)
        self.feedback_velocity = np.zeros(12)
        self.feedback_usable = np.zeros(12, dtype=bool)
        self.jammed = 0
        self.next_imu = 0.0
        self.next_feedback = 0.0
        self.sample_history = []
        self.observation_history = ObservationHistory()
        self.feedback_times = np.zeros(12)
        self.last_action = np.zeros(12)
        self.last_target = np.zeros(12)
        self.nominal_mass = self.model.body_mass.copy()
        self.nominal_inertia = self.model.body_inertia.copy()
        from .depth import DepthCamera
        self.depth_camera = DepthCamera(self.config.depth_camera) if self.config.depth_camera else None
        self.depth_measurement = None
        self.scenario = None
        self.scenario_id = "flat"
        self._terrain_geom_mask = np.zeros(self.model.ngeom,dtype=bool)
        self._terrain_geom_mask[self.model.geom("floor").id] = True
        self._scenario_geom_ids = [[self.model.geom(f"terrain_{i}_{j}").id
            for j in range(len(s.get("geoms",[])))] for i,s in enumerate(self.config.scenarios)]

    def _terrain_mask(self):
        if not hasattr(self,"_terrain_geom_mask"):
            self._terrain_geom_mask=np.zeros(self.model.ngeom,dtype=bool)
            self._terrain_geom_mask[self.model.geom("floor").id]=True
        return self._terrain_geom_mask

    def _select_scenario(self, options):
        if not self.config.scenarios:
            if options and options.get("scenario") not in (None,"flat"):
                raise ValueError("No configured scenario matches the reset request")
            self.scenario=None;self.scenario_id="flat"
            return
        choice=(options or {}).get("scenario")
        if choice is None:
            choice=int(self.np_random.integers(len(self.config.scenarios))) if len(self.config.scenarios)>1 else 0
        if isinstance(choice,str):
            matches=[i for i,s in enumerate(self.config.scenarios) if s["id"]==choice]
            if not matches:raise ValueError(f"Unknown scenario: {choice}")
            choice=matches[0]
        if not isinstance(choice,(int,np.integer)) or not 0<=choice<len(self.config.scenarios):
            raise ValueError("Scenario index is outside the configured curriculum")
        self.scenario_index=int(choice)
        self.scenario=self.config.scenarios[self.scenario_index]
        self.scenario_id=self.scenario["id"]

    def _configure_terrain(self):
        floor=self.model.geom("floor").id
        rotation=Rotation.from_euler("xy",self.scenario.get("slope_deg",[0,0]),degrees=True)
        q=rotation.as_quat();self.model.geom_quat[floor]=q[[3,0,1,2]]
        # The compiled flat plane uses the identity-frame optimization.
        self.model.geom_sameframe[floor]=0
        self._terrain_geom_mask[:]=False;self._terrain_geom_mask[floor]=True
        for index,ids in enumerate(self._scenario_geom_ids):
            active=index==self.scenario_index
            for gid,description in zip(ids,self.config.scenarios[index].get("geoms",[])):
                self.model.geom_contype[gid]=self.model.geom_conaffinity[gid]=int(active)
                self.model.geom_rgba[gid,3]=float(active)
                self._terrain_geom_mask[gid]=active
                if "friction" in description:
                    self.model.geom_friction[gid,0]=description["friction"]

    def _spawn_above_terrain(self):
        """Place the configured pose clear of actual collision surfaces.

        Plane support gives the lower bracket. Terrain AABBs give a conservative
        clear upper bracket; real MuJoCo convex distances then solve vertical
        separation. No guessed leg length or sensor-derived contact is used.
        """
        robot=np.flatnonzero((self.model.geom_bodyid!=0)&
            ((self.model.geom_contype!=0)|(self.model.geom_conaffinity!=0)))
        points=[]
        for gid in robot:
            mid=self.model.geom_dataid[gid];start=self.model.mesh_vertadr[mid]
            vertices=self.model.mesh_vert[start:start+self.model.mesh_vertnum[mid]]
            points.append(vertices@self.data.geom_xmat[gid].reshape(3,3).T+self.data.geom_xpos[gid])
        points=np.concatenate(points)
        floor=self.model.geom("floor").id
        normal=self.data.geom_xmat[floor].reshape(3,3)[:,2]
        separation=(points-self.data.geom_xpos[floor])@normal
        base=float(self.data.qpos[2])
        low=base+(.001-float(separation.min()))/normal[2]
        high=low
        xy_min,xy_max=points[:,:2].min(axis=0),points[:,:2].max(axis=0)
        for gid in np.flatnonzero(self._terrain_mask()):
            if gid==floor:continue
            extent=np.abs(self.data.geom_xmat[gid].reshape(3,3))@self.model.geom_size[gid]
            center=self.data.geom_xpos[gid]
            if np.all(center[:2]+extent[:2]>=xy_min) and np.all(center[:2]-extent[:2]<=xy_max):
                high=max(high,base+center[2]+extent[2]-points[:,2].min()+.001)
        terrain=np.flatnonzero(self._terrain_mask())
        def clear(height):
            self.data.qpos[2]=height;mujoco.mj_forward(self.model,self.data)
            return all(mujoco.mj_geomDistance(self.model,self.data,int(g),int(t),.001,None)>=.001-1e-9
                       for g in robot for t in terrain)
        if clear(low):return
        # Start the upper bracket a complete body-height above the support
        # envelope, away from near-contact GJK degeneracies. Bisection removes
        # this bracket padding; it is not an imposed drop height.
        high+=float(np.ptp(points[:,2]))
        if not clear(high):raise ValueError("Configured terrain cannot provide a clear vertical spawn bracket")
        for _ in range(32):
            middle=(low+high)/2
            if clear(middle):high=middle
            else:low=middle
        self.data.qpos[2]=high;mujoco.mj_forward(self.model,self.data)

    def terrain_height(self, x, y):
        """Highest configured surface at world XY, queried through MuJoCo rays."""
        terrain=np.flatnonzero(self._terrain_mask())
        floor=self.model.geom("floor").id
        normal=self.data.geom_xmat[floor].reshape(3,3)[:,2]
        origin=self.data.geom_xpos[floor]
        height=origin[2]-(normal[0]*(x-origin[0])+normal[1]*(y-origin[1]))/normal[2]
        for gid in terrain:
            if gid!=floor:
                extent=np.abs(self.data.geom_xmat[gid].reshape(3,3))@self.model.geom_size[gid]
                height=max(height,self.data.geom_xpos[gid,2]+extent[2])
        start=np.array([x,y,height+.001]);direction=np.array([0.,0.,-1.])
        distance=min(value for gid in terrain if (value:=mujoco.mju_rayGeom(
            self.data.geom_xpos[gid],self.data.geom_xmat[gid],self.model.geom_size[gid],
            start,direction,self.model.geom_type[gid]))>=0)
        return float(start[2]-distance)

    def _terrain_clearances(self, bodies):
        """Exact plane support and pruned collision-owner terrain distances.

        Actual contacts take precedence for their geom pair. Cached complete
        boot vertices give exact plane support; vectorized world-AABB lower
        bounds exclude pairs that cannot improve that minimum. An unqualified
        MuJoCo GJK result remains an explicitly invalid clearance bound.
        """
        terrain=np.flatnonzero(self._terrain_mask())
        planes=terrain[self.model.geom_type[terrain]==mujoco.mjtGeom.mjGEOM_PLANE]
        objects=terrain[self.model.geom_type[terrain]!=mujoco.mjtGeom.mjGEOM_PLANE]
        contacts={}
        for contact in self.data.contact[:self.data.ncon]:
            key=tuple(sorted((int(contact.geom1),int(contact.geom2))))
            contacts[key]=min(contacts.get(key,math.inf),float(contact.dist))
        if not hasattr(self,"_clearance_geom_ids"):
            self._clearance_geom_ids={body:np.flatnonzero((self.model.geom_bodyid==body)&
                ((self.model.geom_contype!=0)|(self.model.geom_conaffinity!=0))) for body in bodies}
        def bounds(ids):
            rotation=self.data.geom_xmat[ids].reshape(-1,3,3)
            local=self.model.geom_aabb[ids]
            center=self.data.geom_xpos[ids]+np.einsum("nij,nj->ni",rotation,local[:,:3])
            extent=np.einsum("nij,nj->ni",np.abs(rotation),local[:,3:])
            return center-extent,center+extent
        bmin,bmax=bounds(objects)
        values=[];validity=[];lower_bounds=[]
        for body in bodies:
            candidates=[]
            geoms=self._clearance_geom_ids[body]
            # Plane support of the union of all collision hulls is attained at
            # one of its mesh vertices. No narrow-phase query is necessary.
            vertices=self._foot_vertices[self._foot_bodies.index(body)]
            rotation=self.data.xmat[body].reshape(3,3)
            for plane in planes:
                normal=self.data.geom_xmat[plane].reshape(3,3)[:,2]
                offset=np.dot(self.data.xpos[body]-self.data.geom_xpos[plane],normal)
                candidates.append((float((vertices@(rotation.T@normal)).min()+offset),True))
            for (first,second),distance in contacts.items():
                if ((self._terrain_geom_mask[first] and self.model.geom_bodyid[second]==body) or
                    (self._terrain_geom_mask[second] and self.model.geom_bodyid[first]==body)):
                    candidates.append((distance,True))
            best=min((v for v,_ in candidates),default=math.inf)
            if len(objects):
                amin,amax=bounds(geoms)
                separation=np.maximum(amin[:,None,:]-bmax[None,:,:],bmin[None,:,:]-amax[:,None,:])
                gap=np.maximum(separation,0.)
                outside=np.linalg.norm(gap,axis=2)
                overlap=np.minimum(amax[:,None,:]-bmin[None,:,:],bmax[None,:,:]-amin[:,None,:]).min(axis=2)
                bound=np.where(np.any(gap>0,axis=2),outside,-overlap)
                rows,columns=np.nonzero(bound<=best+1e-9)
                order=np.argsort(bound[rows,columns])
                for index in order:
                    row,column=rows[index],columns[index]
                    lower=float(bound[row,column])
                    if lower>best+1e-9:break
                    gid,tid=int(geoms[row]),int(objects[column])
                    if tuple(sorted((gid,tid))) in contacts:continue
                    measured=float(mujoco.mj_geomDistance(self.model,self.data,gid,tid,1e6,None))
                    qualified=math.isfinite(measured) and measured!=0 and measured>=lower-1e-9
                    value=measured if qualified else lower
                    candidates.append((value,qualified));best=min(best,value)
            qualified=all(ok for v,ok in candidates if v<=best+1e-9)
            values.append(best);validity.append(qualified);lower_bounds.append(best)
        return values,validity,lower_bounds

    def _apply_scenario_pushes(self):
        body=self.model.body("torso").id
        self.data.xfrc_applied[body]=0
        for push in self.scenario.get("pushes",[]):
            # Average over this physical integration interval, preserving the
            # configured finite impulse even for non-grid-aligned boundaries.
            overlap=max(0.,min(self.data.time+self.model.opt.timestep,
                push["start_s"]+push["duration_s"])-max(self.data.time,push["start_s"]))
            fraction=overlap/self.model.opt.timestep
            self.data.xfrc_applied[body,:3]+=np.asarray(push["force_n"])*fraction
            self.data.xfrc_applied[body,3:]+=np.asarray(push.get("torque_nm",[0,0,0]))*fraction

    def set_pose(self, angles):
        m = reference()
        angles = np.asarray(angles).reshape(4, 3)
        self.data.qpos[self.qadr] = angles.ravel()
        _, P0, E0, _, _ = m.planar([0, 0, 0])
        gamma0 = math.atan2(*(E0 - P0)[::-1])
        for leg, q in zip(LEGS, angles):
            _, P, E, beta, _ = m.planar(q)
            gamma = math.atan2(*(E - P)[::-1])
            self.data.qpos[self.model.joint(leg + "_pickup").qposadr[0]] = math.atan2(
                math.sin(beta - m.b0 - q[1]), math.cos(beta - m.b0 - q[1])
            )
            self.data.qpos[self.model.joint(leg + "_rod").qposadr[0]] = math.atan2(
                math.sin(gamma - gamma0 - q[2]), math.cos(gamma - gamma0 - q[2])
            )
        mujoco.mj_forward(self.model, self.data)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        if options and "command" in options:
            command = options["command"]
        elif self.commands is not None:
            command = self.commands[int(self.np_random.integers(len(self.commands)))] if len(self.commands) > 1 else self.commands[0]
        else:
            command = self.config.command
        if len(command) != 3 or not all(math.isfinite(value) for value in command):
            raise ValueError("Command is forward m/s, lateral m/s, yaw rad/s")
        self.config.command = list(command)
        self.reward_twists.clear()
        self.observation_history = ObservationHistory()
        self._select_scenario(options)
        if self.depth_camera is not None:
            self.depth_camera.reset()
        self.depth_measurement = None
        mujoco.mj_resetData(self.model, self.data)
        self.body_model.reset()
        self.body_model.balance_configure(enabled=self.config.balance_enabled,
                                         tuning=self.config.balance_tuning)
        self.next_imu = self.next_feedback = 0.0
        self.sample_history = []
        self.feedback_times[:] = 0
        self.jammed = 0
        scale = self.np_random.uniform(
            1 - self.config.randomization, 1 + self.config.randomization
        )
        self.model.body_mass[:] = self.nominal_mass * scale
        self.model.body_inertia[:] = self.nominal_inertia * scale
        mujoco.mj_setConst(self.model, self.data)
        self.model.geom_friction[:, 0] = self.config.friction * self.np_random.uniform(
            1 - self.config.randomization, 1 + self.config.randomization
        )
        if self.scenario is not None:
            self._configure_terrain()
            r=Rotation.from_euler("xyz",self.scenario.get("start_rpy_deg",[0,0,0]),degrees=True).as_quat()
            self.data.qpos[3:7]=r[[3,0,1,2]]
            self.data.qpos[:2]=self.scenario.get("start_xy_m",[0,0])
        self.set_pose(np.deg2rad(self.config.reference_joint_deg))
        # Use compiled collision surfaces, including the current CAD boots.
        # Older reference sole hulls are not the installed assembly's bounds.
        bottom = math.inf
        for gid in range(self.model.ngeom):
            if self.model.geom_bodyid[gid] == 0 or not (
                self.model.geom_contype[gid] or self.model.geom_conaffinity[gid]
            ):
                continue
            mesh = self.model.geom_dataid[gid]
            start = self.model.mesh_vertadr[mesh]
            vertices = self.model.mesh_vert[start:start+self.model.mesh_vertnum[mesh]]
            rotation = self.data.geom_xmat[gid].reshape(3,3)
            bottom = min(bottom, float((vertices @ rotation.T)[:,2].min()
                                       + self.data.geom_xpos[gid,2]))
        if self.scenario is None:
            self.data.qpos[2] -= bottom - 0.001
        else:
            self._spawn_above_terrain()
        self.standing_height = float(self.data.qpos[2])
        if self.scenario is not None:
            rotation=self.data.xmat[self.model.body("torso").id].reshape(3,3)
            upright_bottom=math.inf
            for gid in range(self.model.ngeom):
                if self.model.geom_bodyid[gid]==0 or not (self.model.geom_contype[gid] or self.model.geom_conaffinity[gid]):continue
                mid=self.model.geom_dataid[gid];start=self.model.mesh_vertadr[mid]
                mesh=self.model.mesh_vert[start:start+self.model.mesh_vertnum[mid]]
                world=mesh@self.data.geom_xmat[gid].reshape(3,3).T+self.data.geom_xpos[gid]
                upright_bottom=min(upright_bottom,float(((world-self.data.qpos[:3])@rotation)[:,2].min()))
            self.standing_height=.001-upright_bottom
        self.last_target = np.rad2deg(self.data.qpos[self.qadr])
        self.pwm = self.body_model.pwm_output(self.last_target,
            oscillator_hz=self.config.pwm_oscillator_hz, frequency_hz=self.config.pwm_frequency_hz)
        self.data.ctrl[:] = np.deg2rad(self.pwm["physical_angles"])
        self.last_action = np.zeros(12)
        self.steps = 0
        self.world_heading_delta = 0.0
        self.native_command = None
        mujoco.mj_forward(self.model, self.data)
        rotation = self.data.xmat[self.model.body("torso").id].reshape(3, 3)
        self.reward_last_heading = math.atan2(rotation[1,0], rotation[0,0])
        self.reward_reference_heading = self.reward_last_heading
        self._sample_sensors()
        return self._observation(), {
            "scope": "simulation",
            "scenario_id": self.scenario_id,
            "geometry_sha256": hashlib.sha256(GEOMETRY.read_bytes()).hexdigest(),
            "command": list(self.config.command),
        }

    def set_command(self, command):
        """Change the requested task without resetting posture, sensors or motion.

        Training scores each command's progress independently. Previous physical
        movement must not be credited to a newly requested direction.
        """
        if len(command) != 3 or not all(math.isfinite(value) for value in command):
            raise ValueError("Command is forward m/s, lateral m/s, yaw rad/s")
        command = list(command)
        if command != self.config.command:
            self.config.command = command
            self.reward_twists.clear()
        return self._observation()

    def observation(self):
        imu_status = self.body_model.imu_status(1+self.data.time*1e6)
        result = dict(
            schema=self.config.observation_schema,
            joint_deg=self.feedback_angles.tolist(),
            joint_velocity_deg_s=self.feedback_velocity.tolist(),
            target_deg=self.last_target.tolist(),
            target_limits_deg=self.config.target_limits_deg,
            joint_usable=self.feedback_usable.tolist(),
            orientation_wxyz=self.imu_sample[:4].tolist(),
            angular_rate_rad_s=self.imu_sample[7:10].tolist(),
            acceleration_m_s2=self.imu_sample[4:7].tolist(),
            imu_quality=imu_status["quality"],
            imu_sample_age_s=imu_status["sample_age_s"],
            command=self.config.command,
            events={"jam": bool(self.jammed)},
            vision=self.depth_observation(),
            previous_action=self.last_action.tolist(),
            joint_sample_age_s=np.maximum(0,self.data.time-self.feedback_times).tolist(),
            joint_sample_time_s=self.feedback_times.tolist(),
            observation_time_s=float(self.data.time),
        )
        return self.with_critic(self.observation_history.project(result))

    def with_critic(self, observation):
        """Training value information; never used by the deployed actor."""
        if observation["schema"] != HISTORY_SCHEMA:
            return observation
        pace = np.mean(self.reward_twists, axis=0) if self.reward_twists else np.zeros(3)
        error = self.reward_reference_heading-self.reward_last_heading
        scale = [self.config.reward_velocity_scale_m_s]*2 + [self.config.reward_yaw_scale_rad_s]
        return dict(observation, training_critic=[*(pace/scale).tolist(), math.sin(error), math.cos(error)])

    def depth_observation(self):
        from .depth import project_depth
        return project_depth(self.depth_measurement or {}, self.data.time,
                             "simulation", 1)

    def _sample_sensors(self):
        now = self.data.time
        if self.depth_camera is not None:
            self.depth_measurement = self.depth_camera.update(self.model, self.data, self.np_random,
                robot_id="simulation", epoch=1, gateway_instance="simulation", now_s=now,
                geom_mask=self._terrain_geom_mask)
        if now + 1e-10 >= self.next_imu:
            self.imu_sample = self.body_model.imu_sample(
                1+now*1e6,
                self.data.sensor("accel").data+self.np_random.normal(0,self.config.imu_accel_noise_std,3),
                self.data.sensor("gyro").data+self.np_random.normal(0,self.config.imu_gyro_noise_std,3))
            self.next_imu += 1/208
        angles = np.rad2deg(self.data.qpos[self.qadr]).copy()
        self.sample_history.append((now, angles))
        scan = self.config.robot['feedback']['scan_us']/1e6
        while len(self.sample_history)>2 and self.sample_history[1][0]<now-scan-.02:
            self.sample_history.pop(0)
        if now + 1e-10 >= self.next_feedback:
            timestamps=self.body_model.sample_times(now)
            history=np.array([v for _,v in self.sample_history]);times=np.array([t for t,_ in self.sample_history])
            sampled=np.array([np.interp(t,times,history[:,j]) for j,t in enumerate(timestamps)])
            raw=self.body_model.raw_samples(sampled)+self.np_random.normal(0,self.config.feedback_noise_raw_std,12)
            raw=np.rint(np.clip(raw,0,4095))
            self.feedback_angles,self.feedback_velocity,self.feedback_usable,self.jammed = self.body_model.feedback_sample(raw,self.last_target,1+timestamps*1e6)
            self.feedback_times = timestamps
            self.next_feedback += .02

    def _observation(self):
        return np.asarray(vector(self.observation()), dtype=np.float32)

    def foot_measurements(self):
        """Evaluation-only lower-leg/boot collision measurements, never policy inputs."""
        if not hasattr(self, "_foot_vertices"):
            self._foot_vertices = []
            self._foot_bodies = [self.model.body(leg+"_pickup_body").id for leg in LEGS]
            for bid in self._foot_bodies:
                vertices = []
                for gid in np.flatnonzero(self.model.geom_bodyid == bid):
                    if not (self.model.geom_contype[gid] or self.model.geom_conaffinity[gid]):
                        continue
                    mid = self.model.geom_dataid[gid]
                    start = self.model.mesh_vertadr[mid]
                    mesh = self.model.mesh_vert[start:start+self.model.mesh_vertnum[mid]]
                    world = mesh @ self.data.geom_xmat[gid].reshape(3,3).T+self.data.geom_xpos[gid]
                    vertices.append((world-self.data.xpos[bid]) @ self.data.xmat[bid].reshape(3,3))
                self._foot_vertices.append(np.concatenate(vertices))
        clearance = [float((vertices @ self.data.xmat[bid].reshape(3,3)[2,:]
                           + self.data.xpos[bid,2]).min())
                     for bid,vertices in zip(self._foot_bodies,self._foot_vertices)]
        valid=[True]*4
        lower_bound=list(clearance)
        if getattr(self.config,"scenarios",[]):
            clearance,valid,lower_bound=self._terrain_clearances(self._foot_bodies)
        contact = [False]*4
        force = np.zeros(6)
        terrain = self._terrain_mask()
        for index, pair in enumerate(self.data.contact[:self.data.ncon]):
            gid = pair.geom1 if terrain[pair.geom2] else pair.geom2 if terrain[pair.geom1] else None
            if gid is None:
                continue
            bid = int(self.model.geom_bodyid[gid])
            if bid in self._foot_bodies:
                mujoco.mj_contactForce(self.model,self.data,index,force)
                contact[self._foot_bodies.index(bid)] |= bool(force[0] > 0)
        return dict(clearance_m=clearance, clearance_valid=valid,
                    clearance_lower_bound_m=lower_bound, contact=contact)

    def step(self, action):
        requested = np.array(foot_offsets(action, self.config.foot_action_scale_mm))
        fitted = self.body_model.foot_target(requested.reshape(4,3), self.config.reference_joint_deg,
            self.last_target, self.config.joint_speed_deg_s, 1/self.config.control_hz,
            now_us=1+self.data.time*1e6)
        # The firmware rejects a geometrically unresolvable request without
        # writing PWM. Keep that outcome visible to learning and evaluation.
        self.target_rejected = fitted is None
        if fitted is not None:
            self.last_target, self.resolved_goal = fitted["ramped_angles"], fitted["goal_angles"]
        result = self._advance(action)
        result[-1].update(requested_foot_offset_mm=requested.reshape(4,3).tolist(),
            fitted_foot_offset_mm=fitted["applied_offset_mm"].tolist() if fitted else None,
            foot_fit=fitted["leg_fit"].tolist() if fitted else None,
            balance_usable=fitted["balance_usable"] if fitted else False,
            balance_correction_rad=fitted["balance_correction_rad"].tolist() if fitted else None,
            balance_reduced=fitted["balance_reduced"] if fitted else False)
        return result

    def virtual_body(self):
        """Attach the production P4 executor to this plant's acquired sensors."""
        from .native import VirtualBody
        return VirtualBody(self.body_model, self.config.reference_joint_deg,
            joint_speed_deg_s=self.config.joint_speed_deg_s,
            balance=self.config.balance_enabled,
            heading_feedback=self.config.heading_feedback_enabled,
            balance_tuning=self.config.balance_tuning,
            oscillator_hz=self.config.pwm_oscillator_hz,
            frequency_hz=self.config.pwm_frequency_hz)

    def advance_body(self, executor, action=None):
        """Advance physics from actual PCA output; never fit a policy target here.

        Receipts belong to the body executor. The caller publishes those and a
        fresh paired telemetry packet after this sensor-acquisition interval.
        With action=None this is also the standalone virtual hardware loop.
        """
        output = executor.tick(round(1+self.data.time*1e6))
        self.last_target = np.asarray(output["logical_angles"]).copy()
        self.target_rejected = any(message.get("t") == "nak" for message in output["messages"])
        pwm = {**output, "enabled": output["joint_enabled"]}
        result = self._advance_physics(pwm) if action is None else self._advance(action, pwm)
        return result, output

    def start_native_walk(self, command, *, heading_enabled, balance_enabled,
                          tuning=(1.0, 1.0, 0.0, 0.0)):
        """Run the existing firmware walking math in this same physical model.

        A baseline comparison, not a second physical controller. This does not
        reproduce body-task entry transitions or saved-policy admission/history.
        Command is the actual wire intent, retaining speed percentage semantics.
        """
        self.body_model.walk_configure(speed_deg_s=self.config.joint_speed_deg_s,
            heading_enabled=heading_enabled, balance_enabled=balance_enabled,
            tuning=tuning)
        accepted = self.body_model.walk_accept(command, 1+self.data.time*1e6)
        if accepted:
            self.native_command = dict(command)
        return accepted

    def update_native_walk(self, command):
        accepted = self.body_model.walk_accept(command, 1+self.data.time*1e6)
        if accepted:
            self.native_command = dict(command)
        return accepted

    def step_native_walk(self):
        """Return baseline measurements, never a fixed-forward training score."""
        frame = self.body_model.walk_tick(1+self.data.time*1e6, self.last_target)
        self.target_rejected = frame is None
        if frame is not None:
            self.last_target = frame["mapped_angles"].copy()
        metrics = self._advance_physics()
        self.steps += 1
        observed = self.observation()
        observed.pop("previous_action")
        # Public percentage/stride commands have no documented conversion to
        # m/s. Preserve their real wire semantics instead of inventing one.
        observed.pop("command")
        observed.pop("schema")
        return dict(command=dict(self.native_command or {}), observation=observed,
                    frame=frame, scope="native_walk_simulation_baseline", **metrics)

    def _contact_slip_speed_squared(self):
        """Ground-contact tangential speed squared, weighted by body-weight load.

        Simulation measurement only. Rigid-body point velocities reuse MuJoCo's
        body Jacobians; several sole hull contacts share one Jacobian evaluation.
        Scenario terrain uses each actual contact normal; historical flat
        episodes retain their exact world-XY calculation.
        """
        if not hasattr(self, "_slip_bodies"):
            self._slip_bodies = np.array([
                self.model.body(leg+"_pickup_body").id for leg in LEGS])
            self._slip_leg_for_body = np.full(self.model.nbody, -1, dtype=int)
            self._slip_leg_for_body[self._slip_bodies] = np.arange(len(LEGS))
            self._slip_jacp = np.empty((3, self.model.nv))
            self._slip_jacr = np.empty((3, self.model.nv))
            self._slip_force = np.empty(6)
            self._slip_linear = np.empty((len(LEGS), 3))
            self._slip_angular = np.empty((len(LEGS), 3))
        count = self.data.ncon
        if not count:
            return 0.0
        contacts = self.data.contact
        first, second = contacts.geom1[:count], contacts.geom2[:count]
        terrain=self._terrain_mask()
        other = np.where(terrain[first], second, np.where(terrain[second], first, -1))
        indices = np.flatnonzero(other >= 0)
        bodies = self.model.geom_bodyid[other[indices]]
        legs = self._slip_leg_for_body[bodies]
        foot = legs >= 0
        indices, bodies, legs = indices[foot], bodies[foot], legs[foot]
        normal = np.empty(len(indices))
        for index, contact in enumerate(indices):
            mujoco.mj_contactForce(self.model, self.data, int(contact), self._slip_force)
            normal[index] = self._slip_force[0]
        loaded = normal > 0
        if not loaded.any():
            return 0.0
        indices, bodies, legs, normal = (
            values[loaded] for values in (indices, bodies, legs, normal))
        for leg in set(legs.tolist()):
            body = self._slip_bodies[leg]
            mujoco.mj_jacBody(self.model, self.data, self._slip_jacp,
                             self._slip_jacr, int(body))
            self._slip_linear[leg] = self._slip_jacp @ self.data.qvel
            self._slip_angular[leg] = self._slip_jacr @ self.data.qvel
        offsets = contacts.pos[indices] - self.data.xpos[bodies]
        velocities = self._slip_linear[legs] + np.cross(self._slip_angular[legs], offsets)
        if getattr(self.config,"scenarios",[]):
            normals=contacts.frame[indices,:3]
            tangent=velocities-np.sum(velocities*normals,axis=1)[:,None]*normals
            squared=np.sum(tangent*tangent,axis=1)
        else:
            squared=np.sum(velocities[:, :2]**2,axis=1)
        weighted_speed_squared = float(normal @ squared)
        # reset() can randomize the actual model mass between episodes.
        body_weight = mujoco.mj_getTotalmass(self.model) * np.linalg.norm(self.model.opt.gravity)
        return weighted_speed_squared / body_weight

    def _advance_physics(self, output=None):
        before = self.data.qpos[:3].copy()
        self.pwm = output if output is not None else self.body_model.pwm_output(self.last_target,
            oscillator_hz=self.config.pwm_oscillator_hz, frequency_hz=self.config.pwm_frequency_hz)
        self.data.ctrl[:] = np.deg2rad(self.pwm["physical_angles"])
        enabled = np.asarray(self.pwm.get("enabled", [True]*12), dtype=bool)
        substeps = self.config.physics_hz // self.config.control_hz
        slip_speed_squared = 0.0
        for _ in range(substeps):
            # DC motor torque-speed envelope: opposing loads can stall it;
            # external forces can back-drive it. Do not clip simulated qvel.
            speed = self.data.qvel[self.vadr]
            maximum = math.radians(self.config.motor_no_load_speed_deg_s)
            self.model.actuator_forcerange[:, 0] = -self.config.torque_nm * np.clip(1+speed/maximum, 0, 1) * enabled
            self.model.actuator_forcerange[:, 1] = self.config.torque_nm * np.clip(1-speed/maximum, 0, 1) * enabled
            if self.scenario is not None:
                self._apply_scenario_pushes()
            mujoco.mj_step(self.model, self.data)
            self._sample_sensors()
            slip_speed_squared += self._contact_slip_speed_squared()
        rotation = self.data.xmat[self.model.body("torso").id].reshape(3, 3)
        displacement = self.data.qpos[:3] - before
        velocity = rotation.T @ displacement * self.config.control_hz
        ground_height=self.terrain_height(*self.data.qpos[:2]) if self.scenario is not None else 0.
        return dict(scenario_id=self.scenario_id, body_clearance_m=float(self.data.qpos[2]-ground_height),
                    terrain_height_m=ground_height, velocity_body_m_s=velocity.tolist(), upright=float(rotation[2,2]),
                    ground_world_displacement_m=displacement[:2].tolist(),
                    heading_rad=math.atan2(rotation[1,0], rotation[0,0]),
                    contact_slip_speed_squared_m2_s2=slip_speed_squared/substeps,
                    target_rejected=self.target_rejected, jammed_joints=int(self.jammed))

    def _advance(self, action, output=None):
        # Read before and after the same physical interval. No stale previous
        # episode velocity or command target can masquerade as acceleration.
        previous_joint_velocity = self.data.qvel[self.vadr].copy()
        metrics = self._advance_physics(output)
        self.steps += 1
        velocity = np.asarray(metrics["velocity_body_m_s"])
        upright = metrics["upright"]
        # Desired heading follows the request, never the robot's accidental
        # turn. Use horizontal ground displacement so tilt/vertical bobbing
        # cannot redefine forward progress. Ground truth is reward-only.
        requested_turn = self.config.command[2] / self.config.control_hz
        reference_heading = self.reward_reference_heading + requested_turn / 2
        c, s = math.cos(reference_heading), math.sin(reference_heading)
        dx, dy = metrics["ground_world_displacement_m"]
        command_velocity = np.array([c*dx+s*dy, -s*dx+c*dy]) * self.config.control_hz
        self.reward_reference_heading += requested_turn
        heading = metrics["heading_rad"]
        heading_delta = math.atan2(math.sin(heading-self.reward_last_heading),
                                  math.cos(heading-self.reward_last_heading))
        self.world_heading_delta += heading_delta
        self.reward_last_heading = heading
        self.reward_twists.append([*command_velocity,heading_delta*self.config.control_hz])
        if self.config.reward_profile == "locomotion":
            # Ground-truth dynamics are reward-only. The actor still consumes
            # the production fourth-wire/IMU observation through Body Control.
            reward, components = locomotion_reward(
                command_velocity, heading_delta*self.config.control_hz,
                self.config.command, upright,
                metrics["body_clearance_m"]/self.standing_height,
                vertical_velocity=self.data.qvel[2],  # free-root world Z, not tilted body Z
                angular_velocity_xy=self.data.sensor("gyro").data[:2],
                joint_velocity=self.data.qvel[self.vadr],
                previous_joint_velocity=previous_joint_velocity,
                joint_torque=self.data.actuator_force,
                action=action, previous_action=self.last_action,
                contact_slip_speed_squared=metrics["contact_slip_speed_squared_m2_s2"],
                config=self.config)
            travel_reward = components["tracking_linear"]+components["tracking_yaw"]
            slip_cost = components["slip"]
        else:
            # Reward new progress only. Cumulative-average potentials can increase
            # while stationary by continuing to credit earlier displacement.
            travel_reward, reward_components = movement_reward(
                command_velocity, heading_delta*self.config.control_hz, self.config.command,
                upright, metrics["body_clearance_m"]/self.standing_height,
                velocity_scale=self.config.reward_velocity_scale_m_s,
                yaw_scale=self.config.reward_yaw_scale_rad_s,
                cross_track_cost=self.config.reward_cross_track_cost,
                overspeed_cost=self.config.reward_overspeed_cost,
                pace_twist=np.mean(self.reward_twists,axis=0), details=True)
            effort = float(np.mean((self.data.actuator_force / self.config.torque_nm) ** 2))
            slip_cost = CONTACT_SLIP_COST * metrics["contact_slip_speed_squared_m2_s2"]
            action_change_cost = 0.01 * float(np.mean((action - self.last_action) ** 2))
            reward = float(
                travel_reward
                - slip_cost
                - 0.05 * effort
                - action_change_cost
            )
            components = dict(**reward_components, slip=slip_cost,
                              effort=.05*effort, action_change=action_change_cost)
        self.last_action = np.asarray(action).copy()
        fallen = upright < 0.3 or metrics["body_clearance_m"] < 0.025
        terminated = bool(fallen or not np.isfinite(self.data.qpos).all())
        truncated = self.steps >= round(
            self.config.episode_seconds * self.config.control_hz
        )
        return (
            self._observation(),
            reward,
            terminated,
            truncated,
            dict(
                command=list(self.config.command),
                scenario_id=self.scenario_id,
                body_clearance_m=metrics["body_clearance_m"],
                terrain_height_m=metrics["terrain_height_m"],
                velocity_body_m_s=velocity.tolist(),
                velocity_command_m_s=command_velocity.tolist(),
                ground_world_displacement_m=metrics["ground_world_displacement_m"],
                heading_rad=heading,
                contact_slip_speed_squared_m2_s2=metrics["contact_slip_speed_squared_m2_s2"],
                upright=upright,
                fallen=bool(fallen),
                reward=reward,
                travel_reward=travel_reward,
                contact_slip_cost=slip_cost,
                reward_components=components,
                scope="simulation",
                target_rejected=self.target_rejected,
                jammed_joints=int(self.jammed),
            ),
        )

    def render(self):
        if self.renderer is None:
            self.renderer = mujoco.Renderer(self.model, height=480, width=640)
        self.renderer.update_scene(self.data)
        return self.renderer.render()

    def close(self):
        self.body_model.close()
        if self.renderer:
            self.renderer.close()


def make_environment(config, **kwargs):
    """Select the recorded execution path for training, evaluation and video."""
    if config.execution_backend == "body_control":
        from .connected_environment import BodyControlEnvironment
        return BodyControlEnvironment(config, **kwargs)
    return GaitEnvironment(config, **kwargs)
