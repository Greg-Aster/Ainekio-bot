from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
import numpy as np

from gateway.person_identity import FaceGallery, PersonEvidence, PersonIdentityBackend, PersonTracker
from gateway.perception import RecognitionResult, RecognizedObject, parse_recognition


def feature(index=0):
    result = np.zeros(128, dtype=np.float32)
    result[index] = 1
    return result


def person(index=0, x=.1, match=None, visible=False, color=0):
    return PersonEvidence(index, (x, .1, .3, .7), feature(color), match, visible)


ALICE = {"personId": "alice", "name": "Alice", "similarity": .8}
BOB = {"personId": "bob", "name": "Bob", "similarity": .85}


class GalleryTests(unittest.TestCase):
    def test_persistence_forget_model_binding_and_no_photo_storage(self):
        with TemporaryDirectory() as root:
            path = Path(root) / "known-people.json"
            gallery = FaceGallery(path, "model-hash")
            alice = gallery.add("Alice", feature())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            saved = FaceGallery(path, "model-hash")
            self.assertEqual(saved.match(feature())["personId"], alice)
            self.assertIsNone(saved.match(feature(1)))
            self.assertEqual(saved.list(), [{"personId": alice, "name": "Alice", "samples": 1}])
            self.assertNotIn("jpeg", path.read_text())
            with self.assertRaisesRegex(ValueError, "original"):
                FaceGallery(path, "different-model")
            saved.forget(alice)
            self.assertIsNone(FaceGallery(path, "model-hash").match(feature()))

    def test_ambiguous_enrollments_are_unknown_and_capacity_fits_private_store(self):
        with TemporaryDirectory() as root:
            gallery = FaceGallery(Path(root) / "people.json", "hash")
            gallery.add("Alice", feature())
            gallery.add("Similar person", feature())
            self.assertIsNone(gallery.match(feature()))
            with self.assertRaisesRegex(ValueError, "already enrolled"):
                gallery.add("Alice", feature())
            for index in range(2, 16):
                for sample in range(4):
                    gallery.add(f"Person {index}", feature(index * 4 + sample))
            FaceGallery(gallery.path, "hash")
            with self.assertRaises(ValueError):
                gallery.add("Overflow", feature(100))


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.tracker = PersonTracker()

    def update(self, counter, time, people, source=("robot", 1, 0)):
        return self.tracker.update(source, counter, time, people)

    def test_named_track_motion_face_hidden_expiry_and_face_reacquisition(self):
        first = self.update(1, 0, [person(match=ALICE, visible=True)])[0]
        hidden = self.update(2, 1, [person(x=.15)])[0]
        self.assertEqual(hidden["trackId"], first["trackId"])
        self.assertEqual(hidden["state"], "tracked")
        self.assertEqual(hidden["faceAgeMs"], 1000)
        self.update(3, 2, [person(x=.2)])
        expired = self.update(4, 3.1, [person(x=.21)])[0]
        self.assertEqual(expired["state"], "unknown")
        self.assertNotIn("name", expired)
        seen = self.update(5, 4, [person(x=.7, match=ALICE, visible=True)])[0]
        self.assertEqual(seen["personId"], "alice")
        self.assertNotEqual(seen["trackId"], first["trackId"])

    def test_crossing_disappearance_and_lookalike_color_do_not_prove_identity(self):
        self.update(1, 0, [person(match=ALICE, visible=True), person(1, .5, BOB, True)])
        crossed = self.update(2, .5, [person(x=.3), person(1, .3)])
        self.assertTrue(all(x["state"] == "unknown" for x in crossed.values()))
        self.assertEqual(self.update(3, 1, []), {})
        self.assertEqual(self.update(4, 1.5, [person()])[0]["state"], "unknown")

    def test_replacement_visible_unknown_and_duplicate_identity_clear_names(self):
        self.update(1, 0, [person(match=ALICE, visible=True)])
        self.assertEqual(self.update(2, .5, [person(visible=True)])[0]["state"], "unknown")
        two = self.update(3, 1, [person(match=ALICE, visible=True), person(1, .6, ALICE, True)])
        self.assertTrue(all(x["state"] == "unknown" for x in two.values()))
        next_frame = self.update(4, 1.5, [person(), person(1, .6)])
        self.assertTrue(all(x["state"] == "unknown" for x in next_frame.values()))

    def test_duplicate_out_of_order_reconnect_off_on_and_long_gap(self):
        first = self.update(8, 0, [person(match=ALICE, visible=True)])[0]
        for counter in (8, 7):
            with self.assertRaisesRegex(ValueError, "distinct"):
                self.update(counter, .1, [person()])
        unknown = self.update(9, 2, [person()])[0]
        self.assertEqual(unknown["state"], "unknown")
        self.assertNotEqual(first["trackId"], unknown["trackId"])
        for source in (("robot", 2, 0), ("robot", 2, 1), ("other", 1, 0)):
            self.assertEqual(self.update(1, 3, [person()], source)[0]["state"], "unknown")

    def test_similar_clothes_unseen_replacement_is_an_explicit_limitation(self):
        self.update(1, 0, [person(match=ALICE, visible=True)])
        # The inputs cannot distinguish Alice turning away from an unseen
        # similarly clothed replacement. Do not label this a fresh face match.
        estimate = self.update(2, .5, [person()])[0]
        self.assertEqual(estimate["state"], "tracked")
        self.assertNotIn("similarity", estimate)
        self.assertEqual(estimate["faceAgeMs"], 500)

    def test_forget_invalidates_inflight_embeddings_and_contract_roundtrip(self):
        with TemporaryDirectory() as root:
            gallery = FaceGallery(Path(root) / "people.json", "hash")
            alice = gallery.add("Alice", feature())
            backend = PersonIdentityBackend(None, SimpleNamespace(model_hash="hash", detector_hash="detector-hash"), gallery)
            recognition = RecognitionResult("fixture", "fixture", "", (RecognizedObject("person", .9, (.1, .1, .3, .7)),), ())
            result = (recognition, [person(match=feature(), visible=True)])
            first = backend.finalize_frame(result, ("robot", 1, 0), 1, 0)
            self.assertEqual(first.objects[0].identity["personId"], alice)
            message = first.message()
            parsed = parse_recognition({k: message[k] for k in ("summary", "objects", "uncertainties")}, backend=message["backend"], model=message["model"])
            self.assertEqual(parsed, first)
            gallery.forget(alice)
            later = backend.finalize_frame(result, ("robot", 1, 0), 2, .5)
            self.assertEqual(later.objects[0].identity["state"], "unknown")
