"""Commercial-clean Apache-2.0 / MIT offline detector and open-vocabulary vision adapter."""
from __future__ import annotations

import base64
from dataclasses import dataclass, replace
import hashlib
import json
import math
import os
from pathlib import Path
from uuid import uuid4

from protocol.binary_helpers import MAX_JPEG_BYTES
from .perception import MAX_OBJECTS, RecognitionResult, parse_recognition


def _iou_matrix(boxes_a, boxes_b):
    """Compute pairwise IoU between [N, 4] and [M, 4] xyxy arrays."""
    import numpy as np
    if len(boxes_a) == 0 or len(boxes_b) == 0:
        return np.zeros((len(boxes_a), len(boxes_b)), dtype=np.float32)
    ax1, ay1, ax2, ay2 = boxes_a[:, 0:1], boxes_a[:, 1:2], boxes_a[:, 2:3], boxes_a[:, 3:4]
    bx1, by1, bx2, by2 = boxes_b[:, 0], boxes_b[:, 1], boxes_b[:, 2], boxes_b[:, 3]
    ix1 = np.maximum(ax1, bx1)
    iy1 = np.maximum(ay1, by1)
    ix2 = np.minimum(ax2, bx2)
    iy2 = np.minimum(ay2, by2)
    inter = np.maximum(0.0, ix2 - ix1) * np.maximum(0.0, iy2 - iy1)
    area_a = np.maximum(0.0, ax2 - ax1) * np.maximum(0.0, ay2 - ay1)
    area_b = np.maximum(0.0, bx2 - bx1) * np.maximum(0.0, by2 - by1)
    union = area_a + area_b - inter
    return np.where(union > 1e-8, inter / union, 0.0).astype(np.float32)


def _nms_class_aware(objects: list[dict[str, object]], iou_threshold: float) -> list[dict[str, object]]:
    """Suppress duplicate overlapping detections of the same class (expects score-descending input)."""
    import numpy as np

    if len(objects) <= 1:
        return objects
    kept: list[dict[str, object]] = []
    kept_xyxy_by_label: dict[str, list[list[float]]] = {}
    for item in objects:
        label = str(item["label"])
        b = item["box"]
        cand = [float(b["x"]), float(b["y"]), float(b["x"]) + float(b["width"]), float(b["y"]) + float(b["height"])]
        prior = kept_xyxy_by_label.get(label)
        if prior:
            cand_arr = np.asarray([cand], dtype=np.float32)
            prior_arr = np.asarray(prior, dtype=np.float32)
            ious = _iou_matrix(cand_arr, prior_arr)[0]
            ix1 = np.maximum(cand_arr[:, 0:1], prior_arr[:, 0])
            iy1 = np.maximum(cand_arr[:, 1:2], prior_arr[:, 1])
            ix2 = np.minimum(cand_arr[:, 2:3], prior_arr[:, 2])
            iy2 = np.minimum(cand_arr[:, 3:4], prior_arr[:, 3])
            inter = np.maximum(0.0, ix2 - ix1) * np.maximum(0.0, iy2 - iy1)
            area_c = max(1e-8, (cand[2] - cand[0]) * (cand[3] - cand[1]))
            area_p = np.maximum(1e-8, (prior_arr[:, 2] - prior_arr[:, 0]) * (prior_arr[:, 3] - prior_arr[:, 1]))
            containment = (inter[0] / np.minimum(area_c, area_p))
            if float(np.max(ious)) >= iou_threshold or float(np.max(containment)) >= 0.70:
                continue
            prior.append(cand)
        else:
            kept_xyxy_by_label[label] = [cand]
        kept.append(item)
    return kept


def _assign_pairs(cost_matrix, max_cost: float) -> list[tuple[int, int]]:
    """Minimum-cost bipartite assignment using SciPy when available or greedy fallback."""
    import numpy as np
    if cost_matrix.size == 0:
        return []
    try:
        from scipy.optimize import linear_sum_assignment
        rows, cols = linear_sum_assignment(cost_matrix)
        return [(int(r), int(c)) for r, c in zip(rows, cols) if float(cost_matrix[r, c]) <= max_cost]
    except ImportError:
        pairs = []
        used_r, used_c = set(), set()
        flat = np.argsort(cost_matrix, axis=None)
        n_cols = cost_matrix.shape[1]
        for idx in flat:
            r, c = divmod(int(idx), n_cols)
            if float(cost_matrix[r, c]) > max_cost:
                break
            if r not in used_r and c not in used_c:
                used_r.add(r)
                used_c.add(c)
                pairs.append((r, c))
        return pairs


