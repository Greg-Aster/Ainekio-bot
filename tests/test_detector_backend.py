from pathlib import Path
import asyncio
import json
import os
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from gateway.detector_backend import BoxTracker, DetectorBackend


class Tensor:
    def __init__(self, values):
        self.values = np.asarray(values, dtype=np.float32)

    def detach(self):
        return self

    def cpu(self):
        return self

    def to(self, _device):
        return self

    def tolist(self):
        return self.values.tolist()


class DetectorBackendTests(unittest.TestCase):
    def _write_onnx_fixture(self, directory: str, *, image_size: int = 320, classes: dict | None = None) -> Path:
        onnx_path = Path(directory) / "fixture.onnx"
        onnx_path.write_bytes(b"fixture-onnx-bytes")
        meta = {
            "schema": "ainekio-onnx-detector-v1",
            "upstream_repo": "PekingU/rtdetr_v2_r18vd",
            "license": "Apache-2.0",
            "onnx_file": onnx_path.name,
            "image_size": image_size,
            "input_name": "pixel_values",
            "rescale_factor": 1.0 / 255.0,
            "do_normalize": False,
            "classes": classes or {"0": "person", "1": "cup"},
        }
        onnx_path.with_suffix(".json").write_text(json.dumps(meta))
        return onnx_path

    def test_visual_target_description_is_preserved_in_recognition(self):
        from gateway.perception import parse_recognition
        description = "The keys with the distinctive red fabric loop beside the notebook, including the small brass key and the larger silver key"
        result = parse_recognition(
            {"summary": "Selected target", "objects": [{"label": description}], "uncertainties": []},
            backend="owlv2",
            model="fixture",
        )
        self.assertEqual(result.message()["objects"][0]["label"], description)

    def test_text_prompt_uses_local_open_vocab_model_and_preserves_label_order(self):
        processor = Mock(return_value={"input_ids": Tensor([[1, 2]])})
        detector = Mock()
        backend = DetectorBackend.__new__(DetectorBackend)
        backend._base_classes = {0: "person"}
        backend._base_model_id = "rtdetrv2@abc"
        backend._open_vocab_processor = processor
        backend._open_vocab_detector = detector
        backend._open_vocab_model_id = "owlv2@def"
        backend._tracker = BoxTracker()
        backend._track_source = ("robot", 1, 0)
        backend.classes = {0: "person"}
        backend._mode = "release"
        backend._query_id = None
        backend._vision_target = None

        receipt = backend.configure_vision(
            {"operation": "search", "requestId": "keys-and-cup", "labels": ["keys", "cup"]}
        )
        processor.assert_called_once_with(text=[["keys", "cup"]], return_tensors="pt")
        self.assertEqual(receipt["classes"], ["keys", "cup"])
        self.assertEqual(receipt["queryId"], "keys-and-cup")
        self.assertEqual(backend._mode, "search")
        self.assertEqual(backend.model, "owlv2@def")
        self.assertIsNone(backend._track_source)

        released = backend.configure_vision({"operation": "release"})
        self.assertEqual(released["classes"], ["person"])
        self.assertIsNone(released["queryId"])
        self.assertIsNone(backend.vision_target())
        self.assertEqual(backend.model, "rtdetrv2@abc")

        for bogus in (["unknown_direction"], ["unknown_floortopology", "cup"], ["unknown"], ["none"]):
            with self.assertRaisesRegex(ValueError, "concrete visual entity"):
                backend.configure_vision({"operation": "search", "requestId": "bogus", "labels": bogus})
        self.assertEqual(backend._mode, "release")
        self.assertIsNone(backend.vision_target())

    def test_visual_prompt_uses_reference_pixels_and_commits_only_on_success(self):
        processor = Mock(return_value={"pixel_values": Tensor([[[[0.0]]]]), "query_pixel_values": Tensor([[[[0.0]]]])})
        detector = SimpleNamespace(image_guided_detection=Mock(side_effect=RuntimeError("model inference failed")))

        backend = DetectorBackend.__new__(DetectorBackend)
        backend.device = "cpu"
        backend._base_classes = {0: "person"}
        backend._base_model_id = "rtdetrv2@abc"
        backend._open_vocab_processor = processor
        backend._open_vocab_detector = detector
        backend._open_vocab_model_id = "owlv2@def"
        backend._tracker = None
        backend._track_source = ("robot", 1, 0)
        backend.classes = {0: "person"}
        backend._mode = "release"
        backend._query_id = None
        backend._vision_target = None
        backend.model = "rtdetrv2@abc"

        reference = np.zeros((200, 400, 3), dtype=np.uint8)
        request = {
            "operation": "select",
            "requestId": "selected-region",
            "description": "my keys",
            "frame": {"id": "original-frame", "dataUrl": "data:image/jpeg;base64,/9j/2Q=="},
            "box": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4},
        }
        import contextlib
        fake_cv2 = SimpleNamespace(
            imdecode=Mock(return_value=reference),
            cvtColor=Mock(side_effect=lambda arr, _code: arr),
            IMREAD_COLOR=1,
            COLOR_BGR2RGB=4,
        )
        fake_torch = SimpleNamespace(no_grad=contextlib.nullcontext)
        with patch.dict("sys.modules", {"cv2": fake_cv2, "torch": fake_torch}):
            with self.assertRaisesRegex(RuntimeError, "model inference failed"):
                backend.configure_vision(request)
            self.assertEqual(backend._mode, "release")
            self.assertEqual(backend.classes, {0: "person"})
            self.assertIsNone(backend._query_id)
            self.assertEqual(backend._track_source, ("robot", 1, 0))

            detector.image_guided_detection.side_effect = None
            detector.image_guided_detection.return_value = SimpleNamespace()
            receipt = backend.configure_vision(request)

        call_kwargs = processor.call_args.kwargs
        self.assertEqual(call_kwargs["images"].size, (400, 200))
        self.assertEqual(call_kwargs["query_images"].size, (120, 80))
        self.assertEqual(receipt["referenceFrameId"], "original-frame")
        self.assertEqual(receipt["queryId"], "selected-region")
        self.assertEqual(backend.classes, {0: "my keys"})
        self.assertEqual(backend._mode, "select")
        self.assertIsNone(backend._track_source)

    def test_tracking_keeps_unmatched_detections_and_scopes_ids_to_camera_generation(self):
        from gateway.perception import RecognitionResult, RecognizedObject, parse_recognition

        backend = DetectorBackend.__new__(DetectorBackend)
        backend.classes = {0: "keys", 1: "cup"}
        backend._track_source = backend._track_namespace = None
        backend._tracker = BoxTracker(high_thresh=0.5, low_thresh=0.1, new_thresh=0.5, match_iou=0.25)

        result = RecognitionResult(
            "rtdetrv2",
            "fixture",
            "",
            (
                RecognizedObject("keys", 0.8, (0.1, 0.2, 0.3, 0.4)),
                RecognizedObject("cup", 0.2, (0.5, 0.5, 0.1, 0.1)),
            ),
            (),
        )
        first = backend.finalize_frame(result, ("robot", 1, 0), 10, 1.0)
        second = backend.finalize_frame(result, ("robot", 1, 0), 11, 1.1)
        self.assertIsNotNone(first.objects[0].track_id)
        self.assertEqual(first.objects[0].track_id, second.objects[0].track_id)
        self.assertEqual(len(first.objects), 2, "tracker confirmation cannot discard a detection")
        self.assertIsNone(first.objects[1].track_id, "low-confidence unseeded detection stays untracked")
        self.assertIsNone(first.objects[0].identity, "continuity cannot invent personal identity")

        message = first.message()
        roundtrip = parse_recognition(
            {key: message[key] for key in ("summary", "objects", "uncertainties")},
            backend="rtdetrv2",
            model="fixture",
        )
        self.assertEqual(roundtrip.objects[0].track_id, first.objects[0].track_id)

        third = backend.finalize_frame(result, ("robot", 2, 0), 1, 1.2)
        self.assertNotEqual(first.objects[0].track_id, third.objects[0].track_id)
        fourth = backend.finalize_frame(result, ("robot", 2, 2), 2, 1.3)
        self.assertNotEqual(third.objects[0].track_id, fourth.objects[0].track_id)

        empty = backend.finalize_frame(
            RecognitionResult("rtdetrv2", "fixture", "", (), ()),
            ("robot", 2, 2),
            3,
            1.4,
        )
        self.assertEqual(empty.objects, (), "absent tracks cannot be emitted as detections")

    def test_saved_detector_configuration_survives_launcher_restart_and_cli_can_override(self):
        from gateway.server.__main__ import _parser
        with patch.dict(
            os.environ,
            {
                "AINEKIO_VISION_DETECTOR_WEIGHTS": "/local/rtdetrv2_320.onnx",
                "AINEKIO_VISION_DETECTOR_DEVICE": "cpu",
                "AINEKIO_VISION_OPEN_VOCAB_DEVICE": "cuda",
                "AINEKIO_VISION_DETECTOR_IMAGE_SIZE": "320",
                "AINEKIO_VISION_DETECTOR_TRACKER": "iou",
                "AINEKIO_VISION_OPEN_VOCAB_MODEL": "/local/owlv2",
                "AINEKIO_VISION_MAX_FRAME_AGE_S": "2.5",
            },
        ):
            args = _parser().parse_args([])
            self.assertEqual(args.vision_detector_weights, "/local/rtdetrv2_320.onnx")
            self.assertEqual(args.vision_detector_device, "cpu")
            self.assertEqual(args.vision_open_vocab_device, "cuda")
            self.assertEqual(args.vision_detector_image_size, 320)
            self.assertEqual(args.vision_detector_tracker, "iou")
            self.assertEqual(args.vision_open_vocab_model, "/local/owlv2")
            self.assertEqual(args.vision_max_frame_age_s, 2.5)
            self.assertEqual(_parser().parse_args(["--vision-detector-image-size", "640"]).vision_detector_image_size, 640)

    def test_gateway_rejects_ambiguous_backend_selection_before_startup(self):
        from gateway.server.__main__ import _run_production
        args = SimpleNamespace(
            vision_detector_weights="/explicit/local.onnx",
            vision_url="http://127.0.0.1:8080/v1/chat/completions",
            vision_model="existing-model",
        )
        with self.assertRaisesRegex(ValueError, "not both"):
            asyncio.run(_run_production(args))

    def test_local_weights_and_input_validation_precede_inference(self):
        with self.assertRaises(FileNotFoundError):
            DetectorBackend("/nonexistent/explicitly-selected-weights.onnx")
        with TemporaryDirectory() as directory:
            onnx_path = self._write_onnx_fixture(directory, image_size=320)
            with self.assertRaises(ValueError):
                DetectorBackend(str(onnx_path), image_size=321)
            with self.assertRaises(ValueError):
                DetectorBackend(str(onnx_path), image_size=320, confidence=float("nan"))
            with self.assertRaisesRegex(ValueError, "image_size=320"):
                DetectorBackend(str(onnx_path), image_size=640)

    def test_onnx_detector_classes_and_boxes_use_existing_recognition_contract(self):
        session = SimpleNamespace(
            get_inputs=lambda: [SimpleNamespace(name="pixel_values")],
            run=Mock(
                return_value=[
                    np.asarray(
                        [[[-0.01, 0.2, 0.3, 0.8], [-0.01, 0.21, 0.29, 0.79], [0.4, 0.4, 0.4, 0.5]]],
                        dtype=np.float32,
                    ),
                    np.asarray([[0.8, 0.75, 0.7]], dtype=np.float32),
                    np.asarray([[0, 0, 0]], dtype=np.int64),
                ]
            ),
        )
        fake_ort = SimpleNamespace(
            SessionOptions=lambda: SimpleNamespace(intra_op_num_threads=1, inter_op_num_threads=1),
            InferenceSession=Mock(return_value=session),
        )
        decoded = np.zeros((240, 320, 3), dtype=np.uint8)
        fake_cv2 = SimpleNamespace(
            imdecode=Mock(return_value=decoded),
            cvtColor=Mock(side_effect=lambda arr, _code: arr),
            resize=Mock(side_effect=lambda _arr, size, interpolation=None: np.zeros((size[1], size[0], 3), dtype=np.uint8)),
            IMREAD_COLOR=1,
            COLOR_BGR2RGB=4,
            INTER_LINEAR=1,
        )
        with TemporaryDirectory() as directory, patch.dict("sys.modules", {"onnxruntime": fake_ort, "cv2": fake_cv2}):
            weights = self._write_onnx_fixture(directory, image_size=320, classes={"0": "person"})
            backend = DetectorBackend(str(weights), image_size=320)
            result = backend(b"\xff\xd8\xff\xd9")
            self.assertEqual(backend.classes, {0: "person"})
            self.assertEqual(result.backend, "rtdetrv2")
            self.assertEqual(len(result.objects), 1, "NMS suppresses duplicate overlapping DETR query")
            self.assertEqual(result.objects[0].label, "person")
            self.assertAlmostEqual(result.objects[0].box[0], 0.0)
            self.assertAlmostEqual(result.objects[0].box[1], 0.2)
            self.assertAlmostEqual(result.objects[0].box[2], 0.3)
            self.assertAlmostEqual(result.objects[0].box[3], 0.6)
            self.assertAlmostEqual(result.objects[0].score, 0.8)
            self.assertIn("fixture.onnx@", result.model)
            self.assertNotIn("identity", result.message()["objects"][0])

            fake_cv2.imdecode.return_value = None
            with self.assertRaisesRegex(ValueError, "decodable"):
                backend(b"\xff\xd8\xff\xd9")
            with self.assertRaisesRegex(ValueError, "bounded JPEG"):
                backend(b"not an image")

    def test_exported_local_rtdetrv2_onnx_executes_when_present(self):
        real_onnx = Path(__file__).resolve().parents[1] / "build/models/vision/rtdetrv2_r18vd_640.onnx"
        if not real_onnx.is_file():
            self.skipTest("Local RT-DETRv2 ONNX artifact not installed")
        try:
            import cv2
            import onnxruntime  # noqa: F401
        except ImportError:
            self.skipTest("cv2 and onnxruntime required for live ONNX check")
        backend = DetectorBackend(str(real_onnx), device="cpu", image_size=640, tracker="iou")
        self.assertEqual(backend.classes[0], "person")
        ok, encoded = cv2.imencode(".jpg", np.zeros((480, 640, 3), dtype=np.uint8))
        self.assertTrue(ok)
        result = backend(encoded.tobytes())
        self.assertEqual(result.backend, "rtdetrv2")
        self.assertIn("rtdetrv2_r18vd_640.onnx@", result.model)


if __name__ == "__main__":
    unittest.main()
