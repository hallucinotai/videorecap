"""S3 storage helpers for enrichment layer artifacts."""

from __future__ import annotations

import logging
import os

from app.enrichment.registry import get_layer, intermediate_key_for

logger = logging.getLogger(__name__)


class LayerStorage:
    """Upload and resolve enrichment layer files in object storage."""

    def __init__(self, job_id: str, storage_service):
        self.job_id = job_id
        self.storage = storage_service

    def s3_key_for(self, layer_id: str) -> str:
        layer = get_layer(layer_id)
        return f"jobs/{self.job_id}/layers/{layer_id}/{layer.filename}"

    def upload_layer(self, layer_id: str, local_path: str) -> str:
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"Layer file not found: {local_path}")
        s3_key = self.s3_key_for(layer_id)
        with open(local_path, "rb") as f:
            self.storage.upload_file(s3_key, f)
        logger.debug("Uploaded layer %s → %s", layer_id, s3_key)
        return s3_key

    @staticmethod
    def resolve_s3_key(intermediate_keys: dict, layer_id: str) -> str | None:
        if not intermediate_keys:
            return None

        primary = intermediate_key_for(layer_id)
        if primary in intermediate_keys:
            return intermediate_keys[primary]

        # StepStorage fallback keys
        fallbacks = {
            "L0": ["step_01.transcript", "transcription"],
            "L1": ["step_01.layer_L1", "layer.L1"],
            "L2": ["step_01.layer_L2", "layer.L2"],
            "L3": ["step_01.layer_L3", "layer.L3"],
            "L4": ["step_01.layer_L4", "layer.L4"],
        }
        for key in fallbacks.get(layer_id, []):
            if key in intermediate_keys:
                return intermediate_keys[key]
        return None

    @staticmethod
    def download_url(job_id: str, layer_id: str) -> str:
        return f"/jobs/{job_id}/debug/layers/{layer_id}"

    @staticmethod
    def resolve_latest_layer_path(intermediate_keys: dict) -> tuple[str | None, str | None]:
        """Return (layer_id, s3_key) for the highest available enrichment layer."""
        for layer_id in ("L4", "L3", "L2", "L1", "L0"):
            s3_key = LayerStorage.resolve_s3_key(intermediate_keys, layer_id)
            if s3_key:
                return layer_id, s3_key
        return None, None
