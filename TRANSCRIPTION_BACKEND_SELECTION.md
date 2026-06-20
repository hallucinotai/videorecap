# Transcription Backend Selection & Priority System

## Quick Answer: Which Backend Gets Used?

The VideoRecap system uses a **priority-based selection** that chooses between Whisper and AssemblyAI:

```
IF AssemblyAI is ENABLED and API KEY exists
    ↓
    USE: AssemblyAI with Speaker Diarization
    ✅ Identifies who is speaking
    ✅ Extracts speaker names from "I'm..." phrases
    ✅ Near real-time, cloud-based
    ❌ Costs $0.025/minute
    
ELSE IF include_emotions=true (Premium tier)
    ↓
    USE: Whisper + Google Cloud Emotion Analysis
    ✅ Transcription + emotional context
    ✅ Better clip selection based on emotions
    ✅ More engaging narration
    ❌ Requires Google Cloud API credits
    
ELSE
    ↓
    USE: Basic Whisper Transcription
    ✅ Free, local processing
    ✅ Works offline
    ✅ No API keys needed
    ❌ No speaker identification
    ❌ No emotional context
```

---

## The Relationship: Why Both?

### Whisper (Free/Local)
- **Created by:** OpenAI
- **Type:** Open-source ML model
- **Runs on:** Your hardware (GPU/CPU)
- **What it does:** Converts speech audio → text with timestamps
- **Cannot do:** Identify who is speaking, understand emotions

### AssemblyAI (Paid/Cloud)
- **Created by:** AssemblyAI (startup)
- **Type:** Cloud API service
- **Runs on:** AssemblyAI's servers
- **What it does:** Advanced speech-to-text WITH speaker diarization (who spoke when)
- **Advantage:** Knows which sentences belong to which speaker

### They Solve Different Problems

**Whisper solves:** "What words were said?"
```
[0.5s - 2.1s] "Hi, my name is John"
[2.2s - 4.8s] "Hi John, I'm Sarah"
```

**AssemblyAI solves:** "What words were said + who said them?"
```
[0.5s - 2.1s] Speaker A (John): "Hi, my name is John"
[2.2s - 4.8s] Speaker B (Sarah): "Hi John, I'm Sarah"
```

---

## Why VideoRecap Uses Both

### Tier Strategy

**BASIC Tier (Free):**
- Uses Whisper only
- Cost: $0
- Output: Simple transcript with timestamps
- Good for: General video summaries where speaker identity isn't important

**PREMIUM Tier:**
- Can use Whisper + emotions (better narration matching emotional tone)
- Cost: Google Cloud Speech API credits (~$75/month per 500 minutes)
- Output: Transcript + emotion data per segment
- Good for: Videos where emotional context matters

**ENTERPRISE Tier (Future):**
- Uses AssemblyAI for speaker identification
- Cost: AssemblyAI API credits (~$125/month per 500 minutes)
- Output: Transcript with speaker names + roles
- Good for: Podcasts, interviews, multi-speaker content

---

## Code Implementation

### Entry Point: `transcribe_with_optional_emotions()`

**Location:** `modules/transcription.py:433`

```python
def transcribe_with_optional_emotions(
    video_path,
    output_dir="output/transcriptions",
    model_size="small",
    language=None,
    include_emotions=False,
    enable_assemblyai_diarization=False,      # ← Priority #1
    assemblyai_api_key=None,
    assemblyai_language_code="en"
):
    """
    Choose transcription backend based on what's available.
    
    PRIORITY:
    1. AssemblyAI (if enabled + API key)
    2. Whisper + Emotions (if include_emotions=True)
    3. Basic Whisper (fallback)
    """
    
    # PRIORITY 1: AssemblyAI Speaker Diarization
    if enable_assemblyai_diarization and assemblyai_api_key:
        print("🎤 Using AssemblyAI with SPEAKER DIARIZATION")
        transcript_file = transcribe_video_with_assemblyai(
            video_path,
            output_dir,
            api_key=assemblyai_api_key,
            language_code=assemblyai_language_code
        )
        return transcript_file, None  # No separate emotions file
    
    # PRIORITY 2: Whisper + Emotions (Premium)
    if include_emotions:
        print("🎙️ Using PREMIUM tier (with emotion analysis)")
        return transcribe_video_with_emotions(
            video_path,
            output_dir,
            model_size,
            language,
            skip_emotions_on_error=True
        )
    
    # PRIORITY 3: Basic Whisper (Free)
    print("📝 Using BASIC tier (transcription only)")
    transcript_file = transcribe_video(video_path, output_dir, model_size, language)
    return transcript_file, None
```

