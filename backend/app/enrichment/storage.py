"""S3 storage helpers for enrichment layer artifacts."""

from __future__ import annotations

import logging
import os

from app.enrichment.registry import (
    get_layer,
    get_sublayer,
    intermediate_key_for,
    sublayer_intermediate_key,
)

logger = logging.getLogger(__name__)


class LayerStorage:
    """Upload and resolve enrichment layer files in object storage."""

    def __init__(self, job_id: str, storage_service):
        self.job_id = job_id
        self.storage = storage_service

    def s3_key_for(self, layer_id: str) -> str:
        layer = get_layer(layer_id)
        return f"jobs/{self.job_id}/layers/{layer_id}/{layer.filename}"

    def s3_key_for_sublayer(self, layer_id: str, sublayer_id: str) -> str:
        sub = get_sublayer(layer_id, sublayer_id)
        return f"jobs/{self.job_id}/layers/{layer_id}/sublayers/{sub.artifact_filename}"

    def s3_key_for_speaker_asset(self, speaker_id: str, filename: str = "portrait.jpg") -> str:
        return f"jobs/{self.job_id}/assets/speakers/{speaker_id}/{filename}"

    def upload_layer(self, layer_id: str, local_path: str) -> str:
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"Layer file not found: {local_path}")
        s3_key = self.s3_key_for(layer_id)
        with open(local_path, "rb") as f:
            self.storage.upload_file(s3_key, f)
        logger.debug("Uploaded layer %s → %s", layer_id, s3_key)
        return s3_key

    def upload_sublayer(self, layer_id: str, sublayer_id: str, local_path: str) -> str:
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"Sublayer file not found: {local_path}")
        s3_key = self.s3_key_for_sublayer(layer_id, sublayer_id)
        with open(local_path, "rb") as f:
            self.storage.upload_file(s3_key, f)
        logger.debug("Uploaded sublayer %s.%s → %s", layer_id, sublayer_id, s3_key)
        return s3_key

    def upload_speaker_asset(self, speaker_id: str, local_path: str, filename: str = "portrait.jpg") -> str:
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"Speaker asset not found: {local_path}")
        s3_key = self.s3_key_for_speaker_asset(speaker_id, filename)
        with open(local_path, "rb") as f:
            self.storage.upload_file(s3_key, f)
        logger.debug("Uploaded speaker asset %s → %s", speaker_id, s3_key)
        return s3_key

    def speaker_asset_url(self, speaker_id: str, filename: str = "portrait.jpg", expires_in: int = 3600) -> str:
        s3_key = self.s3_key_for_speaker_asset(speaker_id, filename)
        return self.storage.generate_presigned_url(s3_key, expires_in=expires_in)

    @staticmethod
    def resolve_s3_key(intermediate_keys: dict, layer_id: str) -> str | None:
        if not intermediate_keys:
            return None

        primary = intermediate_key_for(layer_id)
        if primary in intermediate_keys:
            return intermediate_keys[primary]

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
    def resolve_sublayer_s3_key(intermediate_keys: dict, layer_id: str, sublayer_id: str) -> str | None:
        if not intermediate_keys:
            return None
        primary = sublayer_intermediate_key(layer_id, sublayer_id)
        if primary in intermediate_keys:
            return intermediate_keys[primary]
        fallback = f"step_01.layer_{layer_id}_{sublayer_id}"
        return intermediate_keys.get(fallback)

    @staticmethod
    def download_url(job_id: str, layer_id: str, sublayer_id: str | None = None) -> str:
        if sublayer_id:
            return f"/jobs/{job_id}/debug/layers/{layer_id}/sublayers/{sublayer_id}"
        return f"/jobs/{job_id}/debug/layers/{layer_id}"

    @staticmethod
    def resolve_latest_layer_path(intermediate_keys: dict) -> tuple[str | None, str | None]:
        """Return (layer_id, s3_key) for the highest available enrichment layer."""
        for layer_id in ("L4", "L3", "L2", "L1", "L0"):
            s3_key = LayerStorage.resolve_s3_key(intermediate_keys, layer_id)
            if s3_key:
                return layer_id, s3_key
        return None, None
