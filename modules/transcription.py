"""
Modular Video Transcription and Recap Generation

This module contains individual functions for each step of the workflow.
Each function is independent and can be called separately.
"""

import json
import os
import threading
from typing import Any

import whisper
from moviepy.editor import VideoFileClip

try:
    import assemblyai as aai
except ImportError:
    aai = None

# Get the directory where this file is located (parent of modules/)
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# One Whisper model per (model_size) per process — Celery workers reuse the same process,
# so the second+ job avoids disk load and model init latency.
_WHISPER_MODEL_CACHE: dict[str, Any] = {}
_WHISPER_LOAD_LOCK = threading.Lock()
# Last Redis "generation" this process applied (see sync_whisper_cache_invalidation).
_WHISPER_GEN_SEEN: int = -1

# Redis key for global cache bust (INCR from API); workers observe on next transcribe.
WHISPER_CACHE_REDIS_KEY = "videorecap:whisper_cache_gen"


def is_whisper_model_cached(model_size: str) -> bool:
    return model_size in _WHISPER_MODEL_CACHE


def _get_whisper_model(model_size: str):
    if model_size not in _WHISPER_MODEL_CACHE:
        with _WHISPER_LOAD_LOCK:
            if model_size not in _WHISPER_MODEL_CACHE:
                print(f"Loading Whisper model '{model_size}' (cached for reuse in this worker)...")
                _WHISPER_MODEL_CACHE[model_size] = whisper.load_model(model_size)
    else:
        print(f"Using cached Whisper model '{model_size}' (no reload)")
    return _WHISPER_MODEL_CACHE[model_size]


def clear_whisper_model_cache() -> None:
    """Remove loaded Whisper models from this process (next job loads from disk again)."""
    global _WHISPER_MODEL_CACHE
    with _WHISPER_LOAD_LOCK:
        _WHISPER_MODEL_CACHE.clear()
    print("Whisper in-process cache cleared for this worker.")


def sync_whisper_cache_invalidation(redis_url: str | None) -> None:
    """If Redis generation changed (user requested cache clear), drop local Whisper cache."""
    global _WHISPER_GEN_SEEN
    if not redis_url:
        return
    try:
        import redis as redis_sync

        r = redis_sync.Redis.from_url(redis_url, decode_responses=True)
        try:
            raw = r.get(WHISPER_CACHE_REDIS_KEY)
            gen = int(raw) if raw is not None else 0
        finally:
            r.close()
    except Exception as exc:
        print(f"Whisper cache generation check skipped: {exc}")
        return

    if gen != _WHISPER_GEN_SEEN:
        if _WHISPER_MODEL_CACHE:
            clear_whisper_model_cache()
        _WHISPER_GEN_SEEN = gen


def get_output_path(relative_path):
    """Convert relative output path to absolute path"""
    return os.path.join(SCRIPT_DIR, relative_path)


