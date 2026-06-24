"""L3: Text-based gender inference from transcript (English, deterministic)."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from modules.enrichment.document import (
    GENDER_NAME_HINT_CONFIDENCE,
    GENDER_NARRATION_MIN,
    GENDER_REVIEW_MAX,
    deep_copy_doc,
    mark_layer_ok,
    utterances_to_segment_refs,
)

_SELF_FEMALE_RE = re.compile(
    r"\b(?:i'?m|i am)\s+(?:a\s+)?(?:woman|girl|female)\b", re.I
)
_SELF_MALE_RE = re.compile(
    r"\b(?:i'?m|i am)\s+(?:a\s+)?(?:man|boy|male|guy|dude)\b", re.I
)
_SELF_MALE_RHETORICAL_RE = re.compile(
    r"\b(?:what kind of (?:guy|man)|as a man)\b", re.I
)
_SELF_FEMALE_RHETORICAL_RE = re.compile(
    r"\b(?:what kind of (?:woman|girl)|as a woman)\b", re.I
)
_KINSHIP_FEMALE_RE = re.compile(
    r"\bmy\s+(?:mother|mom|wife|daughter|sister|girlfriend|aunt|grandma|grandmother)\b", re.I
)
_KINSHIP_MALE_RE = re.compile(
    r"\bmy\s+(?:father|dad|husband|son|brother|boyfriend|uncle|grandpa|grandfather)\b", re.I
)
_PRONOUN_FEMALE_RE = re.compile(r"\b(she|her|hers)\b", re.I)
_PRONOUN_MALE_RE = re.compile(r"\b(he|him|his)\b", re.I)
_HONORIFIC_FEMALE_RE = re.compile(r"\b(?:ma'?am|madam|miss|mrs|ms)\b", re.I)
_HONORIFIC_MALE_RE = re.compile(r"\b(?:sir|mister|mr)\b", re.I)
_DESCRIPTIVE_FEMALE_RE = re.compile(r"\b(?:pretty girl|young woman|that woman|the woman)\b", re.I)
_DESCRIPTIVE_MALE_RE = re.compile(r"\b(?:that man|the man|young man|handsome man)\b", re.I)

# Weak name hints only — low confidence by design
_FEMALE_NAMES = {
    "sarah", "jane", "mary", "emma", "olivia", "sophia", "emily", "anna", "lisa", "kate",
    "jennifer", "jessica", "michelle", "linda", "patricia", "elizabeth", "barbara", "susan",
}
_MALE_NAMES = {
    "james", "john", "michael", "david", "robert", "william", "richard", "joseph", "thomas",
    "charles", "daniel", "matthew", "mark", "paul", "steven", "andrew", "kevin", "brian",
}


def _add_vote(
    votes: dict[str, list[tuple[str, float, str]]],
    speaker_id: str,
    gender: str,
    confidence: float,
    evidence: str,
) -> None:
    if speaker_id and gender in ("male", "female"):
        votes[speaker_id].append((gender, confidence, evidence))


def _aggregate_gender(votes: list[tuple[str, float, str]]) -> dict[str, Any]:
    if not votes:
        return {
            "gender": "unknown",
            "gender_confidence": 0.0,
            "gender_evidence": [],
            "requires_review": False,
            "pronoun_hint": None,
        }

    scores: dict[str, float] = defaultdict(float)
    evidence: list[str] = []
    for gender, confidence, tag in votes:
        scores[gender] += confidence
        evidence.append(f"{tag}:{confidence:.2f}")

    best_gender = max(scores, key=scores.get)
    confidence = round(min(1.0, scores[best_gender]), 2)

    requires_review = confidence < GENDER_NARRATION_MIN and best_gender in ("male", "female")
    if confidence < GENDER_REVIEW_MAX and best_gender in ("male", "female"):
        requires_review = True

    pronoun_hint = None
    if confidence >= GENDER_NARRATION_MIN:
        pronoun_hint = "she" if best_gender == "female" else "he"

    return {
        "gender": best_gender,
        "gender_confidence": confidence,
        "gender_evidence": evidence,
        "requires_review": requires_review,
        "pronoun_hint": pronoun_hint,
    }


def _resolve_addressee(
    utterances: list[dict[str, Any]],
    utterance_index: int,
    speaker_id: str,
    speaker_ids: set[str],
) -> str | None:
    """Pick who an honorific/descriptor in this turn is most likely directed at."""
    others = [s for s in speaker_ids if s != speaker_id]
    if len(others) == 1:
        return others[0]
    for utterance in reversed(utterances[: utterance_index + 1]):
        if utterance["speaker"] != speaker_id:
            return utterance["speaker"]
    return None


def _collect_votes(
    utterances: list[dict[str, Any]],
    l2_speakers: dict[str, Any],
) -> dict[str, list[tuple[str, float, str]]]:
    votes: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
    name_to_speaker: dict[str, str] = {}
    for speaker_id, info in l2_speakers.items():
        name = info.get("name")
        if name:
            name_to_speaker[name.lower()] = speaker_id

    speaker_ids = {u["speaker"] for u in utterances}

    for idx, utterance in enumerate(utterances):
        speaker_id = utterance["speaker"]
        text = utterance["text"]
        uid = utterance["id"]

        if _SELF_FEMALE_RE.search(text):
            _add_vote(votes, speaker_id, "female", 0.92, f"self_id:{uid}")
        if _SELF_FEMALE_RHETORICAL_RE.search(text):
            _add_vote(votes, speaker_id, "female", 0.88, f"self_rhetorical:{uid}")
        if _SELF_MALE_RE.search(text):
            _add_vote(votes, speaker_id, "male", 0.92, f"self_id:{uid}")
        if _SELF_MALE_RHETORICAL_RE.search(text):
            _add_vote(votes, speaker_id, "male", 0.88, f"self_rhetorical:{uid}")
        if _KINSHIP_FEMALE_RE.search(text):
            _add_vote(votes, speaker_id, "female", 0.72, f"kinship_female:{uid}")
        if _KINSHIP_MALE_RE.search(text):
            _add_vote(votes, speaker_id, "male", 0.72, f"kinship_male:{uid}")

    # Pronouns / honorifics / descriptors spoken about other speakers
    for idx, utterance in enumerate(utterances):
        speaker_id = utterance["speaker"]
        text = utterance["text"]
        uid = utterance["id"]

        for name, target_id in name_to_speaker.items():
            if target_id == speaker_id:
                continue
            if re.search(rf"\b{re.escape(name)}\b", text, re.I):
                if _PRONOUN_FEMALE_RE.search(text):
                    _add_vote(votes, target_id, "female", 0.78, f"pronoun_she:{uid}")
                if _PRONOUN_MALE_RE.search(text):
                    _add_vote(votes, target_id, "male", 0.78, f"pronoun_he:{uid}")

        target = _resolve_addressee(utterances, idx, speaker_id, speaker_ids)
        if target:
            if _HONORIFIC_FEMALE_RE.search(text):
                _add_vote(votes, target, "female", 0.62, f"honorific_female:{uid}")
            if _HONORIFIC_MALE_RE.search(text):
                _add_vote(votes, target, "male", 0.62, f"honorific_male:{uid}")
            if _DESCRIPTIVE_FEMALE_RE.search(text):
                _add_vote(votes, target, "female", 0.58, f"address_female:{uid}")
            if _DESCRIPTIVE_MALE_RE.search(text):
                _add_vote(votes, target, "male", 0.58, f"address_male:{uid}")

    # Weak name hints from L2
    for speaker_id, info in l2_speakers.items():
        name = (info.get("name") or "").strip()
        if not name:
            continue
        lower = name.lower()
        if lower in _FEMALE_NAMES:
            _add_vote(
                votes, speaker_id, "female", GENDER_NAME_HINT_CONFIDENCE, f"name_hint:{name}"
            )
        elif lower in _MALE_NAMES:
            _add_vote(
                votes, speaker_id, "male", GENDER_NAME_HINT_CONFIDENCE, f"name_hint:{name}"
            )

    return votes


class S1TextAnalysisEnricher:
    sublayer_id = "S1"

    def enrich(self, doc: dict[str, Any], ctx: Any) -> dict[str, Any]:
        l1 = doc.get("L1_transcript") or {}
        utterances = l1.get("utterances") or []
        l2_speakers = doc.get("L2_speakers") or {}

        if not utterances:
            raise ValueError("L3 requires L1_transcript utterances")

        language_code = (doc.get("L0_metadata") or {}).get("language_code") or "en"
        if not str(language_code).lower().startswith("en"):
            l3_gender = {
                sid: {
                    "speaker_id": sid,
                    "gender": "unknown",
                    "gender_confidence": 0.0,
                    "gender_status": "skipped_language",
                    "gender_source": "text_analysis",
                    "gender_evidence": [],
                    "requires_review": False,
                    "pronoun_hint": None,
                }
                for sid in l2_speakers.keys()
            }
        else:
            votes = _collect_votes(utterances, l2_speakers)
            l3_gender = {}
            for speaker_id in sorted(set(u["speaker"] for u in utterances) | set(l2_speakers.keys())):
                aggregated = _aggregate_gender(votes.get(speaker_id, []))
                l3_gender[speaker_id] = {
                    "speaker_id": speaker_id,
                    **aggregated,
                    "gender_status": "proposed",
                    "gender_source": "text_analysis",
                }

        metadata = deep_copy_doc(doc.get("metadata") or {})
        metadata["gender_analysis"] = "text_l3"

        output = deep_copy_doc(doc)
        output["L3_gender"] = l3_gender
        output["metadata"] = metadata
        if "segments" not in output:
            output["segments"] = utterances_to_segment_refs(utterances)

        return output
