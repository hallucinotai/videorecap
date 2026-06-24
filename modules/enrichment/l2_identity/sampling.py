"""Generate sample timestamps inside utterances from word chunks or uniform spacing."""

from __future__ import annotations

from typing import Any

DEFAULT_WORDS_PER_CHUNK = 3
DEFAULT_UNIFORM_INTERVAL_SEC = 1.0
MIN_CHUNK_DURATION_SEC = 0.15


def sample_timestamps_for_utterance(
    utterance: dict[str, Any],
    *,
    words_per_chunk: int = DEFAULT_WORDS_PER_CHUNK,
    uniform_interval_sec: float = DEFAULT_UNIFORM_INTERVAL_SEC,
) -> list[dict[str, Any]]:
    """
    Return sample points inside [start, end] for lip/face analysis.

    Prefers AssemblyAI word timestamps grouped into 3–4 word chunks; falls back
    to ~1 fps uniform sampling within the utterance.
    """
    start = float(utterance["start"])
    end = float(utterance["end"])
    words = utterance.get("words") or []

    if words and len(words) >= 2:
        chunks = _word_chunk_samples(words, words_per_chunk=words_per_chunk)
        if chunks:
            return [
                {
                    "timestamp_sec": round(c["timestamp_sec"], 3),
                    "chunk_text": c["chunk_text"],
                    "method": "word_chunks",
                    "word_start_idx": c["word_start_idx"],
                    "word_end_idx": c["word_end_idx"],
                }
                for c in chunks
                if start <= c["timestamp_sec"] <= end
            ]

    return _uniform_samples(start, end, uniform_interval_sec)


def _word_chunk_samples(words: list[dict[str, Any]], words_per_chunk: int) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    n = len(words)
    i = 0
    while i < n:
        group = words[i : i + words_per_chunk]
        if not group:
            break
        w_start = float(group[0].get("start", 0))
        w_end = float(group[-1].get("end", w_start))
        if w_end - w_start < MIN_CHUNK_DURATION_SEC and len(group) < n - i:
            # Extend chunk slightly for very short groups
            extended = words[i : min(n, i + words_per_chunk + 1)]
            group = extended
            w_end = float(group[-1].get("end", w_start))
        center = (w_start + w_end) / 2.0
        text = " ".join(str(w.get("text", "")).strip() for w in group if w.get("text"))
        chunks.append(
            {
                "timestamp_sec": center,
                "chunk_text": text,
                "word_start_idx": i,
                "word_end_idx": i + len(group) - 1,
            }
        )
        i += words_per_chunk
    return chunks


def _uniform_samples(start: float, end: float, interval_sec: float) -> list[dict[str, Any]]:
    if end <= start:
        return []

    duration = end - start
    samples: list[dict[str, Any]] = []

    if duration <= interval_sec:
        center = (start + end) / 2.0
        samples.append(
            {
                "timestamp_sec": round(center, 3),
                "chunk_text": None,
                "method": "utterance_midpoint",
            }
        )
        return samples

    t = start + min(0.5, duration * 0.1)
    while t < end - 0.05:
        samples.append(
            {
                "timestamp_sec": round(t, 3),
                "chunk_text": None,
                "method": "uniform_1fps",
            }
        )
        t += interval_sec
    return samples