def transcribe_video(video_path, output_dir="output/transcriptions", model_size="small", language=None):
    """
    Step 1: Transcribe video to text with timestamps
    
    Args:
        video_path: Path to input video file
        output_dir: Directory to save transcription
        model_size: Whisper model size (tiny, base, small, medium, large)
        language: Language code (e.g., 'en' for English, 'es' for Spanish). Auto-detect if None.
    
    Returns:
        Path to transcription file
    """
    print(f"\n{'='*70}")
    print(f"STEP 1: TRANSCRIBING VIDEO")
    print(f"{'='*70}")
    print(f"Video: {video_path}")
    print(f"Model: {model_size}")
    if language:
        print(f"Language: {language}")
    
    model = _get_whisper_model(model_size)
    
    # Create output directories
    output_path = get_output_path(output_dir)
    os.makedirs(output_path, exist_ok=True)
    
    original_dir = get_output_path("output/original")
    os.makedirs(original_dir, exist_ok=True)
    
    # Extract audio from video
    print("Extracting audio from video...")
    video = VideoFileClip(video_path)
    temp_audio = os.path.join(original_dir, "extracted_audio.wav")
    video.audio.write_audiofile(temp_audio, verbose=False, logger=None)
    video.close()
    
    print(f"Audio extracted to: {temp_audio}")
    
    # Transcribe audio
    print("Transcribing audio...")
    transcribe_options = {"verbose": True}
    if language:
        transcribe_options["language"] = language
    result = model.transcribe(temp_audio, **transcribe_options)
    
    # Process segments
    transcript_data = []
    for segment in result['segments']:
        transcript_data.append({
            "start": segment['start'],
            "end": segment['end'],
            "text": segment['text'].strip()
        })
    
    # Save transcription
    output_path = get_output_path(output_dir)
    os.makedirs(output_path, exist_ok=True)
    
    # Save as JSON
    json_file = os.path.join(output_path, "transcription.json")
    with open(json_file, "w") as f:
        json.dump(transcript_data, f, indent=2)
    
    # Save as human-readable text
    txt_file = os.path.join(output_path, "transcription.txt")
    with open(txt_file, "w") as f:
        for segment in transcript_data:
            f.write(f"{segment['start']:.2f}s to {segment['end']:.2f}s: {segment['text']}\n")
    
    # Save full transcription text to original folder
    full_text_file = os.path.join(original_dir, "full_transcription.txt")
    with open(full_text_file, "w") as f:
        for segment in transcript_data:
            f.write(f"{segment['text']}\n")
    
    print(f"✅ Transcription complete!")
    print(f"   Segments: {len(transcript_data)}")
    print(f"   JSON: {json_file}")
    print(f"   Text: {txt_file}")
    print(f"   Full text: {full_text_file}")
    print(f"   Extracted audio: {temp_audio} (preserved)")
    
    return json_file


