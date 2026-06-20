"""
Video Processing Modules

Contains functions for:
- Generating AI-powered recap suggestions
- Extracting and combining video clips
- Removing audio from videos
"""

import os
import json
import sys
from moviepy.editor import VideoFileClip, concatenate_videoclips

# Add backend app to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'backend'))
from app.prompts.narration_prompts import get_narration_system_prompt

# Get the directory where this file is located
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_output_path(relative_path):
    """Convert relative output path to absolute path"""
    return os.path.join(SCRIPT_DIR, relative_path)


def _parse_llm_json(raw: str) -> dict:
    """Strip markdown fences and parse JSON from an LLM response."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def _read_transcript_segments(path: str) -> list[dict]:
    """Load transcript segments from JSON or legacy .txt.

    Handles enhanced transcript format (with speaker diarization) and legacy format.
    For enhanced format, extracts segments and includes speaker/speaker_name info.
    """
    if path.endswith(".json"):
        with open(path, "r") as f:
            data = json.load(f)

        # Check if this is enhanced format with metadata and segments
        if isinstance(data, dict) and "segments" in data and "metadata" in data:
            # Enhanced transcript format from AssemblyAI with speaker diarization
            segments_dict = data.get("segments", {})
            segments = []
            for seg_id, segment in segments_dict.items():
                seg = {
                    "start": segment.get("start", 0),
                    "end": segment.get("end", 0),
                    "text": segment.get("text", ""),
                }
                # Include speaker info if available
                if "speaker" in segment:
                    seg["speaker"] = segment["speaker"]
                if "speaker_name" in segment:
                    seg["speaker_name"] = segment["speaker_name"]
                if "speaker_confidence" in segment:
                    seg["speaker_confidence"] = segment["speaker_confidence"]
                segments.append(seg)
            return segments
        elif isinstance(data, list):
            # Legacy or simple array format
            return data
        else:
            return []

    # Legacy .txt format
    segments = []
    with open(path, "r") as f:
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
    return segments


def _merge_emotions_with_segments(segments: list[dict], emotions_file: str) -> list[dict]:
    """
    Merge emotion data into transcript segments by time overlap.

    Each segment gets populated with emotion info from the emotions data
    if the time ranges overlap. Adds: emotions{}, dominant_emotion, intensity.
    """
    if not emotions_file or not os.path.exists(emotions_file):
        return segments

    try:
        with open(emotions_file, "r") as f:
            emotions_data = json.load(f)
    except Exception as e:
        print(f"⚠️  Could not load emotions file: {e}")
        return segments

    # Build a time-indexed map of emotions for fast lookup
    emotions_by_time = {}
    for emotion_segment in emotions_data:
        start = emotion_segment.get("start", 0)
        end = emotion_segment.get("end", 0)
        emotions_by_time[(start, end)] = emotion_segment

    # Merge emotions into transcript segments
    for segment in segments:
        seg_start = segment.get("start", 0)
        seg_end = segment.get("end", 0)

        # Find overlapping emotion segment(s)
        best_overlap = None
        best_overlap_amount = 0

        for (emo_start, emo_end), emotion_segment in emotions_by_time.items():
            # Calculate overlap
            overlap_start = max(seg_start, emo_start)
            overlap_end = min(seg_end, emo_end)
            overlap = max(0, overlap_end - overlap_start)

            if overlap > best_overlap_amount:
                best_overlap = emotion_segment
                best_overlap_amount = overlap

        if best_overlap:
            segment["emotions"] = best_overlap.get("emotions", {})
            segment["dominant_emotion"] = best_overlap.get("dominant_emotion", "neutral")
            segment["intensity"] = best_overlap.get("intensity", 0.5)
            segment["confidence"] = best_overlap.get("confidence", 0.8)

    return segments


def validate_clip_timings(clip_timings: list[dict], video_duration: float | None = None) -> list[dict]:
    """Sanitize and validate LLM-returned clip windows.

    Fixes:
      - Negative / zero-length clips (dropped)
      - end > video_duration (clamped)
      - Overlapping ranges (later clip trimmed)
      - Non-chronological order (sorted)

    Returns the cleaned list; raises ValueError if nothing survives.
    """
    cleaned = []
    for clip in sorted(clip_timings, key=lambda c: c["start"]):
        start = round(float(clip.get("start", 0)), 2)
        end = round(float(clip.get("end", start)), 2)
        if end <= start:
            continue
        if video_duration is not None and start >= video_duration:
            continue
        if video_duration is not None and end > video_duration:
            end = round(video_duration, 2)
        if cleaned:
            prev_end = cleaned[-1]["end"]
            if start < prev_end:
                start = prev_end
            if end <= start:
                continue
        cleaned.append({**clip, "start": start, "end": end})

    if not cleaned:
        raise ValueError("No valid clip timings after validation")
    return cleaned


def generate_recap_suggestions(transcription_file, target_duration=30, output_dir="output/transcriptions", narration_language=None, emotions_file=None):
    """
    Step 3: Generate AI-powered recap suggestions using two focused LLM calls.

    Call 1 — Clip selection (video-editor mindset): returns clip_timings only.
    Call 2 — Narration (scriptwriter mindset): given the selected clips, writes
             recap_text calibrated to the visual timeline.

    Accepts JSON (preferred) or legacy .txt transcription files.
    Optionally incorporates emotion analysis to prioritize emotionally intense moments.

    Args:
        transcription_file: Path to transcription JSON or .txt
        target_duration: Target recap duration in seconds
        output_dir: Directory to save recap data
        narration_language: Language for the narration output (e.g. "Tamil").
                            If None, narration is written in the same language as the transcript.
        emotions_file: Optional path to emotions.json (from transcribe_video_with_emotions).
                       If provided, clips will be weighted toward emotional intensity.

    Returns:
        Path to recap_data.json
    """
    from openai import OpenAI
    import dotenv

    dotenv.load_dotenv()

    print(f"\n{'='*70}")
    print(f"STEP 3: GENERATING AI RECAP SUGGESTIONS")
    print(f"{'='*70}")
    print(f"Input: {transcription_file}")
    if emotions_file:
        print(f"Emotions: {emotions_file}")

    segments = _read_transcript_segments(transcription_file)
    if not segments:
        raise ValueError("Transcription file is empty or has no segments")

    # Merge emotions if provided
    if emotions_file:
        segments = _merge_emotions_with_segments(segments, emotions_file)
        emotion_context = "\n\nEach segment also includes emotion analysis (if available): dominant_emotion, intensity (0-1 scale), and detailed emotions breakdown."
    else:
        emotion_context = ""

    transcript_json = json.dumps(segments, indent=2)

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), max_retries=5)
    model_name = os.getenv("OPENAI_MODEL", "gpt-4o")

    narration_word_target = max(35, min(220, round(target_duration * 2.0)))
    narration_word_min = max(25, narration_word_target - 25)
    narration_word_max = min(230, narration_word_target + 30)
    print(f"Target duration: {target_duration}s (narration ~{narration_word_target} words, range {narration_word_min}-{narration_word_max})")

    # ------------------------------------------------------------------
    # CALL 1 — Clip selection
    # ------------------------------------------------------------------
    clip_system = (
        "You are a professional video editor. Your job is to select the most "
        "important clip windows from a timestamped transcript to build a recap "
        "of a specific target duration. Think about coverage, pacing, emotional "
        "impact, and avoiding redundancy. Always respond with valid JSON only."
    )
    if emotions_file:
        clip_system += (
            " When emotion data is available, prioritize segments with higher "
            "intensity scores and dominant emotions (joy, surprise, anger) that "
            "drive narrative momentum. Use emotion intensity as a tiebreaker when "
            "content importance is similar."
        )

    clip_prompt = f"""Below is a transcript as a JSON array. Each element has "start" (seconds),
