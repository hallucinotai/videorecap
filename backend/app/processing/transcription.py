import os
from contextlib import contextmanager
from typing import Callable

from app.config import settings


@contextmanager
def patched_module_paths(working_dir: str):
    """Temporarily patch SCRIPT_DIR and get_output_path in modules.transcription."""
    import modules.transcription as mod

    original_script_dir = mod.SCRIPT_DIR
    original_get_output_path = mod.get_output_path

    mod.SCRIPT_DIR = working_dir
    mod.get_output_path = lambda rel: os.path.join(working_dir, rel)
    try:
        yield
    finally:
        mod.SCRIPT_DIR = original_script_dir
        mod.get_output_path = original_get_output_path


def transcribe_video_service(
    video_path: str,
    working_dir: str,
    model_size: str = "small",
    language: str | None = None,
    include_emotions: bool = False,
    progress_callback: Callable | None = None,
) -> dict:
    """Wrap modules.transcription.transcribe_with_optional_emotions with path isolation.

    Supports multiple transcription backends:
    - AssemblyAI with speaker diarization (if ENABLE_ASSEMBLYAI_DIARIZATION=true)
    - Emotion analysis via Google Cloud Speech (if include_emotions=true)
    - Default Whisper transcription (free/local)

    Args:
        include_emotions: If True, performs emotion analysis (PREMIUM tier).
                         If False, transcription only (BASIC/FREE tier).

    Returns:
        {"transcription_file": path, "emotions_file": path_or_none}
    """
    from modules.transcription import (
        is_whisper_model_cached,
        sync_whisper_cache_invalidation,
        transcribe_with_optional_emotions,
    )

    with patched_module_paths(working_dir):
        sync_whisper_cache_invalidation(settings.REDIS_URL)

        # Determine which transcription method to use
        tier = ""
        if settings.ENABLE_ASSEMBLYAI_DIARIZATION and settings.ASSEMBLYAI_API_KEY:
            tier = "AssemblyAI with SPEAKER DIARIZATION"
        elif include_emotions:
            tier = "PREMIUM (with emotion analysis)"
        else:
            tier = "BASIC (transcription only)"

        if progress_callback:
            if settings.ENABLE_ASSEMBLYAI_DIARIZATION and settings.ASSEMBLYAI_API_KEY:
                progress_callback(step=1, message=f"Transcribing [{tier}] - identifying speakers…")
            elif is_whisper_model_cached(model_size):
                progress_callback(step=1, message=f"Transcribing [{tier}] (Whisper model already loaded)…")
            else:
                progress_callback(
                    step=1,
                    message=f"Loading Whisper model (first job on this worker), then transcribing [{tier}]…",
                )

        transcription_file, emotions_file = transcribe_with_optional_emotions(
            video_path,
            output_dir="output/transcriptions",
            model_size=model_size,
            language=language,
            include_emotions=include_emotions,
            enable_assemblyai_diarization=settings.ENABLE_ASSEMBLYAI_DIARIZATION,
            assemblyai_api_key=settings.ASSEMBLYAI_API_KEY,
            assemblyai_language_code=settings.ASSEMBLYAI_LANGUAGE_CODE,
        )

        if progress_callback:
            if settings.ENABLE_ASSEMBLYAI_DIARIZATION and settings.ASSEMBLYAI_API_KEY:
                progress_callback(step=1, message="Transcription + speaker diarization complete")
            else:
                msg = "Transcription + emotion analysis complete" if include_emotions else "Transcription complete"
                progress_callback(step=1, message=msg)

        return {
            "transcription_file": transcription_file,
            "emotions_file": emotions_file,
        }


def translate_transcription_service(
    transcription_file: str,
    working_dir: str,
    source_lang: str,
    target_lang: str,
    progress_callback: Callable | None = None,
) -> dict:
    """Wrap modules.transcription.translate_transcription with path isolation."""
    from modules.transcription import translate_transcription

    with patched_module_paths(working_dir):
        if progress_callback:
            progress_callback(step=2, message=f"Translating {source_lang} → {target_lang}...")
        result_path = translate_transcription(
            transcription_file,
            source_lang=source_lang,
            target_lang=target_lang,
            output_dir="output/transcriptions",
        )
        if progress_callback:
            progress_callback(step=2, message="Translation complete")
        return {"translated_file": result_path}
