"""Local enrolled-face estimates and short visual tracks; no command authority.

Only accepted, fresh frames update tracks. Photos are not retained. Enrollment
embeddings are private local data, tied to the exact face model's SHA-256.
"""
from __future__ import annotations

import base64
from collections import Counter
from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
import threading
from uuid import uuid4

from .perception import RecognitionResult
from .security import _atomic_secure_json, _read_json


MAX_PEOPLE = 16
MAX_SAMPLES = 4
FACE_THRESHOLD = 0.363  # OpenCV SFace cosine reference; not a probability.
FACE_MARGIN = 0.08
TRACK_GAP_S = 1.5
FACE_MEMORY_S = 3.0


def unit_feature(value):
    import numpy as np
    vector = np.asarray(value, dtype=np.float32).reshape(-1)
    if vector.size != 128 or not np.isfinite(vector).all() or np.linalg.norm(vector) < 1e-8:
        raise ValueError("Face embedding must contain 128 finite nonzero features")
    return vector / np.linalg.norm(vector)


class FaceGallery:
    def __init__(self, path: Path, model_hash: str):
        self.path, self.model_hash = path, model_hash
        self.lock = threading.RLock()
        self.revision = 0
        self.people = {}
        if path.exists():
            data = _read_json(path)
            if data.get("version") != 1 or data.get("modelHash") != model_hash:
                raise ValueError("Enrolled faces require the original recognition model")
            people = data.get("people")
            if not isinstance(people, dict) or len(people) > MAX_PEOPLE:
                raise ValueError("Invalid face gallery")
            for person_id, person in people.items():
                if not isinstance(person_id, str) or not 1 <= len(person_id) <= 80:
                    raise ValueError("Invalid enrolled person id")
                self._name(person.get("name"))
                samples = person.get("samples")
                if not isinstance(samples, list) or not 1 <= len(samples) <= MAX_SAMPLES:
                    raise ValueError("Invalid face samples")
                for sample in samples:
                    self._decode(sample)
            self.people = people

    @staticmethod
    def _name(name):
        if not isinstance(name, str) or not name.strip() or len(name) > 80 or any(ord(c) < 32 for c in name):
            raise ValueError("Enter a name of 1 to 80 characters")
        return name.strip()

    @staticmethod
    def _decode(sample):
        import numpy as np
        return unit_feature(np.frombuffer(base64.b64decode(sample, validate=True), dtype="<f4"))

    def list(self):
        with self.lock:
            return [{"personId": key, "name": item["name"], "samples": len(item["samples"])}
                    for key, item in self.people.items()]

    def add(self, name, feature):
        name = self._name(name)
        sample = base64.b64encode(unit_feature(feature).astype("<f4").tobytes()).decode("ascii")
        with self.lock:
            person_id = next((key for key, item in self.people.items() if item["name"].casefold() == name.casefold()), None)
            if person_id is None and len(self.people) >= MAX_PEOPLE:
                raise ValueError("The gallery holds up to 16 people; forget a person before adding another")
            person_id = person_id or str(uuid4())
            previous = self.people.get(person_id, {"name": name, "samples": []})
            if sample in previous["samples"]:
                raise ValueError("This photo is already enrolled; use a different photo")
            if len(previous["samples"]) >= MAX_SAMPLES:
                raise ValueError("This person already has four samples; forget them to enroll a new set")
            updated = {**self.people, person_id: {"name": name, "samples": [*previous["samples"], sample]}}
            self._save(updated)
            return person_id

    def forget(self, person_id):
        with self.lock:
            if person_id not in self.people:
                raise ValueError("Enrolled person was not found")
            self._save({key: value for key, value in self.people.items() if key != person_id})

    def _save(self, people):
        _atomic_secure_json(self.path, {"version": 1, "modelHash": self.model_hash, "people": people})
        self.people = people
        self.revision += 1

    def match(self, feature):
        vector = unit_feature(feature)
        with self.lock:
            scores = sorted(((max(float(vector @ self._decode(sample)) for sample in item["samples"]),
                              key, item["name"]) for key, item in self.people.items()), reverse=True)
        if not scores or scores[0][0] < FACE_THRESHOLD:
            return None
        if len(scores) > 1 and scores[0][0] - scores[1][0] < FACE_MARGIN:
            return None
        score, person_id, name = scores[0]
        return {"personId": person_id, "name": name, "similarity": min(1.0, max(-1.0, score))}


