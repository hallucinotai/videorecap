"""Tests for utterance-scoped timestamp sampling."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.enrichment.l2_identity.sampling import sample_timestamps_for_utterance


def test_word_chunk_sampling():
    utterance = {
        "start": 80.28,
        "end": 86.78,
        "text": "No. No, do not do that, okay? Don't.",
        "words": [
            {"text": "No.", "start": 80.28, "end": 80.9},
            {"text": "No,", "start": 81.0, "end": 81.5},
            {"text": "do", "start": 82.1, "end": 82.3},
            {"text": "not", "start": 82.35, "end": 82.5},
            {"text": "do", "start": 82.55, "end": 82.7},
            {"text": "that,", "start": 82.75, "end": 83.2},
            {"text": "okay?", "start": 84.2, "end": 84.8},
            {"text": "Don't.", "start": 85.6, "end": 86.5},
        ],
    }
    samples = sample_timestamps_for_utterance(utterance, words_per_chunk=3)
    assert len(samples) >= 2
    assert all(s["method"] == "word_chunks" for s in samples)
    assert all(80.28 <= s["timestamp_sec"] <= 86.78 for s in samples)
    assert samples[0]["chunk_text"]


def test_uniform_fallback_without_words():
    utterance = {"start": 80.0, "end": 86.0, "text": "hello world"}
    samples = sample_timestamps_for_utterance(utterance, uniform_interval_sec=1.0)
    assert len(samples) >= 5
    assert samples[0]["method"] == "uniform_1fps"


def test_short_utterance_midpoint():
    utterance = {"start": 1.0, "end": 1.4, "text": "Hi"}
    samples = sample_timestamps_for_utterance(utterance)
    assert len(samples) == 1
    assert samples[0]["method"] == "utterance_midpoint"
