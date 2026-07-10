"""Shared helpers for manual enrichment layer scripts."""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from run_paths import (
    assets_dir as run_assets_dir,
    infer_run_name,
    layers_dir as run_layers_dir,
    raw_transcript_path,
    resolve_run_name,
    transcriptions_dir as run_transcriptions_dir,
)


LAYER_CHAIN = (
    ("L0", "transcription.json", None),
    ("L1", "enrichment_L1.json", "L0"),
    ("L2", "enrichment_L2.json", "L1"),
    ("LP", "enrichment_LP.json", "L2"),
    ("L3", "enrichment_L3.json", "LP"),
    ("L4", "enrichment_L4.json", "L3"),
)


@dataclass
class EnrichmentRunContext:
    """Minimal stand-in for backend EnrichmentContext (no FastAPI dependency)."""

    job_id: str
    working_dir: str
    run_name: str | None = None
    video_path: str | None = None
    audio_path: str | None = None
    layers_output_dir: str | None = None
    assets_dir: str | None = None
    raw_speakers: dict[str, Any] | None = None
    raw_metadata: dict[str, Any] | None = None
    speaker_asset_paths: dict[str, str] = field(default_factory=dict)
    lp_s1_partial: dict[str, Any] | None = None


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def setup_import_paths() -> Path:
    root = repo_root()
    backend = root / "backend"
    scripts = root / "scripts"
    # Insert backend/scripts first, repo root last — root must win for `modules.*`
    # (backend also ships a modules/ copy; without this, outputs land in backend/output/).
    for path in (backend, scripts, root):
        path_str = str(path)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)
    return root


@contextmanager
def patched_module_paths(working_dir: str | Path):
    """Patch modules.transcription output paths to resolve under working_dir."""
    import modules.transcription as mod

    original_script_dir = mod.SCRIPT_DIR
    original_get_output_path = mod.get_output_path
    base = str(Path(working_dir).expanduser().resolve())

    mod.SCRIPT_DIR = base
    mod.get_output_path = lambda rel: os.path.join(base, rel)
    try:
        yield
    finally:
        mod.SCRIPT_DIR = original_script_dir
        mod.get_output_path = original_get_output_path


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


def default_input_path(layer_id: str, working_dir: Path, run_name: str) -> Path:
    prev = previous_layer_id(layer_id)
    if prev == "L0":
        return raw_transcript_path(working_dir, run_name)
    if prev is None:
        raise ValueError("L0 has no enrichment input")
    return run_layers_dir(working_dir, run_name) / layer_filename(prev)


def default_output_path(layer_id: str, working_dir: Path, run_name: str) -> Path:
    if layer_id == "L0":
        return raw_transcript_path(working_dir, run_name)
    return run_layers_dir(working_dir, run_name) / layer_filename(layer_id)


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


def default_audio_path(working_dir: Path) -> Path:
    return working_dir / "output" / "original" / "extracted_audio.wav"


def build_run_context(
    *,
    job_id: str,
    working_dir: Path,
    run_name: str,
    layers_output_dir: Path,
    raw_transcript: Path | None,
    video_path: Path | None,
    audio_path: Path | None = None,
) -> EnrichmentRunContext:
    raw_speakers: dict[str, Any] = {}
    raw_metadata: dict[str, Any] = {}
    if raw_transcript is not None:
        raw_speakers, raw_metadata = load_raw_context(raw_transcript)

    assets_dir = run_assets_dir(working_dir, run_name)
    assets_dir.mkdir(parents=True, exist_ok=True)

    resolved_audio = audio_path
    if resolved_audio is None:
        default = default_audio_path(working_dir)
        if default.is_file():
            resolved_audio = default

    return EnrichmentRunContext(
        job_id=job_id,
        working_dir=str(working_dir),
        run_name=run_name,
        video_path=str(video_path) if video_path else None,
        audio_path=str(resolved_audio) if resolved_audio else None,
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

    if layer_id == "L3":
        from modules.enrichment.document import prune_l3_document

        result = prune_l3_document(result)

    write_json(output_path, result)

    if sublayer_paths:
        print("  Sublayer artifacts:")
        for key, path in sorted(sublayer_paths.items()):
            print(f"    {key}: {path}")

    return result


def add_run_name_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--run-name",
        default=None,
        help=(
            "Output folder name under output/transcriptions/<run-name>/ "
            "(default: video filename stem, or inferred from --input)"
        ),
    )