class LocalFaces:
    def __init__(self, detector_path, recognizer_path):
        import cv2
        detector_path, recognizer_path = Path(detector_path).resolve(strict=True), Path(recognizer_path).resolve(strict=True)
        with recognizer_path.open("rb") as stream:
            self.model_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        with detector_path.open("rb") as stream:
            self.detector_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        self.detector = cv2.FaceDetectorYN.create(str(detector_path), "", (320, 320), 0.8, 0.3, 500)
        self.recognizer = cv2.FaceRecognizerSF.create(str(recognizer_path), "")

    def faces(self, image):
        height, width = image.shape[:2]
        self.detector.setInputSize((width, height))
        _, faces = self.detector.detect(image)
        return [] if faces is None else [(face, unit_feature(self.recognizer.feature(
            self.recognizer.alignCrop(image, face)))) for face in faces[:32]]


def decode_jpeg(jpeg):
    import cv2
    import numpy as np
    from protocol.binary_helpers import MAX_JPEG_BYTES
    if not isinstance(jpeg, bytes) or not 4 <= len(jpeg) <= MAX_JPEG_BYTES or not jpeg.startswith(b"\xff\xd8"):
        raise ValueError("Select a bounded JPEG image")
    frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("Cannot decode this JPEG image")
    return frame


def overlap(a, b):
    x, y = max(a[0], b[0]), max(a[1], b[1])
    w, h = max(0, min(a[0] + a[2], b[0] + b[2]) - x), max(0, min(a[1] + a[3], b[1] + b[3]) - y)
    intersection = w * h
    return intersection / max(1e-9, a[2] * a[3] + b[2] * b[3] - intersection)


@dataclass
class PersonEvidence:
    index: int
    box: tuple
    appearance: object
    face: object = None
    face_visible: bool = False


class PersonTracker:
    """Mutually unambiguous box/appearance continuity, reidentified by fresh faces.

    An occluded track is never emitted as visible. Crowded crossings, a visible
    nonmatch, long gaps and source changes cannot inherit a previous name.
    """
    def __init__(self):
        self.source = None
        self.counter = None
        self.time = None
        self.tracks = []

    def update(self, source, counter, now, evidence):
        import numpy as np
        if source == self.source and self.counter is not None and not 0 < ((counter - self.counter) & 0xffffffff) < 0x80000000:
            raise ValueError("Identity tracking requires distinct successive frames")
        if source != self.source or self.time is None or now - self.time > TRACK_GAP_S or now < self.time:
            self.tracks = []
            self.counter = None
        old = self.tracks
        candidates = []
        for item in evidence:
            candidates.append([i for i, track in enumerate(old)
                if overlap(item.box, track["box"]) >= .3
                and float(np.minimum(item.appearance, track["appearance"]).sum()) >= .65])
        uses = Counter(index for choices in candidates for index in choices)
        new, identities = [], {}
        for item, choices in zip(evidence, candidates):
            prior = old[choices[0]] if len(choices) == 1 and uses[choices[0]] == 1 else None
            # A directly observed different/unrecognized face breaks inherited identity.
            if prior and item.face_visible and (not item.face or not prior["match"]
                    or item.face["personId"] != prior["match"]["personId"]):
                prior = None
            track_id = prior["trackId"] if prior else str(uuid4())
            match = item.face
            face_at = now if match else (prior["faceAt"] if prior else None)
            if not match and not item.face_visible and prior and face_at is not None and now - face_at <= FACE_MEMORY_S:
                match = prior["match"]
            identity = {"trackId": track_id, "state": "face_match" if item.face else "tracked" if match else "unknown"}
            if match:
                identity.update({"personId": match["personId"], "name": match["name"], "faceAgeMs": (now - face_at) * 1000})
                if item.face:
                    identity["similarity"] = item.face["similarity"]
            identities[item.index] = identity
            new.append({"trackId": track_id, "box": item.box, "appearance": item.appearance,
                        "match": match, "faceAt": face_at})
        names = Counter(identity.get("personId") for identity in identities.values() if identity.get("personId"))
        for identity, track in zip(identities.values(), new):
            if names.get(identity.get("personId"), 0) > 1:
                identity.clear()
                identity.update({"trackId": track["trackId"], "state": "unknown"})
                track["match"] = None
        self.source, self.counter, self.time, self.tracks = source, counter, now, new
        return identities