@dataclass
class _TrackState:
    track_id: int
    label: str
    box_xyxy: tuple[float, float, float, float]
    velocity_xy: tuple[float, float] = (0.0, 0.0)
    hits: int = 1
    lost_frames: int = 0

    def predicted_xyxy(self) -> tuple[float, float, float, float]:
        x1, y1, x2, y2 = self.box_xyxy
        vx, vy = self.velocity_xy
        return (x1 + vx, y1 + vy, x2 + vx, y2 + vy)


class BoxTracker:
    """Two-stage IoU + velocity continuity tracker with zero copyleft dependencies."""

    def __init__(
        self,
        *,
        high_thresh: float = 0.5,
        low_thresh: float = 0.1,
        new_thresh: float = 0.5,
        match_iou: float = 0.25,
        max_lost: int = 30,
        min_hits: int = 1,
    ) -> None:
        if not (0.0 <= low_thresh <= high_thresh <= 1.0 and 0.0 <= new_thresh <= 1.0 and 0.0 < match_iou <= 1.0):
            raise ValueError("Tracker thresholds must be valid unit-interval values")
        if type(max_lost) is not int or max_lost < 1 or type(min_hits) is not int or min_hits < 1:
            raise ValueError("Tracker frame budgets must be positive integers")
        self.high_thresh = float(high_thresh)
        self.low_thresh = float(low_thresh)
        self.new_thresh = float(new_thresh)
        self.match_iou = float(match_iou)
        self.max_lost = max_lost
        self.min_hits = min_hits
        self.reset()

    @classmethod
    def from_config(cls, spec: str) -> "BoxTracker":
        name = spec.strip()
        if not name:
            raise ValueError("Tracker configuration must not be empty")
        if name.lower() in {"iou", "default", "kalman"}:
            return cls()
        cfg_path = Path(name).expanduser().resolve(strict=True)
        if cfg_path.suffix.lower() != ".json":
            raise ValueError("Custom tracker configuration must be 'iou' or a local .json file")
        data = json.loads(cfg_path.read_text())
        if not isinstance(data, dict):
            raise ValueError("Tracker JSON configuration must be an object")
        allowed = {"high_thresh", "low_thresh", "new_thresh", "match_iou", "max_lost", "min_hits"}
        unknown = set(data) - allowed
        if unknown:
            raise ValueError(f"Unsupported tracker configuration keys: {sorted(unknown)}")
        return cls(**data)

    def reset(self) -> None:
        self._tracks: list[_TrackState] = []
        self._next_id = 1

    def update(self, detections: list[tuple[int, str, float, tuple[float, float, float, float]]]) -> dict[int, int]:
        """Update tracks from [(obj_index, label, score, (x1, y1, x2, y2)), ...] and map obj_index -> track_id."""
        import numpy as np

        for trk in self._tracks:
            trk.lost_frames += 1

        high_dets = [d for d in detections if d[2] >= self.high_thresh]
        low_dets = [d for d in detections if self.low_thresh <= d[2] < self.high_thresh]

        assigned: dict[int, int] = {}
        unmatched_tracks = list(range(len(self._tracks)))

        def _associate(track_indices: list[int], det_list: list[tuple[int, str, float, tuple[float, float, float, float]]]):
            if not track_indices or not det_list:
                return track_indices, list(range(len(det_list)))
            pred_boxes = np.asarray([self._tracks[ti].predicted_xyxy() for ti in track_indices], dtype=np.float32)
            det_boxes = np.asarray([d[3] for d in det_list], dtype=np.float32)
            ious = _iou_matrix(pred_boxes, det_boxes)
            cost = 1.0 - ious
            for r, ti in enumerate(track_indices):
                for c, det in enumerate(det_list):
                    if self._tracks[ti].label != det[1]:
                        cost[r, c] = 2.0
            matches = _assign_pairs(cost, 1.0 - self.match_iou)
            matched_r = {r for r, _ in matches}
            matched_c = {c for _, c in matches}
            for r, c in matches:
                trk = self._tracks[track_indices[r]]
                obj_idx, _, _, new_box = det_list[c]
                old_cx = 0.5 * (trk.box_xyxy[0] + trk.box_xyxy[2])
                old_cy = 0.5 * (trk.box_xyxy[1] + trk.box_xyxy[3])
                new_cx = 0.5 * (new_box[0] + new_box[2])
                new_cy = 0.5 * (new_box[1] + new_box[3])
                dt = max(1, trk.lost_frames)
                vx = 0.5 * trk.velocity_xy[0] + 0.5 * ((new_cx - old_cx) / dt)
                vy = 0.5 * trk.velocity_xy[1] + 0.5 * ((new_cy - old_cy) / dt)
                trk.box_xyxy = new_box
                trk.velocity_xy = (vx, vy)
                trk.hits += 1
                trk.lost_frames = 0
                if trk.hits >= self.min_hits:
                    assigned[obj_idx] = trk.track_id
            rem_tracks = [ti for idx, ti in enumerate(track_indices) if idx not in matched_r]
            rem_dets = [idx for idx in range(len(det_list)) if idx not in matched_c]
            return rem_tracks, rem_dets

        unmatched_tracks, unmatched_high = _associate(unmatched_tracks, high_dets)
        unmatched_tracks, _ = _associate(unmatched_tracks, low_dets)

        for idx in unmatched_high:
            obj_idx, label, score, box = high_dets[idx]
            if score >= self.new_thresh:
                tid = self._next_id
                self._next_id += 1
                trk = _TrackState(track_id=tid, label=label, box_xyxy=box, hits=1, lost_frames=0)
                self._tracks.append(trk)
                if trk.hits >= self.min_hits:
                    assigned[obj_idx] = tid

        self._tracks = [t for t in self._tracks if t.lost_frames <= self.max_lost]
        return assigned