"end" (seconds), and "text" (what was spoken).{emotion_context}

{transcript_json}

Select clips for a {target_duration}-second video recap.

RULES:
1. Pick segments with the most important or interesting content first.
2. {"When emotion data is present, prioritize segments with high emotional intensity (intensity > 0.6) and strong emotions (joy, surprise, anger). " if emotions_file else ""}If meaningful dialogue clips total less than {target_duration}s, add
   supplemental segments (visual transitions, atmospheric moments) to reach
   the target. Label the reason accordingly.
3. Keep clips in chronological order (sorted by start time).
4. No overlapping ranges. No duplicate timestamps.
5. Sum of (end - start) for all clips must equal EXACTLY {target_duration}s (±2s tolerance).

Return JSON only — no explanation, no markdown fences:
{{
  "clip_timings": [
    {{"start": <float>, "end": <float>, "reason": "<why this clip>"}},
    ...
  ]
}}"""

    tolerance = 2.0
    clip_timings = []
    actual_duration = 0
    max_attempts = 3
    clip_messages = [
        {"role": "system", "content": clip_system},
        {"role": "user", "content": clip_prompt},
    ]

    for attempt in range(1, max_attempts + 1):
        print(f"[Call 1] Selecting clips (attempt {attempt}/{max_attempts})...")
        response = client.chat.completions.create(
            model=model_name,
            messages=clip_messages,
            max_tokens=2000,
        )
        result_text = response.choices[0].message.content or ""
        clip_data = _parse_llm_json(result_text)
        clip_timings = clip_data.get("clip_timings", [])
        actual_duration = sum(c["end"] - c["start"] for c in clip_timings)

        if abs(actual_duration - target_duration) <= tolerance:
            print(f"   Duration OK: {actual_duration:.1f}s (target {target_duration}s)")
            break

        print(f"   Duration mismatch: {actual_duration:.1f}s vs target {target_duration}s — retrying...")
        clip_messages.append({"role": "assistant", "content": result_text})
        clip_messages.append({"role": "user", "content": (
            f"The clips total {actual_duration:.1f}s but the target is {target_duration}s. "
            f"Adjust clips so they total EXACTLY {target_duration}s. Return corrected JSON."
        )})

    if abs(actual_duration - target_duration) > tolerance and actual_duration > 0:
        print(f"   Scaling clips: {actual_duration:.1f}s -> {target_duration}s")
        scale = target_duration / actual_duration
        for clip in clip_timings:
            mid = (clip["start"] + clip["end"]) / 2
            half = ((clip["end"] - clip["start"]) * scale) / 2
            clip["start"] = max(0, round(mid - half, 1))
            clip["end"] = round(mid + half, 1)
        actual_duration = sum(c["end"] - c["start"] for c in clip_timings)
        print(f"   Scaled duration: {actual_duration:.1f}s")

    clip_timings = sorted(clip_timings, key=lambda c: c["start"])
    clip_timings = validate_clip_timings(clip_timings)

    # ------------------------------------------------------------------
    # CALL 2 — Narration
    # ------------------------------------------------------------------
    clip_summary = json.dumps(clip_timings, indent=2)
    LANG_MAP = {"en": "English", "es": "Spanish", "fr": "French", "de": "German",
                "pt": "Portuguese", "it": "Italian", "ja": "Japanese", "ko": "Korean",
                "zh": "Chinese", "hi": "Hindi", "ta": "Tamil", "ar": "Arabic", "ru": "Russian"}
    lang_label = LANG_MAP.get(narration_language, narration_language) if narration_language else "English"
    # Load narration system prompt from versioned prompts
    narr_system = get_narration_system_prompt(with_emotion=bool(emotions_file))

    emotion_guidance = ""
    if emotions_file:
        # Extract dominant emotions and speaker context from selected clips for guidance
        selected_emotions = []
        selected_speakers = set()
        for clip in clip_timings:
            # Find the strongest emotion in this clip
            for segment in segments:
                if segment.get("start", 0) >= clip["start"] and segment.get("end", 0) <= clip["end"]:
                    emotion = segment.get("dominant_emotion", "neutral")
                    intensity = segment.get("intensity", 0.5)
                    if emotion != "neutral" and intensity > 0.5:
                        selected_emotions.append(emotion)
                    # Track speaker names
                    if segment.get("speaker_name"):
                        selected_speakers.add(segment["speaker_name"])

        speaker_guidance = ""
        if selected_speakers:
            speaker_guidance = f"\n\nKey speakers: {', '.join(sorted(selected_speakers))}"

        if selected_emotions:
            emotion_guidance = (
                f"\n\nEmotional arc guidance: The clips contain strong moments of "
                f"{', '.join(set(selected_emotions))}. Reflect this emotional journey "
                f"in your narration tone and pacing.{speaker_guidance}"
            )
        else:
            emotion_guidance = speaker_guidance
    else:
        # No emotions file, but still extract speaker context including corrections
        selected_speakers = set()
        speaker_corrections = {}  # Track which speakers corrected their names

        for segment in segments:
            if segment.get("speaker_name"):
                speaker_id = segment.get("speaker", "Unknown")
                selected_speakers.add(segment["speaker_name"])
                # Check if this speaker had name corrections (from metadata)
                if segment.get("corrected_from"):
                    if speaker_id not in speaker_corrections:
                        speaker_corrections[speaker_id] = segment.get("corrected_from", [])

        speaker_guidance = ""
        if selected_speakers:
            speaker_list = sorted(selected_speakers)
            # Add correction context if available
            if speaker_corrections:
                speaker_notes = []
                for speaker_name in speaker_list:
                    # Find if this speaker had corrections
                    has_correction = any(speaker_name == seg.get("speaker_name") and seg.get("corrected_from")
                                        for seg in segments)
                    if has_correction:
                        corrected_from = next((seg.get("corrected_from", []) for seg in segments
                                              if seg.get("speaker_name") == speaker_name and seg.get("corrected_from")), [])
                        if corrected_from:
                            corrections_str = ", ".join(corrected_from)
                            speaker_notes.append(f"{speaker_name} (initially said name was {corrections_str}, then corrected)")
                        else:
                            speaker_notes.append(speaker_name)
                    else:
                        speaker_notes.append(speaker_name)
                speaker_guidance = f"\n\nKey speakers: {', '.join(speaker_notes)}"
            else:
                speaker_guidance = f"\n\nKey speakers: {', '.join(speaker_list)}"

    narr_prompt = f"""Here's a {target_duration}-second recap assembled from these clips:

