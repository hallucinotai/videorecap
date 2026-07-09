"""Extract per-utterance audio clips from a source WAV using turn timing."""

from __future__ import annotations

import os
import wave
from typing import Any

MIN_UTTERANCE_DURATION_SEC = 0.4


def utterance_clip_path(assets_dir: str, utterance_id: str) -> str:
    return os.path.join(assets_dir, "utterance_audio", f"{utterance_id}.wav")


def _clip_wav(
    source_path: str,
    *,
    start_sec: float,
    end_sec: float,
    output_path: str,
    min_duration_sec: float,
) -> str | None:
    duration = float(end_sec) - float(start_sec)
    if duration < min_duration_sec:
        return None

    with wave.open(source_path, "rb") as src:
        sample_rate = src.getframerate()
        start_frame = max(0, int(float(start_sec) * sample_rate))
        end_frame = min(src.getnframes(), int(float(end_sec) * sample_rate))
        if end_frame <= start_frame:
            return None
        if (end_frame - start_frame) / sample_rate < min_duration_sec:
            return None

        src.setpos(start_frame)
        frames = src.readframes(end_frame - start_frame)
        params = src.getparams()

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with wave.open(output_path, "wb") as out:
        out.setparams(params)
        out.writeframes(frames)
    return output_path


def _clip_with_pydub(
    source_path: str,
    *,
    start_sec: float,
    end_sec: float,
    output_path: str,
    min_duration_sec: float,
) -> str | None:
    try:
        from pydub import AudioSegment
    except ImportError as exc:
        raise ImportError(
            "pydub is required for non-WAV utterance audio clipping. Install with: pip install pydub"
        ) from exc

    audio = AudioSegment.from_file(source_path)
    start_ms = max(0, int(float(start_sec) * 1000))
    end_ms = min(len(audio), int(float(end_sec) * 1000))
    if end_ms <= start_ms:
        return None

    clip = audio[start_ms:end_ms]
    if clip.duration_seconds < min_duration_sec:
        return None

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    clip.export(output_path, format="wav")
    return output_path


def clip_utterance(
    source_path: str,
    *,
    start_sec: float,
    end_sec: float,
    output_path: str,
    min_duration_sec: float = MIN_UTTERANCE_DURATION_SEC,
) -> str | None:
    """Clip [start_sec, end_sec] from source audio. Returns output_path or None if too short."""
    if not os.path.isfile(source_path):
        raise FileNotFoundError(f"Source audio not found: {source_path}")

    ext = os.path.splitext(source_path)[1].lower()
    if ext == ".wav":
        return _clip_wav(
            source_path,
            start_sec=start_sec,
            end_sec=end_sec,
            output_path=output_path,
            min_duration_sec=min_duration_sec,
        )
    return _clip_with_pydub(
        source_path,
        start_sec=start_sec,
        end_sec=end_sec,
        output_path=output_path,
        min_duration_sec=min_duration_sec,
    )


def clip_utterances(
    source_path: str,
    utterances: list[dict[str, Any]],
    *,
    assets_dir: str,
    min_duration_sec: float = MIN_UTTERANCE_DURATION_SEC,
) -> dict[str, str | None]:
    """Return utterance_id -> clip path (or None when skipped)."""
    clips: dict[str, str | None] = {}
    for utterance in utterances:
        uid = utterance.get("id")
        if not uid:
            continue
        output_path = utterance_clip_path(assets_dir, str(uid))
        clips[str(uid)] = clip_utterance(
            source_path,
            start_sec=float(utterance.get("start", 0)),
            end_sec=float(utterance.get("end", 0)),
            output_path=output_path,
            min_duration_sec=min_duration_sec,
        )
    return clips