def transcribe_video_with_assemblyai(
    video_path,
    output_dir="output/transcriptions",
    api_key=None,
    language_code="en"
):
    """
    Transcribe video using AssemblyAI with speaker diarization support.

    This function transcribes audio and identifies different speakers,
    providing speaker labels (A, B, C, etc.) and confidence scores.

    Args:
        video_path: Path to input video file
        output_dir: Directory to save transcription
        api_key: AssemblyAI API key (required)
        language_code: Language code (default: "en")

    Returns:
        Path to transcription file (with speaker diarization)
    """
    if not aai:
        raise ImportError("assemblyai package not installed. Install with: pip install assemblyai")

    if not api_key:
        raise ValueError("AssemblyAI API key is required but not provided")

    print(f"\n{'='*70}")
    print(f"STEP 1: TRANSCRIBING VIDEO WITH SPEAKER DIARIZATION (AssemblyAI)")
    print(f"{'='*70}")
    print(f"Video: {video_path}")
    print(f"Language: {language_code}")
    print(f"Provider: AssemblyAI with speaker diarization")

    # Set up AssemblyAI client
    aai.settings.api_key = api_key

    # Extract audio from video (AssemblyAI works with audio files)
    print("Extracting audio from video...")
    video = VideoFileClip(video_path)
    temp_audio = os.path.join(get_output_path("output/original"), "extracted_audio.wav")
    os.makedirs(os.path.dirname(temp_audio), exist_ok=True)
    video.audio.write_audiofile(temp_audio, verbose=False, logger=None)
    video.close()
    print(f"Audio extracted to: {temp_audio}")

    # Transcribe with AssemblyAI
    print("Transcribing audio with speaker diarization...")

    try:
        settings = aai.Settings(api_key=api_key)
        client = aai.Client(settings=settings)
    except Exception as e:
        raise RuntimeError(f"Failed to initialize AssemblyAI client: {e}") from e

    try:
        config = aai.TranscriptionConfig(
            speaker_labels=True,
            speech_models=["universal-3-pro", "universal-2"],
            language_code=language_code,
        )
        transcriber = aai.Transcriber(client=client)
        transcript = transcriber.transcribe(temp_audio, config=config)
    except Exception as e:
        raise RuntimeError(f"AssemblyAI transcription failed: {e}") from e

    # Check if transcription was successful
    if not transcript or transcript.status.value != "completed":
        status_value = transcript.status.value if transcript and hasattr(transcript, 'status') else 'unknown'
        raise RuntimeError(f"AssemblyAI transcription did not complete: {status_value}")

    # Extract speaker names from text (e.g., "I'm John" or "I am Jane")
    # Strategy: Count all name mentions per speaker, use most frequent as final name
    # This handles self-corrections: "I'm James" (1x) → "I'm Lanes" (2x) = choose "Lanes"
    import re
    speaker_names = {}
    speaker_name_counts = {}  # Track mention counts for each speaker

    for segment in transcript.utterances:
        speaker_id = segment.speaker or "Unknown"
        if speaker_id not in speaker_name_counts:
            speaker_name_counts[speaker_id] = {}

        # Find all name mentions in this segment
        matches = re.finditer(r"[Ii](?:'m| am) ([A-Z][a-z]+)", segment.text)
        for match in matches:
            name = match.group(1)
            speaker_name_counts[speaker_id][name] = speaker_name_counts[speaker_id].get(name, 0) + 1

    # Choose most frequent name per speaker (handles self-corrections naturally)
    for speaker_id, names_dict in speaker_name_counts.items():
        if names_dict:
            speaker_names[speaker_id] = max(names_dict, key=names_dict.get)

    # Process segments with speaker information
    transcript_data = {}
    speakers_info = {}

    for i, segment in enumerate(transcript.utterances):
        speaker_id = segment.speaker or "Unknown"

        # Build transcript entry with speaker
        segment_entry = {
            "text": segment.text.strip(),
            "start": float(segment.start / 1000),  # Convert ms to seconds
            "end": float(segment.end / 1000),
            "speaker": speaker_id,
            "speaker_confidence": float(segment.confidence) if segment.confidence else 0.0,
        }
        # Use canonical speaker-level name (not segment-level extraction)
        # This ensures consistency: all segments for Speaker A use the same final name
        if speaker_id in speaker_names:
            segment_entry["speaker_name"] = speaker_names[speaker_id]
        transcript_data[str(i)] = segment_entry

        # Track speaker stats
        if speaker_id not in speakers_info:
            speakers_info[speaker_id] = {
                "speaker_id": speaker_id,
                "name": speaker_names.get(speaker_id),  # Add extracted name if found
                "total_words": 0,
                "total_duration_seconds": 0.0,
                "confidence_scores": []
            }

        speakers_info[speaker_id]["total_words"] += len(segment.text.split())
        speakers_info[speaker_id]["total_duration_seconds"] += (segment.end - segment.start) / 1000
        if segment.confidence:
            speakers_info[speaker_id]["confidence_scores"].append(float(segment.confidence))

    # Calculate average confidence for each speaker and track name corrections
    for speaker_id, info in speakers_info.items():
        if info["confidence_scores"]:
            info["avg_confidence"] = sum(info["confidence_scores"]) / len(info["confidence_scores"])
        else:
            info["avg_confidence"] = 0.0
        # Clean up intermediate data
        del info["confidence_scores"]

        # Track name mentions and corrections if speaker identified themselves multiple times
        if speaker_id in speaker_name_counts and speaker_name_counts[speaker_id]:
            info["name_mentions"] = speaker_name_counts[speaker_id]
            # Flag if speaker corrected themselves (mentioned different names)
            if len(speaker_name_counts[speaker_id]) > 1:
                final_name = info["name"]
                corrected_from = [n for n in speaker_name_counts[speaker_id].keys() if n != final_name]
                if corrected_from:
                    info["corrected_from"] = corrected_from

    # Create output structure with metadata
    output_structure = {
        "metadata": {
            "provider": "assemblyai",
            "speaker_diarization_enabled": True,
            "language_code": language_code,
        },
        "speakers": speakers_info,
        "segments": transcript_data
    }

    # Save transcription
    output_path = get_output_path(output_dir)
    os.makedirs(output_path, exist_ok=True)

    # Save as JSON
    json_file = os.path.join(output_path, "transcription.json")
    with open(json_file, "w") as f:
        json.dump(output_structure, f, indent=2)

    # Save as human-readable text
    txt_file = os.path.join(output_path, "transcription.txt")
    with open(txt_file, "w") as f:
        for seg_id, segment in transcript_data.items():
            f.write(f"[{segment['start']:.2f}s - {segment['end']:.2f}s] [{segment['speaker']}]: {segment['text']}\n")

    print(f"✅ Transcription complete with speaker diarization!")
    print(f"   Segments: {len(transcript_data)}")
    print(f"   Speakers found: {len(speakers_info)}")
    for speaker_id, info in speakers_info.items():
        name_str = f" ({info['name']})" if info.get('name') else ""
        print(f"     - Speaker {speaker_id}{name_str}: {info['total_words']} words, {info['total_duration_seconds']:.1f}s, confidence: {info['avg_confidence']:.2f}")
    print(f"   JSON: {json_file}")
    print(f"   Text: {txt_file}")
    print(f"   Extracted audio: {temp_audio} (preserved)")

    return json_file


