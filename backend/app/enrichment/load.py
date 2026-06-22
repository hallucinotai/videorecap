"""Load enrichment layer documents from object storage."""

from __future__ import annotations

import json
import logging
import tempfile
from typing import Any

from app.enrichment.registry import get_layer
from app.enrichment.storage import LayerStorage
from app.services.storage import storage

logger = logging.getLogger(__name__)


def load_layer_json_from_storage(intermediate_keys: dict, layer_id: str) -> dict[str, Any] | None:
    s3_key = LayerStorage.resolve_s3_key(intermediate_keys or {}, layer_id)
    if not s3_key:
        return None
    try:
        response = storage.client.get_object(Bucket=storage.bucket, Key=s3_key)
        return json.loads(response["Body"].read().decode("utf-8"))
    except Exception:
        logger.exception("Failed to load layer %s from %s", layer_id, s3_key)
        return None


def save_layer_json_to_storage(job_id: str, layer_id: str, doc: dict[str, Any], intermediate_keys: dict) -> str:
    layer = get_layer(layer_id)
    layer_storage = LayerStorage(job_id, storage)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        json.dump(doc, tmp, indent=2)
        tmp_path = tmp.name
    try:
        s3_key = layer_storage.upload_layer(layer_id, tmp_path)
    finally:
        import os
        os.unlink(tmp_path)
    from app.enrichment.registry import intermediate_key_for
    intermediate_keys[intermediate_key_for(layer_id)] = s3_key
    return s3_key
