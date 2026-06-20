# VideoRecap Transcript-to-Narration Workflow

## High-Level Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        VIDEO RECAP GENERATION PIPELINE                      │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────┐
│   VIDEO    │
│   INPUT    │
└──────┬──────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 1: TRANSCRIPTION & DIARIZATION                                         │
│ Function: transcribe_video_with_emotions()                                  │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Audio Extraction ──► Speech Recognition (Whisper) ──► JSON Transcript     │
│                                                          ├─ start (float)   │
│  Optional:           Speaker Diarization (AssemblyAI)   ├─ end (float)     │
│  ├─ Speaker names    ├─ Speaker 1, Speaker 2, etc.     ├─ text (str)      │
│  ├─ Speaker IDs      ├─ Label correction via frequency ├─ speaker_name    │
│  └─ Corrections      └─ Self-correction mechanism      └─ corrected_from  │
│                                                                              │
│  Output: transcription.json (array of segments)                            │
│          emotions.json (optional, with emotion analysis)                   │
│                                                                              │
└──────────────────┬───────────────────────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 2: EMOTION ANALYSIS (Optional)                                         │
│ Function: analyze_emotions()                                                │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  For each transcript segment:                                               │
│  ├─ Extract audio clip (start → end)                                       │
│  ├─ Analyze with emotion model (e.g., Wav2Vec + classifier)               │
│  └─ Output:                                                                │
│     ├─ dominant_emotion (joy, anger, sadness, fear, neutral, etc.)       │
│     ├─ intensity (0.0 - 1.0 scale)                                        │
│     ├─ confidence scores for each emotion                                 │
│     └─ timestamps within the segment                                       │
│                                                                              │
│  Output: emotions.json (merged with transcript segments)                   │
│                                                                              │
└──────────────────┬───────────────────────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 3A: CLIP SELECTION (LLM Call 1)                                        │
│ Function: generate_recap_suggestions() - Part 1                             │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  INPUT:  transcript.json + emotions.json (optional)                        │
│          target_duration (e.g., 30 seconds)                                │
│                                                                              │
│  SYSTEM PROMPT:                                                             │
│  "You are a professional video editor. Select the most important           │
│   clip windows from a timestamped transcript to build a recap of a         │
│   specific target duration. Think about coverage, pacing, emotional        │
│   impact, and avoiding redundancy."                                        │
│                                                                              │
│  USER PROMPT:                                                               │
│  "Below is a transcript as a JSON array. Each element has start, end,      │
│   text, and optional emotion data. Select clips for a 30-second video      │
│   recap."                                                                   │
│                                                                              │
│  LLM MODEL: GPT-4o (or configurable)                                       │
│  MAX TOKENS: 1500                                                           │
│                                                                              │
│  OUTPUT SCHEMA (JSON):                                                      │
│  {                                                                          │
│    "clips": [                                                              │
│      {"start": 5.2, "end": 12.8, "reason": "high emotional intensity"},  │
│      {"start": 25.1, "end": 34.5, "reason": "key plot point"},           │
│      ...                                                                    │
│    ]                                                                        │
│  }                                                                          │
│                                                                              │
│  SELECTION LOGIC:                                                           │
│  ├─ Aim for ~target_duration seconds total                                │
│  ├─ If emotions available: prioritize high-intensity segments             │
│  ├─ Consider diversity: avoid consecutive similar topics                  │
│  ├─ Include key moments: pivots, reveals, emotional arcs                 │
│  └─ Respect natural breaks: segment boundaries, speaker changes           │
│                                                                              │
│  Output: clip_timings (list of {start, end, reason})                     │
│                                                                              │
└──────────────────┬───────────────────────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 3B: NARRATION GENERATION (LLM Call 2)                                  │
│ Function: generate_recap_suggestions() - Part 2                             │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  INPUT:  Selected clip_timings (from Step 3A)                             │
│          Full transcript.json                                               │
│          Optional: emotions.json                                           │
│          narration_language (e.g., "Tamil", defaults to transcript lang)  │
│                                                                              │
│  SYSTEM PROMPT: (from app/prompts/narration_prompts.py)                   │
│  ┌────────────────────────────────────────────────────────────────┐       │
│  │ ACTIVE: v4 (Factual Accuracy Enhanced)                         │       │
│  │                                                                 │       │
│  │ "You are a friend casually telling someone about a video      │       │
│  │  you just watched. You speak naturally and conversationally.  │       │
│  │  Tell the story, not the transcript."                          │       │
│  │                                                                 │       │
│  │ INCLUDES:                                                       │       │
│  │ ✓ FACTUAL ACCURACY RULES - Never invent details               │       │
│  │ ✓ CHARACTER REFERENCE POLICY - Natural identifiers             │       │
│  │ ✓ STORYTELLING INTELLIGENCE - 10 analytical dimensions        │       │
│  │ ✓ NARRATIVE FLOW - Goal → Obstacle → Action → Consequence    │       │
│  │ ✓ EMOTIONAL DELIVERY - Match emotional arc                    │       │
│  │                                                                 │       │
│  │ [Full prompt: 3196 characters, loaded from narration_prompts] │       │
│  └────────────────────────────────────────────────────────────────┘       │
│                                                                              │
│  USER PROMPT:                                                               │
│  "Here's a 30-second recap assembled from these clips:                     │
│   [clip_summary with timings]                                              │
│                                                                              │
│   The original transcript:                                                 │
│   [full transcript_json]                                                   │
│                                                                              │
│   [emotion_guidance if available]                                          │
│                                                                              │
│   Tell this story like you're excitedly sharing it with a friend.         │
│   Hit the highlights, use character names if available..."                 │
│                                                                              │
│  RULES ENFORCED:                                                            │
│  1. About ~220 spoken words (for 30-second clip)                          │
│  2. Write ENTIRELY in [language]                                           │
│  3. Tell as one continuous, flowing story                                 │
│  4. Use character/speaker names from transcript                           │
│  5. Skip boring parts — focus on interesting/surprising/funny             │
│  6. Sound natural and conversational                                       │
│  7. No meta-commentary ("the video shows", "in this clip")                │
│                                                                              │
│  LLM MODEL: GPT-4o                                                         │
│  MAX TOKENS: 1500                                                           │
│                                                                              │
│  OUTPUT SCHEMA (JSON):                                                      │
│  {                                                                          │
│    "recap_text": "Sarah walks into the coffee shop, surprised to see..."  │
│  }                                                                          │
│                                                                              │
│  Output: recap_text (narration script)                                    │
│                                                                              │
└──────────────────┬───────────────────────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 4: RECAP DATA ASSEMBLY                                                 │
│ Function: generate_recap_suggestions() - Assembly                           │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Combine all outputs into single JSON:                                     │
│                                                                              │
│  recap_data.json:                                                          │
│  {                                                                          │
│    "recap_text": "Narration script from Step 3B",                         │
│    "clip_timings": [                                                       │
│      {"start": 5.2, "end": 12.8},                                        │
│      {"start": 25.1, "end": 34.5}                                        │
│    ],                                                                       │
│    "total_duration": 25.9,                                                │
│    "emotions_used": true,                                                │
│    "clip_emotions": [                                                      │
│      {                                                                     │
│        "start": 5.2, "end": 12.8,                                        │
│        "dominant_emotion": "joy",                                         │
│        "intensity": 0.85                                                  │
│      },                                                                    │
│      ...                                                                  │
│    ]                                                                       │
│  }                                                                          │
│                                                                              │
│  Output: recap_data.json                                                   │
│                                                                              │
└──────────────────┬───────────────────────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 5: VIDEO CLIP EXTRACTION & ASSEMBLY                                    │
│ Function: extract_and_merge_clips()                                         │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  INPUT: original_video.mp4 + recap_data.json (clip_timings)               │
│                                                                              │
│  FOR EACH clip in clip_timings:                                           │
│  ├─ Extract segment: video[start:end]                                     │
│  └─ Store as intermediate file                                            │
│                                                                              │
│  MERGE all clips:                                                           │
│  ├─ Concatenate in order (using moviepy)                                  │
│  ├─ Preserve original audio                                               │
│  └─ Smooth transitions                                                     │
│                                                                              │
│  OUTPUT: recap_video.mp4 (video without narration audio)                  │
│                                                                              │
│  Output: recap_video.mp4                                                   │
│                                                                              │
└──────────────────┬───────────────────────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 6: TEXT-TO-SPEECH NARRATION GENERATION                                 │
│ Function: generate_voiceover() [from audio_processing.py]                   │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  INPUT: recap_text (from Step 3B) + narration_language                    │
│                                                                              │
│  TTS SERVICE: (Configurable)                                               │
│  ├─ OpenAI TTS (default, multiple voices)                                 │
│  ├─ ElevenLabs (high-quality, natural)                                   │
│  ├─ Google Cloud TTS                                                      │
│  └─ Or local TTS engine                                                   │
│                                                                              │
│  VOICE SELECTION:                                                           │
│  ├─ Language: Use narration_language                                       │
│  ├─ Speaker: Configurable (e.g., "alloy", "nova", "shimmer")            │
│  ├─ Speed: Adjustable (default 1.0)                                       │
│  └─ Pitch: Adjustable (optional)                                          │
│                                                                              │
│  INPUT: "Sarah walks into the coffee shop, surprised to see..."           │
│  OUTPUT: narration.mp3 (audio file)                                        │
│                                                                              │
│  Output: narration.mp3                                                     │
│                                                                              │
└──────────────────┬───────────────────────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ STEP 7: AUDIO MERGING & FINAL VIDEO ASSEMBLY                                │
│ Function: merge_audio_with_video()                                          │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  INPUT: recap_video.mp4 (video without narration)                         │
│         narration.mp3 (voiceover)                                          │
│         Optional: Keep original audio (background music/ambient sound)    │
│                                                                              │
│  AUDIO MIXING:                                                              │
│  ├─ Narration volume: 100%                                                │
│  ├─ Original audio volume: 20-30% (ducked/reduced)                       │
│  └─ Or: Completely replace original audio with narration                 │
│                                                                              │
│  OUTPUT: final_recap_video.mp4                                            │
│          (video with narration + optional background audio)               │
│                                                                              │
│  Output: final_recap_video.mp4                                             │
│                                                                              │
└──────────────────┬───────────────────────────────────────────────────────────┘
                   │
                   ▼
            ┌──────────────┐
            │  FINAL VIDEO │
            │   OUTPUT     │
            └──────────────┘