def _hash_path(path: Path) -> str:
    if path.is_file():
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    digest = hashlib.sha256()
    for child in sorted(p for p in path.rglob("*") if p.is_file()):
        digest.update(str(child.relative_to(path)).encode("utf-8"))
        with child.open("rb") as stream:
            digest.update(hashlib.file_digest(stream, "sha256").digest())
    return digest.hexdigest()


class DetectorBackend:
    """Explicit local Apache-2.0 / MIT detector; no model-name resolution or download fallback.

    Default continuous detection runs RT-DETRv2 via ONNX Runtime (.onnx + .json metadata)
    or a local RT-DETRv2 directory. Optional open-vocabulary text search and one-shot
    visual region selection run via a local Apache-2.0 OWLv2 directory.
    CameraFramePlugin owns serialization, buffering and freshness.
    """

    def __init__(
        self,
        weights: str,
        *,
        device: str = "cpu",
        image_size: int = 640,
        confidence: float = 0.40,
        search_confidence: float = 0.12,
        select_confidence: float = 0.92,
        tracker: str | None = None,
        open_vocab_model: str | None = None,
    ) -> None:
        path = Path(weights).expanduser().resolve(strict=True)
        if type(image_size) is not int or not 32 <= image_size <= 2048 or image_size % 32:
            raise ValueError("Detector image size must be a multiple of 32 between 32 and 2048")
        for thresh_name, thresh_val in (
            ("confidence", confidence),
            ("search_confidence", search_confidence),
            ("select_confidence", select_confidence),
        ):
            if type(thresh_val) not in (int, float) or not math.isfinite(thresh_val) or not 0 <= thresh_val <= 1:
                raise ValueError(f"Detector {thresh_name} must be between 0 and 1")

        self.device = device
        self.image_size = image_size
        self.confidence = float(confidence)
        self.search_confidence = float(search_confidence)
        self.select_confidence = float(select_confidence)
        self._weights_path = path
        self._onnx_session = None
        self._onnx_meta: dict[str, object] | None = None
        self._hf_detector = None
        self._hf_processor = None

        if path.is_file() and path.suffix.lower() == ".onnx":
            meta_path = path.with_suffix(".json")
            if not meta_path.is_file():
                raise ValueError(f"ONNX detector requires metadata sidecar {meta_path.name}")
            meta = json.loads(meta_path.read_text())
            if not isinstance(meta, dict) or meta.get("schema") != "ainekio-onnx-detector-v1":
                raise ValueError("ONNX detector metadata must declare schema 'ainekio-onnx-detector-v1'")
            fixed_size = meta.get("image_size")
            if fixed_size is not None and int(fixed_size) != image_size:
                raise ValueError(
                    f"ONNX detector {path.name} is compiled for image_size={fixed_size}, not {image_size}"
                )
            raw_classes = meta.get("classes")
            if not isinstance(raw_classes, dict) or not raw_classes:
                raise ValueError("ONNX detector metadata must define non-empty classes")
            import onnxruntime as ort
            options = ort.SessionOptions()
            options.intra_op_num_threads = int(os.environ.get("AINEKIO_VISION_THREADS", "4"))
            options.inter_op_num_threads = 1
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if device.startswith("cuda") else ["CPUExecutionProvider"]
            self._onnx_session = ort.InferenceSession(str(path), sess_options=options, providers=providers)
            self._onnx_meta = meta
            self._base_classes = {int(k): str(v) for k, v in sorted(raw_classes.items(), key=lambda kv: int(kv[0]))}
        elif path.is_dir() and (path / "config.json").is_file():
            from transformers import AutoImageProcessor, AutoModelForObjectDetection
            self._hf_processor = AutoImageProcessor.from_pretrained(str(path), local_files_only=True)
            self._hf_detector = AutoModelForObjectDetection.from_pretrained(str(path), local_files_only=True).to(device).eval()
            self._base_classes = {
                int(k): str(v)
                for k, v in sorted(self._hf_detector.config.id2label.items(), key=lambda kv: int(kv[0]))
            }
        else:
            raise ValueError("Detector requires an existing local .onnx file or HuggingFace detector directory")

        digest = _hash_path(path)
        self._base_model_id = f"{path.name}@{digest}"
        self.model = self._base_model_id
        self.classes = dict(self._base_classes)

        self._open_vocab_processor = None
        self._open_vocab_detector = None
        self._open_vocab_model_id: str | None = None
        if open_vocab_model:
            ov_path = Path(open_vocab_model).expanduser().resolve(strict=True)
            if not ov_path.is_dir() or not (ov_path / "config.json").is_file():
                raise ValueError("Open-vocabulary vision requires an existing local OWLv2 model directory")
            from transformers import Owlv2ForObjectDetection, Owlv2Processor
            self._open_vocab_processor = Owlv2Processor.from_pretrained(str(ov_path), local_files_only=True)
            self._open_vocab_detector = Owlv2ForObjectDetection.from_pretrained(str(ov_path), local_files_only=True).to(device).eval()
            self._open_vocab_model_id = f"{ov_path.name}@{_hash_path(ov_path)}"

        self._mode = "release"
        self._search_labels: list[str] | None = None
        self._visual_query_crop = None
        self._query_id: str | None = None
        self._vision_target: dict[str, object] | None = None

        self._tracker = BoxTracker.from_config(tracker) if tracker else None
        self._track_source = None
        self._track_namespace: str | None = None

    @property
    def tracking_enabled(self) -> bool:
        return self._tracker is not None

    def vision_operations(self) -> list[str]:
        if self._open_vocab_detector is not None and self._open_vocab_processor is not None:
            return ["release", "search", "select"]
        return ["release"]

    def vision_target(self):
        return self._vision_target

    def configure_vision(self, request: dict[str, object]) -> dict[str, object]:
        """Called on the camera's single inference executor, never robot receive.

        Builds and validates the requested configuration before committing so a
        failed prompt never leaves half-updated class names on the active model.
        """
        operation = request.get("operation")
        if operation == "release":
            next_mode = "release"
            next_classes = dict(self._base_classes)
            next_query_id = None
            next_search_labels = None
            next_visual_crop = None
            next_model_id = self._base_model_id
        elif operation == "search":
            if self._open_vocab_detector is None or self._open_vocab_processor is None:
                raise ValueError("Text search requires a configured local open-vocabulary OWLv2 model")
            raw_labels = request.get("labels")
            if not isinstance(raw_labels, list) or not raw_labels:
                raise ValueError("Text search requires at least one label")
            labels = [str(label).strip() for label in raw_labels if isinstance(label, str) and label.strip()]
            if len(labels) != len(raw_labels):
                raise ValueError("Text search labels must be non-empty strings")
            # Validate tokenization before mutating active state.
            self._open_vocab_processor(text=[labels], return_tensors="pt")
            next_mode = "search"
            next_classes = {index: label for index, label in enumerate(labels)}
            next_query_id = str(request["requestId"])
            next_search_labels = labels
            next_visual_crop = None
            next_model_id = self._open_vocab_model_id or self._base_model_id
        elif operation == "select":
            if self._open_vocab_detector is None or self._open_vocab_processor is None:
                raise ValueError("Visual selection requires a configured local open-vocabulary OWLv2 model")
            import cv2
            import numpy as np
            from PIL import Image
            import torch

            frame_info = request["frame"]
            data_url = str(frame_info["dataUrl"])
            jpeg = base64.b64decode(data_url.split(",", 1)[1], validate=True)
            reference_bgr = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
            if reference_bgr is None:
                raise ValueError("Selected reference image cannot be decoded")
            height, width = reference_bgr.shape[:2]
            box = request["box"]
            bx, by, bw, bh = (float(box[key]) for key in ("x", "y", "width", "height"))
            x1 = max(0, min(width - 1, int(round(bx * width))))
            y1 = max(0, min(height - 1, int(round(by * height))))
            x2 = max(x1 + 1, min(width, int(round((bx + bw) * width))))
            y2 = max(y1 + 1, min(height, int(round((by + bh) * height))))
            reference_rgb = cv2.cvtColor(reference_bgr, cv2.COLOR_BGR2RGB)
            crop_rgb = Image.fromarray(reference_rgb[y1:y2, x1:x2])
            ref_pil = Image.fromarray(reference_rgb)

            # Verify one-shot visual query execution before committing state.
            inputs = self._open_vocab_processor(images=ref_pil, query_images=crop_rgb, return_tensors="pt")
            inputs = {k: v.to(self.device) if hasattr(v, "to") else v for k, v in inputs.items()}
            with torch.no_grad():
                self._open_vocab_detector.image_guided_detection(**inputs)

            description = str(request["description"]).strip()
            if not description:
                raise ValueError("Visual selection requires a non-empty description")
            next_mode = "select"
            next_classes = {0: description}
            next_query_id = str(request["requestId"])
            next_search_labels = None
            next_visual_crop = crop_rgb
            next_model_id = self._open_vocab_model_id or self._base_model_id
        else:
            raise ValueError(f"Unsupported vision operation: {operation}")

        self._mode = next_mode
        self.classes = next_classes
        self._query_id = next_query_id
        self._search_labels = next_search_labels
        self._visual_query_crop = next_visual_crop
        self.model = next_model_id
        self._track_source = None
        if self._tracker is not None:
            self._tracker.reset()

        receipt: dict[str, object] = {
            "operation": operation,
            "queryId": self._query_id,
            "classes": list(self.classes.values()),
            "tracking": self.tracking_enabled,
            **({"referenceFrameId": request["frame"]["id"]} if operation == "select" else {}),
        }
        self._vision_target = receipt if operation != "release" else None
        return receipt

    def finalize_frame(self, result: RecognitionResult, source, counter, received_at) -> RecognitionResult:
        """Associate only frames accepted by the existing camera owner.

        Keep every detection, including those without a confirmed track. IDs
        estimate image continuity; they do not prove physical or named identity.
        """
        if self._tracker is None:
            return result
        if source != self._track_source:
            self._tracker.reset()
            self._track_source = source
            self._track_namespace = uuid4().hex

        dets: list[tuple[int, str, float, tuple[float, float, float, float]]] = []
        for index, item in enumerate(result.objects):
            if item.box is not None and item.score is not None:
                x, y, width, height = item.box
                dets.append((index, item.label, float(item.score), (x, y, x + width, y + height)))

        matched = self._tracker.update(dets)
        ids = {obj_idx: f"{self._track_namespace}:{tid}" for obj_idx, tid in matched.items()}
        return replace(
            result,
            objects=tuple(
                replace(item, track_id=ids.get(index))
                for index, item in enumerate(result.objects)
            ),
        )

    def _detect_onnx(self, frame_bgr) -> list[dict[str, object]]:
        import cv2
        import numpy as np

        meta = self._onnx_meta
        assert self._onnx_session is not None and meta is not None
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb, (self.image_size, self.image_size), interpolation=cv2.INTER_LINEAR)
        tensor = resized.astype(np.float32) * float(meta.get("rescale_factor", 1.0 / 255.0))
        if meta.get("do_normalize"):
            mean = np.asarray(meta.get("image_mean", [0.0, 0.0, 0.0]), dtype=np.float32)
            std = np.asarray(meta.get("image_std", [1.0, 1.0, 1.0]), dtype=np.float32)
            tensor = (tensor - mean) / std
        chw = np.transpose(tensor, (2, 0, 1))[None, ...]
        input_name = str(meta.get("input_name") or self._onnx_session.get_inputs()[0].name)
        boxes_xyxy, scores, labels = self._onnx_session.run(None, {input_name: chw})
        boxes_arr = np.asarray(boxes_xyxy[0], dtype=np.float64)
        scores_arr = np.asarray(scores[0], dtype=np.float64)
        labels_arr = np.asarray(labels[0], dtype=np.int64)

        order = np.argsort(-scores_arr)
        objects: list[dict[str, object]] = []
        for idx in order:
            score = float(scores_arr[idx])
            if score < self.confidence:
                break
            x1, y1, x2, y2 = (min(1.0, max(0.0, float(v))) for v in boxes_arr[idx])
            if x2 <= x1 or y2 <= y1:
                continue
            cls_id = int(labels_arr[idx])
            label = self.classes.get(cls_id)
            if not label:
                continue
            objects.append(
                {
                    "label": label,
                    "score": min(1.0, max(0.0, score)),
                    "box": {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1},
                }
            )
        return _nms_class_aware(objects, iou_threshold=0.50)[:MAX_OBJECTS]

    def _detect_hf(self, frame_bgr) -> list[dict[str, object]]:
        import cv2
        from PIL import Image
        import torch

        assert self._hf_detector is not None and self._hf_processor is not None
        height, width = frame_bgr.shape[:2]
        pil = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
        inputs = self._hf_processor(
            images=pil,
            size={"height": self.image_size, "width": self.image_size},
            return_tensors="pt",
        )
        inputs = {k: v.to(self.device) if hasattr(v, "to") else v for k, v in inputs.items()}
        with torch.no_grad():
            outputs = self._hf_detector(**inputs)
        processed = self._hf_processor.post_process_object_detection(
            outputs,
            threshold=self.confidence,
            target_sizes=torch.tensor([[height, width]], device=outputs.logits.device),
        )[0]
        scores = processed["scores"].detach().cpu().tolist()
        labels = processed["labels"].detach().cpu().tolist()
        boxes = processed["boxes"].detach().cpu().tolist()
        ranked = sorted(zip(scores, labels, boxes), key=lambda row: row[0], reverse=True)
        objects: list[dict[str, object]] = []
        for score, cls_id, box in ranked:
            x1 = min(1.0, max(0.0, float(box[0]) / width))
            y1 = min(1.0, max(0.0, float(box[1]) / height))
            x2 = min(1.0, max(0.0, float(box[2]) / width))
            y2 = min(1.0, max(0.0, float(box[3]) / height))
            if x2 <= x1 or y2 <= y1:
                continue
            label = self.classes.get(int(cls_id))
            if not label:
                continue
            objects.append(
                {
                    "label": label,
                    "score": min(1.0, max(0.0, float(score))),
                    "box": {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1},
                }
            )
        return _nms_class_aware(objects, iou_threshold=0.50)[:MAX_OBJECTS]

    def _detect_open_vocab(self, frame_bgr) -> list[dict[str, object]]:
        import cv2
        from PIL import Image
        import torch

        assert self._open_vocab_detector is not None and self._open_vocab_processor is not None
        height, width = frame_bgr.shape[:2]
        pil = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
        target_sizes = torch.tensor([[height, width]])

        if self._mode == "search":
            assert self._search_labels is not None
            inputs = self._open_vocab_processor(text=[self._search_labels], images=pil, return_tensors="pt")
            inputs = {k: v.to(self.device) if hasattr(v, "to") else v for k, v in inputs.items()}
            with torch.no_grad():
                outputs = self._open_vocab_detector(**inputs)
            outputs_cpu = type(outputs)(**{k: v.cpu() if hasattr(v, "cpu") else v for k, v in outputs.items()})
            processed = self._open_vocab_processor.post_process_grounded_object_detection(
                outputs_cpu,
                threshold=self.search_confidence,
                target_sizes=target_sizes,
            )[0]
            scores = processed["scores"].tolist()
            labels = processed["labels"].tolist()
            boxes = processed["boxes"].tolist()
            ranked = sorted(zip(scores, labels, boxes), key=lambda row: row[0], reverse=True)
            objects: list[dict[str, object]] = []
            for score, cls_id, box in ranked:
                x1 = min(1.0, max(0.0, float(box[0]) / width))
                y1 = min(1.0, max(0.0, float(box[1]) / height))
                x2 = min(1.0, max(0.0, float(box[2]) / width))
                y2 = min(1.0, max(0.0, float(box[3]) / height))
                if x2 <= x1 or y2 <= y1:
                    continue
                label = self.classes.get(int(cls_id))
                if not label:
                    continue
                objects.append(
                    {
                        "label": label,
                        "score": min(1.0, max(0.0, float(score))),
                        "box": {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1},
                    }
                )
            return _nms_class_aware(objects, iou_threshold=0.45)[:MAX_OBJECTS]

        assert self._mode == "select" and self._visual_query_crop is not None
        inputs = self._open_vocab_processor(images=pil, query_images=self._visual_query_crop, return_tensors="pt")
        inputs = {k: v.to(self.device) if hasattr(v, "to") else v for k, v in inputs.items()}
        with torch.no_grad():
            outputs = self._open_vocab_detector.image_guided_detection(**inputs)
        outputs_cpu = type(outputs)(**{k: v.cpu() if hasattr(v, "cpu") else v for k, v in outputs.items()})
        processed = self._open_vocab_processor.post_process_image_guided_detection(
            outputs_cpu,
            threshold=self.select_confidence,
            target_sizes=target_sizes,
        )[0]
        scores = processed["scores"].tolist()
        boxes = processed["boxes"].tolist()
        ranked = sorted(zip(scores, boxes), key=lambda row: row[0], reverse=True)
        objects = []
        label = self.classes[0]
        for score, box in ranked:
            x1 = min(1.0, max(0.0, float(box[0]) / width))
            y1 = min(1.0, max(0.0, float(box[1]) / height))
            x2 = min(1.0, max(0.0, float(box[2]) / width))
            y2 = min(1.0, max(0.0, float(box[3]) / height))
            if x2 <= x1 or y2 <= y1:
                continue
            objects.append(
                {
                    "label": label,
                    "score": min(1.0, max(0.0, float(score))),
                    "box": {"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1},
                }
            )
        return _nms_class_aware(objects, iou_threshold=0.45)[:MAX_OBJECTS]

    def __call__(self, jpeg: bytes) -> RecognitionResult:
        if not isinstance(jpeg, bytes) or not 4 <= len(jpeg) <= MAX_JPEG_BYTES or not jpeg.startswith(b"\xff\xd8"):
            raise ValueError("Detector input requires a bounded JPEG")
        import cv2
        import numpy as np

        frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("Detector input is not a decodable JPEG")

        if self._mode in {"search", "select"}:
            objects = self._detect_open_vocab(frame)
            backend_name = "owlv2"
        elif self._onnx_session is not None:
            objects = self._detect_onnx(frame)
            backend_name = "rtdetrv2"
        else:
            objects = self._detect_hf(frame)
            backend_name = "rtdetrv2"

        return replace(
            parse_recognition(
                {
                    "summary": f"{len(objects)} class detections in this frame.",
                    "objects": objects,
                    "uncertainties": [
                        "Class detections do not establish personal identity, distance, walkability or obstacle avoidance."
                    ],
                },
                backend=backend_name,
                model=self.model,
            ),
            query_id=self._query_id,
        )
