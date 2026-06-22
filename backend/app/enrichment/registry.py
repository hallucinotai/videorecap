"""Central registry for enrichment layers."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.enrichment.base import BaseEnricher


@dataclass(frozen=True)
class LayerDefinition:
    layer_id: str
    label: str
    description: str
    filename: str
    media_type: str = "application/json"
    depends_on: str | None = None
    is_raw: bool = False
    enricher_module: str | None = None
    enricher_class_name: str | None = None

    def load_enricher(self) -> BaseEnricher | None:
        if not self.enricher_module or not self.enricher_class_name:
            return None
        module = import_module(self.enricher_module)
        enricher_cls = getattr(module, self.enricher_class_name)
        return enricher_cls()


LAYER_REGISTRY: tuple[LayerDefinition, ...] = (
    LayerDefinition(
        layer_id="L0",
        label="Raw transcript",
        description="Raw AssemblyAI transcript with speaker diarization (JSON)",
        filename="transcription.json",
        depends_on=None,
        is_raw=True,
    ),
    LayerDefinition(
        layer_id="L1",
        label="Normalize",
        description="Normalized utterances with stable IDs (JSON)",
        filename="enrichment_L1.json",
        depends_on="L0",
        enricher_module="modules.enrichment.l1_normalize",
        enricher_class_name="L1NormalizeEnricher",
    ),
    LayerDefinition(
        layer_id="L2",
        label="Speakers",
        description="Speaker identity enrichment and utterance flags (JSON)",
        filename="enrichment_L2.json",
        depends_on="L1",
        enricher_module="modules.enrichment.l2_speakers",
        enricher_class_name="L2SpeakerEnricher",
    ),
)

_LAYER_BY_ID: dict[str, LayerDefinition] = {layer.layer_id: layer for layer in LAYER_REGISTRY}


def get_layer(layer_id: str) -> LayerDefinition:
    layer = _LAYER_BY_ID.get(layer_id)
    if not layer:
        raise KeyError(f"Unknown enrichment layer: {layer_id}")
    return layer


def get_enrichment_layers() -> list[LayerDefinition]:
    """All registered layers including L0 (raw)."""
    return list(LAYER_REGISTRY)


def get_processable_layers() -> list[LayerDefinition]:
    """Layers with enrichers (L1, L2, ...)."""
    return [layer for layer in LAYER_REGISTRY if layer.enricher_module is not None]


def intermediate_key_for(layer_id: str) -> str:
    if layer_id == "L0":
        return "transcription"
    return f"layer.{layer_id}"


def latest_enrichment_layer_id() -> str | None:
    processable = get_processable_layers()
    return processable[-1].layer_id if processable else None
