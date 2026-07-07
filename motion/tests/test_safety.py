import unittest

from ainekio_motion.safety import SafetyController
from ainekio_motion.types import MotionCommand, RobotCommand


class SafetyControllerTests(unittest.TestCase):
    def test_rejects_expired_command_as_stop(self) -> None:
        safety = SafetyController()
        decision = safety.accept(MotionCommand(RobotCommand.WALK, issued_at_ms=100, ttl_ms=50), at_ms=200)

        self.assertFalse(decision.accepted)
        self.assertEqual(decision.command.command, RobotCommand.STOP)
        self.assertEqual(decision.reason, "command_expired")

    def test_offline_fallback_idles_when_disconnected(self) -> None:
        safety = SafetyController(offline_fallback_ms=100)
        safety.mark_connected(at_ms=1000)

        command = safety.offline_fallback_command(at_ms=1200)

        self.assertIsNotNone(command)
        assert command is not None
        self.assertEqual(command.command, RobotCommand.IDLE)
        self.assertEqual(command.source, "offline-fallback")

    def test_rejects_expired_lease(self) -> None:
        safety = SafetyController()
        safety.grant_lease("remote-a", ttl_ms=100, at_ms=1000)

        decision = safety.accept(
            MotionCommand(RobotCommand.WALK, issued_at_ms=1150, ttl_ms=500, lease_id="remote-a"),
            at_ms=1150,
        )

        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "lease_expired")


if __name__ == "__main__":
    unittest.main()
