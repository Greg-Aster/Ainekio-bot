import unittest

from ainekio_motion.backend import DisabledPca9685Backend, VirtualBackend
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

    def test_virtual_backend_preserves_root_motion(self) -> None:
        backend = VirtualBackend()
        command = MotionCommand(
            RobotCommand.WALK,
            root_motion=RootMotionIntent(forward=1.0, duration_ms=500),
        )

        backend.apply(command)

        self.assertEqual(backend.telemetry[-1].root_motion, command.root_motion)

    def test_physical_backend_refuses_when_disabled(self) -> None:
        backend = DisabledPca9685Backend(hardware_enabled=False)

        with self.assertRaises(RuntimeError):
            backend.apply(MotionCommand(RobotCommand.WALK))


if __name__ == "__main__":
    unittest.main()
