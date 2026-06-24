"""Base types for enrichment enrichers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EnrichmentContext:
    job_id: str
    working_dir: str
    video_path: str | None = None
    layers_output_dir: str | None = None
    assets_dir: str | None = None
    raw_speakers: dict[str, Any] | None = None
    raw_metadata: dict[str, Any] | None = None
    speaker_asset_paths: dict[str, str] = field(default_factory=dict)


class BaseEnricher(ABC):
    layer_id: str

    @abstractmethod
    def enrich(self, doc: dict[str, Any], ctx: EnrichmentContext) -> dict[str, Any]:
        """Transform input document into this layer's output document."""
