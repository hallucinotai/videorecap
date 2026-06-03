# Video Recap Generation Core Process - Input to Output

## Overview

This document explains the complete 7-step process from user uploading a video to downloading the final recap video.

**Trigger:** User uploads video and creates a job  
**Output:** Recap video with AI-generated narration  
**Time:** 2-10 minutes (depends on video length and model size)

---

## Complete Process Flow with Models & AI

### Step 0: Upload & Job Creation
**User Action:** Upload video to frontend  
**Backend:** Create job record

| Input | Value |
|-------|-------|
| **Type** | Video file (MP4, WebM, etc.) |
| **Example** | `tutorial_30min.mp4` (file size: 500MB) |
| **Metadata** | filename, file size |

| Output | Value |
|--------|-------|
| **Job ID** | Auto-generated UUID (e.g., `job-abc123xyz`) |
| **Status** | `pending` |
| **Location** | S3 bucket → `uploads/{job_id}/tutorial_30min.mp4` |
| **Database** | New `RecapJob` record created |

| Configuration Set | Default | User Can Change |
|---|---|---|
| `target_duration` | 30 seconds | ✅ Yes |
| `whisper_model` | `small` | ✅ Yes (tiny/base/small/medium/large) |
| `language` | Auto-detect | ✅ Yes |
| `translate_to` | None (optional) | ✅ Yes |
| `tts_model` | `tts-1` | ✅ Yes |
| `tts_voice` | `nova` | ✅ Yes |

**AI/Models Used:** None yet (just setup)

---

### Step 1: Transcribe Video
**Purpose:** Convert video audio to text with timestamps  
**AI Model:** OpenAI Whisper  
**Duration:** 2-5 minutes (depends on video length)

| Input | Value |
|-------|-------|
| **File** | `tutorial_30min.mp4` (from S3) |
| **Model** | Whisper `small` (or user-selected size) |
| **Language** | Auto-detect or user-specified |
| **Whisper Sizes** | `tiny` (39M) → `base` (140M) → `small` (466M) → `medium` (1.5GB) → `large` (2.9GB) |

**Processing:**
```
1. Extract audio from video
2. Load Whisper model to GPU/CPU
3. Run inference on audio
4. Output: JSON with segments
```

| Output | Example |
|--------|---------|
| **File** | `transcription.json` |
| **Format** | Array of segments |
| **Structure** | `[{"start": 0.5, "end": 5.2, "text": "Hello everyone..."}]` |
| **Storage** | S3 → `jobs/{job_id}/transcription/transcription.json` |
| **Segments** | ~100-200 for 30-min video |

| AI Model Used | Type | Provider | Cost |
|---|---|---|---|
| **Whisper** | Speech-to-Text | OpenAI | FREE (local inference) |
| **Same AI?** | Yes | - | All transcription uses same Whisper model |

**Status Update:** `current_step=1`, `progress_pct=15%`

---

### Step 2: Translate (Optional)
**Purpose:** Translate transcript to different language  
**AI Model:** OpenAI GPT API  
**Duration:** 30 seconds - 2 minutes

| Input | Condition |
|-------|-----------|
| **Triggered?** | Only if user set `translate_to` |
| **Transcription** | From Step 1 |
| **Languages** | English → Tamil, Spanish, French, etc. |

| If User Skips | Output |
|---|---|
| `translate_to = None` | Step 2 skipped (no translation) |
| `translate_to = "Tamil"` | Continue with translation |

**Processing (if translation enabled):**
```
1. Load transcription JSON
2. Call OpenAI GPT API
3. Translate each segment
4. Preserve timestamps
5. Output: translated_transcription.json
```

| Output | Format |
|--------|--------|
| **File** | `translated.json` |
| **Structure** | Same as transcription but translated text |
| **Example** | `[{"start": 0.5, "end": 5.2, "text": "வணக்கம் எல்லாருக்கும்..."}]` |
| **Active Transcription** | Now uses translated version for next steps |

