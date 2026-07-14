from __future__ import annotations

import unittest

from emulator.body.core import CoreLifecycle, CoreRejection, PortableCore
from Emulator.tests.support import build_core_library


class PortableCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.library_path = build_core_library()

    def setUp(self) -> None:
        self.core = PortableCore(self.library_path)
        self.core.begin_session(12, "tether")

    def tearDown(self) -> None:
        self.core.close()

    def test_rejection_enum_matches_portable_c_abi(self) -> None:
        self.assertEqual(
            {member.name: member.value for member in CoreRejection},
            {
                "NONE": 0,
                "STALE": 1,
                "MODE": 2,
                "UNSAFE": 3,
                "LIMIT": 4,
                "UNKNOWN": 5,
                "BUSY": 6,
                "PROFILE": 7,
                "ASSET_MISSING": 8,
                "MALFORMED": 9,
            },
        )

    def test_accepts_movement_and_rejects_duplicate_sequence(self) -> None:
        stand = {"t": "intent", "seq": 1, "name": "stand"}

        decision = self.core.accept(stand)

        self.assertTrue(decision.accepted)
        self.assertEqual(decision.lifecycle, CoreLifecycle.ACK_THEN_DONE)
        self.assertTrue(self.core.servos_attached)
        self.assertEqual(self.core.profile, 1)
        self.assertEqual(self.core.accept(stand).rejection, CoreRejection.STALE)

    def test_claims_unavailable_sequence_without_executing(self) -> None:
        self.assertEqual(self.core.claim_sequence(4), CoreRejection.NONE)
        self.assertFalse(self.core.servos_attached)

        stop = {"t": "stop", "seq": 4}
        self.assertEqual(self.core.accept(stop).rejection, CoreRejection.STALE)

    def test_failsafe_detaches_servos(self) -> None:
        self.core.accept({"t": "intent", "seq": 1, "name": "stand"})

        self.core.enter_failsafe()

        self.assertFalse(self.core.servos_attached)
        self.assertEqual(self.core.state, 4)


if __name__ == "__main__":
    unittest.main()