```

---

## Key Data Transformations

### Transcript Segment Structure
```json
{
  "start": 5.2,
  "end": 12.8,
  "text": "Sarah walks into the coffee shop",
  "speaker_name": "Narrator",
  "corrected_from": ["Speaker 1", "Unknown Speaker"]
}
```

### With Emotion Analysis
```json
{
  "start": 5.2,
  "end": 12.8,
  "text": "Sarah walks into the coffee shop",
  "speaker_name": "Narrator",
  "dominant_emotion": "joy",
  "intensity": 0.85,
  "emotions": {
    "joy": 0.85,
    "surprise": 0.15,
    "neutral": 0.0
  }
}
```

### Clip Selection Output
```json
{
  "clips": [
    {"start": 5.2, "end": 12.8, "reason": "High emotional intensity, establishes setup"},
    {"start": 25.1, "end": 34.5, "reason": "Key revelation, drives narrative forward"}
  ]
}
```

### Final Recap Data
```json
{
  "recap_text": "Sarah walks into the coffee shop, surprised to see her old friend waiting...",
  "clip_timings": [
    {"start": 5.2, "end": 12.8},
    {"start": 25.1, "end": 34.5}
  ],
  "total_duration": 25.9,
  "emotions_used": true,
  "clip_emotions": [
    {"start": 5.2, "end": 12.8, "dominant_emotion": "joy", "intensity": 0.85}
  ]
}
```

---

## Critical Decision Points

### 1. Emotion Analysis (Optional Path)
```
┌─ YES: Include emotions.json
│       └─ Clip selection weighs emotional intensity
│       └─ Narration receives emotion_guidance
│       └─ Final output includes clip_emotions metadata
│
└─ NO: Skip emotion analysis
        └─ Clip selection uses only content importance
        └─ Narration doesn't get emotion context
        └─ Faster processing