def add_common_args(parser: argparse.ArgumentParser, *, layer_id: str) -> None:
    add_run_name_arg(parser)
    parser.add_argument(
        "--input",
        default=None,
        help="Input JSON from the previous step (default: prior layer for this run)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON for this layer (default: layers dir for this run)",
    )
    parser.add_argument(
        "--job-id",
        default="local-debug",
        help="Job id stored in pipeline_meta (default: local-debug)",
    )
    parser.add_argument(
        "--working-dir",
        default=str(repo_root()),
        help="Repo/working directory for relative output paths",
    )
    parser.add_argument(
        "--layers-dir",
        default=None,
        help="Directory for layer outputs and sublayer artifacts (default: run layers dir)",
    )


def add_raw_transcript_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--raw-transcript",
        default=None,
        help="L0 transcription.json (default: output/transcriptions/<run-name>/transcription.json)",
    )


def add_video_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--video",
        default=None,
        help="Video file for L2 video reconcile (optional; skips S1 if omitted)",
    )


def add_audio_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--audio",
        default=None,
        help=(
            "Source audio WAV for L3 voice gender (optional; defaults to "
            "output/original/extracted_audio.wav under --working-dir)"
        ),
    )


def parse_paths(
    args: argparse.Namespace,
    *,
    layer_id: str,
) -> tuple[Path, Path, Path, Path, str]:
    working_dir = Path(args.working_dir).expanduser().resolve()

    video_path = (
        resolve_path(args.video, base=working_dir)
        if getattr(args, "video", None)
        else None
    )
    input_path = (
        resolve_path(args.input, base=working_dir)
        if getattr(args, "input", None)
        else None
    )
    raw_transcript_arg = getattr(args, "raw_transcript", None)
    raw_transcript_path_arg = (
        resolve_path(raw_transcript_arg, base=working_dir)
        if raw_transcript_arg
        else None
    )

    run_name = resolve_run_name(
        run_name=getattr(args, "run_name", None),
        video_path=video_path,
        input_path=input_path or raw_transcript_path_arg,
        working_dir=working_dir,
    )

    if input_path is None:
        input_path = default_input_path(layer_id, working_dir, run_name)
    if getattr(args, "output", None):
        output_path = resolve_path(args.output, base=working_dir)
    else:
        output_path = default_output_path(layer_id, working_dir, run_name)
    if getattr(args, "layers_dir", None):
        layers_dir = resolve_path(args.layers_dir, base=working_dir)
    else:
        layers_dir = run_layers_dir(working_dir, run_name)

    return working_dir, input_path, output_path, layers_dir, run_name


def resolve_raw_transcript_path(args: argparse.Namespace, working_dir: Path, run_name: str) -> Path:
    if getattr(args, "raw_transcript", None):
        return resolve_path(args.raw_transcript, base=working_dir)
    return raw_transcript_path(working_dir, run_name)


def print_chain_hint(layer_id: str, output_path: Path, *, working_dir: Path | None = None) -> None:
    next_layer = None
    for i, (lid, _, _) in enumerate(LAYER_CHAIN):
        if lid == layer_id and i + 1 < len(LAYER_CHAIN):
            next_layer = LAYER_CHAIN[i + 1]
            break
    if not next_layer:
        print("\nChain complete (terminal layer).")
        return
    next_id, _, _ = next_layer
    if next_id == "L0":
        return
    script_map = {
        "L1": "run_l1_normalize.py",
        "L2": "run_l2_identity.py",
        "L3": "run_l3_gender.py",
        "L4": "run_l4_finalize.py",
    }
    script = script_map.get(next_id)
    if not script:
        return

    base = working_dir or repo_root()
    run_name = infer_run_name(output_path, working_dir=base)
    print("\nNext step:")
    if run_name:
        print(f"  python scripts/enrichment/{script} --run-name {run_name}")
    else:
        print(f"  python scripts/enrichment/{script} --input {output_path}")
