import unittest

from ainekio_motion.commands import parse_robot_command, translate_environment_action
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

    def test_robot_command_preserves_simulator_command(self) -> None:
        command = translate_environment_action(
            {"type": "robotCommand", "command": "wave", "simulatorCommand": "rn wv"},
            issued_at_ms=100,
        )

        self.assertIsNotNone(command)
        assert command is not None
        self.assertEqual(command.command, RobotCommand.WAVE)
        self.assertEqual(command.metadata["simulatorCommand"], "rn wv")

    def test_official_emote_commands_map_to_simulator_serial_commands(self) -> None:
        expected = {
            "dance": "rn dn",
            "swim": "rn sw",
            "point": "rn pt",
            "pushup": "rn pu",
            "bow": "rn bw",
            "cute": "rn ct",
            "freaky": "rn fk",
            "worm": "rn wm",
            "shake": "rn sk",
            "shrug": "rn sg",
            "dead": "rn dd",
            "crab": "rn cb",
        }

        for command_name, simulator_command in expected.items():
            with self.subTest(command_name=command_name):
                command = translate_environment_action(
                    {"type": "robotCommand", "command": command_name},
                    issued_at_ms=100,
                )

                self.assertIsNotNone(command)
                assert command is not None
                self.assertEqual(command.command.value, command_name)
                self.assertEqual(command.metadata["simulatorCommand"], simulator_command)

    def test_robot_command_aliases_keep_common_phrases_semantic(self) -> None:
        self.assertEqual(parse_robot_command("push up"), RobotCommand.PUSHUP)
        self.assertEqual(parse_robot_command("push_up"), RobotCommand.PUSHUP)
        self.assertEqual(parse_robot_command("pushups"), RobotCommand.PUSHUP)
        self.assertEqual(parse_robot_command("play_dead"), RobotCommand.DEAD)
        self.assertEqual(parse_robot_command("walk_forward"), RobotCommand.WALK)


if __name__ == "__main__":
    unittest.main()
