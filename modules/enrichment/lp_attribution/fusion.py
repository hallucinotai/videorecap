"""Score combiner for LP.S3 multimodal speaker attribution."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

WEIGHT_LLM = 0.35
WEIGHT_VISUAL = 0.40
WEIGHT_DIARIZATION = 0.25
WEIGHT_DIARIZATION_MISMATCH = 0.15


def _speaker_char_map(l2_identity: dict[str, Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for speaker_id, profile in l2_identity.items():
        if not speaker_id or str(speaker_id).startswith("_"):
            continue
        cluster = (profile.get("face") or {}).get("cluster_id")
        if cluster:
            mapping[str(speaker_id)] = str(cluster)
    return mapping


def _char_speaker_map(
    speaker_character_votes: dict[str, dict[str, float]],
) -> dict[str, str]:
    """Dominant diarization speaker per visual character."""
    result: dict[str, str] = {}
    char_weights: dict[str, Counter] = defaultdict(Counter)
    for speaker_id, char_votes in speaker_character_votes.items():
        for char_id, weight in (char_votes or {}).items():
            char_weights[str(char_id)][str(speaker_id)] += float(weight or 0)
    for char_id, counter in char_weights.items():
        if counter:
            result[char_id] = counter.most_common(1)[0][0]
    return result


def build_speaker_merge_suggestions(
    l2_identity: dict[str, Any],
    speaker_character_votes: dict[str, dict[str, float]],
) -> list[dict[str, Any]]:
    """Suggest merging diarization labels that map to the same visual cluster."""
    char_by_speaker = _speaker_char_map(l2_identity)
    cluster_to_speakers: dict[str, list[str]] = defaultdict(list)
    for speaker_id, char_id in char_by_speaker.items():
        cluster_to_speakers[char_id].append(speaker_id)

    suggestions: list[dict[str, Any]] = []
    for char_id, speakers in sorted(cluster_to_speakers.items()):
        if len(speakers) < 2:
            continue
        weights = {
            sp: sum((speaker_character_votes.get(sp) or {}).values())
            for sp in speakers
        }
        canonical = max(weights, key=weights.get)
        for speaker_id in speakers:
            if speaker_id == canonical:
                continue
            suggestions.append(
                {
                    "from_speaker": speaker_id,
                    "to_speaker": canonical,
                    "character_id": char_id,
                    "reason": "shared_visual_cluster",
                    "confidence": round(
                        weights.get(speaker_id, 0) / max(sum(weights.values()), 1),
                        2,
                    ),
                }
            )
    return suggestions


def fuse_speaker_prediction(
    *,
    diarization_speaker: str,
    llm_speaker: str | None,
    visual_speaker: str | None,
    count_mismatch: bool,
) -> tuple[str, float, list[str]]:
    """Weighted vote for final speaker_predicted."""
    weights: Counter = Counter()
    evidence: list[str] = []

    diar_weight = WEIGHT_DIARIZATION_MISMATCH if count_mismatch else WEIGHT_DIARIZATION
    if diarization_speaker:
        weights[str(diarization_speaker)] += diar_weight
        evidence.append(f"diarization:{diarization_speaker}:{diar_weight:.2f}")

    if llm_speaker:
        weights[str(llm_speaker)] += WEIGHT_LLM
        evidence.append(f"llm:{llm_speaker}:{WEIGHT_LLM:.2f}")

    if visual_speaker:
        weights[str(visual_speaker)] += WEIGHT_VISUAL
        evidence.append(f"visual:{visual_speaker}:{WEIGHT_VISUAL:.2f}")

    if not weights:
        return diarization_speaker, 0.0, evidence

    predicted, score = weights.most_common(1)[0]
    total = sum(weights.values())
    confidence = round(float(score) / total, 2) if total > 0 else 0.0
    return predicted, confidence, evidence


def character_for_speaker(
    speaker_id: str,
    l2_identity: dict[str, Any],
    speaker_character_votes: dict[str, dict[str, float]],
) -> str | None:
    face = (l2_identity.get(speaker_id) or {}).get("face") or {}
    cluster = face.get("cluster_id")
    if cluster:
        return str(cluster)
    votes = speaker_character_votes.get(speaker_id) or {}
    if votes:
        return max(votes, key=lambda k: float(votes[k] or 0))
    return None
