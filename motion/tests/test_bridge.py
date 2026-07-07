import unittest

from ainekio_motion.bridge import filter_reconnect_actions
from ainekio_motion.types import RobotCommand


class ReconnectCatchUpTests(unittest.TestCase):
    def test_filters_expired_actions(self) -> None:
        actions = [
            {"type": "move", "direction": "forward", "issued_at_ms": 1000, "ttl_ms": 200},
            {"type": "move", "direction": "right", "issued_at_ms": 1250, "ttl_ms": 500},
        ]

        commands = filter_reconnect_actions(actions, at_ms=1500)

        self.assertEqual([command.command for command in commands], [RobotCommand.TURN_RIGHT])


if __name__ == "__main__":
    unittest.main()
