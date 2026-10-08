from pathlib import Path
import asyncio
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