### How Pipeline Uses It

**Location:** `backend/app/workers/pipeline.py:163`

```python
# Step 1: Transcribe (automatically selects backend)
result = transcribe_video_service(
    local_video_path,
    working_dir,
    model_size=model_size,
    language=language,
    include_emotions=include_emotions,           # From job tier
    progress_callback=self._progress_callback,
)

transcription_file = result["transcription_file"]
emotions_file = result.get("emotions_file")     # None if AssemblyAI

# Step 3: Recap generation uses the transcript (any format)
result = generate_recap_service(
    active_transcription,                       # Works with any format
    working_dir,
    target_duration=target_duration,
    narration_language=narration_lang,
    emotions_file=emotions_file,                # Optional
    progress_callback=self._progress_callback,
)
```

---

## What Gets Stored

### AssemblyAI Output Example
```json
{
  "metadata": {
    "provider": "assemblyai",
    "speaker_diarization_enabled": true,
    "language_code": "en"
  },
  "speakers": {
    "A": {
      "speaker_id": "A",
      "name": "John",
      "total_duration_seconds": 125.3,
      "avg_confidence": 0.94
    },
    "B": {
      "speaker_id": "B", 
      "name": "Sarah",
      "total_duration_seconds": 98.5,
      "avg_confidence": 0.92
    }
  },
  "segments": {
    "0": {
      "text": "Hi, I'm John.",
      "start": 0.5,
      "end": 2.1,
      "speaker": "A",
      "speaker_name": "John"
    },
    "1": {
      "text": "Hi John, I'm Sarah.",
      "start": 2.2,
      "end": 4.8,
      "speaker": "B",
      "speaker_name": "Sarah"
    }
  }
}
```

### Whisper + Emotions Output Example
```json
{
  "transcript": [
    {
      "start": 0.5,
      "end": 2.1,
      "text": "Hi, my name is John",
      "confidence": 0.98
    },
    {
      "start": 2.2,
      "end": 4.8,
      "text": "Hi John, I'm Sarah",
      "confidence": 0.95
    }
  ],
  "emotions": [
    {
      "start": 0.5,
      "end": 2.1,
      "dominant_emotion": "joy",
      "intensity": 0.82,
      "emotions": {"joy": 0.82, "neutral": 0.15, "sadness": 0.03}
    },
    {
      "start": 2.2,
      "end": 4.8,
      "dominant_emotion": "joy",
      "intensity": 0.78,
      "emotions": {"joy": 0.78, "neutral": 0.20, "sadness": 0.02}
    }
  ]
}
```

### Basic Whisper Output Example
```json
[
  {
    "start": 0.5,
    "end": 2.1,
    "text": "Hi, my name is John"
  },
  {
    "start": 2.2,
    "end": 4.8,
    "text": "Hi John, I'm Sarah"
  }
]
```

---

## Decision Matrix: Which Backend to Use

| Scenario | Use | Why | Cost |
|----------|-----|-----|------|
| Podcast with 2 hosts | AssemblyAI | Need to know who said what | $125/mo |
| Interview Q&A | AssemblyAI | Distinguish interviewer from guest | $125/mo |
| Movie/film clip | Whisper+Emotions | Need emotional context, speakers less important | $75/mo |
| Lecture/seminar | Whisper Basic | Single speaker, no emotion needed | $0 |
| Product demo video | Whisper Basic | Single speaker, straightforward | $0 |
| User testimonials | AssemblyAI | Multiple speakers, need attribution | $125/mo |

