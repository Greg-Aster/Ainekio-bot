"""Optional offline detector adapter for the existing camera recognition owner."""
from __future__ import annotations

import hashlib
import base64
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from protocol.binary_helpers import MAX_JPEG_BYTES
from .perception import MAX_OBJECTS, RecognitionResult, parse_recognition


class YoloBackend:
    """Explicit local weights only; no model-name resolution or download fallback.

    Ultralytics is an optional dependency in the selected Python environment.
    Segmentation models supply their detected boxes; masks are not distance data.
    CameraFramePlugin owns serialization, buffering and freshness.
    """

    def __init__(self, weights: str, *, device: str = "cpu", image_size: int = 640,
                 confidence: float = 0.25, tracker: str | None = None,
                 text_encoder: str | None = None) -> None:
        path = Path(weights).expanduser().resolve(strict=True)
        if not path.is_file() or path.suffix != ".pt":
            raise ValueError("YOLO requires an existing local .pt weights file")
        if type(image_size) is not int or not 32 <= image_size <= 2048 or image_size % 32:
            raise ValueError("YOLO image size must be a multiple of 32 between 32 and 2048")
        if type(confidence) not in (int, float) or not 0 <= confidence <= 1:
            raise ValueError("YOLO confidence must be between 0 and 1")
        from ultralytics import YOLO
        self.detector = YOLO(str(path))
        self._weights = str(path)
        self._text_encoder = None
        self._query_id = None
        self._vision_target = None
        if self.detector.task not in {"detect", "segment"}:
            raise ValueError("YOLO recognition requires detection or segmentation weights")
        self.device, self.image_size, self.confidence = device, image_size, confidence
        self.classes = dict(self.detector.names)
        if text_encoder:
            encoder_path = Path(text_encoder).expanduser().resolve(strict=True)
            import clip
            from ultralytics.nn.text_model import MobileCLIPTS
            from ultralytics.utils.torch_utils import select_device
            self._text_encoder = MobileCLIPTS(select_device(device), str(encoder_path))
        self._tracker = None
        self._track_source = None
        self._track_namespace = None
        if tracker:
            # Explicit optional dependency: fail at configuration, rather than
            # allowing Ultralytics to install a package during camera inference.
            import lap
            from ultralytics.trackers.byte_tracker import BYTETracker
            from ultralytics.utils import YAML, IterableSimpleNamespace
            from ultralytics.utils.checks import check_yaml
            self._tracker = BYTETracker(IterableSimpleNamespace(**YAML.load(check_yaml(tracker))))
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        self.model = f"{path.name}@{digest}"

    @property
    def tracking_enabled(self) -> bool:
        return self._tracker is not None

    def vision_operations(self) -> list[str]:
        return ["release", *(["search"] if hasattr(self.detector, "set_classes") and self._text_encoder is not None else []),
                *(["select"] if hasattr(self.detector, "get_visual_pe") else [])]

    def vision_target(self):
        return self._vision_target

    def configure_vision(self, request: dict[str, object]) -> dict[str, object]:
        """Called on the camera's single inference executor, never robot receive."""
        from ultralytics import YOLO
        # Build the requested configuration before committing it. A failed
        # prompt must not leave half-updated class names on the active model.
        detector = YOLO(self._weights)
        operation = request["operation"]
        if operation == "release":
            classes = dict(detector.names)
            query_id = None
        elif operation == "search":
            if not hasattr(detector, "set_classes") or self._text_encoder is None:
                raise ValueError("Text search requires prompted YOLOE weights and a configured local text encoder")
            labels = request["labels"]
            detector.to(self._text_encoder.device)
            detector.model.clip_model = self._text_encoder
            embeddings = detector.model.get_text_pe(labels, cache_clip_model=True)
            detector.set_classes(labels, embeddings)
            classes = dict(detector.names)
            query_id = str(request["requestId"])
        elif operation == "select":
            if not hasattr(detector, "get_visual_pe"):
                raise ValueError("Visual selection requires prompted YOLOE weights")
            import cv2
            import numpy as np
            from ultralytics.models.yolo.yoloe import YOLOEVPDetectPredictor, YOLOEVPSegPredictor
            frame = request["frame"]
            jpeg = base64.b64decode(frame["dataUrl"].split(",", 1)[1], validate=True)
            reference = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
            if reference is None:
                raise ValueError("Selected reference image cannot be decoded")
            height, width = reference.shape[:2]
            box = request["box"]
            x, y, w, h = (box[key] for key in ("x", "y", "width", "height"))
            detector.predict(reference, refer_image=reference,
                predictor=YOLOEVPSegPredictor if detector.task == "segment" else YOLOEVPDetectPredictor,
                visual_prompts={"bboxes": np.asarray([[x * width, y * height, (x + w) * width, (y + h) * height]]), "cls": np.asarray([0])},
                device=self.device, imgsz=self.image_size, conf=self.confidence,
                max_det=MAX_OBJECTS, verbose=False, save=False)
            classes = {0: request["description"]}
            query_id = str(request["requestId"])
        else:
            raise ValueError(f"Unsupported vision operation: {operation}")
        self.detector, self.classes, self._query_id = detector, classes, query_id
        self._track_source = None
        receipt = {"operation": operation, "queryId": self._query_id,
            "classes": list(self.classes.values()), "tracking": self.tracking_enabled,
            **({"referenceFrameId": request["frame"]["id"]} if operation == "select" else {})}
        self._vision_target = receipt if operation != "release" else None
        return receipt

    def finalize_frame(self, result: RecognitionResult, source, counter, received_at) -> RecognitionResult:
        """Associate only frames accepted by the existing camera owner.

        Keep every detection, including those without a confirmed track. IDs
        estimate image continuity; they do not prove physical or named identity.
        """
        if self._tracker is None:
            return result
        import numpy as np
        from ultralytics.engine.results import Boxes
        if source != self._track_source:
            self._tracker.reset()
            self._track_source = source
            self._track_namespace = uuid4().hex
        # ByteTrack's geometric calculations are scale-independent. Use a
        # consistent unit square, rather than changing scale with image size.
        rows, indices = [], []
        labels = {label: index for index, label in self.classes.items()}
        for index, item in enumerate(result.objects):
            if item.box is not None and item.score is not None:
                x, y, width, height = item.box
                rows.append([x, y, x + width, y + height, item.score, labels[item.label]])
                indices.append(index)
        boxes = Boxes(np.asarray(rows, dtype=np.float32).reshape(-1, 6), (1, 1))
        tracks = self._tracker.update(boxes)
        ids = {indices[int(track[-1])]: f"{self._track_namespace}:{int(track[4])}" for track in tracks}
        return replace(result, objects=tuple(replace(item, track_id=ids.get(index))
            for index, item in enumerate(result.objects)))

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
        return replace(parse_recognition({"summary": f"{len(objects)} class detections in this frame.",
            "objects": objects,
            "uncertainties": ["Class detections do not establish personal identity, distance, walkability or obstacle avoidance."]},
            backend="ultralytics", model=self.model), query_id=self._query_id)
