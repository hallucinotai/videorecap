"""LLM batch analysis for LP.S1 text/context attribution."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

DIALOGUE_ACTS = frozenset(
    {"question", "answer", "reaction", "statement", "greeting", "other"}
)
MOODS = frozenset(
    {"neutral", "curious", "playful", "assertive", "warm", "tense", "surprised", "other"}
)

_SYSTEM_PROMPT = """You analyze a diarized video transcript for speaker attribution context.
Return JSON with exactly these keys:
{
  "utterances": [
    {
      "id": "u1",
      "dialogue_act": "question|answer|reaction|statement|greeting|other",
      "mood": "neutral|curious|playful|assertive|warm|tense|surprised|other",
      "addressee_hint": "name or role or null",
      "speaker_hint": "A|B|C or null",
      "text_evidence": "short rationale"
    }
  ],
  "speakers": {
    "A": {
      "speaking_style": "brief style note",
      "typical_mood": "dominant mood",
      "context_summary": "1-2 sentences about this speaker's role in the scene"
    }
  }
}
Use only speaker ids present in the transcript. speaker_hint is your best guess from text alone (may differ from diarization labels)."""


def _default_model() -> str:
    return os.environ.get("GPT_MODEL") or "gpt-4o-mini"


def _format_transcript_for_prompt(utterances: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for utterance in utterances:
        uid = utterance.get("id") or "?"
        speaker = utterance.get("speaker") or "?"
        text = (utterance.get("text") or "").strip()
        lines.append(f'{uid} [{speaker}]: "{text}"')
    return "\n".join(lines)


def _normalize_utterance_row(row: dict[str, Any]) -> dict[str, Any]:
    dialogue_act = str(row.get("dialogue_act") or "other").lower()
    if dialogue_act not in DIALOGUE_ACTS:
        dialogue_act = "other"
    mood = str(row.get("mood") or "neutral").lower()
    if mood not in MOODS:
        mood = "other"
    speaker_hint = row.get("speaker_hint")
    if speaker_hint is not None:
        speaker_hint = str(speaker_hint).strip() or None
    addressee = row.get("addressee_hint")
    if addressee is not None:
        addressee = str(addressee).strip() or None
    return {
        "dialogue_act": dialogue_act,
        "mood": mood,
        "addressee_hint": addressee,
        "speaker_hint": speaker_hint,
        "text_evidence": str(row.get("text_evidence") or "").strip(),
    }


def openai_available() -> bool:
    if not os.environ.get("OPENAI_API_KEY"):
        return False
    try:
        from openai import OpenAI  # noqa: F401

        return True
    except ImportError:
        return False


def run_attribution_llm_batch(
    utterances: list[dict[str, Any]],
    *,
    speaker_ids: list[str],
    language_code: str = "en",
    model: str | None = None,
) -> dict[str, Any]:
    """Call GPT once for the full transcript; return normalized LP_text payload."""
    if not openai_available():
        raise RuntimeError("openai_unavailable")

    from openai import OpenAI

    model = model or _default_model()
    client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    transcript_block = _format_transcript_for_prompt(utterances)
    user_content = (
        f"Language: {language_code}\n"
        f"Diarization speaker ids: {', '.join(speaker_ids)}\n\n"
        f"Transcript:\n{transcript_block}"
    )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        max_tokens=4096,
    )
    raw = response.choices[0].message.content or "{}"
    parsed = json.loads(raw)

    by_id: dict[str, dict[str, Any]] = {}
    for row in parsed.get("utterances") or []:
        uid = row.get("id")
        if uid:
            by_id[str(uid)] = _normalize_utterance_row(row)

    speaker_profiles: dict[str, Any] = {}
    for speaker_id in speaker_ids:
        block = (parsed.get("speakers") or {}).get(speaker_id) or {}
        speaker_profiles[speaker_id] = {
            "speaking_style": str(block.get("speaking_style") or "").strip(),
            "typical_mood": str(block.get("typical_mood") or "neutral").strip(),
            "context_summary": str(block.get("context_summary") or "").strip(),
        }

    return {
        "method": "llm_batch_v1",
        "model": model,
        "utterances": by_id,
        "speakers": speaker_profiles,
        "raw_response": parsed,
    }
