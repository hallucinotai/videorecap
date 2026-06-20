# VideoRecap Workflow - Process Table

## Complete Pipeline

| Step | Process | Model/Tool | Input | Output | Duration | Optional |
|------|---------|-----------|-------|--------|----------|----------|
| 1 | Audio Extraction | FFmpeg | `video.mp4` | `audio.wav` | ~30s | No |
| 2 | Speech Recognition | Whisper (OpenAI) | `audio.wav` | `transcript.json` (segments) | ~2-3 min | No |
| 3 | Speaker Diarization | AssemblyAI | `audio.wav` | Speaker labels, names, corrections | ~1-2 min | No |
| 4 | Merge Transcript & Diarization | Code | `transcript.json` + speaker labels | Enhanced transcript with `speaker_name` | <1s | No |
| 5 | Emotion Analysis | Wav2Vec + Classifier | Audio segments | `emotions.json` (intensity, emotion type) | ~3-5 min | **YES** |
| 6 | Merge Emotions with Transcript | Code | `transcript.json` + `emotions.json` | Transcript with emotion metadata | <1s | **YES** |
| 7 | Clip Selection (LLM Call 1) | GPT-4o | Transcript + Emotions (opt) + target_duration | `clip_timings` (list of {start, end}) | ~10-15s | No |
| 8 | Narration Generation (LLM Call 2) | GPT-4o | Selected clips + Full transcript + Emotion guidance (opt) + Language | `recap_text` (narration script) | ~10-15s | No |
| 9 | Assemble Recap Data | Code | All outputs from steps 7-8 | `recap_data.json` (unified structure) | <1s | No |
| 10 | Extract Video Clips | MoviePy | `video.mp4` + `clip_timings` | Multiple video segments (one per clip) | ~30-45s | No |
| 11 | Merge Video Clips | MoviePy | Video segments (in order) | `recap_video.mp4` (no narration audio) | ~10-20s | No |
| 12 | Text-to-Speech | OpenAI TTS / ElevenLabs / Google TTS | `recap_text` + language + voice settings | `narration.mp3` (audio file) | ~5-10s | No |
| 13 | Audio Mixing | FFmpeg / MoviePy | `recap_video.mp4` + `narration.mp3` + optional original audio | `final_recap_video.mp4` (video + narration) | ~10-20s | No |

---

## Data Flow Table

| Step | Data Structure | Size (Est.) | Format | Contains |
|------|----------------|-------------|--------|----------|
| 2 | `transcript.json` | 50-500 KB | JSON Array | [{start, end, text, speaker_name}] |
| 5 | `emotions.json` | 100-800 KB | JSON Array | [{start, end, dominant_emotion, intensity, emotions{}}] |
| 7 | `clip_timings` | 1-5 KB | JSON Array | [{start, end, reason}] |
| 8 | `recap_text` | 2-5 KB | Plain Text | Full narration script |
| 9 | `recap_data.json` | 10-20 KB | JSON Object | {recap_text, clip_timings, total_duration, emotions_used, clip_emotions} |
| 12 | `narration.mp3` | 200-800 KB | MP3 Audio | Voiceover narration |
| 13 | `final_recap_video.mp4` | 10-50 MB | MP4 Video | Video + narration audio |

---

## LLM Models & Prompts

| Step | Task | Model | System Prompt Version | Input Tokens (Est.) | Output Tokens (Est.) | Cost (Est.) |
|------|------|-------|--------|---------------|---------------|------------|
| 7 | Clip Selection | GPT-4o | Video Editor Mindset | 2,000-5,000 | 200-400 | $0.01-0.05 |
| 8 | Narration | GPT-4o | v4 (Factual Accuracy Enhanced) | 3,000-8,000 | 150-300 | $0.02-0.10 |

---

## Processing Parameters

| Step | Parameter | Default | Range | Impact |
|------|-----------|---------|-------|--------|
| 7 | `target_duration` | 30s | 10-180s | Affects how many clips selected |
| 8 | `narration_language` | Same as transcript | Any language | Output language for narration |
| 8 | `narration_word_target` | ~220 (for 30s) | Calculated | Controls narration length |
| 12 | TTS Voice | "alloy" | "alloy", "echo", "fable", "onyx", "nova", "shimmer" | Voice characteristics |
| 12 | TTS Speed | 1.0 | 0.25-4.0 | Narration speed |
| 13 | Original Audio Level | 25% | 0-100% | Background sound volume |
| 13 | Narration Audio Level | 100% | 0-100% | Voiceover volume |

---

## Optional Paths

### Without Emotion Analysis
| Step | Skipped | Impact |
|------|---------|--------|
| 5 | Emotion Analysis | Clip selection uses only content importance; no emotional weighting |
| 6 | Emotion Merge | No emotion_guidance provided to narration LLM |
| - | Processing Time | Saves ~3-5 minutes |

