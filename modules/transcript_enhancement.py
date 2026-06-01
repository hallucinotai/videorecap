import json
import re
from typing import Dict, Any, Optional


def load_enhanced_transcript(transcript_path: str) -> Dict[str, Any]:
    """Load the enhanced transcript JSON with speaker diarization."""
    with open(transcript_path, "r") as f:
        return json.load(f)


def get_speaker_label(speaker_id: str, speaker_info: Dict[str, Any]) -> str:
    """Get a readable label for a speaker (e.g., 'Speaker A (James)' or just 'Speaker A')."""
    if speaker_info.get("name"):
        return f"Speaker {speaker_id} ({speaker_info['name']})"
    return f"Speaker {speaker_id}"


def get_speaker_context(transcript: Dict[str, Any]) -> Dict[str, str]:
    """Build a speaker context mapping (speaker_id -> readable label)."""
    context = {}
    for speaker_id, speaker_info in transcript.get("speakers", {}).items():
        context[speaker_id] = get_speaker_label(speaker_id, speaker_info)
    return context


def extract_speaker_mentions(segment_text: str) -> Optional[str]:
    """Extract speaker names mentioned in segment text."""
    # Pattern: "I'm [Name]" or "I am [Name]"
    match = re.search(r"[Ii](?:'m| am) ([A-Z][a-z]+)", segment_text)
    if match:
        return match.group(1)
    return None


def build_narration_context(transcript: Dict[str, Any]) -> Dict[str, Any]:
    """Build context for narration generation including speaker info."""
    speaker_context = get_speaker_context(transcript)
    segments = transcript.get("segments", {})

    # Build segment summaries with speaker names
    segment_summaries = []
    for seg_id, segment in segments.items():
        speaker_label = speaker_context.get(segment["speaker"], f"Speaker {segment['speaker']}")
        segment_summaries.append({
            "time": f"{segment['start']:.1f}s",
            "speaker": speaker_label,
            "speaker_name": segment.get("speaker_name"),
            "text": segment["text"],
            "confidence": segment.get("speaker_confidence", 0.0)
        })

    return {
        "speaker_context": speaker_context,
        "speakers": transcript.get("speakers", {}),
        "segments": segment_summaries,
        "metadata": transcript.get("metadata", {})
    }


def create_speaker_summary(transcript: Dict[str, Any]) -> str:
    """Create a summary of who's speaking in the video."""
    speakers = transcript.get("speakers", {})
    if not speakers:
        return ""

    lines = []
    for speaker_id in sorted(speakers.keys()):
        info = speakers[speaker_id]
        name_str = f" - {info['name']}" if info.get("name") else ""
        duration = info.get("total_duration_seconds", 0)
        word_count = info.get("total_words", 0)
        lines.append(f"Speaker {speaker_id}{name_str}: {word_count} words, {duration:.1f}s")

    return "Speakers: " + "; ".join(lines) if lines else ""


def get_transcript_for_narration(transcript_path: str) -> Dict[str, Any]:
    """Load transcript and prepare it for narration generation with speaker context."""
    transcript = load_enhanced_transcript(transcript_path)
    narration_context = build_narration_context(transcript)
    speaker_summary = create_speaker_summary(transcript)

    return {
        "transcript": transcript,
        "narration_context": narration_context,
        "speaker_summary": speaker_summary,
        "speakers": narration_context["speaker_context"]
    }
