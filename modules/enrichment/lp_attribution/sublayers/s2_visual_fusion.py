"""LP.S2: Visual fusion from L2 identity artifacts (no lip sync)."""

from __future__ import annotations

from typing import Any

from modules.enrichment.composite import SublayerSkipped
from modules.enrichment.document import deep_copy_doc
from modules.enrichment.lp_attribution.fusion import _char_speaker_map, character_for_speaker


def _visual_utterance_row(
    utterance: dict[str, Any],
    *,
    speaker_character_votes: dict[str, dict[str, float]],
    l2_identity: dict[str, Any],
    char_to_speaker: dict[str, str],
) -> dict[str, Any]:
    uid = str(utterance.get("id") or "")
    diarization = str(utterance.get("speaker") or "")
    visible_char = utterance.get("character_id")

    character_visual = visible_char
    if diarization and not character_visual:
        character_visual = character_for_speaker(
            diarization, l2_identity, speaker_character_votes
        )

    speaker_visual = diarization
    if character_visual and character_visual in char_to_speaker:
        speaker_visual = char_to_speaker[character_visual]
    elif diarization:
        votes = speaker_character_votes.get(diarization) or {}
        if votes:
            character_visual = character_visual or max(
                votes, key=lambda k: float(votes[k] or 0)
            )
            speaker_visual = diarization

    evidence: list[str] = []
    if diarization and character_visual:
        weight = float((speaker_character_votes.get(diarization) or {}).get(character_visual) or 0)
        if weight:
            evidence.append(f"cooccur:{diarization}:{character_visual}:{weight:.1f}")
    if visible_char and visible_char != character_visual:
        evidence.append(f"visible:{visible_char}")

    confidence = 0.5
    if diarization and character_visual:
        votes = speaker_character_votes.get(diarization) or {}
        total = sum(float(v or 0) for v in votes.values())
        if total > 0:
            confidence = round(float(votes.get(character_visual, 0)) / total, 2)

    return {
        "utterance_id": uid,
        "character_visual": character_visual,
        "speaker_visual": speaker_visual,
        "visual_confidence": confidence,
        "visual_evidence": evidence,
    }


class S2VisualFusionEnricher:
    sublayer_id = "S2"

    def enrich(self, doc: dict[str, Any], ctx: Any) -> dict[str, Any]:
        l2_obs = doc.get("L2_character_observation") or {}
        l2_identity = doc.get("L2_identity") or {}
        if not l2_obs and not l2_identity:
            raise SublayerSkipped("no_l2_identity")

        speaker_character_votes = l2_obs.get("speaker_character_votes") or {}
        if not speaker_character_votes and not l2_identity:
            raise SublayerSkipped("no_visual_signals")

        utterances = (doc.get("L1_transcript") or {}).get("utterances") or []
        char_to_speaker = _char_speaker_map(speaker_character_votes)

        per_utterance: dict[str, Any] = {}
        for utterance in utterances:
            uid = utterance.get("id")
            if not uid:
                continue
            per_utterance[str(uid)] = _visual_utterance_row(
                utterance,
                speaker_character_votes=speaker_character_votes,
                l2_identity=l2_identity,
                char_to_speaker=char_to_speaker,
            )

        output = deep_copy_doc(doc)
        output["LP_visual"] = {
            "method": "l2_cooccurrence_v1",
            "count_mismatch": bool(l2_obs.get("count_mismatch")),
            "utterances": per_utterance,
            "char_to_speaker": char_to_speaker,
        }
        return output


def s2_artifact(doc: dict[str, Any]) -> dict[str, Any]:
    lp_visual = doc.get("LP_visual") or {}
    return {
        "method": lp_visual.get("method"),
        "count_mismatch": lp_visual.get("count_mismatch"),
        "utterances": lp_visual.get("utterances") or {},
        "char_to_speaker": lp_visual.get("char_to_speaker") or {},
    }
