"""Tests for scene understanding inject + recap prompt guidance (no live vision)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
# Prefer repo-root modules over backend/modules when both exist on path.
_backend = str(ROOT / "backend")
sys.path = [p for p in sys.path if p != _backend]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Stub moviepy before importing modules.video_processing (media stack not needed).
sys.modules.setdefault("moviepy", MagicMock())
sys.modules.setdefault("moviepy.editor", MagicMock())

from modules.scene_understanding import (
    build_narration_scene_fields,
    inject_scene_into_transcript_doc,
    inject_scene_into_transcript_file,
    scene_understanding_enabled,
)


def _fake_scene_result() -> dict:
    return {
        "method": "scene_understanding_v1",
        "model": "gpt-4o",
        "narrative": "A person walks into a room and waves. " * 20,
        "segments": [
            {
                "batch_index": 0,
                "start_sec": 0.0,
                "end_sec": 4.0,
                "description": "Wide shot of an empty hallway.",
            },
            {
                "batch_index": 1,
                "start_sec": 4.0,
                "end_sec": 8.0,
                "description": "Someone enters and waves at the camera.",
            },
        ],
    }


def test_scene_understanding_enabled(monkeypatch):
    monkeypatch.delenv("ENABLE_SCENE_UNDERSTANDING", raising=False)
    assert scene_understanding_enabled() is False
    monkeypatch.setenv("ENABLE_SCENE_UNDERSTANDING", "true")
    assert scene_understanding_enabled() is True
    monkeypatch.setenv("ENABLE_SCENE_UNDERSTANDING", "0")
    assert scene_understanding_enabled() is False


def test_build_narration_scene_fields_truncates():
    fields = build_narration_scene_fields(
        _fake_scene_result(),
        summary_max_chars=80,
        segment_desc_max_chars=20,
    )
    assert fields["scene_method"] == "scene_understanding_v1"
    assert fields["scene_model"] == "gpt-4o"
    assert len(fields["scene_summary"]) <= 80
    assert fields["scene_summary"].endswith("…")
    assert len(fields["scene_segments"]) == 2
    assert fields["scene_segments"][0]["start"] == 0.0
    assert fields["scene_segments"][0]["end"] == 4.0
    assert len(fields["scene_segments"][0]["description"]) <= 20


def test_inject_scene_into_transcript_doc():
    doc = {"narration_context": {"cast_summary": "Ada (Speaker A)"}, "L1_transcript": {}}
    updated = inject_scene_into_transcript_doc(doc, _fake_scene_result())
    ctx = updated["narration_context"]
    assert ctx["cast_summary"] == "Ada (Speaker A)"
    assert "scene_summary" in ctx
    assert len(ctx["scene_segments"]) == 2


def test_inject_scene_into_transcript_file(tmp_path):
    path = tmp_path / "enrichment_L4.json"
    path.write_text(json.dumps({"narration_context": {}}), encoding="utf-8")
    dest = inject_scene_into_transcript_file(path, _fake_scene_result())
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data["narration_context"]["scene_method"] == "scene_understanding_v1"


def test_generate_recap_includes_scene_guidance(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    from modules.video_processing import generate_recap_suggestions

    transcript = {
        "narration_context": {
            "scene_summary": "VISUAL_SCENE_MARKER: person waves in hallway",
            "scene_segments": [
                {"start": 0.0, "end": 5.0, "description": "hallway wave"},
            ],
        },
        "L1_transcript": {
            "utterances": [
                {"id": "u1", "start": 0.0, "end": 5.0, "text": "Hello there", "speaker": "A", "confidence": 0.9},
                {"id": "u2", "start": 5.0, "end": 10.0, "text": "How are you", "speaker": "B", "confidence": 0.9},
            ]
        },
        "segments": {
            "0": {"start": 0.0, "end": 5.0, "text": "Hello there", "speaker": "A"},
            "1": {"start": 5.0, "end": 10.0, "text": "How are you", "speaker": "B"},
        },
    }
    transcript_path = tmp_path / "transcript.json"
    transcript_path.write_text(json.dumps(transcript), encoding="utf-8")

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    clip_response = MagicMock()
    clip_response.choices = [
        MagicMock(
            message=MagicMock(
                content=json.dumps(
                    {
                        "clip_timings": [
                            {"start": 0.0, "end": 15.0, "reason": "intro"},
                            {"start": 15.0, "end": 30.0, "reason": "outro"},
                        ]
                    }
                )
            )
        )
    ]
    narr_response = MagicMock()
    narr_response.choices = [
        MagicMock(
            message=MagicMock(
                content=json.dumps({"recap_text": "This is a short recap narration about waving."})
            )
        )
    ]

    with patch("openai.OpenAI") as mock_openai:
        client = MagicMock()
        mock_openai.return_value = client
        client.chat.completions.create.side_effect = [clip_response, narr_response]
        result_path = generate_recap_suggestions(
            str(transcript_path),
            target_duration=30,
            output_dir=str(out_dir),
        )

    assert Path(result_path).is_file()
    clip_user = client.chat.completions.create.call_args_list[0].kwargs["messages"][1]["content"]
    narr_user = client.chat.completions.create.call_args_list[1].kwargs["messages"][1]["content"]
    assert "VISUAL_SCENE_MARKER" in clip_user
    assert "VISUAL_SCENE_MARKER" in narr_user
