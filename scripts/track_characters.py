#!/usr/bin/env python3
"""
Detect and track faces (characters) in a video using MTCNN + OpenCV CSRT trackers.

Local test utility — lives under scripts/ (gitignored). Not part of the app pipeline.

Pipeline:
  1. MTCNN detects faces on a schedule (~1/sec)
  2. NMS deduplicates overlapping boxes in the same frame
  3. CSRT tracks each face; active count is capped to faces detected now
  4. Lost tracks can re-activate within a short gap instead of spawning new IDs
  5. Post-merge clusters fragmented tracks by position + time into real characters

Usage:
  python scripts/track_characters.py \\
    --video assets/input_video.mp4 \\
    --output-dir scripts/character_tracks

Dependencies (local test env only):
  pip install opencv-contrib-python mtcnn tensorflow
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any


def _create_csrt_tracker(cv2):
    if hasattr(cv2, "legacy") and hasattr(cv2.legacy, "TrackerCSRT_create"):
        return cv2.legacy.TrackerCSRT_create()
    if hasattr(cv2, "TrackerCSRT_create"):
        return cv2.TrackerCSRT_create()
    raise SystemExit(
        "CSRT tracker not available. Install with:\n"
        "  pip install opencv-contrib-python"
    )


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh

    inter_x1 = max(ax, bx)
    inter_y1 = max(ay, by)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0, inter_x2 - inter_x1)
    inter_h = max(0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    if inter_area == 0:
        return 0.0

    union = aw * ah + bw * bh - inter_area
    return inter_area / union if union > 0 else 0.0


def _clamp_bbox(x: int, y: int, w: int, h: int, frame_w: int, frame_h: int) -> tuple[int, int, int, int]:
    x = max(0, min(x, frame_w - 1))
    y = max(0, min(y, frame_h - 1))
    w = max(1, min(w, frame_w - x))
    h = max(1, min(h, frame_h - y))
    return x, y, w, h


def _bbox_from_mtcnn(box: list[int]) -> tuple[int, int, int, int]:
    x, y, w, h = box
    return int(x), int(y), int(w), int(h)


def _bbox_center(bbox: tuple[int, int, int, int]) -> tuple[float, float]:
    x, y, w, h = bbox
    return x + w / 2.0, y + h / 2.0


def _sample_bbox(sample: dict[str, Any]) -> tuple[int, int, int, int]:
    b = sample["bbox"]
    return b["x"], b["y"], b["w"], b["h"]


def _nms_detections(
    detections: list[dict[str, Any]],
    iou_threshold: float = 0.35,
) -> list[dict[str, Any]]:
    """Drop overlapping MTCNN boxes in the same frame (keep highest confidence)."""
    if len(detections) <= 1:
        return detections

    ordered = sorted(detections, key=lambda d: d["confidence"], reverse=True)
    kept: list[dict[str, Any]] = []
    for det in ordered:
        if all(_iou(det["bbox"], k["bbox"]) < iou_threshold for k in kept):
            kept.append(det)
    return kept


@dataclass
class FaceTrack:
    character_id: int
    first_frame: int
    last_frame: int
    first_seen_sec: float
    last_seen_sec: float
    samples: list[dict[str, Any]] = field(default_factory=list)
    active: bool = True
    consecutive_failures: int = 0
    _tracker: Any = field(default=None, repr=False)

    @property
    def last_bbox(self) -> tuple[int, int, int, int] | None:
        if not self.samples:
            return None
        return _sample_bbox(self.samples[-1])

    def median_center(self) -> tuple[float, float]:
        xs = [s["bbox"]["x"] + s["bbox"]["w"] / 2 for s in self.samples]
        ys = [s["bbox"]["y"] + s["bbox"]["h"] / 2 for s in self.samples]
        return median(xs), median(ys)

    def add_sample(
        self,
        *,
        frame_idx: int,
        timestamp_sec: float,
        bbox: tuple[int, int, int, int],
        confidence: float | None,
        source: str,
    ) -> None:
        self.last_frame = frame_idx
        self.last_seen_sec = timestamp_sec
        self.samples.append(
            {
                "frame": frame_idx,
                "timestamp_sec": round(timestamp_sec, 3),
                "bbox": {"x": bbox[0], "y": bbox[1], "w": bbox[2], "h": bbox[3]},
                "confidence": round(confidence, 4) if confidence is not None else None,
                "source": source,
            }
        )


class CharacterTracker:
    def __init__(
        self,
        *,
        min_confidence: float = 0.92,
        detect_interval_frames: int = 24,
        iou_match_threshold: float = 0.20,
        max_tracker_failures: int = 30,
        sample_every_n_frames: int = 5,
        min_track_samples: int = 5,
        reid_gap_sec: float = 8.0,
        merge_center_distance_px: float = 90.0,
        merge_max_gap_sec: float = 10.0,
        expected_characters: int | None = None,
    ):
        self.min_confidence = min_confidence
        self.detect_interval_frames = max(1, detect_interval_frames)
        self.iou_match_threshold = iou_match_threshold
        self.max_tracker_failures = max_tracker_failures
        self.sample_every_n_frames = max(1, sample_every_n_frames)
        self.min_track_samples = min_track_samples
        self.reid_gap_sec = reid_gap_sec
        self.merge_center_distance_px = merge_center_distance_px
        self.merge_max_gap_sec = merge_max_gap_sec
        self.expected_characters = expected_characters

        self._next_id = 1
        self.active_tracks: list[FaceTrack] = []
        self.finished_tracks: list[FaceTrack] = []
        self.recently_retired: list[tuple[FaceTrack, float]] = []
        self.timeline: list[dict[str, Any]] = []

    def _prune_retired(self, now_sec: float) -> None:
        self.recently_retired = [
            (t, ts) for t, ts in self.recently_retired
            if now_sec - ts <= self.reid_gap_sec
        ]

    def _new_track(
        self,
        cv2,
        frame,
        bbox: tuple[int, int, int, int],
        frame_idx: int,
        timestamp_sec: float,
        confidence: float,
        *,
        source: str = "mtcnn",
    ) -> FaceTrack:
        tracker = _create_csrt_tracker(cv2)
        tracker.init(frame, bbox)
        track = FaceTrack(
            character_id=self._next_id,
            first_frame=frame_idx,
            last_frame=frame_idx,
            first_seen_sec=timestamp_sec,
            last_seen_sec=timestamp_sec,
            _tracker=tracker,
        )
        track.add_sample(
            frame_idx=frame_idx,
            timestamp_sec=timestamp_sec,
            bbox=bbox,
            confidence=confidence,
            source=source,
        )
        self._next_id += 1
        self.active_tracks.append(track)
        return track

    def _reactivate_track(
        self,
        cv2,
        frame,
        track: FaceTrack,
        bbox: tuple[int, int, int, int],
        frame_idx: int,
        timestamp_sec: float,
        confidence: float,
    ) -> None:
        tracker = _create_csrt_tracker(cv2)
        tracker.init(frame, bbox)
        track._tracker = tracker
        track.active = True
        track.consecutive_failures = 0
        if track in self.finished_tracks:
            self.finished_tracks.remove(track)
        if track not in self.active_tracks:
            self.active_tracks.append(track)
        self.recently_retired = [(t, ts) for t, ts in self.recently_retired if t is not track]
        if frame_idx % self.sample_every_n_frames == 0:
            track.add_sample(
                frame_idx=frame_idx,
                timestamp_sec=timestamp_sec,
                bbox=bbox,
                confidence=confidence,
                source="reid",
            )

    def _retire_track(self, track: FaceTrack, timestamp_sec: float) -> None:
        track.active = False
        track._tracker = None
        if track in self.active_tracks:
            self.active_tracks.remove(track)
        if track not in self.finished_tracks:
            self.finished_tracks.append(track)
        self.recently_retired.append((track, timestamp_sec))

    def _detect_faces(self, detector, frame_rgb) -> list[dict[str, Any]]:
        raw = detector.detect_faces(frame_rgb)
        faces: list[dict[str, Any]] = []
        for item in raw:
            conf = float(item.get("confidence", 0))
            if conf < self.min_confidence:
                continue
            box = item.get("box")
            if not box:
                continue
            faces.append({"bbox": _bbox_from_mtcnn(box), "confidence": conf})
        return _nms_detections(faces)

    def _match_score(
        self,
        track: FaceTrack,
        det: dict[str, Any],
    ) -> float:
        last = track.last_bbox
        if last is None:
            return 0.0
        iou = _iou(last, det["bbox"])
        tc = _bbox_center(last)
        dc = _bbox_center(det["bbox"])
        dist = math.hypot(tc[0] - dc[0], tc[1] - dc[1])
        dist_score = max(0.0, 1.0 - dist / self.merge_center_distance_px)
        return max(iou, dist_score * 0.85)

    def _try_reid(
        self,
        cv2,
        frame,
        det: dict[str, Any],
        frame_idx: int,
        timestamp_sec: float,
    ) -> bool:
        dc = _bbox_center(det["bbox"])
        best: tuple[float, FaceTrack] | None = None

        for track, retired_at in self.recently_retired:
            if not track.samples:
                continue
            gap = timestamp_sec - track.last_seen_sec
            if gap > self.reid_gap_sec:
                continue
            tc = track.median_center()
            dist = math.hypot(tc[0] - dc[0], tc[1] - dc[1])
            if dist > self.merge_center_distance_px:
                continue
            score = max(0.0, 1.0 - dist / self.merge_center_distance_px)
            if best is None or score > best[0]:
                best = (score, track)

        if best is None:
            return False

        self._reactivate_track(
            cv2, frame, best[1], det["bbox"], frame_idx, timestamp_sec, det["confidence"]
        )
        return True

    def _cull_excess_tracks(
        self,
        detections: list[dict[str, Any]],
        timestamp_sec: float,
    ) -> None:
        """Never keep more active tracks than faces visible right now."""
        if not detections:
            return
        while len(self.active_tracks) > len(detections):
            scored: list[tuple[float, FaceTrack]] = []
            for track in self.active_tracks:
                best = max(
                    (self._match_score(track, det) for det in detections),
                    default=0.0,
                )
                scored.append((best, track))
            scored.sort(key=lambda x: x[0])
            self._retire_track(scored[0][1], timestamp_sec)

    def _associate_and_refresh(
        self,
        cv2,
        frame,
        detections: list[dict[str, Any]],
        frame_idx: int,
        timestamp_sec: float,
    ) -> None:
        self._prune_retired(timestamp_sec)

        pairs: list[tuple[float, int, int]] = []
        for ti, track in enumerate(self.active_tracks):
            for di, det in enumerate(detections):
                score = self._match_score(track, det)
                if score >= self.iou_match_threshold:
                    pairs.append((score, ti, di))

        pairs.sort(reverse=True)
        used_tracks: set[int] = set()
        used_dets: set[int] = set()

        for score, ti, di in pairs:
            if ti in used_tracks or di in used_dets:
                continue
            track = self.active_tracks[ti]
            det = detections[di]
            bbox = det["bbox"]
            tracker = _create_csrt_tracker(cv2)
            tracker.init(frame, bbox)
            track._tracker = tracker
            track.consecutive_failures = 0
            if frame_idx % self.sample_every_n_frames == 0:
                track.add_sample(
                    frame_idx=frame_idx,
                    timestamp_sec=timestamp_sec,
                    bbox=bbox,
                    confidence=det["confidence"],
                    source="mtcnn_refresh",
                )
            used_tracks.add(ti)
            used_dets.add(di)

        for di, det in enumerate(detections):
            if di in used_dets:
                continue
            if self._try_reid(cv2, frame, det, frame_idx, timestamp_sec):
                continue
            self._new_track(
                cv2, frame, det["bbox"], frame_idx, timestamp_sec, det["confidence"]
            )

        for ti, track in enumerate(self.active_tracks):
            if ti not in used_tracks:
                track.consecutive_failures += 1
                if track.consecutive_failures >= self.max_tracker_failures:
                    self._retire_track(track, timestamp_sec)

        self._cull_excess_tracks(detections, timestamp_sec)

    def _update_trackers(
        self,
        frame,
        frame_idx: int,
        timestamp_sec: float,
    ) -> None:
        for track in list(self.active_tracks):
            if track._tracker is None:
                track.consecutive_failures += 1
                if track.consecutive_failures >= self.max_tracker_failures:
                    self._retire_track(track, timestamp_sec)
                continue

            ok, raw_bbox = track._tracker.update(frame)
            if not ok:
                track.consecutive_failures += 1
                if track.consecutive_failures >= self.max_tracker_failures:
                    self._retire_track(track, timestamp_sec)
                continue

            track.consecutive_failures = 0
            x, y, w, h = (int(v) for v in raw_bbox)
            bbox = (x, y, w, h)
            if frame_idx % self.sample_every_n_frames == 0:
                track.add_sample(
                    frame_idx=frame_idx,
                    timestamp_sec=timestamp_sec,
                    bbox=bbox,
                    confidence=None,
                    source="csrt",
                )

    def _record_timeline(self, frame_idx: int, timestamp_sec: float) -> None:
        active_ids = [t.character_id for t in self.active_tracks]
        self.timeline.append(
            {
                "frame": frame_idx,
                "timestamp_sec": round(timestamp_sec, 3),
                "active_character_count": len(active_ids),
                "character_ids": active_ids,
            }
        )

    def process_video(
        self,
        video_path: Path,
        *,
        max_frames: int | None = None,
        progress_every: int = 100,
    ) -> dict[str, Any]:
        try:
            import cv2
        except ImportError as exc:
            raise SystemExit("opencv-contrib-python is required.") from exc

        try:
            from mtcnn import MTCNN
        except ImportError as exc:
            raise RuntimeError(
                "MTCNN not available. Install with:\n"
                "  pip install mtcnn tensorflow"
            ) from exc

        _create_csrt_tracker(cv2)

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise FileNotFoundError(f"Cannot open video: {video_path}")

        fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        frame_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

        if max_frames is not None:
            total_frames = min(total_frames, max_frames) if total_frames else max_frames

        detector = MTCNN()
        started = time.time()
        frame_idx = 0

        print(f"Video: {video_path}")
        print(f"  {frame_w}x{frame_h} @ {fps:.2f} fps  |  ~{total_frames} frames")
        print(f"  MTCNN every {self.detect_interval_frames} frames (~{self.detect_interval_frames / fps:.1f}s)")
        print()

        while True:
            if max_frames is not None and frame_idx >= max_frames:
                break

            ok, frame_bgr = cap.read()
            if not ok:
                break

            timestamp_sec = frame_idx / fps
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

            run_detect = (
                frame_idx % self.detect_interval_frames == 0
                or not self.active_tracks
            )
            if run_detect:
                detections = self._detect_faces(detector, frame_rgb)
                detections = [
                    {
                        "bbox": _clamp_bbox(*d["bbox"], frame_w, frame_h),
                        "confidence": d["confidence"],
                    }
                    for d in detections
                ]
                self._associate_and_refresh(
                    cv2, frame_bgr, detections, frame_idx, timestamp_sec
                )

            self._update_trackers(frame_bgr, frame_idx, timestamp_sec)

            if frame_idx % self.sample_every_n_frames == 0:
                self._record_timeline(frame_idx, timestamp_sec)

            if progress_every and frame_idx > 0 and frame_idx % progress_every == 0:
                pct = (frame_idx / total_frames * 100) if total_frames else 0
                print(
                    f"  frame {frame_idx}/{total_frames} ({pct:.0f}%)  "
                    f"active={len(self.active_tracks)}  raw_ids={self._next_id - 1}",
                    flush=True,
                )

            frame_idx += 1

        cap.release()

        for track in list(self.active_tracks):
            self._retire_track(track, track.last_seen_sec)

        elapsed = time.time() - started
        all_tracks = self.finished_tracks
        merged = merge_fragment_tracks(
            all_tracks,
            center_distance_px=self.merge_center_distance_px,
            max_gap_sec=self.merge_max_gap_sec,
            min_track_samples=self.min_track_samples,
        )

        if self.expected_characters is not None:
            final = cluster_characters_by_position(
                merged["characters"],
                expected=self.expected_characters,
                min_track_samples=self.min_track_samples,
            )
        else:
            final = {
                "character_count": merged["character_count"],
                "characters": merged["characters"],
                "clustered": False,
            }

        tracks_out = []
        for t in sorted(all_tracks, key=lambda x: x.character_id):
            tracks_out.append(_track_to_dict(t))

        return {
            "video": str(video_path.resolve()),
            "fps": round(fps, 3),
            "frame_count": frame_idx,
            "duration_sec": round(frame_idx / fps, 3) if fps else None,
            "frame_size": {"width": frame_w, "height": frame_h},
            "processing_sec": round(elapsed, 2),
            "settings": {
                "min_confidence": self.min_confidence,
                "detect_interval_frames": self.detect_interval_frames,
                "iou_match_threshold": self.iou_match_threshold,
                "max_tracker_failures": self.max_tracker_failures,
                "sample_every_n_frames": self.sample_every_n_frames,
                "min_track_samples": self.min_track_samples,
                "reid_gap_sec": self.reid_gap_sec,
                "merge_center_distance_px": self.merge_center_distance_px,
                "merge_max_gap_sec": self.merge_max_gap_sec,
                "expected_characters": self.expected_characters,
            },
            "unique_character_count": final["character_count"],
            "fragment_count_after_overlap_merge": merged["character_count"],
            "total_raw_tracks": len(all_tracks),
            "characters": final["characters"],
            "fragments": merged["characters"],
            "clustered_to_expected": final["clustered"],
            "tracks": tracks_out,
            "timeline": self.timeline,
        }


def _track_to_dict(track: FaceTrack) -> dict[str, Any]:
    cx, cy = track.median_center()
    return {
        "character_id": track.character_id,
        "first_seen_sec": round(track.first_seen_sec, 3),
        "last_seen_sec": round(track.last_seen_sec, 3),
        "duration_sec": round(track.last_seen_sec - track.first_seen_sec, 3),
        "sample_count": len(track.samples),
        "median_center": {"x": round(cx, 1), "y": round(cy, 1)},
        "counted": len(track.samples) >= 1,
        "samples": track.samples,
    }


def _temporal_overlap_sec(a: FaceTrack, b: FaceTrack) -> float:
    start = max(a.first_seen_sec, b.first_seen_sec)
    end = min(a.last_seen_sec, b.last_seen_sec)
    return max(0.0, end - start)


def _temporal_gap_sec(a: FaceTrack, b: FaceTrack) -> float:
    if a.last_seen_sec < b.first_seen_sec:
        return b.first_seen_sec - a.last_seen_sec
    if b.last_seen_sec < a.first_seen_sec:
        return a.first_seen_sec - b.last_seen_sec
    return 0.0


def _should_merge_tracks(
    a: FaceTrack,
    b: FaceTrack,
    *,
    center_distance_px: float,
    max_gap_sec: float,
) -> bool:
    """Merge only duplicate trackers (overlap + nearby center).

    Gap-based re-id is handled live during tracking; post-merge must not
    chain left/right faces that appear back-to-back at different positions.
    """
    del max_gap_sec
    ac = a.median_center()
    bc = b.median_center()
    dist = math.hypot(ac[0] - bc[0], ac[1] - bc[1])
    if dist > center_distance_px:
        return False
    return _temporal_overlap_sec(a, b) > 0.5


def cluster_characters_by_position(
    characters: list[dict[str, Any]],
    *,
    expected: int,
    min_track_samples: int,
) -> dict[str, Any]:
    """Merge counted characters into *expected* screen-position clusters (e.g. 2 speakers)."""
    counted = [c for c in characters if c["counted"]]
    if len(counted) <= expected:
        return {"character_count": len(counted), "characters": characters, "clustered": False}

    # Weighted k-means (simple Lloyd) on median face centers; weight = duration.
    points = [
        (
            c["median_center"]["x"],
            c["median_center"]["y"],
            max(c["duration_sec"], 0.1),
        )
        for c in counted
    ]

    # Init centroids: spread along x-axis (works well for dialogue shots).
    xs = sorted(p[0] for p in points)
    step = max(1, len(xs) // expected)
    centroids = [(xs[i * step], points[0][1]) for i in range(expected)]

    for _ in range(20):
        groups: list[list[tuple[float, float, float]]] = [[] for _ in range(expected)]
        for x, y, w in points:
            best = min(
                range(expected),
                key=lambda i: (x - centroids[i][0]) ** 2 + (y - centroids[i][1]) ** 2,
            )
            groups[best].append((x, y, w))

        new_centroids: list[tuple[float, float]] = []
        for g in groups:
            if not g:
                new_centroids.append(centroids[len(new_centroids)])
                continue
            tw = sum(w for _, _, w in g)
            cx = sum(x * w for x, _, w in g) / tw
            cy = sum(y * w for _, y, w in g) / tw
            new_centroids.append((cx, cy))
        if new_centroids == centroids:
            break
        centroids = new_centroids

    # Assign each counted fragment to nearest centroid.
    assignments: list[list[dict[str, Any]]] = [[] for _ in range(expected)]
    for char in counted:
        x, y = char["median_center"]["x"], char["median_center"]["y"]
        best = min(
            range(expected),
            key=lambda i: (x - centroids[i][0]) ** 2 + (y - centroids[i][1]) ** 2,
        )
        assignments[best].append(char)

    clustered: list[dict[str, Any]] = []
    for idx, group in enumerate(assignments, start=1):
        if not group:
            continue
        member_ids: list[int] = []
        for g in group:
            member_ids.extend(g["merged_from_track_ids"])
        total_samples = sum(g["total_samples"] for g in group)
        first_seen = min(g["first_seen_sec"] for g in group)
        last_seen = max(g["last_seen_sec"] for g in group)
        cx = median([g["median_center"]["x"] for g in group])
        cy = median([g["median_center"]["y"] for g in group])
        clustered.append(
            {
                "character_id": idx,
                "merged_from_track_ids": sorted(set(member_ids)),
                "merged_from_fragment_ids": [g["character_id"] for g in group],
                "first_seen_sec": round(first_seen, 3),
                "last_seen_sec": round(last_seen, 3),
                "duration_sec": round(last_seen - first_seen, 3),
                "total_samples": total_samples,
                "median_center": {"x": round(cx, 1), "y": round(cy, 1)},
                "counted": total_samples >= min_track_samples,
            }
        )

    return {
        "character_count": sum(1 for c in clustered if c["counted"]),
        "characters": clustered,
        "clustered": True,
    }


def merge_fragment_tracks(
    tracks: list[FaceTrack],
    *,
    center_distance_px: float,
    max_gap_sec: float,
    min_track_samples: int,
) -> dict[str, Any]:
    """Cluster fragmented raw tracks into real on-screen characters."""
    n = len(tracks)
    if n == 0:
        return {"character_count": 0, "characters": []}

    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for i in range(n):
        for j in range(i + 1, n):
            if _should_merge_tracks(
                tracks[i],
                tracks[j],
                center_distance_px=center_distance_px,
                max_gap_sec=max_gap_sec,
            ):
                union(i, j)

    groups: dict[int, list[FaceTrack]] = {}
    for i, track in enumerate(tracks):
        groups.setdefault(find(i), []).append(track)

    characters: list[dict[str, Any]] = []
    for idx, group in enumerate(sorted(groups.values(), key=lambda g: min(t.first_seen_sec for t in g)), start=1):
        member_ids = sorted(t.character_id for t in group)
        total_samples = sum(len(t.samples) for t in group)
        first_seen = min(t.first_seen_sec for t in group)
        last_seen = max(t.last_seen_sec for t in group)
        cx = median([t.median_center()[0] for t in group])
        cy = median([t.median_center()[1] for t in group])
        counted = total_samples >= min_track_samples
        characters.append(
            {
                "character_id": idx,
                "merged_from_track_ids": member_ids,
                "first_seen_sec": round(first_seen, 3),
                "last_seen_sec": round(last_seen, 3),
                "duration_sec": round(last_seen - first_seen, 3),
                "total_samples": total_samples,
                "median_center": {"x": round(cx, 1), "y": round(cy, 1)},
                "counted": counted,
            }
        )

    counted_chars = [c for c in characters if c["counted"]]
    return {
        "character_count": len(counted_chars),
        "characters": characters,
    }


def _write_summary_txt(report: dict[str, Any], path: Path) -> None:
    lines = [
        f"Video: {report['video']}",
        f"Duration: {report['duration_sec']}s  |  FPS: {report['fps']}",
        f"Unique characters: {report['unique_character_count']}",
        f"Fragments after overlap-merge: {report.get('fragment_count_after_overlap_merge', '?')}",
        f"Raw fragmented tracks: {report['total_raw_tracks']}",
        "",
        "Characters:",
    ]
    for char in report["characters"]:
        flag = "counted" if char["counted"] else "ignored (too brief)"
        ids = ", ".join(f"#{i:02d}" for i in char["merged_from_track_ids"])
        lines.append(
            f"  Character {char['character_id']}  {char['first_seen_sec']:7.1f}s - {char['last_seen_sec']:7.1f}s  "
            f"center=({char['median_center']['x']:.0f},{char['median_center']['y']:.0f})  "
            f"from tracks [{ids}]  [{flag}]"
        )
    if report.get("fragments"):
        lines.extend(["", "Fragments (pre-cluster):"])
        for char in report["fragments"]:
            ids = ", ".join(f"#{i:02d}" for i in char["merged_from_track_ids"])
            lines.append(
                f"  Fragment {char['character_id']}  center=({char['median_center']['x']:.0f},{char['median_center']['y']:.0f})  "
                f"tracks [{ids}]"
            )
    lines.extend(["", "Raw tracks (pre-merge):"])
    for track in report["tracks"]:
        lines.append(
            f"  #{track['character_id']:02d}  {track['first_seen_sec']:7.1f}s - {track['last_seen_sec']:7.1f}s  "
            f"center=({track['median_center']['x']:.0f},{track['median_center']['y']:.0f})  "
            f"({track['sample_count']} samples)"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Track faces/characters in video with MTCNN detection + CSRT tracking."
    )
    parser.add_argument("--video", required=True, type=Path, help="Input video path")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("./character_tracks"),
        help="Directory for JSON report + summary (default: ./character_tracks)",
    )
    parser.add_argument(
        "--detect-interval",
        type=float,
        default=1.0,
        help="Run MTCNN every N seconds (default: 1.0)",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.92,
        help="MTCNN minimum face confidence (default: 0.92)",
    )
    parser.add_argument(
        "--sample-every",
        type=int,
        default=5,
        help="Record bbox coordinates every N frames (default: 5)",
    )
    parser.add_argument(
        "--min-track-samples",
        type=int,
        default=5,
        help="Minimum total samples for a merged character to count (default: 5)",
    )
    parser.add_argument(
        "--merge-distance",
        type=float,
        default=90.0,
        help="Merge overlapping tracks within N pixels (duplicate trackers only, default: 90)",
    )
    parser.add_argument(
        "--expected-characters",
        type=int,
        default=2,
        help="Collapse fragments into N screen-position clusters (default: 2). Use 0 to disable.",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Optional cap for quick testing (process only first N frames)",
    )
    args = parser.parse_args(argv)

    if not args.video.is_file():
        print(f"Video not found: {args.video}", file=sys.stderr)
        return 1

    try:
        import cv2
    except ImportError:
        print("Install opencv-contrib-python: pip install opencv-contrib-python", file=sys.stderr)
        return 1

    cap = cv2.VideoCapture(str(args.video))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    cap.release()
    detect_interval_frames = max(1, int(round(args.detect_interval * fps)))

    tracker = CharacterTracker(
        min_confidence=args.min_confidence,
        detect_interval_frames=detect_interval_frames,
        sample_every_n_frames=args.sample_every,
        min_track_samples=args.min_track_samples,
        merge_center_distance_px=args.merge_distance,
        expected_characters=args.expected_characters or None,
    )

    try:
        report = tracker.process_video(args.video, max_frames=args.max_frames)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "character_tracks.json"
    txt_path = args.output_dir / "character_tracks_summary.txt"

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    _write_summary_txt(report, txt_path)

    print()
    print(f"Unique characters:          {report['unique_character_count']}")
    print(f"Fragments (overlap-merge):  {report.get('fragment_count_after_overlap_merge', '?')}")
    print(f"Raw fragmented tracks:      {report['total_raw_tracks']}")
    print(f"Report:  {json_path.resolve()}")
    print(f"Summary: {txt_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