---

## Configuration Steps

### Enable AssemblyAI
```bash
# .env file
ASSEMBLYAI_API_KEY=aai_YOUR_KEY_HERE
ENABLE_ASSEMBLYAI_DIARIZATION=true
ASSEMBLYAI_LANGUAGE_CODE=en
```

Then restart:
```bash
make restart
```

New jobs will automatically use AssemblyAI.

### Enable Whisper + Emotions
```bash
# .env file
OPENAI_API_KEY=sk_YOUR_KEY_HERE
GOOGLE_CLOUD_SPEECH_API_KEY=YOUR_KEY_HERE
```

Then when submitting job:
```json
{
  "video_url": "...",
  "include_emotions": true,
  "whisper_model": "small"
}
```

### Use Basic Whisper (Default)
```bash
# No special config needed
# Just submit job with include_emotions=false
```

---

## Key Differences in Downstream Processing

### When Using AssemblyAI
```python
# Recap generation receives speaker context
transcript = {
    "segments": [
        {"text": "...", "speaker": "A", "speaker_name": "John"},
        {"text": "...", "speaker": "B", "speaker_name": "Sarah"}
    ]
}

# LLM can write: "John explains how the algorithm works, 
#                 while Sarah asks clarifying questions"
```

### When Using Whisper + Emotions
```python
# Recap generation receives emotional context
data = {
    "transcript": [...],
    "emotions": [
        {"dominant_emotion": "excitement", "intensity": 0.85},
        {"dominant_emotion": "confusion", "intensity": 0.60}
    ]
}

# LLM knows to select exciting moments and 
# match narration tone to the emotional arc
```

### When Using Basic Whisper
```python
# Only text available
transcript = [
    {"text": "...", "start": 0.5, "end": 2.1},
    {"text": "...", "start": 2.2, "end": 4.8}
]

# LLM selects clips based purely on keyword matching
```

---

## Performance Metrics

| Backend | Processing Time | Accuracy | Cost |
|---------|-----------------|----------|------|
| Basic Whisper (small) | 2-3x real-time | 85-90% | $0 |
| Basic Whisper (medium) | 4-5x real-time | 90-93% | $0 |
| Whisper + Emotions | 3-5 minutes extra | +emotion data | $0.15/min |
| AssemblyAI | 1-2x real-time | 90-95% | $0.025/min |

For a 5-minute video:
- Whisper small: ~15 minutes total (+ emotion: +3-5 min)
- AssemblyAI: ~8-10 minutes total

---

## Testing Each Backend

### Test Basic Whisper
```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "video_url": "https://...",
    "include_emotions": false,
    "whisper_model": "small"
  }'
```

### Test Whisper + Emotions
```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "video_url": "https://...",
    "include_emotions": true,
    "whisper_model": "small"
  }'
```

### Test AssemblyAI
```bash
# Set ASSEMBLYAI_API_KEY and ENABLE_ASSEMBLYAI_DIARIZATION first
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "video_url": "https://..."
  }'
# Will automatically use AssemblyAI if configured
```

---

## Summary

| Aspect | Whisper | AssemblyAI |
|--------|---------|-----------|
| **Primary Function** | Speech-to-text | Speech-to-text + speaker ID |
| **Speaker Info** | ❌ None | ✅ Who spoke, name extraction |
| **Local/Cloud** | ✅ Local | ☁️ Cloud |
| **Cost** | $0 | $0.025/min (~$125/mo) |
| **Use In VideoRecap** | BASIC tier | PREMIUM/ENTERPRISE tier |
| **Emotion Analysis** | Via Google Cloud (optional) | Not included |
| **Best For** | Single speaker, cost-conscious | Multi-speaker, attribution needed |

**Bottom Line:** VideoRecap intelligently chooses the best backend based on your configuration and job requirements, automatically providing speaker identification when available, emotion context when enabled, or clean transcription by default.