```

### 2. Narration Language
```
If narration_language specified:
├─ Translate concept to target language
├─ Must maintain factual accuracy
├─ Use language-appropriate idioms/phrases
└─ TTS uses target language voice

Else:
└─ Use same language as transcript
```

### 3. Original Audio Handling
```
┌─ Option A: Keep original audio (ducked)
│           └─ Narration 100%, original 20-30%
│           └─ Maintains ambient sound/music
│
└─ Option B: Replace with narration only
            └─ Cleaner, narration stands out
            └─ No competing audio
```

---

## LLM Prompt Versions

The narration generation uses versioned system prompts (from `app/prompts/narration_prompts.py`):

| Version | Features | Status |
|---------|----------|--------|
| **v4** | Factual Accuracy Rules, Character Reference Policy, Storytelling Intelligence, Narrative Flow, Emotional Delivery | ✅ Active |
| v3 | CHARACTER REFERENCE POLICY + NARRATIVE FLOW | Archived |
| v2 | Enhanced storytelling with 10 dimensions | Archived |
| v1 | Original with basic guidance | Archived |

**Version control**: All prompts stored in single Python constants file. Switch versions:
```python
from app.prompts.narration_prompts import set_active_prompt_version
set_active_prompt_version('v3')  # Rollback if needed
```

---

## Performance Metrics

```
Typical processing time for 5-minute video:

