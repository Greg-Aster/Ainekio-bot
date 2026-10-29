"""Calibrated, reference-anchored planar vision. No movement authority or VIO claim."""
from __future__ import annotations

import math
import base64
from uuid import uuid4

import cv2
import numpy as np

if __package__:
    from .depth_motion import rigid
else:
    from depth_motion import rigid


def array(value, shape, name):
    result = np.asarray(value, dtype=float)
    if result.shape != shape or not np.isfinite(result).all():
        raise ValueError(f"{name} must be a finite {shape} array")
    return result


def pose_from_plane(points, pixels, k, distortion, ambiguity_pixels):
    """Return all physically plausible planar poses and their measured reprojection errors."""
    count, rotations, translations, errors = cv2.solvePnPGeneric(
        np.asarray(points, np.float64), np.asarray(pixels, np.float64), k, distortion,
        flags=cv2.SOLVEPNP_IPPE)
    candidates = []
    for rv, tv, error in zip(rotations, translations, errors):
        r = cv2.Rodrigues(rv)[0]
        if np.all((r @ np.asarray(points).T + tv)[2] > 0):
            transform = np.eye(4)
            transform[:3, :3], transform[:3, 3] = r, tv.ravel()
            candidates.append((float(error[0]), transform))
    candidates.sort(key=lambda item: item[0])
    if not candidates:
        raise ValueError("No positive-depth ground-plane pose")
    # Distinct solutions inside the calibration's measured pixel error cannot be resolved.
    best = candidates[0]
    ambiguous = any(error - best[0] <= ambiguity_pixels and not np.allclose(t, best[1], atol=1e-6)
                    for error, t in candidates[1:])
    return best[1], {"reprojectionPixels": best[0], "alternativeErrorsPixels": [x[0] for x in candidates[1:]], "ambiguous": ambiguous}