### With Emotion Analysis
| Step | Enabled | Impact |
|------|---------|--------|
| 5 | Emotion Analysis | Adds emotion metadata to each segment |
| 6 | Emotion Merge | Enriches transcript with intensity scores |
| 7 | Clip Selection | Considers emotional intensity as selection criterion |
| 8 | Narration | Receives emotion_guidance to match emotional arc |

---

## File Outputs

| File | Format | Size | Created by Step | Used by Step |
|------|--------|------|-----------------|--------------|
| `audio.wav` | WAV | 50-500 MB | 1 | 2, 3 |
| `transcript.json` | JSON | 50-500 KB | 2 | 4, 7, 8 |
| `emotions.json` | JSON | 100-800 KB | 5 | 6 |
| `clip_timings` | JSON | 1-5 KB | 7 | 10 |
| `recap_text` | TXT | 2-5 KB | 8 | 12 |
| `recap_data.json` | JSON | 10-20 KB | 9 | Storage/Database |
| `narration.mp3` | MP3 | 200-800 KB | 12 | 13 |
| `recap_video.mp4` | MP4 | 10-50 MB | 11 | 13 |
| `final_recap_video.mp4` | MP4 | 10-50 MB | 13 | Final Output |

---

## Configuration & Version Control

| Component | Location | Type | Versions | Active |
|-----------|----------|------|----------|--------|
| Narration Prompt | `backend/app/prompts/narration_prompts.py` | Python Constants | v1, v2, v3, v4 | v4 |
| Whisper Model | Environment variable | String | base, small, medium, large | medium |
| GPT Model | Environment variable | String | gpt-4o, gpt-4-turbo | gpt-4o |
| TTS Service | Code config | String | openai, elevenlabs, google | openai |
| Emotion Model | Code config | String | wav2vec-based | wav2vec |

---

## Performance Summary

| Metric | Value | Notes |
|--------|-------|-------|
| Total Processing Time | 6-10 min | For 5-minute video |
| Bottleneck | Transcription | Takes 2-3x real-time |
| Fastest Step | Assembly/Merging | <1 second |
| Most Variable | Emotion Analysis | 3-5 min (optional) |
| LLM Latency | 20-30s | Both LLM calls combined |
| TTS Latency | 5-10s | 30-second narration |
| Video Processing | 40-65s | Extraction + merging |
| Total API Cost | $0.03-0.15 | Two GPT-4o calls |

---

## Quality Checkpoints

| Step | Checkpoint | Pass Criteria | Fail Action |
|------|-----------|--------------|------------|
| 2 | Transcription Quality | >95% word accuracy | Retry with different model |
| 4 | Speaker Names | Correctly identified | Manual correction |
| 7 | Clip Coverage | Clips cover key moments | Adjust selection criteria |
| 8 | Narration | Factual, natural, ~word target | Regenerate with prompt v3 or v2 |
| 12 | TTS Quality | Clear, appropriate pacing | Switch TTS provider |
| 13 | Final Video | Audio synced, balanced levels | Re-mix audio levels |

---

## Rollback Procedure

| Component | Rollback Method | Time to Apply |
|-----------|-----------------|---|
| Narration Prompt | Change `ACTIVE_PROMPT_VERSION` in `narration_prompts.py` | <30 seconds |
| Whisper Model | Update environment variable `WHISPER_MODEL` | <30 seconds |
| GPT Model | Update environment variable `OPENAI_MODEL` | <30 seconds |
| TTS Service | Update code config, rebuild | ~2 minutes |
| Emotion Model | Update code config, rebuild | ~2 minutes |

---

## Current Narration Prompt Versions

| Version | Name | Added | Key Features | Status |
|---------|------|-------|--------------|--------|
| v4 | Factual Accuracy Enhanced | 2026-06-02 | ✓ FACTUAL ACCURACY RULES<br>✓ CHARACTER REFERENCE POLICY<br>✓ 10 STORYTELLING DIMENSIONS<br>✓ NARRATIVE FLOW<br>✓ EMOTIONAL DELIVERY | **ACTIVE** |
| v3 | Enhanced Storytelling | 2026-06-02 | ✓ CHARACTER REFERENCE POLICY<br>✓ NARRATIVE FLOW<br>✓ 10 STORYTELLING DIMENSIONS | Archived |
| v2 | Initial Enhanced | 2026-06-02 | ✓ 10 STORYTELLING REQUIREMENTS<br>✓ Cause-and-effect focus<br>✓ Examples | Archived |
| v1 | Original | 2026-06-02 | Basic storytelling guidance<br>10 dimensions (unstructured) | Archived |
