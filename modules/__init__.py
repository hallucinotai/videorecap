"""
Modular Video Transcription and Recap Generation

This package contains modular functions for video processing workflows.

Modules:
- transcription: Video transcription and translation
- video_processing: Recap generation, clip extraction, audio removal
- audio_processing: TTS generation and audio-video merging
- enrichment: Transcript enrichment layers (L1, L2, …)
"""

__all__ = [
    "transcribe_video",
    "translate_transcription",
    "generate_recap_suggestions",
    "extract_and_merge_clips",
    "remove_audio_from_video",
    "generate_tts_audio",
    "merge_audio_with_video",
]


def __getattr__(name: str):
    if name in ("transcribe_video", "translate_transcription"):
        from .transcription import transcribe_video, translate_transcription

        return transcribe_video if name == "transcribe_video" else translate_transcription
    if name in ("generate_recap_suggestions", "extract_and_merge_clips", "remove_audio_from_video"):
        from .video_processing import (
            extract_and_merge_clips,
            generate_recap_suggestions,
            remove_audio_from_video,
        )

        return {
            "generate_recap_suggestions": generate_recap_suggestions,
            "extract_and_merge_clips": extract_and_merge_clips,
            "remove_audio_from_video": remove_audio_from_video,
        }[name]
    if name in ("generate_tts_audio", "merge_audio_with_video"):
        from .audio_processing import generate_tts_audio, merge_audio_with_video

        return generate_tts_audio if name == "generate_tts_audio" else merge_audio_with_video
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
