"""Scene / shot boundary helpers for scene understanding.

Two strategies feed the same vision describe path:
  - fixed: uniform time windows (handled in scene_understanding)
  - pyscenedetect: ContentDetector cuts, then merge short adjacent shots,
    then hard-split any window longer than SCENE_MAX_DURATION_SEC
"""

from __future__ import annotations

import logging
import math
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_BOUNDARY_MODE = "fixed"
DEFAULT_DETECT_THRESHOLD = 27.0
DEFAULT_MIN_SCENE_SEC = 4.0
DEFAULT_MAX_SCENE_SEC = 45.0
# Safety cap for vision API calls when duration * sample_fps is large.
DEFAULT_MAX_FRAMES_PER_SCENE = 48


def boundary_mode_from_env(override: str | None = None) -> str:
    raw = (override if override is not None else os.environ.get("SCENE_BOUNDARY_MODE") or "").strip().lower()
    if not raw:
        return DEFAULT_BOUNDARY_MODE
    if raw in ("fixed", "batch", "time", "uniform"):
        return "fixed"
    if raw in ("pyscenedetect", "pyscene", "scenedetect", "detect", "shots"):
        return "pyscenedetect"
    logger.warning("Unknown SCENE_BOUNDARY_MODE=%r; using %s", raw, DEFAULT_BOUNDARY_MODE)
    return DEFAULT_BOUNDARY_MODE


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(str(raw).strip())
    except ValueError:
        return default


def pyscenedetect_available() -> dict[str, Any]:
    status: dict[str, Any] = {"scenedetect": False, "error": None}
    try:
        from scenedetect import detect  # noqa: F401
        from scenedetect.detectors import ContentDetector  # noqa: F401

        status["scenedetect"] = True
    except ImportError as exc:
        status["error"] = str(exc)
    return status


def detect_raw_scenes_pyscenedetect(
    video_path: str | Path,
    *,
    threshold: float | None = None,
    max_duration: float | None = None,
) -> list[tuple[float, float]]:
    """
    Run PySceneDetect ContentDetector; return raw shot windows (start_sec, end_sec).

    Raises RuntimeError if scenedetect is not installed.
    """
    try:
        from scenedetect import detect
        from scenedetect.detectors import ContentDetector
    except ImportError as exc:
        raise RuntimeError(
            "pyscenedetect_unavailable: pip install scenedetect"
        ) from exc

    path = Path(video_path)
    if not path.is_file():
        raise FileNotFoundError(f"Video not found: {path}")

    resolved_threshold = (
        threshold if threshold is not None else _env_float("SCENE_DETECT_THRESHOLD", DEFAULT_DETECT_THRESHOLD)
    )

    scene_list = detect(str(path), ContentDetector(threshold=resolved_threshold))

    # Duration fallback if detector returns nothing
    duration: float | None = None
    try:
        from scenedetect import open_video

        video = open_video(str(path))
        if video.duration is not None:
            duration = float(video.duration.get_seconds())
    except Exception:
        duration = None

    windows: list[tuple[float, float]] = []
    for start_tc, end_tc in scene_list:
        start = float(start_tc.get_seconds())
        end = float(end_tc.get_seconds())
        if max_duration is not None:
            if start >= max_duration:
                break
            end = min(end, max_duration)
        if end > start + 1e-3:
            windows.append((round(start, 3), round(end, 3)))

    if not windows and duration and duration > 0:
        end = min(duration, max_duration) if max_duration is not None else duration
        windows = [(0.0, round(end, 3))]

    logger.info(
        "PySceneDetect: video=%s threshold=%.1f raw_scenes=%d duration=%.1fs",
        path.name,
        resolved_threshold,
        len(windows),
        duration or 0.0,
    )
    return windows


def merge_scene_windows(
    windows: list[tuple[float, float]],
    *,
    min_duration_sec: float | None = None,
    max_duration_sec: float | None = None,
) -> list[tuple[float, float]]:
    """
    Merge consecutive short PySceneDetect shots into longer scene windows.

    Rules:
      - Walk shots in order; accumulate into a current scene.
      - Close current scene when adding the next shot would exceed max_duration_sec
        (and current already meets min_duration_sec), OR when current already
        exceeds max_duration_sec.
      - Always merge a shot shorter than min into the current/previous scene when possible.
      - Final scene is always emitted.
    """
    if not windows:
        return []

    min_d = (
        min_duration_sec
        if min_duration_sec is not None
        else _env_float("SCENE_MIN_DURATION_SEC", DEFAULT_MIN_SCENE_SEC)
    )
    max_d = (
        max_duration_sec
        if max_duration_sec is not None
        else _env_float("SCENE_MAX_DURATION_SEC", DEFAULT_MAX_SCENE_SEC)
    )
    if max_d < min_d:
        max_d = min_d

    merged: list[tuple[float, float]] = []
    cur_start, cur_end = windows[0]

    for start, end in windows[1:]:
        cur_len = cur_end - cur_start
        next_len = end - start
        combined_len = end - cur_start

        # Prefer merging short shots into the current scene.
        if cur_len < min_d or next_len < min_d:
            if combined_len <= max_d * 1.25:
                # Allow slight overshoot when absorbing a short shot.
                cur_end = end
                continue
            # Current is short but combining blows past max — close and start new.
            merged.append((cur_start, cur_end))
            cur_start, cur_end = start, end
            continue

        if combined_len <= max_d:
            cur_end = end
            continue

        merged.append((cur_start, cur_end))
        cur_start, cur_end = start, end

    merged.append((cur_start, cur_end))

    # Second pass: fold any remaining undersized tail into previous when possible.
    if len(merged) >= 2:
        last_start, last_end = merged[-1]
        if (last_end - last_start) < min_d:
            prev_start, prev_end = merged[-2]
            if (last_end - prev_start) <= max_d * 1.25:
                merged[-2] = (prev_start, last_end)
                merged.pop()

    logger.info(
        "Scene merge: raw=%d → merged=%d (min=%.1fs max=%.1fs)",
        len(windows),
        len(merged),
        min_d,
        max_d,
    )
    return [(round(s, 3), round(e, 3)) for s, e in merged]


