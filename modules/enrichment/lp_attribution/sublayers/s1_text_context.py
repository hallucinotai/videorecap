"""LP.S1: Text/context analysis via LLM batch pass."""

from __future__ import annotations

from typing import Any

from modules.enrichment.composite import SublayerSkipped
from modules.enrichment.document import deep_copy_doc, language_code_from_doc, real_speaker_ids
from modules.enrichment.lp_attribution.llm_batch import openai_available, run_attribution_llm_batch


class S1TextContextEnricher:
    sublayer_id = "S1"

    def enrich(self, doc: dict[str, Any], ctx: Any) -> dict[str, Any]:
        utterances = (doc.get("L1_transcript") or {}).get("utterances") or []
        if not utterances:
            raise SublayerSkipped("no_utterances")

        if not openai_available():
            raise SublayerSkipped("openai_unavailable")

        speaker_ids = real_speaker_ids(
            {u.get("speaker"): True for u in utterances if u.get("speaker")}
        )
        try:
            lp_text = run_attribution_llm_batch(
                utterances,
                speaker_ids=speaker_ids,
                language_code=language_code_from_doc(doc),
            )
        except RuntimeError as exc:
            raise SublayerSkipped(str(exc).replace("openai_unavailable", "openai_unavailable")) from exc
        except Exception as exc:
            raise SublayerSkipped("llm_failed") from exc

        enriched_utterances: list[dict[str, Any]] = []
        by_id = lp_text.get("utterances") or {}
        for utterance in utterances:
            row = dict(utterance)
            analysis = by_id.get(str(row.get("id") or ""))
            if analysis:
                row["dialogue_act"] = analysis.get("dialogue_act")
                row["mood"] = analysis.get("mood")
                if analysis.get("addressee_hint"):
                    row["addressee_hint"] = analysis["addressee_hint"]
            enriched_utterances.append(row)

        output = deep_copy_doc(doc)
        output["L1_transcript"] = {
            **(output.get("L1_transcript") or {}),
            "utterances": enriched_utterances,
        }
        output["LP_text"] = {
            "method": lp_text.get("method"),
            "model": lp_text.get("model"),
            "utterances": by_id,
            "speakers": lp_text.get("speakers") or {},
        }
        return output


def s1_artifact(doc: dict[str, Any]) -> dict[str, Any]:
    lp_text = doc.get("LP_text") or {}
    return {
        "method": lp_text.get("method"),
        "model": lp_text.get("model"),
        "utterances": lp_text.get("utterances") or {},
        "speakers": lp_text.get("speakers") or {},
    }
