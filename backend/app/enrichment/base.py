"""Base types for enrichment enrichers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class EnrichmentContext:
    job_id: str
    working_dir: str
    video_path: str | None = None
    raw_speakers: dict[str, Any] | None = None
    raw_metadata: dict[str, Any] | None = None


class BaseEnricher(ABC):
    layer_id: str

    @abstractmethod
    def enrich(self, doc: dict[str, Any], ctx: EnrichmentContext) -> dict[str, Any]:
        """Transform input document into this layer's output document."""
