"""Backward-compatible shim — use modules.enrichment.l2_identity."""

from modules.enrichment.l2_identity import L2IdentityEnricher, L2SpeakerEnricher

__all__ = ["L2IdentityEnricher", "L2SpeakerEnricher"]
