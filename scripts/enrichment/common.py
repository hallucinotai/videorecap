"""Shared helpers for manual enrichment layer scripts."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


LAYER_CHAIN = (
    ("L0", "transcription.json", None),
    ("L1", "enrichment_L1.json", "L0"),
    ("L2", "enrichment_L2.json", "L1"),
    ("L3", "enrichment_L3.json", "L2"),
    ("L4", "enrichment_L4.json", "L3"),
)

DEFAULT_LAYERS_DIR = "output/transcriptions/layers"
DEFAULT_RAW_TRANSCRIPT = "output/transcriptions/transcription.json"


@dataclass
class EnrichmentRunContext:
    """Minimal stand-in for backend EnrichmentContext (no FastAPI dependency)."""

    job_id: str
    working_dir: str
    video_path: str | None = None
    layers_output_dir: str | None = None
    assets_dir: str | None = None
    raw_speakers: dict[str, Any] | None = None
    raw_metadata: dict[str, Any] | None = None
    speaker_asset_paths: dict[str, str] = field(default_factory=dict)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def setup_import_paths() -> Path:
    root = repo_root()
    backend = root / "backend"
    for path in (root, backend):
        path_str = str(path)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)
    return root


def load_env_file() -> None:
    env_path = repo_root() / ".env"
    if not env_path.is_file():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(env_path)


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def write_json(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)


def resolve_path(path: str | Path, *, base: Path) -> Path:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = base / p
    return p.resolve()


def default_layers_dir(base: Path) -> Path:
    return resolve_path(DEFAULT_LAYERS_DIR, base=base)


def layer_filename(layer_id: str) -> str:
    for lid, filename, _ in LAYER_CHAIN:
        if lid == layer_id:
            return filename
    raise KeyError(f"Unknown layer: {layer_id}")


def previous_layer_id(layer_id: str) -> str | None:
    for lid, _, prev in LAYER_CHAIN:
        if lid == layer_id:
            return prev
    raise KeyError(f"Unknown layer: {layer_id}")


def default_input_path(layer_id: str, base: Path) -> Path:
    prev = previous_layer_id(layer_id)
    if prev == "L0":
        return resolve_path(DEFAULT_RAW_TRANSCRIPT, base=base)
    if prev is None:
        raise ValueError("L0 has no enrichment input")
    return default_layers_dir(base) / layer_filename(prev)


def default_output_path(layer_id: str, base: Path) -> Path:
    return default_layers_dir(base) / layer_filename(layer_id)


def load_raw_context(raw_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    from modules.enrichment.document import is_assemblyai_enhanced

    raw_doc = load_json(raw_path)
    if not is_assemblyai_enhanced(raw_doc):
        raise ValueError(
            f"{raw_path} is not AssemblyAI enhanced format "
            "(expected metadata.provider=assemblyai with speakers + segments dicts). "
            "Run scripts/enrichment/run_l0_transcribe.py first."
        )
    return raw_doc.get("speakers") or {}, raw_doc.get("metadata") or {}


def validate_layer_input(layer_id: str, doc: dict[str, Any], input_path: Path) -> None:
    if layer_id == "L1":
        from modules.enrichment.document import is_assemblyai_enhanced

        if not is_assemblyai_enhanced(doc):
            raise ValueError(f"L1 input must be raw AssemblyAI transcript: {input_path}")
        return

    if layer_id == "L2":
        if not (doc.get("L1_transcript") or {}).get("utterances"):
            raise ValueError(f"L2 input must include L1_transcript.utterances: {input_path}")
        return

    if layer_id == "L3":
        if not doc.get("L2_speakers") and not doc.get("L2_identity"):
            raise ValueError(f"L3 input must include L2_speakers or L2_identity: {input_path}")
        return

    if layer_id == "L4":
        if not doc.get("L3_gender"):
            raise ValueError(f"L4 input must include L3_gender: {input_path}")
        return


def build_run_context(
    *,
    job_id: str,
    working_dir: Path,
    layers_output_dir: Path,
    raw_transcript: Path | None,
    video_path: Path | None,
) -> EnrichmentRunContext:
    raw_speakers: dict[str, Any] = {}
    raw_metadata: dict[str, Any] = {}
    if raw_transcript is not None:
        raw_speakers, raw_metadata = load_raw_context(raw_transcript)

    assets_dir = working_dir / "output" / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    return EnrichmentRunContext(
        job_id=job_id,
        working_dir=str(working_dir),
        video_path=str(video_path) if video_path else None,
        layers_output_dir=str(layers_output_dir),
        assets_dir=str(assets_dir),
        raw_speakers=raw_speakers,
        raw_metadata=raw_metadata,
    )


def run_enrichment_layer(
    layer_id: str,
    *,
    input_path: Path,
    output_path: Path,
    ctx: EnrichmentRunContext,
) -> dict[str, Any]:
    from app.enrichment.registry import get_layer

    setup_import_paths()
    doc = load_json(input_path)
    validate_layer_input(layer_id, doc, input_path)

    layer_def = get_layer(layer_id)
    enricher = layer_def.load_enricher()
    if enricher is None:
        raise ValueError(f"Layer {layer_id} has no enricher")

    result = enricher.enrich(doc, ctx)
    sublayer_paths = result.pop("_sublayer_paths", None) or {}

    write_json(output_path, result)

    if sublayer_paths:
        print("  Sublayer artifacts:")
        for key, path in sorted(sublayer_paths.items()):
            print(f"    {key}: {path}")

    return result


def add_common_args(parser: argparse.ArgumentParser, *, layer_id: str) -> None:
    root = repo_root()
    parser.add_argument(
        "--input",
        default=str(default_input_path(layer_id, root)),
        help="Input JSON from the previous step",
    )
    parser.add_argument(
        "--output",
        default=str(default_output_path(layer_id, root)),
        help="Output JSON for this layer",
    )
    parser.add_argument(
        "--job-id",
        default="local-debug",
        help="Job id stored in pipeline_meta (default: local-debug)",
    )
    parser.add_argument(
        "--working-dir",
        default=str(root),
        help="Repo/working directory for relative output paths",
    )
    parser.add_argument(
        "--layers-dir",
        default=str(default_layers_dir(root)),
        help="Directory for layer outputs and sublayer artifacts",
    )


def add_raw_transcript_arg(parser: argparse.ArgumentParser) -> None:
    root = repo_root()
    parser.add_argument(
        "--raw-transcript",
        default=str(resolve_path(DEFAULT_RAW_TRANSCRIPT, base=root)),
        help="L0 transcription.json (speakers/metadata for L2+)",
    )


def add_video_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--video",
        default=None,
        help="Video file for L2 video reconcile (optional; skips S1 if omitted)",
    )


def parse_paths(args: argparse.Namespace) -> tuple[Path, Path, Path, Path]:
    working_dir = Path(args.working_dir).expanduser().resolve()
    input_path = resolve_path(args.input, base=working_dir)
    output_path = resolve_path(args.output, base=working_dir)
    layers_dir = resolve_path(args.layers_dir, base=working_dir)
    return working_dir, input_path, output_path, layers_dir


def print_chain_hint(layer_id: str, output_path: Path) -> None:
    next_layer = None
    for i, (lid, _, _) in enumerate(LAYER_CHAIN):
        if lid == layer_id and i + 1 < len(LAYER_CHAIN):
            next_layer = LAYER_CHAIN[i + 1]
            break
    if not next_layer:
        print("\nChain complete (terminal layer).")
        return
    next_id, next_file, _ = next_layer
    if next_id == "L0":
        return
    script_map = {
        "L1": "run_l1_normalize.py",
        "L2": "run_l2_identity.py",
        "L3": "run_l3_gender.py",
        "L4": "run_l4_finalize.py",
    }
    script = script_map.get(next_id)
    if script:
        print(f"\nNext step:")
        print(f"  python scripts/enrichment/{script} --input {output_path}")