Step 1 (Transcription):     ~2-3 minutes (5x real-time)
Step 2 (Emotion Analysis):  ~3-5 minutes (optional)
Step 3A (Clip Selection):   ~10-15 seconds (LLM)
Step 3B (Narration):        ~10-15 seconds (LLM)
Step 4 (Assembly):          < 1 second
Step 5 (Video Extraction):  ~30-45 seconds
Step 6 (TTS):               ~5-10 seconds (30-second narration)
Step 7 (Audio Merge):       ~10-20 seconds

Total: ~6-10 minutes (depending on video length)
```

---

## Error Handling

```
┌─ Transcription fails
│  └─ Return error to user, suggest re-upload

├─ No emotions data (optional)
│  └─ Continue without emotion context

├─ Clip selection returns empty
│  └─ Retry with adjusted parameters

├─ Narration generation fails
│  └─ Retry with shorter duration or different prompt version

├─ TTS generation fails
│  └─ Retry with fallback voice/language

└─ Audio merge fails
   └─ Return raw video + narration file separately
```

---

## Version Control & Rollback

All narration prompts managed in `backend/app/prompts/narration_prompts.py`:

```python
ACTIVE_PROMPT_VERSION = 'v4'  # Change this to switch

PROMPTS = {
    'v4': { 'name': '...', 'system': '...', 'emotion_addon': '...' },
    'v3': { ... },
    'v2': { ... },
    'v1': { ... }
}

def get_narration_system_prompt(version=None, with_emotion=False):
    """Get the prompt for specified version"""
    version = version or ACTIVE_PROMPT_VERSION
    return PROMPTS[version]['system'] + (
        PROMPTS[version].get('emotion_addon', '') if with_emotion else ''
    )
```

To rollback:
1. Edit `narration_prompts.py`: `ACTIVE_PROMPT_VERSION = 'v3'`
2. Run: `make restart`
3. New recaps will use v3 prompt