def transcribe_video_with_emotions(
    video_path,
    output_dir="output/transcriptions",
    model_size="small",
    language=None,
    skip_emotions_on_error=True
):
    """
    Step 1+: Transcribe video AND analyze emotions from audio (PREMIUM FEATURE)

    This is the premium version that includes emotion analysis.
    Cost: +$0.02-0.05 per video (Google Cloud Speech API)
    Time: +5-8 seconds per video

    Args:
        video_path: Path to input video file
        output_dir: Directory to save transcription
        model_size: Whisper model size (tiny, base, small, medium, large)
        language: Language code (e.g., 'en' for English, 'es' for Spanish). Auto-detect if None.
        skip_emotions_on_error: If True, continue without emotions if analysis fails

    Returns:
        Tuple: (transcription_file_path, emotions_file_path or None)
    """
    # Step 1: First, do regular transcription (reuse existing function)
    transcript_file = transcribe_video(video_path, output_dir, model_size, language)

    # Step 1.5: Analyze emotions (NEW)
    print(f"\n{'='*70}")
    print(f"STEP 1.5: ANALYZING AUDIO EMOTIONS (PREMIUM)")
    print(f"{'='*70}")

    try:
        # Import here to avoid hard dependency
        from app.processing.emotion_analysis import analyze_audio_emotions

        audio_path = os.path.join(get_output_path("output/original"), "extracted_audio.wav")

        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        print(f"Audio: {audio_path}")
        print("Analyzing emotions from speech...")

        emotions = analyze_audio_emotions(audio_path)

        # Save emotions as JSON
        output_path = get_output_path(output_dir)
        emotions_file = os.path.join(output_path, "emotions.json")
        with open(emotions_file, "w") as f:
            json.dump(emotions, f, indent=2)

        print(f"✅ Emotion analysis complete!")
        print(f"   Segments analyzed: {len(emotions)}")
        print(f"   Emotions file: {emotions_file}")
        print(f"   Cost: +$0.02-0.05 (Google Cloud Speech API)")

        return transcript_file, emotions_file

    except Exception as e:
        error_msg = f"Emotion analysis failed: {e}"
        print(f"⚠️  {error_msg}")

        if skip_emotions_on_error:
            print("   Continuing without emotions (will use basic transcription only)")
            return transcript_file, None
        else:
            raise


def transcribe_with_optional_emotions(
    video_path,
    output_dir="output/transcriptions",
    model_size="small",
    language=None,
    include_emotions=False,
    enable_assemblyai_diarization=False,
    assemblyai_api_key=None,
    assemblyai_language_code="en"
):
    """
    Unified transcription function that respects subscription tier and feature flags.

    This is the MAIN function to use. It dispatches to:
    - transcribe_video_with_assemblyai() if AssemblyAI diarization enabled
    - transcribe_video_with_emotions() for PREMIUM tier (with emotions)
    - transcribe_video() for FREE/BASIC tier

    Args:
        video_path: Path to input video file
        output_dir: Directory to save transcription
        model_size: Whisper model size
        language: Language code
        include_emotions: Boolean - whether to include emotion analysis
        enable_assemblyai_diarization: Boolean - whether to use AssemblyAI with speaker diarization
        assemblyai_api_key: AssemblyAI API key (required if diarization enabled)
        assemblyai_language_code: Language code for AssemblyAI

    Returns:
        Tuple: (transcription_file, emotions_file or None)
    """
    # Priority: AssemblyAI with diarization if enabled
    if enable_assemblyai_diarization and assemblyai_api_key:
        print("🎤 Using AssemblyAI with SPEAKER DIARIZATION")
        transcript_file = transcribe_video_with_assemblyai(
            video_path,
            output_dir,
            api_key=assemblyai_api_key,
            language_code=assemblyai_language_code
        )
        return transcript_file, None

    # Fallback: Emotion analysis if enabled
    if include_emotions:
        print("🎙️  Using PREMIUM tier (with emotion analysis)")
        return transcribe_video_with_emotions(
            video_path,
            output_dir,
            model_size,
            language,
            skip_emotions_on_error=True
        )

    # Default: Basic Whisper transcription
    print("📝 Using BASIC tier (transcription only)")
    transcript_file = transcribe_video(video_path, output_dir, model_size, language)
    return transcript_file, None


