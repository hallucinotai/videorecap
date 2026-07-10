"""Continuous person tracking for L2.S1 (YOLOv11 → ByteTrack → ArcFace).

Ported from scripts/layer1_character_tracking.py (video branch only).
Adapts full-video character timelines into FaceObservation rows so LP can
consume speaker_character_votes without schema changes.

SKIPPED — auto-correct "who spoke" from video (scorecard row 5):
  Tracks are for character presence / identity votes only. Do not rewrite
  diarization from who is on screen — that is not necessarily who spoke and
  collapses speaker labels. Same decision as dormant lip/reconcile paths.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from modules.enrichment.l2_identity.character_observation import (
    CharacterObservationReport,
    FaceObservation,
    _build_characters,
    _significant_character_count,
    _speaker_character_votes,
)

logger = logging.getLogger(__name__)

METHOD = "continuous_tracking_v1"

DEFAULT_YOLO_MODEL = "yolo11n.pt"
DEFAULT_FRAME_STRIDE = 2
DEFAULT_CONF = 0.25
DEFAULT_ARCFACE_SIMILARITY = 0.45
DEFAULT_MIN_TRACK_FRAMES = 5
DEFAULT_MIN_CLUSTER_SAMPLES = 3


# ---------------------------------------------------------------------------
# Dependency probes
# ---------------------------------------------------------------------------


def continuous_tracking_available() -> dict[str, Any]:
    """Return which continuous-tracking deps are importable."""
    status: dict[str, Any] = {
        "ultralytics": False,
        "supervision": False,
        "insightface": False,
        "opencv": False,
        "errors": {},
    }
    try:
        import cv2  # noqa: F401

        status["opencv"] = True
    except ImportError as exc:
        status["errors"]["opencv"] = str(exc)
    try:
        import ultralytics  # noqa: F401

        status["ultralytics"] = True
    except ImportError as exc:
        status["errors"]["ultralytics"] = str(exc)
    try:
        import supervision  # noqa: F401

        status["supervision"] = True
    except ImportError as exc:
        status["errors"]["supervision"] = str(exc)
    try:
        from insightface.app import FaceAnalysis  # noqa: F401

        status["insightface"] = True
    except ImportError as exc:
        status["errors"]["insightface"] = str(exc)
    status["ready"] = bool(
        status["opencv"] and status["ultralytics"] and status["supervision"] and status["insightface"]
    )
    return status


def tracking_mode_from_env() -> str:
    """L2_CHARACTER_TRACKING: continuous | sparse (default continuous)."""
    raw = (os.environ.get("L2_CHARACTER_TRACKING") or "continuous").strip().lower()
    if raw in ("sparse", "sample", "observation"):
        return "sparse"
    return "continuous"


# ---------------------------------------------------------------------------
# YOLOv11 person detection
# ---------------------------------------------------------------------------


class YOLOv11PersonDetector:
    """COCO class-0 (person) detection via Ultralytics YOLOv11."""

    PERSON_CLASS_ID = 0

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_YOLO_MODEL,
        device: str = "cpu",
        conf: float = DEFAULT_CONF,
        iou: float = 0.45,
        min_box_area_ratio: float = 0.002,
    ):
        from ultralytics import YOLO

        self.model = YOLO(model_name)
        self.device = device
        self.conf = conf
        self.iou = iou
        self.min_box_area_ratio = min_box_area_ratio
        self.model_name = model_name

    def detect(self, frame_bgr: np.ndarray) -> np.ndarray:
        """Return Nx5 float32: x1, y1, x2, y2, confidence."""
        h, w = frame_bgr.shape[:2]
        frame_area = float(h * w)
        min_area = frame_area * self.min_box_area_ratio

        results = self.model.predict(
            source=frame_bgr,
            conf=self.conf,
            iou=self.iou,
            classes=[self.PERSON_CLASS_ID],
            device=self.device,
            verbose=False,
        )

        if not results or results[0].boxes is None or len(results[0].boxes) == 0:
            return np.empty((0, 5), dtype=np.float32)

        boxes = results[0].boxes
        xyxy = boxes.xyxy.cpu().numpy()
        confs = boxes.conf.cpu().numpy()

        kept: list[list[float]] = []
        for (x1, y1, x2, y2), score in zip(xyxy, confs):
            area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
            if area < min_area:
                continue
            kept.append([float(x1), float(y1), float(x2), float(y2), float(score)])

        if not kept:
            return np.empty((0, 5), dtype=np.float32)
        return np.array(kept, dtype=np.float32)


# ---------------------------------------------------------------------------
# ByteTrack
# ---------------------------------------------------------------------------


@dataclass
class RawTrack:
    track_id: int
    frames: list[int] = field(default_factory=list)
    embeddings: list[np.ndarray] = field(default_factory=list)
    bboxes: list[np.ndarray] = field(default_factory=list)
    confidences: list[float] = field(default_factory=list)


class ByteTrackRunner:
    """ByteTrack via supervision; records per-frame active track IDs."""

    def __init__(self, *, min_confidence: float = DEFAULT_CONF):
        import supervision as sv

        self._sv = sv
        self.tracker = sv.ByteTrack(track_activation_threshold=min_confidence)
        self._records: dict[int, RawTrack] = {}

    def update(
        self,
        frame_index_1based: int,
        frame_bgr: np.ndarray,
        detections_xyxy_conf: np.ndarray,
        arcface: ArcFaceEncoder | None = None,
    ) -> list[tuple[int, np.ndarray]]:
        sv = self._sv
        if detections_xyxy_conf.size == 0:
            dets = sv.Detections.empty()
        else:
            dets = sv.Detections(
                xyxy=detections_xyxy_conf[:, :4],
                confidence=detections_xyxy_conf[:, 4],
                class_id=np.zeros(len(detections_xyxy_conf), dtype=int),
            )

        tracked = self.tracker.update_with_detections(dets)
        active: list[tuple[int, np.ndarray]] = []

        if tracked.tracker_id is None:
            return active

        conf_arr = tracked.confidence
        for i, tid in enumerate(tracked.tracker_id):
            if tid is None:
                continue
            tid_int = int(tid)
            bbox = tracked.xyxy[i].astype(np.float32)
            active.append((tid_int, bbox))

            conf = float(conf_arr[i]) if conf_arr is not None else DEFAULT_CONF
            rec = self._records.setdefault(tid_int, RawTrack(track_id=tid_int))
            if not rec.frames or rec.frames[-1] != frame_index_1based:
                rec.frames.append(frame_index_1based)
                rec.bboxes.append(bbox)
                rec.confidences.append(conf)
                if arcface is not None:
                    emb_list = arcface.encode_detections(frame_bgr, np.array([bbox]))
                    if emb_list and emb_list[0] is not None:
                        rec.embeddings.append(emb_list[0])
                    else:
                        rec.embeddings.append(np.zeros(512, dtype=np.float32))
            else:
                # Same frame refresh — keep latest bbox
                rec.bboxes[-1] = bbox
                rec.confidences[-1] = conf

        return active

    def export(self) -> dict[int, RawTrack]:
        return self._records


# ---------------------------------------------------------------------------
# ArcFace identity embeddings
# ---------------------------------------------------------------------------


class ArcFaceEncoder:
    """Face appearance embeddings for cross-track identity consistency."""

    def __init__(self, *, device: str = "cpu", model_name: str = "buffalo_l"):
        try:
            from insightface.app import FaceAnalysis
        except ImportError as exc:
            raise RuntimeError(
                "insightface is required for ArcFace. Install with:\n"
                "  pip install insightface onnxruntime"
            ) from exc

        ctx_id = 0 if device.startswith("cuda") else -1
        self.app = FaceAnalysis(name=model_name, providers=["CPUExecutionProvider"])
        self.app.prepare(ctx_id=ctx_id, det_size=(640, 640))
        self.model_name = model_name
        self._embed_dim = 512

    @property
    def embed_dim(self) -> int:
        return self._embed_dim

    def encode_detections(
        self,
        frame_bgr: np.ndarray,
        boxes_xyxy: np.ndarray,
    ) -> list[np.ndarray | None]:
        """One ArcFace embedding per detection (None if no face in crop)."""
        if boxes_xyxy.size == 0:
            return []

        h, w = frame_bgr.shape[:2]
        out: list[np.ndarray | None] = []

        for box in boxes_xyxy:
            x1, y1, x2, y2 = (int(max(0, v)) for v in box[:4])
            x2 = min(w, max(x1 + 1, x2))
            y2 = min(h, max(y1 + 1, y2))
            crop = frame_bgr[y1:y2, x1:x2]
            if crop.size == 0:
                out.append(None)
                continue

            faces = self.app.get(crop)
            if not faces:
                face_h = max(1, int((y2 - y1) * 0.45))
                crop2 = frame_bgr[y1 : y1 + face_h, x1:x2]
                faces = self.app.get(crop2) if crop2.size else []

            if not faces:
                out.append(None)
                continue

            best = max(faces, key=lambda f: float(getattr(f, "det_score", 0.0)))
            emb = np.asarray(best.normed_embedding, dtype=np.float32)
            out.append(emb)

        return out


# ---------------------------------------------------------------------------
# ArcFace identity merge
# ---------------------------------------------------------------------------


@dataclass
class TrackSample:
    frame: int
    bbox: tuple[int, int, int, int]
    confidence: float
    embedding: np.ndarray | None = None


@dataclass
class MergedCharacter:
    char_index: int
    frames: list[int]
    samples: list[TrackSample]
    member_track_ids: list[int]


def _track_mean_embedding(track: RawTrack) -> np.ndarray | None:
    usable = [e for e in track.embeddings if e is not None and float(np.linalg.norm(e)) > 1e-6]
    if not usable:
        return None
    mean = np.mean(np.stack(usable, axis=0), axis=0)
    norm = np.linalg.norm(mean)
    return (mean / norm) if norm > 1e-6 else mean


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-6))


def _bbox_tuple(bbox: np.ndarray | list[float]) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = (int(v) for v in bbox[:4])
    return x1, y1, x2, y2


def merge_tracks_by_arcface(
    raw_tracks: dict[int, RawTrack],
    *,
    similarity_threshold: float = DEFAULT_ARCFACE_SIMILARITY,
    min_track_frames: int = DEFAULT_MIN_TRACK_FRAMES,
) -> dict[int, MergedCharacter]:
    """
    Merge ByteTrack IDs into stable characters using ArcFace similarity.
    Returns {char_index: MergedCharacter} with combined frames/samples.
    """
    eligible = {
        tid: t
        for tid, t in raw_tracks.items()
        if len(set(t.frames)) >= min_track_frames
    }
    if not eligible:
        return {}

    ids = list(eligible.keys())
    parent = list(range(len(ids)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    embs = [_track_mean_embedding(eligible[i]) for i in ids]

    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            ei, ej = embs[i], embs[j]
            if ei is not None and ej is not None:
                if _cosine(ei, ej) >= similarity_threshold:
                    union(i, j)

    groups: dict[int, list[int]] = {}
    for idx, tid in enumerate(ids):
        groups.setdefault(find(idx), []).append(tid)

    merged: dict[int, MergedCharacter] = {}
    for char_idx, (_, member_tids) in enumerate(sorted(groups.items()), start=1):
        frames: set[int] = set()
        samples: list[TrackSample] = []
        for tid in member_tids:
            track = eligible[tid]
            frames.update(track.frames)
            for i, frame in enumerate(track.frames):
                bbox = track.bboxes[i] if i < len(track.bboxes) else None
                if bbox is None:
                    continue
                conf = track.confidences[i] if i < len(track.confidences) else DEFAULT_CONF
                emb = track.embeddings[i] if i < len(track.embeddings) else None
                if emb is not None and float(np.linalg.norm(emb)) < 1e-6:
                    emb = None
                samples.append(
                    TrackSample(
                        frame=frame,
                        bbox=_bbox_tuple(bbox),
                        confidence=float(conf),
                        embedding=emb,
                    )
                )
        samples.sort(key=lambda s: s.frame)
        merged[char_idx] = MergedCharacter(
            char_index=char_idx,
            frames=sorted(frames),
            samples=samples,
            member_track_ids=sorted(member_tids),
        )

    return merged


# ---------------------------------------------------------------------------
# Video tracking runner
# ---------------------------------------------------------------------------


@dataclass
class ContinuousTrackingResult:
    fps: float
    frame_count: int
    characters: dict[int, MergedCharacter]
    processed_frames: int
    embedding_method: str = "arcface"


def run_video_tracking(
    video_path: Path,
    *,
    device: str = "cpu",
    yolo_model: str = DEFAULT_YOLO_MODEL,
    conf: float = DEFAULT_CONF,
    frame_stride: int = DEFAULT_FRAME_STRIDE,
    max_frames: int | None = None,
    min_track_frames: int = DEFAULT_MIN_TRACK_FRAMES,
    arcface_similarity: float = DEFAULT_ARCFACE_SIMILARITY,
    arcface_model: str = "buffalo_l",
) -> ContinuousTrackingResult:
    """Run YOLO → ByteTrack → ArcFace merge over the video."""
    import cv2

    detector = YOLOv11PersonDetector(model_name=yolo_model, device=device, conf=conf)
    tracker = ByteTrackRunner(min_confidence=conf)
    arcface = ArcFaceEncoder(device=device, model_name=arcface_model)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise FileNotFoundError(f"Cannot open video: {video_path}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    limit = min(total_frames, max_frames) if (total_frames > 0 and max_frames is not None) else (
        max_frames if max_frames is not None else total_frames
    )
    expected_processed = (limit + frame_stride - 1) // frame_stride if limit else 0

    frame_idx = 0
    processed = 0
    log_every = max(1, expected_processed // 20) if expected_processed else 25

    logger.info(
        "L2 continuous tracking start: total_frames=%s stride=%s expected_analyzed≈%s device=%s",
        total_frames or "?",
        frame_stride,
        expected_processed or "?",
        device,
    )
    print(
        f"  Tracking: 0/{expected_processed or '?'} analyzed "
        f"(video frames {total_frames or '?'}, stride={frame_stride})",
        flush=True,
    )

    try:
        while True:
            if max_frames is not None and frame_idx >= max_frames:
                break
            ok, frame = cap.read()
            if not ok:
                break
            frame_idx += 1
            if (frame_idx - 1) % frame_stride != 0:
                continue
            processed += 1
            dets = detector.detect(frame)
            tracker.update(frame_idx, frame, dets, arcface)
            if processed == 1 or processed % log_every == 0 or (
                expected_processed and processed >= expected_processed
            ):
                pct = (
                    f"{100.0 * processed / expected_processed:.0f}%"
                    if expected_processed
                    else "?"
                )
                msg = (
                    f"  Tracking: {processed}/{expected_processed or '?'} analyzed "
                    f"({pct}) — video frame {frame_idx}/{total_frames or '?'}"
                )
                print(msg, flush=True)
                logger.info(msg.strip())
    finally:
        cap.release()
    print(
        f"  Tracking done: {processed} frames analyzed "
        f"(last video frame {frame_idx}/{total_frames or '?'})",
        flush=True,
    )

    raw = tracker.export()
    merged = merge_tracks_by_arcface(
        raw,
        similarity_threshold=arcface_similarity,
        min_track_frames=min_track_frames,
    )
    return ContinuousTrackingResult(
        fps=fps,
        frame_count=total_frames or frame_idx,
        characters=merged,
        processed_frames=processed,
        embedding_method="arcface",
    )


# ---------------------------------------------------------------------------
# Adapter: continuous tracks → FaceObservation / CharacterObservationReport
# ---------------------------------------------------------------------------


def frame_to_timestamp(frame_1based: int, fps: float) -> float:
    if fps <= 0:
        return 0.0
    return round((frame_1based - 1) / fps, 3)


def adapt_tracks_to_observations(
    tracking: ContinuousTrackingResult,
    utterances: list[dict[str, Any]],
) -> list[FaceObservation]:
    """
    Emit FaceObservation rows for each track sample that falls inside an utterance window.
    Ties visual characters to diarization speakers via temporal co-occurrence.
    """
    fps = tracking.fps if tracking.fps > 0 else 25.0
    observations: list[FaceObservation] = []

    # Precompute utterance intervals
    utt_rows = [
        {
            "id": str(u.get("id") or ""),
            "speaker": str(u.get("speaker") or ""),
            "start": float(u.get("start") or 0),
            "end": float(u.get("end") or 0),
        }
        for u in utterances
        if u.get("speaker") and u.get("id") is not None
    ]

    for char_idx, character in sorted(tracking.characters.items()):
        char_id = f"char_{char_idx}"
        for sample in character.samples:
            ts = frame_to_timestamp(sample.frame, fps)
            matching = [u for u in utt_rows if u["start"] <= ts <= u["end"]]
            if not matching:
                continue

            emb = sample.embedding
            if emb is None:
                emb = np.zeros(512, dtype=np.float32)
            else:
                emb = np.asarray(emb, dtype=np.float32)
                norm = float(np.linalg.norm(emb))
                if norm > 1e-6:
                    emb = emb / norm

            for utt in matching:
                observations.append(
                    FaceObservation(
                        utterance_id=utt["id"],
                        aai_speaker=utt["speaker"],
                        timestamp_sec=ts,
                        sample_method="continuous_track",
                        chunk_text=None,
                        face_index=0,
                        detection_confidence=float(sample.confidence or DEFAULT_CONF),
                        faces_in_frame=1,
                        embedding=emb,
                        embedding_method="arcface",
                        crop_jpeg_base64=None,
                        face_bbox=sample.bbox,
                        appearance_signature=None,
                        character_id=char_id,
                    )
                )

    return observations


def build_report_from_observations(
    observations: list[FaceObservation],
    utterances: list[dict[str, Any]],
    *,
    method: str = METHOD,
    embedding_method: str = "arcface",
    sample_points: int = 0,
    min_cluster_samples: int = DEFAULT_MIN_CLUSTER_SAMPLES,
) -> CharacterObservationReport:
    speaker_ids = sorted({u["speaker"] for u in utterances if u.get("speaker")})
    if not observations:
        return CharacterObservationReport(
            method=method,
            diarization_speaker_count=len(speaker_ids),
            diarization_speaker_ids=speaker_ids,
            character_count_visual=0,
            character_count_significant=0,
            min_cluster_samples=min_cluster_samples,
            count_mismatch=len(speaker_ids) != 0,
            embedding_method=embedding_method,
            sample_points=sample_points,
            faces_sampled=0,
            characters={},
            observations=[],
            speaker_character_votes={},
        )

    character_count = len({o.character_id for o in observations if o.character_id})
    speaker_votes = _speaker_character_votes(observations)
    characters = _build_characters(observations, {})
    significant_count = _significant_character_count(characters, min_cluster_samples)

    obs_rows: list[dict[str, Any]] = []
    for obs in observations:
        obs_rows.append(
            {
                "utterance_id": obs.utterance_id,
                "aai_speaker": obs.aai_speaker,
                "timestamp_sec": obs.timestamp_sec,
                "character_id": obs.character_id,
                "sample_method": obs.sample_method,
                "chunk_text": obs.chunk_text,
                "detection_confidence": round(obs.detection_confidence, 3),
                "faces_in_frame": obs.faces_in_frame,
                "embedding_method": obs.embedding_method,
            }
        )

    return CharacterObservationReport(
        method=method,
        diarization_speaker_count=len(speaker_ids),
        diarization_speaker_ids=speaker_ids,
        character_count_visual=character_count,
        character_count_significant=significant_count,
        min_cluster_samples=min_cluster_samples,
        count_mismatch=character_count != len(speaker_ids),
        embedding_method=embedding_method,
        sample_points=sample_points,
        faces_sampled=len(observations),
        characters=characters,
        observations=obs_rows,
        speaker_character_votes=speaker_votes,
    )


def _env_positive_int(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return None
    try:
        value = int(str(raw).strip())
    except ValueError:
        return None
    return value if value > 0 else None


def run_l2_continuous_tracking(
    doc: dict[str, Any],
    video_path: Path,
    *,
    min_cluster_samples: int = DEFAULT_MIN_CLUSTER_SAMPLES,
    device: str | None = None,
    frame_stride: int | None = None,
    max_frames: int | None = None,
) -> tuple[CharacterObservationReport, list[FaceObservation]]:
    """
    Full-video continuous tracking adapted into L2 character observation outputs.
    Raises on missing deps / unreadable video / empty tracks (caller may fall back).

    Env overrides:
      L2_TRACKING_DEVICE, L2_TRACKING_FRAME_STRIDE, L2_TRACKING_MAX_FRAMES
    """
    deps = continuous_tracking_available()
    if not deps["ready"]:
        missing = [k for k in ("opencv", "ultralytics", "supervision", "insightface") if not deps.get(k)]
        raise RuntimeError(f"continuous_tracking_deps_missing:{','.join(missing)}")

    utterances = (doc.get("L1_transcript") or {}).get("utterances") or []
    if not utterances:
        raise RuntimeError("no_utterances")

    resolved_device = device or os.environ.get("L2_TRACKING_DEVICE") or "cpu"
    resolved_stride = frame_stride
    if resolved_stride is None:
        resolved_stride = _env_positive_int("L2_TRACKING_FRAME_STRIDE") or DEFAULT_FRAME_STRIDE
    resolved_max_frames = max_frames if max_frames is not None else _env_positive_int("L2_TRACKING_MAX_FRAMES")

    tracking = run_video_tracking(
        Path(video_path),
        device=resolved_device,
        frame_stride=resolved_stride,
        max_frames=resolved_max_frames,
    )
    if not tracking.characters:
        raise RuntimeError("no_tracks_detected")

    observations = adapt_tracks_to_observations(tracking, utterances)
    if not observations:
        raise RuntimeError("no_utterance_track_overlap")

    sample_points = sum(len(c.samples) for c in tracking.characters.values())
    report = build_report_from_observations(
        observations,
        utterances,
        method=METHOD,
        embedding_method=tracking.embedding_method,
        sample_points=sample_points,
        min_cluster_samples=min_cluster_samples,
    )
    logger.info(
        "L2 continuous tracking: %d characters, %d observations, %d processed frames @ stride=%d",
        report.character_count_visual,
        len(observations),
        tracking.processed_frames,
        resolved_stride,
    )
    return report, observations
