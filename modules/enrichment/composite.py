"""Composite enricher — runs ordered sublayers and records sublayer status."""

from __future__ import annotations

import json
import os
from typing import Any, Protocol

from modules.enrichment.document import deep_copy_doc, mark_sublayer_ok


class SublayerEnricher(Protocol):
    sublayer_id: str

    def enrich(self, doc: dict[str, Any], ctx: Any) -> dict[str, Any]: ...


def sublayer_artifact_path(output_dir: str, layer_id: str, filename: str) -> str:
    path = os.path.join(output_dir, layer_id, "sublayers", filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def write_sublayer_artifact(path: str, payload: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def run_sublayers(
    doc: dict[str, Any],
    ctx: Any,
    layer_id: str,
    sublayers: list[SublayerEnricher],
    artifact_builders: dict[str, Any] | None = None,
    artifact_filenames: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """
    Run sublayers in order. Returns (merged doc, sublayer_path_by_key e.g. L2.S1).
    """
    artifact_builders = artifact_builders or {}
    artifact_filenames = artifact_filenames or {}
    sublayer_paths: dict[str, str] = {}
    output_dir = getattr(ctx, "layers_output_dir", None) or ""

    for enricher in sublayers:
        sid = enricher.sublayer_id
        skip_reason: str | None = None
        try:
            doc = enricher.enrich(doc, ctx)
            mark_sublayer_ok(doc.setdefault("pipeline_meta", {}), layer_id, sid, "ok")
        except SublayerSkipped as exc:
            skip_reason = exc.reason
            mark_sublayer_ok(
                doc.setdefault("pipeline_meta", {}),
                layer_id,
                sid,
                f"skipped:{skip_reason}",
            )
            on_skip = getattr(enricher, "on_skip", None)
            if callable(on_skip):
                doc = on_skip(doc, ctx, skip_reason)

        builder = artifact_builders.get(sid)
        if builder and output_dir:
            filename = artifact_filenames.get(sid, f"{sid}.json")
            try:
                artifact = builder(deep_copy_doc(doc), skip_reason=skip_reason, ctx=ctx)
            except TypeError:
                artifact = builder(deep_copy_doc(doc))
            path = sublayer_artifact_path(output_dir, layer_id, filename)
            write_sublayer_artifact(path, artifact)
            sublayer_paths[f"{layer_id}.{sid}"] = path

    return doc, sublayer_paths


class SublayerSkipped(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)