class GroundPlane:
    def __init__(self, gateway_instance):
        self.gateway_instance = gateway_instance
        self.calibrations = {}
        self.samples = {}
        self.frames = {}
        self.calibration_frames = {}
        self.references = {}
        self.measurements = {}
        self.contacts = {}

    def restore(self, calibrations):
        for robot, calibration in calibrations.items():
            self.validate_calibration(calibration)
            self.calibrations[robot] = calibration

    @staticmethod
    def validate_calibration(c):
        k = array(c["cameraMatrix"], (3, 3), "cameraMatrix")
        if k[0, 0] <= 0 or k[1, 1] <= 0 or not np.allclose(k[2], [0, 0, 1]):
            raise ValueError("Invalid camera intrinsics")
        d = np.asarray(c["distortion"], dtype=float)
        if d.size not in (4, 5, 8, 12, 14) or not np.isfinite(d).all():
            raise ValueError("Invalid distortion coefficients")
        rigid(c["cameraToBody"])
        if len(c["imageSize"]) != 2 or any(type(v) is not int or v <= 0 for v in c["imageSize"]):
            raise ValueError("imageSize must be measured width and height")
        if not math.isfinite(c["reprojectionPixels"]) or c["reprojectionPixels"] < 0:
            raise ValueError("Missing calibration residual")
        if not isinstance(c.get("geometryId"), str) or not c["geometryId"].strip():
            raise ValueError("Explicit lens/crop/rotation geometryId required")

    def calibration(self, robot, request):
        operation = request.get("operation")
        if operation == "resetSamples":
            self.samples.pop(robot, None)
            return {"samples": 0, "calibration": self.calibrations.get(robot)}
        if operation == "status":
            if robot in self.frames:
                self.calibration_frames[robot] = self.frames[robot]
            result = {"calibration": self.calibrations.get(robot), "samples": len(self.samples.get(robot, [])),
                    "frame": self.frames[robot][1] if robot in self.frames else None,
                    "measurement": self.measurements.get(robot, {"available": False, "reason": "No camera frame"})}
            if request.get("includeImage") and robot in self.calibration_frames:
                gray, _ = self.calibration_frames[robot]
                result["image"] = "data:image/jpeg;base64," + base64.b64encode(cv2.imencode('.jpg', gray)[1]).decode()
            return result
        frame = self.calibration_frames.get(robot)
        if frame is None:
            raise ValueError("No retained camera frame for selected robot")
        gray, identity = frame
        if request.get("frameId") != identity["frameId"]:
            raise ValueError("Select the exact current camera frame")
        if operation in ("capture", "reference"):
            if request.get("pattern") == "rectangle":
                width, height = request.get("widthMetres"), request.get("heightMetres")
                if any(type(v) not in (float, int) or not math.isfinite(v) or v <= 0 for v in (width, height)):
                    raise ValueError("Measured rectangle widthMetres and heightMetres required")
                pixels = array(request.get("pixels"), (4, 2), "pixels")
                if np.any(pixels < 0) or np.any(pixels > [gray.shape[1]-1, gray.shape[0]-1]):
                    raise ValueError("Rectangle corners must belong to the selected image")
                points = np.array([[0, 0, 0], [width, 0, 0], [width, height, 0], [0, height, 0]])
            else:
                columns, rows = request.get("columns"), request.get("rows")
                square = request.get("squareMetres")
                if type(columns) is not int or type(rows) is not int or columns < 2 or rows < 2 or type(square) not in (float, int) or not math.isfinite(square) or square <= 0:
                    raise ValueError("Measured checkerboard inner columns/rows and squareMetres required")
                found, corners = cv2.findChessboardCornersSB(gray, (columns, rows))
                if not found:
                    raise ValueError("Measured checkerboard corners not found in selected frame")
                points = np.zeros((columns * rows, 3), np.float64)
                points[:, :2] = np.mgrid[:columns, :rows].T.reshape(-1, 2) * square
                pixels = corners.reshape(-1, 2).astype(float)
            sample = {"points": points, "pixels": pixels, "identity": identity.copy(), "size": gray.shape[::-1],
                      "pattern": request.get("pattern", "checkerboard")}
            if operation == "capture":
                samples = self.samples.setdefault(robot, [])
                if any(s["identity"]["frameId"] == identity["frameId"] for s in samples):
                    raise ValueError("This frame is already a calibration sample")
                samples.append(sample)
                return {"samples": len(samples), "frameId": identity["frameId"]}
            c = self.calibrations.get(robot)
            if c is None or list(gray.shape[::-1]) != c["imageSize"]:
                raise ValueError("Matching fitted camera calibration required")
            if request.get("geometryId") != c["geometryId"]:
                raise ValueError("Reference geometryId must match calibrated lens/crop/rotation")
            pose, quality = pose_from_plane(points, sample["pixels"], np.array(c["cameraMatrix"]), np.array(c["distortion"]), c["reprojectionPixels"])
            if quality["ambiguous"]:
                raise ValueError("Reference floor pose is ambiguous; select a distinct measured board view")
            self.references[robot] = {"id": str(uuid4()), "points": points, "pixels": sample["pixels"], "gray": gray,
                "initial": pose, "pose": pose, "identity": identity.copy(), "calibrationId": c["id"], "quality": quality}
            self._publish(robot, identity, pose, quality)
            return {"referenceId": self.references[robot]["id"], "measurement": self.measurements[robot]}
        if operation == "fit":
            samples = self.samples.get(robot, [])
            if len(samples) < 3:
                raise ValueError("At least three distinct measured target views required for intrinsic fitting")
            size = samples[0]["size"]
            if any(s["size"] != size for s in samples):
                raise ValueError("Calibration samples have different image geometry")
            transform = rigid(request.get("cameraToBody"))
            geometry = request.get("geometryId")
            if not isinstance(geometry, str) or not geometry.strip():
                raise ValueError("Explicit lens/crop/rotation geometryId required")
            rms, k, d, _, _ = cv2.calibrateCamera([s["points"].astype(np.float32) for s in samples],
                [s["pixels"].astype(np.float32) for s in samples], size, None, None)
            c = {"id": str(uuid4()), "robotId": robot, "imageSize": list(size), "geometryId": geometry,
                 "cameraMatrix": k.tolist(), "distortion": d.ravel().tolist(), "cameraToBody": transform.tolist(),
                 "reprojectionPixels": float(rms), "sampleFrames": [s["identity"] for s in samples],
                 "source": "measured-planar-target", "patterns": sorted({s.get("pattern", "checkerboard") for s in samples}),
                 "metricUncertaintyMetres": None}
            self.validate_calibration(c)
            self.calibrations[robot] = c
            self.references.pop(robot, None)
            self.measurements[robot] = {**identity, "available": False, "reason": "Set a reference board on the ground plane"}
            return {"calibration": c, "measurement": self.measurements[robot]}
        raise ValueError("Unknown calibration operation")

    def _publish(self, robot, identity, pose, quality):
        c, reference = self.calibrations[robot], self.references[robot]
        # cameraToBody maps optical-camera coordinates into body coordinates.
        camera_body = rigid(c["cameraToBody"])
        initial_body_plane = camera_body @ reference["initial"]
        current_body_plane = camera_body @ pose
        initial_body_current_body = initial_body_plane @ np.linalg.inv(current_body_plane)
        position = initial_body_current_body[:3, 3]
        heading = math.degrees(math.atan2(initial_body_current_body[1, 0], initial_body_current_body[0, 0]))
        self.measurements[robot] = {**identity, "available": not quality["ambiguous"],
            "reason": "Ambiguous planar pose" if quality["ambiguous"] else None,
            "source": "calibrated-ground-plane", "referenceId": reference["id"], "calibrationId": c["id"],
            "referenceFrameId": reference["identity"]["frameId"],
            "position": {"xMetres": float(position[0]), "yMetres": float(position[1]),
                         "zMetres": float(position[2]), "headingDegrees": heading, "uncertaintyMetres": None},
            "uncertainty": {**quality, "metricMetres": None, "calibrationReprojectionPixels": c["reprojectionPixels"]}}

    def process(self, robot, epoch, counter, received_at, jpeg, received_iso):
        identity = {"robotId": robot, "epoch": epoch, "gatewayInstance": self.gateway_instance,
            "frameCounter": counter, "frameId": f"ainekio-camera-{self.gateway_instance}-{robot}-{epoch}-{counter}",
            "frameTimestamp": received_iso, "observedAt": received_iso, "receivedAtMonotonic": received_at, "clock": "gateway-receipt"}
        gray = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            self.measurements[robot] = {**identity, "available": False, "reason": "JPEG decode failed"}
            return self.measurements[robot]
        previous = self.frames.get(robot)
        if previous is not None:
            old_gray, old_identity = previous
            for contact in self.contacts.values():
                if contact["robotId"] != robot or not contact.get("available"):
                    continue
                if contact["currentFrameId"] != old_identity["frameId"] or old_identity["epoch"] != epoch or old_gray.shape != gray.shape:
                    contact.update(available=False, reason="Ground contact frame continuity lost")
                    continue
                pixel = np.array(contact["pixel"], np.float32).reshape(1, 1, 2)
                tracked, valid, _ = cv2.calcOpticalFlowPyrLK(old_gray, gray, pixel, None)
                if tracked is None or not valid[0, 0]:
                    contact.update(available=False, reason="Selected ground contact optical tracking lost")
                else:
                    contact.update(pixel=tracked.reshape(2).tolist(), currentFrameId=identity["frameId"])
        self.frames[robot] = (gray, identity)
        c, ref = self.calibrations.get(robot), self.references.get(robot)
        if c is None or ref is None:
            self.measurements[robot] = {**identity, "available": False, "reason": "Measured calibration and floor reference required"}
            return self.measurements[robot]
        if list(gray.shape[::-1]) != c["imageSize"] or ref["identity"]["epoch"] != epoch:
            self.references.pop(robot, None)
            self.measurements[robot] = {**identity, "available": False, "reason": "Camera geometry or body epoch changed; reference unavailable"}
            return self.measurements[robot]
        pixels, status, _ = cv2.calcOpticalFlowPyrLK(ref["gray"], gray, ref["pixels"].astype(np.float32).reshape(-1, 1, 2), None)
        if pixels is None or status is None:
            good = np.zeros(len(ref["points"]), dtype=bool)
        else:
            good = status.ravel().astype(bool)
        try:
            if good.sum() < 4:
                raise ValueError("Insufficient retained floor correspondences")
            points, pixels = ref["points"][good], pixels.reshape(-1, 2)[good]
            pose, quality = pose_from_plane(points, pixels, np.array(c["cameraMatrix"]), np.array(c["distortion"]), c["reprojectionPixels"])
            self._publish(robot, identity, pose, quality)
            ref.update(points=points, pixels=pixels, gray=gray, pose=pose, quality=quality)
        except (ValueError, cv2.error) as error:
            self.measurements[robot] = {**identity, "available": False, "reason": str(error), "referenceId": ref["id"], "calibrationId": c["id"]}
            self.references.pop(robot, None)
        return self.measurements[robot]

    def _range_current(self, frame_id, point):
        # A point must belong to the exact retained frame; never reuse an old pixel after camera motion.
        for robot, (gray, identity) in self.frames.items():
            if identity["frameId"] != frame_id:
                continue
            measurement = self.measurements.get(robot, {})
            if not measurement.get("available"):
                return {"available": False, "reason": "Current metric ground plane unavailable"}
            xy = array([point.get("x"), point.get("y")], (2,), "groundContact")
            if np.any(xy < 0) or np.any(xy > 1):
                raise ValueError("groundContact must be normalized")
            c, ref = self.calibrations[robot], self.references[robot]
            pixel = (xy * [gray.shape[1], gray.shape[0]]).reshape(1, 1, 2)
            ray = np.r_[cv2.undistortPoints(pixel, np.array(c["cameraMatrix"]), np.array(c["distortion"])).ravel(), 1.]
            pose = ref["pose"]
            normal = pose[:3, 2]
            distance = normal @ pose[:3, 3]
            denominator = normal @ ray
            if abs(denominator) < np.finfo(float).eps or distance / denominator <= 0:
                return {"available": False, "reason": "Selected ray has no forward ground-plane intersection"}
            body = rigid(c["cameraToBody"]) @ np.r_[ray * distance / denominator, 1.]
            return {**identity, "available": True, "source": "selected-ground-contact-plane-intersection", "referenceId": ref["id"],
                "calibrationId": c["id"], "groundContact": point, "point": point, "rangeMetres": float(np.linalg.norm(body[:2])), "uncertaintyMetres": None}
        return {"available": False, "reason": "Selected contact source frame is no longer retained"}

    def range(self, frame_id, point, source_frame=None):
        xy = array([point.get("x"), point.get("y")], (2,), "groundContact")
        if np.any(xy < 0) or np.any(xy > 1):
            raise ValueError("groundContact must be normalized")
        if source_frame is not None and source_frame.get("frameId") != frame_id:
            raise ValueError("Retained source identity differs from selected frame")
        key = (frame_id, float(xy[0]), float(xy[1]))
        if key not in self.contacts:
            for robot, (gray, identity) in self.frames.items():
                if identity["frameId"] == frame_id:
                    if source_frame is not None and (source_frame.get("robotId") != robot or source_frame.get("epoch") != identity["epoch"] or source_frame.get("gatewayInstance") != self.gateway_instance):
                        return {"available": False, "reason": "Retained source identity differs from current body camera"}
                    self.contacts[key] = {"robotId": robot, "available": True, "currentFrameId": frame_id,
                        "referenceFrameTimestamp": source_frame.get("frameTimestamp") if source_frame else identity.get("frameTimestamp"),
                        "pixel": (xy * [gray.shape[1], gray.shape[0]]).tolist()}
                    break
        if key not in self.contacts and source_frame is not None:
            robot = source_frame.get("robotId")
            current = self.frames.get(robot)
            if current is not None:
                gray, identity = current
                if source_frame.get("epoch") != identity["epoch"] or source_frame.get("gatewayInstance") != self.gateway_instance:
                    return {"available": False, "reason": "Selected source belongs to a different body epoch"}
                jpeg = base64.b64decode(source_frame["jpeg"], validate=True)
                old_gray = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_GRAYSCALE)
                if old_gray is None or old_gray.shape != gray.shape:
                    return {"available": False, "reason": "Selected source image geometry unavailable or changed"}
                source_pixel = (xy * [gray.shape[1], gray.shape[0]]).astype(np.float32).reshape(1, 1, 2)
                tracked, valid, _ = cv2.calcOpticalFlowPyrLK(old_gray, gray, source_pixel, None)
                if tracked is None or valid is None or not valid[0, 0]:
                    return {"available": False, "reason": "Selected source-to-current optical correspondence lost"}
                self.contacts[key] = {"robotId": robot, "available": True,
                    "currentFrameId": identity["frameId"], "pixel": tracked.reshape(2).tolist(),
                    "referenceFrameTimestamp": source_frame.get("frameTimestamp")}
        contact = self.contacts.get(key)
        if not contact:
            return {"available": False, "reason": "Exact ground-contact source frame is not retained"}
        if not contact["available"]:
            return {**contact, "referenceFrameId": frame_id, "referencePoint": point}
        gray, _ = self.frames[contact["robotId"]]
        current = np.array(contact["pixel"]) / [gray.shape[1], gray.shape[0]]
        if np.any(current < 0) or np.any(current > 1):
            contact.update(available=False, reason="Selected ground contact left the image")
            return {**contact, "referenceFrameId": frame_id, "referencePoint": point}
        result = self._range_current(contact["currentFrameId"], {"x": float(current[0]), "y": float(current[1])})
        return {**result, "referenceFrameId": frame_id, "referencePoint": point,
                "referenceFrameTimestamp": contact.get("referenceFrameTimestamp"), "contactSource": "explicit-selected-ground-contact", "trackingSource": "optical-flow"}
