import unittest

from emulator.backends.sesame import _renderer_payload
from emulator.body.assets import AssetStore


class SesameBackendTests(unittest.TestCase):
    def test_walk_directions_map_to_renderer_contract(self) -> None:
        expected = {
            "fwd": ("walk", "run walk", 1.0, 0.0, 840),
            "back": ("backward", "rn wb", -1.0, 0.0, 840),
            "turn_l": ("turn_left_45", None, 0.0, 5.4, 18720),
            "turn_r": ("turn_right_45", None, 0.0, -5.4, 18720),
        }

        for direction, profile in expected.items():
            with self.subTest(direction=direction):
                payload, duration_ms = _renderer_payload(
                    {"t": "intent", "seq": 7, "name": "walk", "dir": direction, "steps": 3},
                    session_id="session-1",
                )
                command, simulator_command, forward, yaw, expected_duration = profile
                self.assertEqual(payload["source"], "protocol-v1-emulator")
                self.assertEqual(payload["command"], command)
                self.assertEqual(payload["simulatorCommand"], simulator_command)
                self.assertEqual(payload["rootMotion"]["forward"], forward)
                self.assertEqual(payload["rootMotion"]["yaw"], yaw)
                self.assertEqual(payload["units"], 3)
                self.assertEqual(duration_ms, expected_duration)

    def test_stop_maps_to_immediate_stand_command(self) -> None:
        payload, duration_ms = _renderer_payload(
            {"t": "stop", "seq": 8},
            session_id="session-1",
        )

        self.assertEqual(payload["command"], "stop")
        self.assertEqual(payload["simulatorCommand"], "run stand")
        self.assertIsNone(payload["rootMotion"])
        self.assertEqual(payload["protocolSequence"], 8)
        self.assertEqual(duration_ms, 140)

    def test_sit_uses_the_verified_sesame_rest_pose(self) -> None:
        payload, duration_ms = _renderer_payload(
            {"t": "intent", "seq": 9, "name": "sit"},
            session_id="session-1",
        )

        self.assertEqual(payload["command"], "sit")
        self.assertEqual(payload["simulatorCommand"], "run rest")
        self.assertEqual(duration_ms, 400)

    def test_motion_plan_uses_bounded_frames_without_named_uart_command(self) -> None:
        payload, duration_ms = _renderer_payload(
            {
                "t": "motion_plan",
                "seq": 10,
                "map": 1,
                "end": "hold",
                "_joint_map_version": 1,
                "_motion_plan_frames": [
                    {
                        "duration_ms": 300,
                        "targets": [[joint_id, 90.0] for joint_id in range(8)],
                    },
                    {
                        "duration_ms": 400,
                        "targets": [[joint_id, 100.0] for joint_id in range(8)],
                    },
                ],
            },
            session_id="session-1",
        )

        self.assertEqual(payload["command"], "freestyle")
        self.assertIsNone(payload["simulatorCommand"])
        self.assertEqual(payload["jointMapVersion"], 1)
        self.assertEqual(payload["endPose"], "hold")
        self.assertEqual(len(payload["frames"]), 2)
        self.assertEqual(duration_ms, 700)

    def test_owner_emotes_use_asset_frames_without_legacy_uart_commands(self) -> None:
        expected = {
            "nod": 2460,
            "celebrate": 3460,
            "stretch": 4330,
            "macarena": 6140,
            "salsa": 5580,
            "surprised": 2860,
            "sad": 4660,
            "curious": 18490,
            "turn_left_45": 6240,
            "turn_right_45": 6240,
            "turn_left_90": 11520,
            "turn_right_90": 11520,
            "turn_left_180": 22180,
            "turn_right_180": 22180,
            "walk_slow": 10940,
            "run": 4560,
        }
        assets = AssetStore()
        for asset, expected_duration in expected.items():
            with self.subTest(asset=asset):
                payload, duration_ms = _renderer_payload(
                    {"t": "intent", "seq": 11, "name": "emote", "asset": asset},
                    session_id="session-1",
                )
                self.assertEqual(payload["command"], asset)
                self.assertIsNone(payload["simulatorCommand"])
                self.assertEqual(duration_ms, expected_duration)
                motion = assets.motion(asset)
                assert motion is not None
                self.assertEqual(
                    duration_ms,
                    sum(frame.duration_ms for frame in motion.frames),
                )


if __name__ == "__main__":
    unittest.main()
