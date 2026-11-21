"""50 Hz Goal-Conditioned Neural Pose & Emote Controller for Ainekio V2."""

from .contract import (
    POSE_FEATURES,
    POSE_FOOT_SCALE_MM,
    POSE_OBS_SIZE,
    POSE_SAMPLES,
    POSE_SCHEMA,
    PoseObservationHistory,
    assemble_pose_features,
    pose_foot_offsets,
)

from .presence import (
    NEURAL_POSE_PRESENCE_OWNER,
    PRESENCE_DEFAULTS,
    NeuralPosePresence,
    speech_presence_goal_deg,
    validate_presence_settings,
)

__all__ = [
    "NEURAL_POSE_PRESENCE_OWNER",
    "PRESENCE_DEFAULTS",
    "POSE_FEATURES",
    "POSE_FOOT_SCALE_MM",
    "POSE_OBS_SIZE",
    "POSE_SAMPLES",
    "POSE_SCHEMA",
    "NeuralPosePresence",
    "PoseObservationHistory",
    "assemble_pose_features",
    "pose_foot_offsets",
    "speech_presence_goal_deg",
    "validate_presence_settings",
]
