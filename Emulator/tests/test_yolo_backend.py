from pathlib import Path
import asyncio
import os
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from gateway.yolo_backend import YoloBackend


class Tensor:
    def __init__(self, values):
        self.values = values

    def cpu(self):
        return self

    def tolist(self):
        return self.values


class YoloBackendTests(unittest.TestCase):
    def test_visual_target_description_is_preserved_in_recognition(self):
        from gateway.perception import parse_recognition
        description = "The keys with the distinctive red fabric loop beside the notebook, including the small brass key and the larger silver key"
        result = parse_recognition({"summary": "Selected target", "objects": [{"label": description}],
            "uncertainties": []}, backend="fixture", model="fixture")
        self.assertEqual(result.message()["objects"][0]["label"], description)

    def test_text_prompt_uses_explicit_local_encoder_and_preserves_detector_class_order(self):
        encoder = SimpleNamespace(device="cpu")
        embeddings = object()
        detector = SimpleNamespace(to=Mock(), names={0: "cup", 1: "keys"},
            model=SimpleNamespace(get_text_pe=Mock(return_value=embeddings)), set_classes=Mock())
        backend = YoloBackend.__new__(YoloBackend)
        backend._weights, backend._text_encoder, backend._tracker = "/fixture/yoloe.pt", encoder, None
        with patch.dict("sys.modules", {"ultralytics": SimpleNamespace(YOLO=Mock(return_value=detector))}):
            receipt = backend.configure_vision({"operation": "search", "requestId": "keys-and-cup", "labels": ["keys", "cup"]})
        self.assertIs(detector.model.clip_model, encoder)
        detector.model.get_text_pe.assert_called_once_with(["keys", "cup"], cache_clip_model=True)
        detector.set_classes.assert_called_once_with(["keys", "cup"], embeddings)
        self.assertEqual(receipt["classes"], ["cup", "keys"])
        self.assertEqual(receipt["queryId"], "keys-and-cup")

    def test_visual_prompt_uses_its_reference_pixels_and_commits_only_on_success(self):
        import numpy as np
        previous = object()
        detector = SimpleNamespace(task="segment", get_visual_pe=Mock(), predict=Mock())
        backend = YoloBackend.__new__(YoloBackend)
        backend.detector, backend._weights = previous, "/fixture/yoloe.pt"
        backend._tracker = None
        backend._track_source = ("robot", 1, 0)
        backend.classes, backend._query_id = {0: "person"}, None
        backend.device, backend.image_size, backend.confidence = "cpu", 320, .25
        reference = np.zeros((200, 400, 3), dtype=np.uint8)
        request = {"operation": "select", "requestId": "selected-region", "description": "my keys",
            "frame": {"id": "original-frame", "dataUrl": "data:image/jpeg;base64,/9j/2Q=="},
            "box": {"x": .1, "y": .2, "width": .3, "height": .4}}
        with patch.dict("sys.modules", {"ultralytics": SimpleNamespace(YOLO=Mock(return_value=detector)),
                "ultralytics.models.yolo.yoloe": SimpleNamespace(YOLOEVPSegPredictor="segmentation", YOLOEVPDetectPredictor="detection"),
                "cv2": SimpleNamespace(imdecode=Mock(return_value=reference), IMREAD_COLOR=1)}):
            detector.predict.side_effect = RuntimeError("model inference failed")
            with self.assertRaisesRegex(RuntimeError, "model inference failed"):
                backend.configure_vision(request)
            self.assertIs(backend.detector, previous)
            self.assertEqual(backend.classes, {0: "person"})
            self.assertIsNone(backend._query_id)
            detector.predict.side_effect = None
            receipt = backend.configure_vision(request)
        args = detector.predict.call_args
        self.assertIs(args.args[0], reference)
        self.assertIs(args.kwargs["refer_image"], reference)
        self.assertEqual(args.kwargs["predictor"], "segmentation")
        np.testing.assert_allclose(args.kwargs["visual_prompts"]["bboxes"], [[40, 40, 160, 120]])
        self.assertEqual(receipt["referenceFrameId"], "original-frame")
        self.assertEqual(receipt["queryId"], "selected-region")
        self.assertEqual(backend.classes, {0: "my keys"})
        self.assertIsNone(backend._track_source)

    def test_tracking_keeps_unmatched_detections_and_scopes_ids_to_camera_generation(self):
        from gateway.perception import RecognitionResult, RecognizedObject, parse_recognition
        backend = YoloBackend.__new__(YoloBackend)
        backend.classes = {0: "keys", 1: "cup"}
        backend._track_source = backend._track_namespace = None
        backend._tracker = Mock()
        backend._tracker.update.return_value = [[.1, .2, .4, .6, 7, .8, 0, 0]]
        result = RecognitionResult("fixture", "fixture", "", (
            RecognizedObject("keys", .8, (.1, .2, .3, .4)),
            RecognizedObject("cup", .2, (.5, .5, .1, .1))), ())
        boxes = Mock(side_effect=lambda rows, size: rows)
        with patch.dict("sys.modules", {"ultralytics.engine.results": SimpleNamespace(Boxes=boxes)}):
            first = backend.finalize_frame(result, ("robot", 1, 0), 10, 1.)
            second = backend.finalize_frame(result, ("robot", 1, 0), 11, 1.1)
            self.assertEqual(first.objects[0].track_id, second.objects[0].track_id)
            self.assertEqual(len(first.objects), 2, "tracker confirmation cannot discard a detection")
            self.assertIsNone(first.objects[1].track_id)
            self.assertIsNone(first.objects[0].identity, "continuity cannot invent personal identity")
            message = first.message()
            roundtrip = parse_recognition({key: message[key] for key in ("summary", "objects", "uncertainties")},
                backend="fixture", model="fixture")
            self.assertEqual(roundtrip.objects[0].track_id, first.objects[0].track_id)
            third = backend.finalize_frame(result, ("robot", 2, 0), 1, 1.2)
            self.assertNotEqual(first.objects[0].track_id, third.objects[0].track_id)
            fourth = backend.finalize_frame(result, ("robot", 2, 2), 2, 1.3)
            self.assertNotEqual(third.objects[0].track_id, fourth.objects[0].track_id)
            self.assertEqual(backend._tracker.reset.call_count, 3)
            backend._tracker.update.return_value = []
            empty = backend.finalize_frame(RecognitionResult("fixture", "fixture", "", (), ()),
                ("robot", 2, 2), 3, 1.4)
            self.assertEqual(empty.objects, (), "absent tracks cannot be emitted as detections")
            self.assertEqual(boxes.call_args.args[0].shape, (0, 6))

    def test_saved_detector_configuration_survives_launcher_restart_and_cli_can_override(self):
        from gateway.server.__main__ import _parser
        with patch.dict(os.environ, {"AINEKIO_VISION_YOLO_WEIGHTS": "/local/person.pt",
                "AINEKIO_VISION_YOLO_DEVICE": "cpu", "AINEKIO_VISION_YOLO_IMAGE_SIZE": "320",
                "AINEKIO_VISION_YOLO_TRACKER": "bytetrack.yaml"}):
            args = _parser().parse_args([])
            self.assertEqual(args.vision_yolo_weights, "/local/person.pt")
            self.assertEqual(args.vision_yolo_image_size, 320)
            self.assertEqual(args.vision_yolo_tracker, "bytetrack.yaml")
            self.assertEqual(_parser().parse_args(["--vision-yolo-image-size", "640"]).vision_yolo_image_size, 640)

    def test_gateway_rejects_ambiguous_backend_selection_before_startup(self):
        from gateway.server.__main__ import _run_production
        args = SimpleNamespace(vision_yolo_weights="/explicit/local.pt",
            vision_url="http://127.0.0.1:8080/v1/chat/completions", vision_model="existing-model")
        with self.assertRaisesRegex(ValueError, "not both"):
            asyncio.run(_run_production(args))

    def test_local_weights_and_input_validation_precede_inference(self):
        with self.assertRaises(FileNotFoundError):
            YoloBackend("/nonexistent/explicitly-selected-weights.pt")
        with TemporaryDirectory() as directory:
            weights = Path(directory) / "fixture.pt"
            weights.write_bytes(b"fixture")
            with self.assertRaises(ValueError):
                YoloBackend(str(weights), image_size=641)
            with self.assertRaises(ValueError):
                YoloBackend(str(weights), confidence=float("nan"))

    def test_detector_classes_and_boxes_use_existing_recognition_contract(self):
        detector = SimpleNamespace(task="segment", names={0: "person"}, predict=Mock(return_value=[SimpleNamespace(
            boxes=SimpleNamespace(xyxyn=Tensor([[-.01, .2, .3, .8], [.4, .4, .4, .5]]),
                conf=Tensor([.8, .7]), cls=Tensor([0, 0])))]))
        factory = Mock(return_value=detector)
        cv2 = SimpleNamespace(imdecode=Mock(return_value="decoded frame"), IMREAD_COLOR=1)
        numpy = SimpleNamespace(frombuffer=Mock(return_value="compressed bytes"), uint8="uint8")
        with TemporaryDirectory() as directory, patch.dict("sys.modules", {
                "ultralytics": SimpleNamespace(YOLO=factory), "cv2": cv2, "numpy": numpy}):
            weights = Path(directory) / "fixture.pt"
            weights.write_bytes(b"fixture")
            backend = YoloBackend(str(weights))
            result = backend(b"\xff\xd8\xff\xd9")
            factory.assert_called_once_with(str(weights))
            self.assertEqual(backend.classes, {0: "person"})
            self.assertEqual(len(result.objects), 1)
            self.assertEqual(result.objects[0].label, "person")
            self.assertEqual(result.objects[0].box[:3], (0, .2, .3))
            self.assertAlmostEqual(result.objects[0].box[3], .6)
            self.assertEqual(result.objects[0].score, .8)
            self.assertIn("fixture.pt@", result.model)
            self.assertNotIn("identity", result.message()["objects"][0])
            detector.predict.assert_called_once_with("decoded frame", device="cpu", imgsz=640,
                conf=.25, max_det=32, verbose=False, save=False)
            cv2.imdecode.return_value = None
            with self.assertRaisesRegex(ValueError, "decodable"):
                backend(b"\xff\xd8\xff\xd9")
            with self.assertRaisesRegex(ValueError, "bounded JPEG"):
                backend(b"not an image")
            self.assertEqual(detector.predict.call_count, 1)