| AI Model Used | Type | Provider | Cost |
|---|---|---|---|
| **GPT-4o or GPT-3.5** | LLM Translation | OpenAI API | ~$0.02-0.05 per video |
| **Same AI as Step 1?** | **DIFFERENT** | Different provider/model | - |

**Status Update:** `current_step=2`, `progress_pct=25%`

---

### Step 3: Generate AI Recap Suggestions
**Purpose:** Identify important clips and write narration  
**AI Model:** OpenAI GPT-4o (or gpt-4-turbo)  
**Duration:** 2-5 minutes  
**Approach:** TWO focused LLM calls (one for clips, one for narration)

| Input | Value |
|-------|-------|
| **Active Transcription** | From Step 1 or 2 (JSON with segments) |
| **Target Duration** | 30 seconds (user-set) |
| **AI Model** | GPT-4o (from env: `OPENAI_MODEL`) |

**Processing - Call 1: Clip Selection**

```
System Prompt: "You are a professional video editor..."
User Prompt: 
  - Full transcript as JSON
  - Target duration (30s)
  - Rules for clip selection

LLM Response: JSON with clip_timings
```

| Prompt | Content |
|--------|---------|
| **System** | "Think about coverage, pacing, avoiding redundancy" |
| **User** | Transcript JSON + target duration + rules |
| **Output** | `[{"start": 10.5, "end": 15.2, "reason": "explains key concept"}, ...]` |

**Processing - Call 2: Narration Script**

```
System Prompt: "You are a professional scriptwriter..."
User Prompt:
  - Clip timings from Call 1
  - Original transcript
  - Word count target (~60 words for 30s)
  - Narration language (if translated)

LLM Response: Plain text narration script
```

| Output | Format |
|--------|--------|
| **Clip Timings** | `[{"start": 10.5, "end": 15.2, ...}, ...]` |
| **Narration Text** | Plain text (~60-220 words) |
| **File** | `recap_data.json` + `recap_text.txt` |
| **Storage** | S3 intermediate storage |

| AI Model Used | Type | Provider | Cost | Same? |
|---|---|---|---|---|
| **GPT-4o** | LLM (reasoning + text gen) | OpenAI API | ~$0.10-0.30 per video | **DIFFERENT** from Steps 1-2 |

**Important:**
- Uses same AI model twice (GPT-4o) but different prompts
- Call 1: Video-editor mindset (clip selection)
- Call 2: Scriptwriter mindset (narration)

**Status Update:** `current_step=3`, `progress_pct=45%`

---

### Step 4: Generate Text-to-Speech (TTS)
**Purpose:** Create narration audio from recap text  
**AI Model:** OpenAI TTS-1 or TTS-1-HD  
**Duration:** 10-30 seconds

| Input | Value |
|-------|-------|
| **Text** | `recap_text.txt` from Step 3 (~60-220 words) |
| **TTS Model** | `tts-1` (standard) or `tts-1-hd` (high quality) |
| **Voice** | `nova` (female) or user choice: alloy/echo/fable/onyx/shimmer |
| **Example Text** | "Today we covered the fundamentals of machine learning..." |

| Processing | Value |
|---|---|
| **Speed** | Near-realtime |
| **Quality** | `tts-1`: natural and fast; `tts-1-hd`: higher quality |
| **Output Format** | MP3 audio file |

| Output | Value |
|--------|-------|
| **File** | `recap_narration.mp3` |
| **Duration** | ~20-35 seconds (actual from TTS output) |
| **Audio Quality** | 24 kHz, mono/stereo |
| **Storage** | S3 → `jobs/{job_id}/audio/recap_narration.mp3` |

| AI Model Used | Type | Provider | Cost | Same? |
|---|---|---|---|---|
| **TTS-1** | Text-to-Speech | OpenAI API | ~$0.015 per 1000 chars | **DIFFERENT** from all previous |

**Key Logic:**
```python
# Timing calculations
target_duration = 30s
actual_audio_duration = measure(recap_narration.mp3)

# If audio is too short, pad with silence
# If audio is too long, trim video to fit
overshoot_cap = target_duration + 5  # allow 5s buffer
clip_trim_target = max(target_duration, min(overshoot_cap, actual_audio_duration + 1))
```

