import unittest

from ainekio_motion.commands import translate_environment_action
from ainekio_motion.types import RobotCommand


class CommandTranslationTests(unittest.TestCase):
    def test_move_forward_includes_root_motion(self) -> None:
        command = translate_environment_action(
            {"type": "move", "direction": "forward", "duration_ms": 700, "speed": 0.5},
            issued_at_ms=100,
        )

        self.assertIsNotNone(command)
        assert command is not None
        self.assertEqual(command.command, RobotCommand.WALK)
        self.assertIsNotNone(command.root_motion)
        assert command.root_motion is not None
        self.assertEqual(command.root_motion.forward, 1.0)
        self.assertEqual(command.root_motion.duration_ms, 700)

    def test_does_not_tunnel_robot_command_metadata(self) -> None:
        command = translate_environment_action(
            {"type": "interact", "metadata": {"robotCommand": "wave"}},
            issued_at_ms=100,
        )

        self.assertIsNone(command)


if __name__ == "__main__":
    unittest.main()
