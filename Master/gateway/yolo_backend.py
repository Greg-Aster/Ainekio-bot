"""Optional offline detector adapter for the existing camera recognition owner."""
from __future__ import annotations

import hashlib
from pathlib import Path

from protocol.binary_helpers import MAX_JPEG_BYTES
from .perception import MAX_OBJECTS, RecognitionResult, parse_recognition


class YoloBackend:
    """Explicit local weights only; no model-name resolution or download fallback.

    Ultralytics is an optional dependency in the selected Python environment.
    Segmentation models supply their detected boxes; masks are not distance data.
    CameraFramePlugin owns serialization, buffering and freshness.
    """

    def __init__(self, weights: str, *, device: str = "cpu", image_size: int = 640,
                 confidence: float = 0.25) -> None:
        path = Path(weights).expanduser().resolve(strict=True)
        if not path.is_file() or path.suffix != ".pt":
            raise ValueError("YOLO requires an existing local .pt weights file")
        if type(image_size) is not int or not 32 <= image_size <= 2048 or image_size % 32:
            raise ValueError("YOLO image size must be a multiple of 32 between 32 and 2048")
        if type(confidence) not in (int, float) or not 0 <= confidence <= 1:
            raise ValueError("YOLO confidence must be between 0 and 1")
        from ultralytics import YOLO
        self.detector = YOLO(str(path))
        if self.detector.task not in {"detect", "segment"}:
            raise ValueError("YOLO recognition requires detection or segmentation weights")
        self.device, self.image_size, self.confidence = device, image_size, confidence
        self.classes = dict(self.detector.names)
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        self.model = f"{path.name}@{digest}"

    def __call__(self, jpeg: bytes) -> RecognitionResult:
        if not isinstance(jpeg, bytes) or not 4 <= len(jpeg) <= MAX_JPEG_BYTES or not jpeg.startswith(b"\xff\xd8"):
            raise ValueError("YOLO input requires a bounded JPEG")
        import cv2
        import numpy as np
        frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("YOLO input is not a decodable JPEG")
        result = self.detector.predict(frame, device=self.device, imgsz=self.image_size,
            conf=self.confidence, max_det=MAX_OBJECTS, verbose=False, save=False)[0]
        objects = []
        if result.boxes is not None:
            for box, score, label in zip(result.boxes.xyxyn.cpu().tolist(),
                                        result.boxes.conf.cpu().tolist(), result.boxes.cls.cpu().tolist()):
                x1, y1, x2, y2 = (min(1.0, max(0.0, float(value))) for value in box)
                if x2 <= x1 or y2 <= y1:
                    continue
                objects.append({"label": self.classes[int(label)], "score": float(score),
                    "box": {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1}})
        return parse_recognition({"summary": f"{len(objects)} class detections in this frame.",
            "objects": objects,
            "uncertainties": ["Class detections do not establish personal identity, distance, walkability or obstacle avoidance."]},
            backend="ultralytics", model=self.model)