**Status Update:** `current_step=4`, `progress_pct=60%`

---

### Step 5: Extract Video Clips
**Purpose:** Cut out important segments from original video and merge them  
**Method:** FFmpeg (not AI)  
**Duration:** 1-3 minutes

| Input | Value |
|-------|-------|
| **Original Video** | `tutorial_30min.mp4` |
| **Clip Timings** | From Step 3 (e.g., `[{start: 10.5, end: 15.2}, ...]`) |
| **Target Duration** | `clip_trim_target` calculated from Step 4 |

**Processing:**
```
1. Load original video
2. For each clip timing:
   - Extract segment [start, end]
   - Store temporarily
3. Concatenate all clips
4. Trim final result to clip_trim_target
5. Output: merged video file
```

| Output | Value |
|--------|-------|
| **File** | `recap_video.mp4` |
| **Duration** | ~30-35 seconds (matches clip_trim_target) |
| **Format** | MP4 video |
| **Content** | Selected important moments from original |
| **Audio** | Original audio (will be removed next) |

**AI/Models Used:** None (pure video processing)

**Status Update:** `current_step=5`, `progress_pct=75%`

---

### Step 6: Remove Original Audio
**Purpose:** Strip audio from video before adding narration  
**Method:** FFmpeg (not AI)  
**Duration:** 10-30 seconds

| Input | Value |
|-------|-------|
| **Video** | `recap_video.mp4` (with original audio) |

**Processing:**
```
FFmpeg -i recap_video.mp4 -c:v copy -an recap_video_no_audio.mp4
```

| Output | Value |
|--------|-------|
| **File** | `recap_video_no_audio.mp4` |
| **Duration** | Same as input (~30-35s) |
| **Video** | Unchanged |
| **Audio** | Removed (silent) |

**AI/Models Used:** None (FFmpeg codec copy)

**Status Update:** `current_step=6`, `progress_pct=85%`

---

### Step 7: Merge Audio + Video (Final Step)
**Purpose:** Combine TTS narration with video clips  
**Method:** FFmpeg (not AI)  
**Duration:** 30-60 seconds

| Input | Value |
|-------|-------|
| **Video** | `recap_video_no_audio.mp4` (~30s, silent) |
| **Audio** | `recap_narration.mp3` (~25-35s) |
| **Max Duration** | `user_trim_cap` (target + 5s) = 35s |

**Processing:**
```
1. Load video: 30s
2. Load audio: 28s
3. Align: Audio starts at 0s, video starts at 0s
4. Pad/trim to max_duration (35s)
   - If audio > video: trim audio
   - If video > audio: extend audio with silence
5. Output: final merged video
```

**Timing Logic:**
```
Example 1: Video=30s, Audio=28s, Max=35s
→ Output: 30s (video length, audio fits within)

Example 2: Video=30s, Audio=35s, Max=35s
→ Output: 35s (trim video to match audio limit)

Example 3: Video=35s, Audio=28s, Max=35s
→ Output: 35s (pad audio with silence to 7s)
```

| Output | Value |
|--------|-------|
| **File** | `recap_video_with_narration.mp4` |
| **Duration** | ~30-35 seconds |
| **Format** | MP4 video + audio |
| **Content** | Video clips + AI narration synced |
| **Quality** | 1080p or input resolution |
| **Storage** | S3 → `results/{job_id}/recap_video_with_narration.mp4` |

**AI/Models Used:** None (FFmpeg)

**Status Update:** `current_step=7`, `progress_pct=100%`, `status=completed`

---

## AI Models Summary Table