{clip_summary}

The original transcript:
{transcript_json}{emotion_guidance}

Tell this story like you're excitedly sharing it with a friend. Hit the highlights, use character names if you can spot them, and make it flow naturally.

RULES:
1. About {narration_word_target} spoken words (stay within {narration_word_min}-{narration_word_max} words).
2. Write ENTIRELY in {lang_label}. Do not mix languages.
3. Tell it as one continuous, flowing story — not clip-by-clip descriptions.
4. Use character or speaker names from the transcript whenever possible.
5. Skip boring parts — focus on what makes this interesting, surprising, or funny.
6. Sound natural and conversational — like spoken words, not written prose.
7. No filler, no padding instructions, no meta-commentary about the video itself.

Return JSON only:
{{
  "recap_text": "<your narration in {lang_label}>"
}}"""

    print("[Call 2] Writing narration...")
    narr_response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": narr_system},
            {"role": "user", "content": narr_prompt},
        ],
        max_tokens=1500,
    )
    narr_data = _parse_llm_json(narr_response.choices[0].message.content or "{}")
    recap_text = narr_data.get("recap_text", "")

    # ------------------------------------------------------------------
    # Assemble and save
    # ------------------------------------------------------------------
    recap_data = {
        "recap_text": recap_text,
        "clip_timings": clip_timings,
        "total_duration": round(sum(c["end"] - c["start"] for c in clip_timings), 1),
    }

    # Include emotion metadata if available
    if emotions_file:
        recap_data["emotions_used"] = True
        # Add emotion summary for the selected clips
        clip_emotions = []
        for clip in clip_timings:
            for segment in segments:
                seg_start = segment.get("start", 0)
                seg_end = segment.get("end", 0)
                if seg_start >= clip["start"] and seg_end <= clip["end"]:
                    if "dominant_emotion" in segment:
                        clip_emotions.append({
                            "start": clip["start"],
                            "end": clip["end"],
                            "dominant_emotion": segment["dominant_emotion"],
                            "intensity": segment.get("intensity", 0.5)
                        })
                        break  # One emotion summary per clip
        if clip_emotions:
            recap_data["clip_emotions"] = clip_emotions

    output_path = get_output_path(output_dir)
    os.makedirs(output_path, exist_ok=True)

    recap_data_file = os.path.join(output_path, "recap_data.json")
    with open(recap_data_file, "w") as f:
        json.dump(recap_data, f, indent=2)

    recap_text_file = os.path.join(output_path, "recap_text.txt")
    with open(recap_text_file, "w") as f:
        f.write(recap_text)

    clip_count = len(clip_timings)
    total_dur = recap_data["total_duration"]

    print(f"✅ Recap suggestions generated!")
    print(f"   Total clips: {clip_count}")
    print(f"   Total duration: {total_dur}s (target: {target_duration}s)")
    print(f"   Narration words: {len(recap_text.split())}")
    print(f"   Data: {recap_data_file}")
    print(f"   Text: {recap_text_file}")

    return recap_data_file


def extract_and_merge_clips(video_path, recap_data_file, target_duration=30, output_dir="output/videos"):
    """
    Step 4: Extract video clips and merge them
    
    Args:
        video_path: Path to original video
        recap_data_file: Path to recap_data.json
        target_duration: Target duration in seconds (should include overshoot buffer)
        output_dir: Directory to save output video
    
    Returns:
        Path to merged video
    """
    print(f"\n{'='*70}")
    print(f"STEP 4: EXTRACTING AND MERGING VIDEO CLIPS")
    print(f"{'='*70}")
    print(f"Video: {video_path}")
    print(f"Recap data: {recap_data_file}")
    
    # Read recap data
    with open(recap_data_file, "r") as f:
        recap_data = json.load(f)
    
    clip_timings = recap_data.get("clip_timings", [])

    if not clip_timings:
        raise ValueError("No clip timings found in recap_data.json")

    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")

    # Load original video
    print("Loading video...")
    video = VideoFileClip(video_path)

    # Validate and sanitize clip timings against actual video length
    clip_timings = validate_clip_timings(clip_timings, video_duration=video.duration)
    print(f"Validated {len(clip_timings)} clip(s) against video duration {video.duration:.2f}s")

    # Extract clips
    clips = []
    total_clips_duration = 0

    for i, timing in enumerate(clip_timings, 1):
        start = timing["start"]
        end = timing["end"]
        reason = timing.get("reason", "clip")

        print(f"Extracting clip {i}/{len(clip_timings)}: {start}s-{end}s ({reason})")

        try:
            clip = video.subclip(start, end)
            clips.append(clip)
            total_clips_duration += (end - start)
        except Exception as e:
            print(f"Failed to extract clip {i}: {e}")
    
    # Concatenate clips
    print("Combining clips...")
    final_clip = concatenate_videoclips(clips, method="compose")
    
    # Trim video to target duration. The caller requests clips with an
    # overshoot buffer (+5s) so the video should always be longer than the
    # audio narration — just trim the excess.
    current_duration = final_clip.duration
    print(f"Current duration: {current_duration:.2f}s")
    print(f"Target duration: {target_duration}s")
    
    if current_duration > target_duration + 0.1:
        print(f"Trimming video from {current_duration:.2f}s to {target_duration:.1f}s...")
        final_clip = final_clip.subclip(0, target_duration)
        print(f"✅ Trimmed to {final_clip.duration:.2f}s")
    elif current_duration < target_duration - 0.1:
        print(f"⚠️  Video ({current_duration:.2f}s) is shorter than target ({target_duration}s) — proceeding as-is")
    else:
        print(f"✅ Duration matches target: {current_duration:.2f}s")
    
    print(f"\n✅ Final video duration: {final_clip.duration:.2f}s")
    
    # Save video
    output_path = get_output_path(output_dir)
    os.makedirs(output_path, exist_ok=True)
    
    output_file = os.path.join(output_path, "recap_video.mp4")
    print(f"Writing video to {output_file}...")
    
    # Create temp directory for MoviePy temporary files
    temp_dir = get_output_path("output/temp")
    os.makedirs(temp_dir, exist_ok=True)
    temp_audio_file = os.path.join(temp_dir, "temp-audio.m4a")
    
    final_clip.write_videofile(
        output_file,
        codec="libx264",
        audio_codec="aac",
        temp_audiofile=temp_audio_file,
        remove_temp=False  # Keep temp file for debugging
    )
    
    print(f"   Temp audio preserved: {temp_audio_file}")
    
    # Clean up
    video.close()
    final_clip.close()
    for clip in clips:
        clip.close()
    
    print(f"✅ Video clips merged!")
    print(f"   Output: {output_file}")
    print(f"   Duration: {target_duration}s")
    
    return output_file


def remove_audio_from_video(input_video, output_video=None):
    """
    Step 5: Remove audio from video
    
    Args:
        input_video: Path to input video
        output_video: Path for output video (optional)
    
    Returns:
        Path to video without audio
    """
    print(f"\n{'='*70}")
    print(f"STEP 5: REMOVING AUDIO FROM VIDEO")
    print(f"{'='*70}")
    print(f"Input: {input_video}")
    
    if not os.path.exists(input_video):
        raise FileNotFoundError(f"Video file not found: {input_video}")
    
    # Generate output path if not provided
    if output_video is None:
        base_name = os.path.splitext(input_video)[0]
        output_video = f"{base_name}_no_audio.mp4"
    
    print("Loading video...")
    video = VideoFileClip(input_video)
    
    print("Removing audio...")
    video_no_audio = video.without_audio()
    
    print(f"Writing output to {output_video}...")
    video_no_audio.write_videofile(
        output_video,
        codec="libx264",
        audio=False,
        logger=None
    )
    
    # Clean up
    video.close()
    video_no_audio.close()
    
    input_size = os.path.getsize(input_video) / (1024 * 1024)
    output_size = os.path.getsize(output_video) / (1024 * 1024)
    
    print(f"✅ Audio removed!")
    print(f"   Output: {output_video}")
    print(f"   Size: {input_size:.2f}MB → {output_size:.2f}MB")
    
    return output_video


__all__ = [
    'generate_recap_suggestions',
    'extract_and_merge_clips',
    'remove_audio_from_video',
    'validate_clip_timings',
    'get_output_path',
    '_merge_emotions_with_segments',
]