def split_windows_by_max_duration(
    windows: list[tuple[float, float]],
    *,
    max_duration_sec: float | None = None,
) -> list[tuple[float, float]]:
    """
    Hard-split any window longer than max_duration_sec into consecutive chunks.

    Merge only limits how far short shots are combined; a single long PySceneDetect
    shot can still exceed max. This pass enforces the ceiling.
    """
    max_d = (
        max_duration_sec
        if max_duration_sec is not None
        else _env_float("SCENE_MAX_DURATION_SEC", DEFAULT_MAX_SCENE_SEC)
    )
    if max_d <= 0:
        return [(round(s, 3), round(e, 3)) for s, e in windows]

    out: list[tuple[float, float]] = []
    for start, end in windows:
        if end <= start + 1e-3:
            continue
        duration = end - start
        if duration <= max_d + 1e-6:
            out.append((round(start, 3), round(end, 3)))
            continue
        t = start
        while t < end - 1e-6:
            chunk_end = min(t + max_d, end)
            if chunk_end > t + 1e-3:
                out.append((round(t, 3), round(chunk_end, 3)))
            t = chunk_end

    if len(out) != len(windows):
        logger.info(
            "Scene split: %d → %d windows (max=%.1fs)",
            len(windows),
            len(out),
            max_d,
        )
    return out


def frame_count_for_duration(
    duration_sec: float,
    sample_fps: float,
    *,
    min_frames: int = 1,
    max_frames: int | None = None,
) -> int:
    """
    Choose how many frames to sample for a scene window from its duration.

    Ideal count is ceil(duration * sample_fps); clamped to [min_frames, max_frames].
    """
    if duration_sec <= 0:
        return max(1, min_frames)
    fps = sample_fps if sample_fps > 0 else 0.5
    n = max(min_frames, int(math.ceil(duration_sec * fps)))
    if max_frames is not None and max_frames > 0:
        n = min(n, max_frames)
    return n


def max_frames_per_scene_from_env() -> int | None:
    """
    Hard cap for frames sent in one vision call.

    - unset / invalid → default (48)
    - 0 → no cap (duration × sample_fps only)
    - >0 → that cap
    """
    raw = os.environ.get("SCENE_MAX_FRAMES_PER_SCENE")
    if raw is None or not str(raw).strip():
        return DEFAULT_MAX_FRAMES_PER_SCENE
    try:
        value = int(str(raw).strip().split()[0])  # tolerate inline comments
    except ValueError:
        return DEFAULT_MAX_FRAMES_PER_SCENE
    if value == 0:
        return None
    if value < 0:
        return DEFAULT_MAX_FRAMES_PER_SCENE
    return value


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = int(str(raw).strip().split()[0])
    except ValueError:
        return default
    return value if value > 0 else default


def sample_timestamps_in_window(
    start_sec: float,
    end_sec: float,
    *,
    sample_fps: float,
    max_frames: int,
) -> list[float]:
    """Evenly sample timestamps inside [start_sec, end_sec], capped at max_frames."""
    if end_sec <= start_sec:
        return [round(start_sec, 3)]
    if sample_fps <= 0:
        sample_fps = 0.5
    if max_frames <= 0:
        max_frames = 8

    interval = 1.0 / sample_fps
    timestamps: list[float] = []
    t = start_sec
    # Include start; stop at/before end.
    while t <= end_sec + 1e-6:
        timestamps.append(round(t, 3))
        t += interval
    if not timestamps:
        timestamps = [round(start_sec, 3)]
    # Always include end if distinct.
    if timestamps[-1] < end_sec - 0.05:
        timestamps.append(round(end_sec, 3))

    if len(timestamps) <= max_frames:
        return timestamps

    # Downsample evenly to max_frames (keep first and last).
    if max_frames == 1:
        return [timestamps[0]]
    out: list[float] = []
    last_idx = len(timestamps) - 1
    for i in range(max_frames):
        idx = round(i * last_idx / (max_frames - 1))
        ts = timestamps[idx]
        if not out or out[-1] != ts:
            out.append(ts)
    return out


def detect_merged_scenes(
    video_path: str | Path,
    *,
    threshold: float | None = None,
    min_duration_sec: float | None = None,
    max_duration_sec: float | None = None,
    max_duration: float | None = None,
) -> list[tuple[float, float]]:
    """Detect shots with PySceneDetect, merge short ones, then hard-split long ones."""
    raw = detect_raw_scenes_pyscenedetect(
        video_path,
        threshold=threshold,
        max_duration=max_duration,
    )
    merged = merge_scene_windows(
        raw,
        min_duration_sec=min_duration_sec,
        max_duration_sec=max_duration_sec,
    )
    return split_windows_by_max_duration(
        merged,
        max_duration_sec=max_duration_sec,
    )