| Step | Stage | AI Model | Provider | Type | Same as Previous? | Cost |
|------|-------|----------|----------|------|---|---|
| 1 | Transcription | Whisper (small/medium/large) | OpenAI | Speech-to-Text | — | FREE (local) |
| 2 | Translation (optional) | GPT-3.5 / GPT-4o | OpenAI API | LLM | ❌ DIFFERENT | $0.02-0.05 |
| 3 | Recap Generation | GPT-4o (2× calls) | OpenAI API | LLM (reasoning) | ❌ DIFFERENT | $0.10-0.30 |
| 4 | Text-to-Speech | TTS-1 / TTS-1-HD | OpenAI API | TTS | ❌ DIFFERENT | $0.015/1K chars |
| 5 | Clip Extraction | FFmpeg | Local | Video processing | N/A | FREE |
| 6 | Audio Removal | FFmpeg | Local | Video processing | N/A | FREE |
| 7 | Audio-Video Merge | FFmpeg | Local | Video processing | N/A | FREE |

**Key Points:**
- **Whisper** (Step 1): Always same model per job (cached, fast reuse)
- **GPT** (Steps 2-3): Can be different models, but typically GPT-4o for best results
- **TTS** (Step 4): Dedicated OpenAI TTS API
- **Steps 5-7**: No AI, just FFmpeg

---

## End-to-End Example

### Scenario: 30-minute tutorial video → 30-second recap

**Input:**
```
Video: tutorial.mp4 (1920×1080, 30fps, 500MB)
Configuration:
  - target_duration: 30 seconds
  - whisper_model: small
  - translate_to: null (no translation)
  - tts_voice: nova
```

**Execution Timeline:**

| Step | AI Used | Time | Output |
|------|---------|------|--------|
| 1 | Whisper small | 3min | 240 transcript segments |
| 2 | — | 0s | Skipped (no translation) |
| 3 | GPT-4o (2 calls) | 3min | 8 clips selected, 180-word narration |
| 4 | TTS-1 | 20s | 28.5s audio narration |
| 5 | FFmpeg | 2min | 30s video (8 clips merged) |
| 6 | FFmpeg | 30s | 30s video (audio removed) |
| 7 | FFmpeg | 45s | 30s final video (narration added) |
| **TOTAL** | **✅ COMPLETE** | **~10 min** | **recap_video_with_narration.mp4** |

**Final Output:**
```
recap_video_with_narration.mp4
├─ Duration: 30 seconds
├─ Visual: Key moments from 30-minute tutorial
├─ Audio: AI-generated narration (nova voice)
├─ Resolution: 1920×1080
└─ Ready to download!
```

---

## Resumption Logic

If a job fails or user stops it, can resume from any step with cached intermediates.

| Resume Step | What's Used | What Recomputes |
|---|---|---|
| Resume from Step 1 | None | Transcription + all downstream |
| Resume from Step 3 | Transcription (cached) | Recap + downstream |
| Resume from Step 4 | Transcription + Recap | TTS + downstream |
| Resume from Step 5 | All above | Clip extraction + downstream |

**Cache Storage:** S3 → `jobs/{job_id}/{step_name}/file.ext`

---

## Key Differences from Expected Workflow

### What's the SAME AI?
- **Within Step 1:** All transcription uses the same Whisper model (cached per worker)

### What's DIFFERENT AI?
- **Step 1 → Step 2:** Whisper (speech) → GPT (LLM) = different model types
- **Step 2 → Step 3:** GPT-3.5 (translation) → GPT-4o (reasoning) = different models
- **Step 3 → Step 4:** GPT-4o (text reasoning) → TTS-1 (voice synthesis) = different model types

### What's NO AI?
- **Steps 5-7:** Pure FFmpeg video processing

---

## Cost Breakdown (per video)

Assuming 30-minute tutorial → 30-second recap:

| Service | Cost | Usage |
|---------|------|-------|
| Whisper (small) | FREE | Local inference |
| GPT-4o (2 calls) | $0.15 | 1 transcription + 1 narration analysis |
| GPT Translation | $0.03 | 1 translation (if enabled) |
| TTS-1 | $0.02 | 180 words narration |
| **Total per video** | **~$0.20** | **If all services used** |
| **Cheapest** | **$0.15** | **Skip translation** |

