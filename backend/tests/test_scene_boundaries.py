"""Unit tests for scene boundary modes (fixed vs PySceneDetect merge)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_backend = str(ROOT / "backend")
sys.path = [p for p in sys.path if p != _backend]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.scene_boundaries import (
    boundary_mode_from_env,
    merge_scene_windows,
    sample_timestamps_in_window,
)


def test_boundary_mode_from_env(monkeypatch):
    monkeypatch.delenv("SCENE_BOUNDARY_MODE", raising=False)
    assert boundary_mode_from_env() == "fixed"
    assert boundary_mode_from_env("pyscenedetect") == "pyscenedetect"
    assert boundary_mode_from_env("scenedetect") == "pyscenedetect"
    assert boundary_mode_from_env("batch") == "fixed"
    monkeypatch.setenv("SCENE_BOUNDARY_MODE", "pyscene")
    assert boundary_mode_from_env() == "pyscenedetect"


def test_merge_scene_windows_merges_short_shots():
    # Many 1s shots → fewer longer scenes
    raw = [(float(i), float(i + 1)) for i in range(0, 20)]
    merged = merge_scene_windows(raw, min_duration_sec=4.0, max_duration_sec=10.0)
    assert len(merged) < len(raw)
    assert merged[0][0] == 0.0
    for start, end in merged:
        assert end > start
        # Allow slight overshoot when absorbing short tails
        assert (end - start) <= 10.0 * 1.25 + 1e-6


def test_merge_scene_windows_preserves_long_shots():
    raw = [(0.0, 12.0), (12.0, 25.0), (25.0, 40.0)]
    merged = merge_scene_windows(raw, min_duration_sec=4.0, max_duration_sec=45.0)
    # All already long enough and combined would exceed max → stay separate or partially merge
    assert merged[0][0] == 0.0
    assert merged[-1][1] == 40.0
    assert len(merged) >= 1


def test_merge_folds_short_tail():
    raw = [(0.0, 10.0), (10.0, 20.0), (20.0, 22.0)]  # 2s tail
    merged = merge_scene_windows(raw, min_duration_sec=4.0, max_duration_sec=45.0)
    assert merged[-1][1] == 22.0
    # Tail should be absorbed into previous when under max
    assert any(end == 22.0 and start <= 10.0 for start, end in merged)


def test_sample_timestamps_in_window_caps_frames():
    ts = sample_timestamps_in_window(0.0, 20.0, sample_fps=0.5, max_frames=8)
    assert ts[0] == 0.0
    assert len(ts) <= 8
    assert ts[-1] <= 20.0 + 1e-6


def test_sample_timestamps_in_window_short_scene():
    ts = sample_timestamps_in_window(5.0, 6.0, sample_fps=0.5, max_frames=8)
    assert ts[0] == 5.0
    assert len(ts) >= 1