def translate_transcription(input_file, source_lang, target_lang, output_dir="output/transcriptions"):
    """
    Step 2: Translate transcription to another language.

    Accepts either a JSON file (list of {start, end, text}) or a legacy .txt
    file.  Always returns a JSON file so downstream consumers get structured data.

    Args:
        input_file: Path to transcription.json (preferred) or .txt
        source_lang: Source language (e.g., "English")
        target_lang: Target language (e.g., "Tamil")
        output_dir: Directory to save translation

    Returns:
        Path to translated JSON file
    """
    from openai import OpenAI
    import dotenv

    dotenv.load_dotenv()

    print(f"\n{'='*70}")
    print(f"STEP 2: TRANSLATING TRANSCRIPTION")
    print(f"{'='*70}")
    print(f"Input: {input_file}")
    print(f"Translation: {source_lang} → {target_lang}")

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), max_retries=5)
    model_name = os.getenv("OPENAI_MODEL", "gpt-4o")

    # Read segments — support both JSON and legacy .txt
    if input_file.endswith(".json"):
        with open(input_file, "r") as f:
            segments = json.load(f)
    else:
        segments = []
        with open(input_file, "r") as f:
            for line in f:
                parts = line.strip().split(": ", 1)
                if len(parts) == 2:
                    ts, text = parts
                    ts_parts = ts.replace("s", "").split(" to ")
                    try:
                        segments.append({
                            "start": float(ts_parts[0]),
                            "end": float(ts_parts[1]),
                            "text": text,
                        })
                    except (ValueError, IndexError):
                        continue

    # Batch-translate segments to reduce API calls and token usage.
    # Each batch sends a numbered list; the LLM returns translations
    # in the same numbered order.
    BATCH_SIZE = 15
    total = len(segments)
    for batch_start in range(0, total, BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE, total)
        batch = segments[batch_start:batch_end]
        print(f"Translating segments {batch_start + 1}-{batch_end}/{total}...")

        numbered_lines = "\n".join(
            f"{i+1}. {seg['text']}" for i, seg in enumerate(batch)
        )
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": (
                    "You are a professional translator. You will receive numbered lines. "
                    "Translate each line and return ONLY the translated lines in the same "
                    "numbered format (e.g. '1. translated text'). Preserve the numbering "
                    "exactly. Do not add explanations."
                )},
                {"role": "user", "content": (
                    f"Translate each line from {source_lang} to {target_lang}:\n\n{numbered_lines}"
                )},
            ],
            max_tokens=3000,
        )
        result_text = response.choices[0].message.content or ""

        translated = {}
        for line in result_text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            dot_idx = line.find(".")
            if dot_idx > 0:
                try:
                    num = int(line[:dot_idx].strip())
                    translated[num] = line[dot_idx + 1:].strip()
                except ValueError:
                    continue

        for i, seg in enumerate(batch):
            if (i + 1) in translated:
                seg["text"] = translated[i + 1]

    # Save as JSON
    output_path = get_output_path(output_dir)
    os.makedirs(output_path, exist_ok=True)

    output_file = os.path.join(output_path, f"{target_lang.lower()}_transcription.json")
    with open(output_file, "w") as f:
        json.dump(segments, f, indent=2)

    print(f"✅ Translation complete!")
    print(f"   Segments translated: {len(segments)}")
    print(f"   Output: {output_file}")

    return output_file


# Export functions
__all__ = [
    "WHISPER_CACHE_REDIS_KEY",
    "clear_whisper_model_cache",
    "get_output_path",
    "is_whisper_model_cached",
    "sync_whisper_cache_invalidation",
    "transcribe_video",
    "transcribe_video_with_emotions",
    "transcribe_with_optional_emotions",
    "translate_transcription",
]