class PersonIdentityBackend:
    def __init__(self, detector, faces: LocalFaces, gallery: FaceGallery):
        self.detector, self.faces, self.gallery = detector, faces, gallery
        self.tracker = PersonTracker()

    def __call__(self, jpeg):
        """Heavy work on CameraFramePlugin's existing single inference thread."""
        import cv2
        recognition = self.detector(jpeg)
        frame = decode_jpeg(jpeg)
        height, width = frame.shape[:2]
        faces = self.faces.faces(frame)
        people = [(i, item) for i, item in enumerate(recognition.objects) if item.label == "person" and item.box]
        memberships = []
        for face, feature in faces:
            cx, cy = (face[0] + face[2] / 2) / width, (face[1] + face[3] / 2) / height
            memberships.append([i for i, person in people if person.box[0] <= cx <= person.box[0] + person.box[2]
                                and person.box[1] <= cy <= person.box[1] + person.box[3]])
        evidence = []
        for index, item in people:
            x, y, w, h = item.box
            crop = frame[max(0, int(y * height)):max(1, int((y + h) * height)),
                         max(0, int(x * width)):max(1, int((x + w) * width))]
            histogram = cv2.calcHist([cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)], [0, 1], None, [16, 8], [0, 180, 0, 256]).reshape(-1)
            histogram = histogram / max(1, float(histogram.sum()))
            contained = [j for j, members in enumerate(memberships) if index in members]
            feature = faces[contained[0]][1] if len(contained) == 1 and memberships[contained[0]] == [index] else None
            evidence.append(PersonEvidence(index, item.box, histogram, feature, bool(contained)))
        return recognition, evidence

    def finalize_frame(self, result, source, counter, received_at):
        """Commit only after the camera owner accepts freshness and generation."""
        recognition, evidence = result
        with self.gallery.lock:
            evidence = [replace(item, face=self.gallery.match(item.face) if item.face is not None else None) for item in evidence]
            identities = self.tracker.update((*source, self.gallery.revision), counter, received_at, evidence)
        objects = tuple(replace(item, identity=identities.get(index)) for index, item in enumerate(recognition.objects))
        model_hash = hashlib.sha256((recognition.model + self.faces.model_hash + self.faces.detector_hash).encode()).hexdigest()
        return replace(recognition, backend="ultralytics+sface", model="person-identity@" + model_hash, objects=objects,
            summary=f"{len(evidence)} people; {sum(i['state'] == 'face_match' for i in identities.values())} enrolled face matches.",
            uncertainties=("Face matches are estimates, not verified identity or liveness.",
                "Tracked names use short box/color continuity; crossings, similar clothing and occlusion can defeat association.",
                "No distance, obstacle avoidance or motion completion is established."))

    def enroll(self, payload):
        name = self.gallery._name(payload.get("name"))
        try:
            jpeg = base64.b64decode(payload.get("jpeg", ""), validate=True)
        except (ValueError, TypeError) as error:
            raise ValueError("Photo must be a base64 JPEG") from error
        faces = self.faces.faces(decode_jpeg(jpeg))
        if len(faces) != 1:
            raise ValueError("Use a clear photo containing exactly one detectable face")
        self.gallery.add(name, faces[0][1])
        return {"ok": True, "people": self.gallery.list()}

    def status(self):
        return {"configured": True, "people": self.gallery.list(), "model": "SFace 2021dec",
                "modelHash": self.faces.model_hash, "detectorHash": self.faces.detector_hash,
                "matchThreshold": FACE_THRESHOLD, "matchMargin": FACE_MARGIN,
                "trackGapMs": TRACK_GAP_S * 1000, "faceMemoryMs": FACE_MEMORY_S * 1000}
