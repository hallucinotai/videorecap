"""Central registry for enrichment layers."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.enrichment.base import BaseEnricher


@dataclass(frozen=True)
class SubLayerDefinition:
    sublayer_id: str
    label: str
    artifact_filename: str
    enricher_module: str
    enricher_class_name: str


@dataclass(frozen=True)
class LayerDefinition:
    layer_id: str
    label: str
    description: str
    filename: str
    media_type: str = "application/json"
    depends_on: str | None = None
    is_raw: bool = False
    is_terminal: bool = False
    enricher_module: str | None = None
    enricher_class_name: str | None = None
    sublayers: tuple[SubLayerDefinition, ...] = ()

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
        enricher_module="modules.enrichment.l1_normalize.enricher",
        enricher_class_name="L1NormalizeEnricher",
    ),
    LayerDefinition(
        layer_id="L2",
        label="Speaker identity",
        description="Video face clustering + speaker merge, then text names (JSON)",
        filename="enrichment_L2.json",
        depends_on="L1",
        enricher_module="modules.enrichment.l2_identity.enricher",
        enricher_class_name="L2IdentityEnricher",
        sublayers=(
            SubLayerDefinition(
                sublayer_id="S1",
                label="Video reconcile",
                artifact_filename="S1_video.json",
                enricher_module="modules.enrichment.l2_identity.sublayers.s1_video_reconcile",
                enricher_class_name="S1VideoReconcileEnricher",
            ),
            SubLayerDefinition(
                sublayer_id="S2",
                label="Text names",
                artifact_filename="S2_text.json",
                enricher_module="modules.enrichment.l2_identity.sublayers.s2_text_names",
                enricher_class_name="S2TextNamesEnricher",
            ),
        ),
    ),
    LayerDefinition(
        layer_id="L3",
        label="Gender",
        description="Text and visual gender proposals (JSON)",
        filename="enrichment_L3.json",
        depends_on="L2",
        enricher_module="modules.enrichment.l3_gender.enricher",
        enricher_class_name="L3GenderEnricher",
        sublayers=(
            SubLayerDefinition(
                sublayer_id="S1",
                label="Text analysis",
                artifact_filename="S1_text.json",
                enricher_module="modules.enrichment.l3_gender.sublayers.s1_text_analysis",
                enricher_class_name="S1TextAnalysisEnricher",
            ),
            SubLayerDefinition(
                sublayer_id="S2",
                label="Visual hints",
                artifact_filename="S2_visual.json",
                enricher_module="modules.enrichment.l3_gender.sublayers.s2_visual_hints",
                enricher_class_name="S2VisualHintsEnricher",
            ),
        ),
    ),
    LayerDefinition(
        layer_id="L4",
        label="Finalize review",
        description="Merge enrichment proposals and build human review queue (JSON)",
        filename="enrichment_L4.json",
        depends_on="L3",
        enricher_module="modules.enrichment.l4_finalize.enricher",
        enricher_class_name="L4FinalizeEnricher",
        is_terminal=True,
    ),
)

_LAYER_BY_ID: dict[str, LayerDefinition] = {layer.layer_id: layer for layer in LAYER_REGISTRY}


def get_layer(layer_id: str) -> LayerDefinition:
    layer = _LAYER_BY_ID.get(layer_id)
    if not layer:
        raise KeyError(f"Unknown enrichment layer: {layer_id}")
    return layer


def get_sublayers(layer_id: str) -> tuple[SubLayerDefinition, ...]:
    return get_layer(layer_id).sublayers


def get_sublayer(layer_id: str, sublayer_id: str) -> SubLayerDefinition:
    for sub in get_sublayers(layer_id):
        if sub.sublayer_id == sublayer_id:
            return sub
    raise KeyError(f"Unknown sublayer {layer_id}.{sublayer_id}")


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


def sublayer_intermediate_key(layer_id: str, sublayer_id: str) -> str:
    return f"layer.{layer_id}.{sublayer_id}"


def latest_enrichment_layer_id() -> str | None:
    processable = get_processable_layers()
    return processable[-1].layer_id if processable else None


def terminal_layer_id() -> str | None:
    """Layer that owns user review (defaults to last processable layer)."""
    terminal = [layer for layer in get_processable_layers() if layer.is_terminal]
    if terminal:
        return terminal[-1].layer_id
    return latest_enrichment_layer_id()


def iter_downloadable_layers() -> list[tuple[str, str | None, LayerDefinition | SubLayerDefinition]]:
    """Flatten macro layers and sublayers for debug download UI."""
    items: list[tuple[str, str | None, LayerDefinition | SubLayerDefinition]] = []
    for layer in get_enrichment_layers():
        items.append((layer.layer_id, None, layer))
        for sub in layer.sublayers:
            items.append((layer.layer_id, sub.sublayer_id, sub))
    return items
