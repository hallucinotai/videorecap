"""Multi-face detection and lip-motion scoring via MediaPipe."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Mouth landmark indices (MediaPipe Face Mesh 468 topology).
_MOUTH_UPPER = 13
_MOUTH_LOWER = 14
_MOUTH_LEFT = 61
_MOUTH_RIGHT = 291

LIP_WINDOW_SEC = 0.2
LIP_FRAME_STEP_SEC = 0.1


@dataclass
class FaceDetection:
    bbox: tuple[int, int, int, int]  # x1, y1, x2, y2
    confidence: float
    crop: Any = None


@dataclass
class SpeakingFaceResult:
    bbox: tuple[int, int, int, int]
    crop: Any
    detection_confidence: float
    lip_motion_score: float
    mouth_openness: float
    embedding: np.ndarray | None = None
    face_index: int = 0


class VideoFrameReader:
    """Seekable frame reader with small cache."""

    def __init__(self, video_path: str):
        import cv2

        self._cv2 = cv2
        self._cap = cv2.VideoCapture(video_path)
        if not self._cap.isOpened():
            raise RuntimeError(f"Cannot open video: {video_path}")
        self._fps = self._cap.get(cv2.CAP_PROP_FPS) or 25.0

    @property
    def fps(self) -> float:
        return float(self._fps)

    def read_at(self, timestamp_sec: float) -> Any | None:
        self._cap.set(self._cv2.CAP_PROP_POS_MSEC, max(0.0, timestamp_sec) * 1000.0)
        ok, frame = self._cap.read()
        return frame if ok else None

    def read_window(self, center_sec: float, window_sec: float = LIP_WINDOW_SEC, step_sec: float = LIP_FRAME_STEP_SEC) -> list[tuple[float, Any]]:
        times = []
        t = center_sec - window_sec
        while t <= center_sec + window_sec + 1e-6:
            times.append(round(t, 3))
            t += step_sec
        frames: list[tuple[float, Any]] = []
        for ts in times:
            frame = self.read_at(ts)
            if frame is not None:
                frames.append((ts, frame))
        return frames

    def close(self) -> None:
        self._cap.release()


def detect_faces(frame) -> list[FaceDetection]:
    import cv2
    import mediapipe as mp

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w = frame.shape[:2]
    detections: list[FaceDetection] = []
    mp_face = mp.solutions.face_detection
    for model_selection, min_conf in ((1, 0.35), (0, 0.30)):
        with mp_face.FaceDetection(model_selection=model_selection, min_detection_confidence=min_conf) as detector:
            results = detector.process(rgb)
            if not results.detections:
                continue
            for det in results.detections:
                score = float(det.score[0]) if det.score else 0.0
                box = det.location_data.relative_bounding_box
                x1 = max(0, int(box.xmin * w))
                y1 = max(0, int(box.ymin * h))
                x2 = min(w, int((box.xmin + box.width) * w))
                y2 = min(h, int((box.ymin + box.height) * h))
                if x2 <= x1 or y2 <= y1:
                    continue
                pad = int(0.08 * max(x2 - x1, y2 - y1))
                x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
                x2, y2 = min(w, x2 + pad), min(h, y2 + pad)
                crop = frame[y1:y2, x1:x2].copy()
                detections.append(FaceDetection(bbox=(x1, y1, x2, y2), confidence=score, crop=crop))
            if detections:
                break
    return detections


def _landmark_xy(landmark, w: int, h: int) -> tuple[float, float]:
    return landmark.x * w, landmark.y * h


def _mouth_metrics(landmarks, w: int, h: int) -> tuple[float, float]:
    import math

    ux, uy = _landmark_xy(landmarks[_MOUTH_UPPER], w, h)
    lx, ly = _landmark_xy(landmarks[_MOUTH_LOWER], w, h)
    left_x, _ = _landmark_xy(landmarks[_MOUTH_LEFT], w, h)
    right_x, _ = _landmark_xy(landmarks[_MOUTH_RIGHT], w, h)
    openness = math.hypot(lx - ux, ly - uy)
    width = abs(right_x - left_x)
    return openness, width


def lip_motion_on_crop(crop_series: list[Any]) -> tuple[float, float]:
    """
    Compute lip activity score on a series of face crops (same person).
    Returns (motion_score, final_openness).
    """
    import cv2
    import mediapipe as mp

    if not crop_series:
        return 0.0, 0.0

    mp_mesh = mp.solutions.face_mesh
    metrics: list[tuple[float, float]] = []
    with mp_mesh.FaceMesh(
        static_image_mode=True,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.4,
        min_tracking_confidence=0.4,
    ) as mesh:
        for crop in crop_series:
            if crop is None or crop.size == 0:
                continue
            rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
            h, w = crop.shape[:2]
            result = mesh.process(rgb)
            if not result.multi_face_landmarks:
                continue
            lm = result.multi_face_landmarks[0].landmark
            metrics.append(_mouth_metrics(lm, w, h))

    if len(metrics) < 2:
        if metrics:
            return metrics[0][0] * 0.1, metrics[0][0]
        return 0.0, 0.0

    motion = 0.0
    for i in range(1, len(metrics)):
        o0, w0 = metrics[i - 1]
        o1, w1 = metrics[i]
        motion += abs(o1 - o0) + abs(w1 - w0) * 0.5
    return motion, metrics[-1][0]


def _bbox_center(bbox: tuple[int, int, int, int]) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


def _match_face_in_frame(frame, reference_bbox: tuple[int, int, int, int], max_dist_ratio: float = 0.35) -> tuple[int, int, int, int] | None:
    """Find the detection closest to reference bbox center."""
    faces = detect_faces(frame)
    if not faces:
        return None
    ref_cx, ref_cy = _bbox_center(reference_bbox)
    ref_w = max(reference_bbox[2] - reference_bbox[0], 1)
    best = None
    best_dist = float("inf")
    for face in faces:
        cx, cy = _bbox_center(face.bbox)
        dist = ((cx - ref_cx) ** 2 + (cy - ref_cy) ** 2) ** 0.5
        if dist < best_dist:
            best_dist = dist
            best = face.bbox
    if best is None or best_dist > ref_w * max_dist_ratio:
        return None
    return best


def _crop_from_bbox(frame, bbox: tuple[int, int, int, int]) -> Any:
    x1, y1, x2, y2 = bbox
    return frame[y1:y2, x1:x2].copy()


def find_speaking_face(
    reader: VideoFrameReader,
    timestamp_sec: float,
    face_histogram_embedding,
) -> SpeakingFaceResult | None:
    """
    At timestamp_sec, detect all faces, score lip motion in a ±0.2s window,
    return the face with highest mouth activity.
    """
    window_frames = reader.read_window(timestamp_sec)
    if not window_frames:
        return None

    center_frame = min(window_frames, key=lambda item: abs(item[0] - timestamp_sec))[1]
    faces = detect_faces(center_frame)
    if not faces:
        return None

    best_result: SpeakingFaceResult | None = None
    for idx, face in enumerate(faces):
        crop_series: list[Any] = []
        for _ts, frame in window_frames:
            matched = _match_face_in_frame(frame, face.bbox)
            if matched:
                crop_series.append(_crop_from_bbox(frame, matched))
        lip_score, openness = lip_motion_on_crop(crop_series)
        center_crop = face.crop if face.crop is not None else _crop_from_bbox(center_frame, face.bbox)
        embedding = face_histogram_embedding(center_crop)
        candidate = SpeakingFaceResult(
            bbox=face.bbox,
            crop=center_crop,
            detection_confidence=face.confidence,
            lip_motion_score=round(lip_score, 3),
            mouth_openness=round(openness, 3),
            embedding=embedding,
            face_index=idx,
        )
        if best_result is None or candidate.lip_motion_score > best_result.lip_motion_score:
            best_result = candidate

    return best_result
