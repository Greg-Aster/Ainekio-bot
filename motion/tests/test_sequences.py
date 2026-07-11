import unittest

from ainekio_motion.backend import DisabledHardwareBackend, VirtualBackend
from ainekio_motion.sequences import SESAME_PROVISIONAL_SERVO_ORDER, SequenceEngine
from ainekio_motion.types import MotionCommand, RobotCommand, RootMotionIntent


class SequenceEngineTests(unittest.TestCase):
    def test_walk_frames_are_staggered(self) -> None:
        engine = SequenceEngine(motor_stagger_ms=20)
        frames = engine.render(MotionCommand(RobotCommand.WALK), start_ms=1000)

        first_step = frames[: len(SESAME_PROVISIONAL_SERVO_ORDER)]
        self.assertEqual(first_step[0].at_ms, 1000)
        self.assertEqual(first_step[1].at_ms, 1020)
        self.assertEqual(first_step[-1].at_ms, 1140)

    def test_stand_uses_stock_sesame_pose(self) -> None:
        frames = SequenceEngine(motor_stagger_ms=0).render(MotionCommand(RobotCommand.STAND))
        angles = {frame.servo: frame.angle for frame in frames}

        self.assertEqual(
            angles,
            {"R1": 135, "R2": 45, "L1": 45, "L2": 135, "R4": 0, "R3": 180, "L3": 0, "L4": 180},
        )

    def test_virtual_backend_preserves_root_motion(self) -> None:
        backend = VirtualBackend()
        command = MotionCommand(
            RobotCommand.WALK,
            root_motion=RootMotionIntent(forward=1.0, duration_ms=500),
        )

        backend.apply(command)

        self.assertEqual(backend.telemetry[-1].root_motion, command.root_motion)

    def test_hardware_backend_refuses_when_disabled(self) -> None:
        backend = DisabledHardwareBackend(hardware_enabled=False)

        with self.assertRaises(RuntimeError):
            backend.apply(MotionCommand(RobotCommand.WALK))


if __name__ == "__main__":
    unittest.main()
