# AssemblyAI & Whisper Integration in VideoRecap

## Overview

VideoRecap supports **two transcription backends** for speech-to-text processing:

1. **AssemblyAI** - Advanced speaker diarization with speaker identification
2. **Whisper (OpenAI)** - Free, local transcription with optional emotion analysis

The choice between them is determined by configuration, with AssemblyAI taking priority when enabled.

---

## Architecture Comparison

| Feature | Whisper | AssemblyAI |
|---------|---------|-----------|
| **Primary Use** | BASIC tier (free) | Premium tier (speaker ID) |
| **Speaker Diarization** | ❌ No | ✅ Yes (identifies who speaks) |
| **Speaker Identification** | ❌ No | ✅ Yes (extracts names: "I'm John") |
| **Self-Correction Detection** | ❌ No | ✅ Yes (tracks name corrections) |
| **Emotion Analysis** | ✅ Yes (optional via Google Cloud) | ❌ No (not included) |
| **Language Support** | 99+ languages | 100+ languages |
| **Cost** | Free (local) | $0.025/minute |
| **Speed** | Slower (2-3x real-time) | Faster (near real-time) |
| **Privacy** | Full (local processing) | Cloud-based |
| **Accuracy** | 85-95% | 85-95% |

---

## Decision Flow

```
START: transcribe_with_optional_emotions()
  │
  ├─ ASSEMBLYAI_ENABLED && ASSEMBLYAI_API_KEY available?
  │   ├─ YES → Use AssemblyAI with Speaker Diarization
  │   │         Returns: (transcript_file, None)
  │   │
  │   └─ NO ↓
  │
  ├─ include_emotions=True?
  │   ├─ YES → Use Whisper + Google Cloud Emotion Analysis
  │   │         Returns: (transcript_file, emotions_file)
  │   │
  │   └─ NO ↓
  │
  └─ Use Basic Whisper Transcription
      Returns: (transcript_file, None)
```

---

## Implementation Details

### 1. Whisper Transcription (Basic)

**Location:** `modules/transcription.py::transcribe_video()`

**What It Does:**
- Extracts audio from video using MoviePy
- Transcribes using OpenAI's Whisper model
- Outputs timestamped text segments

**Output Format:**
```json
[
  {
    "start": 0.5,
    "end": 5.2,
    "text": "Hello everyone, welcome to the show"
  },
  {
    "start": 5.2,
    "end": 12.8,
    "text": "Today we're discussing artificial intelligence"
  }
]
```

**When Used:**
- BASIC tier (no Premium features)
- `include_emotions=False` and no AssemblyAI API key

**Pros:**
- Free and local (no API calls)
- No privacy concerns
- Fast for small videos

**Cons:**
- No speaker identification
- No emotion analysis (without Premium tier)

---

### 2. Whisper + Emotion Analysis (Premium)

**Location:** `modules/transcription.py::transcribe_video_with_emotions()`

**What It Does:**
1. Transcribes audio using Whisper (same as Basic)
2. Analyzes emotions per segment using Google Cloud Speech API
3. Combines transcript with emotion data

**Output Format:**
```json
{
  "transcript": [
    {
      "start": 0.5,
      "end": 5.2,
      "text": "Hello everyone!",
      "confidence": 0.98
    }
  ],
  "emotions": [
    {
      "start": 0.5,
      "end": 5.2,
      "dominant_emotion": "joy",
      "intensity": 0.85,
      "emotions": {
        "joy": 0.85,
        "neutral": 0.12,
        "sadness": 0.03
      }
    }
  ]
}
```

**When Used:**
- PREMIUM tier with `include_emotions=True`
- AssemblyAI API key NOT available or disabled

**Pros:**
- Includes emotional context for better clip selection
- Narration can match emotional tone
- Still local audio processing (Google Cloud for emotion only)

**Cons:**
- Requires Google Cloud Speech API credits
- Still no speaker identification
- Emotion analysis adds processing time (3-5 minutes extra)

---

### 3. AssemblyAI with Speaker Diarization

**Location:** `modules/transcription.py::transcribe_video_with_assemblyai()`

**What It Does:**
1. Extracts audio from video
2. Sends to AssemblyAI API for transcription
3. AssemblyAI returns **speaker labels** (Speaker A, B, C, etc.)
4. **Extracts speaker names** from phrases like "I'm John" or "I am Sarah"
5. **Detects self-corrections** when speaker mentions different names
6. Returns organized transcript with speaker metadata

**Output Format:**
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
      "total_words": 1245,
      "total_duration_seconds": 125.3,
      "avg_confidence": 0.94,
      "name_mentions": { "John": 3 },
      "corrected_from": []
    },
    "B": {
      "speaker_id": "B",
      "name": "Sarah",
      "total_words": 890,
      "total_duration_seconds": 98.5,
      "avg_confidence": 0.92,
      "name_mentions": { "Sarah": 2, "Sara": 1 },
      "corrected_from": ["Sara"]
    }
  },
  "segments": {
    "0": {
      "text": "Hi, I'm John.",
      "start": 0.5,
      "end": 2.1,
      "speaker": "A",
      "speaker_confidence": 0.98,
      "speaker_name": "John"
    },
    "1": {
      "text": "Hi John, I'm Sarah.",
      "start": 2.2,
      "end": 4.8,
      "speaker": "B",
      "speaker_confidence": 0.95,
      "speaker_name": "Sarah"
    }
  }
}
```

**Key Features:**

#### Speaker Name Extraction
```python
# Uses regex to find "I'm NAME" or "I am NAME" patterns
# Counts all mentions per speaker
# Selects most frequently mentioned name (handles self-corrections)
```

Example:
- Speaker A says: "I'm James" (1 mention) → Later says: "Actually it's Lanes" (2 mentions)
- **Result:** Speaker name = "Lanes" (corrected_from: ["James"])

#### Confidence Tracking
- Each segment has `speaker_confidence` (how sure AssemblyAI is about the speaker)
- Average confidence calculated per speaker
- Used downstream for quality assessment

**When Used:**
- AssemblyAI API key configured and `ENABLE_ASSEMBLYAI_DIARIZATION=true`
- Takes priority over all other methods

**Pros:**
- Identifies who is speaking ✅
- Extracts speaker names ✅
- Detects self-corrections ✅
- High accuracy (95%+)
- Near real-time processing

**Cons:**
- Paid API ($0.025/minute)
- Cloud-based (privacy consideration)
- Requires API key management

---

## Configuration

### Environment Variables

**For Whisper (Basic/Premium):**
```bash
WHISPER_MODEL=small          # tiny, base, small, medium, large
OPENAI_API_KEY=sk-...        # For Premium tier emotion analysis
```

**For AssemblyAI:**
```bash
ASSEMBLYAI_API_KEY=aai_...            # AssemblyAI API key
ENABLE_ASSEMBLYAI_DIARIZATION=true    # Enable speaker diarization
ASSEMBLYAI_LANGUAGE_CODE=en           # Language code (en, es, fr, etc.)
```

### Backend Configuration

**Location:** `backend/app/config.py`

```python
# Whisper settings
WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "small")

# AssemblyAI settings
ENABLE_ASSEMBLYAI_DIARIZATION: bool = os.getenv("ENABLE_ASSEMBLYAI_DIARIZATION", "false").lower() == "true"
ASSEMBLYAI_API_KEY: str = os.getenv("ASSEMBLYAI_API_KEY", "")
ASSEMBLYAI_LANGUAGE_CODE: str = os.getenv("ASSEMBLYAI_LANGUAGE_CODE", "en")
```

### Job Configuration

**When submitting a job via API:**
```json
{
  "whisper_model": "small",
  "language": "en",
  "translate_to": "es",
  "include_emotions": true,
  "target_duration": 30
}
```

---

## Processing Pipeline Integration

### Step 1: Transcription (in Pipeline)

**Location:** `backend/app/workers/pipeline.py::run()`

```python
# Calls transcribe_video_service() which wraps modules.transcription
result = transcribe_video_service(
    local_video_path,
    working_dir,
    model_size=model_size,           # Whisper model size
    language=language,               # Language code
    include_emotions=include_emotions, # Premium tier flag
    progress_callback=self._progress_callback,
)

# Returns
transcription_file = result["transcription_file"]
emotions_file = result.get("emotions_file")  # None if Basic/AssemblyAI
```

**Progress Messages:**
- **AssemblyAI:** `"Transcribing [AssemblyAI with SPEAKER DIARIZATION] - identifying speakers…"`
- **Premium:** `"Transcribing [PREMIUM (with emotion analysis)] (Whisper model already loaded)…"`
- **Basic:** `"Transcribing [BASIC (transcription only)]…"`

### Step 3: Recap Generation (uses transcript from Step 1)

**Location:** `backend/app/processing/video_processing.py::generate_recap_service()`

```python
# Uses transcript for clip selection
result = generate_recap_service(
    active_transcription,      # From Step 1
    working_dir,
    target_duration=target_duration,
    narration_language=narration_lang,
    emotions_file=emotions_file,  # Only if Premium tier
    progress_callback=self._progress_callback,
)
```

**How Each Transcript Type Affects Recap:**

1. **AssemblyAI Transcript:**
   - LLM sees speaker names and IDs
   - Can generate narration like "John explains the concept while Sarah asks questions"
   - Better narrative flow with speaker context

2. **Whisper + Emotions:**
   - LLM sees emotion data for each segment
   - Selects clips during emotionally significant moments
   - Narration can match emotional tone ("exciting moment" vs. "somber reflection")

3. **Basic Whisper:**
   - Only text content available
   - Clip selection based on keywords/length
   - Narration is neutral/generic

---

## Data Flow in Storage

### Step 1: Transcription Storage

**Using Whisper (Basic or Premium):**
```
s3://videorecap/jobs/{job_id}/step_01_transcription/
├── transcript.json          (timestamp + text only)
├── emotions.json            (if Premium tier)
└── metadata.json
    {
      "model": "whisper-small",
      "language": "en",
      "include_emotions": true/false
    }
```

**Using AssemblyAI:**
```
s3://videorecap/jobs/{job_id}/step_01_transcription/
├── transcript.json          (with speaker info)
└── metadata.json
    {
      "provider": "assemblyai",
      "speaker_diarization_enabled": true,
      "language_code": "en"
    }
```

### Resume from Step 1

If a job is stopped and resumed from Step 2+:
- Downloads `transcript.json` (AssemblyAI or Whisper format)
- Downloads `emotions.json` (if available)
- Uses same format downstream (format-agnostic)

---

## Whisper Model Selection Guide

| Model | Speed | Accuracy | VRAM | Use Case |
|-------|-------|----------|------|----------|
| **tiny** | ⚡⚡⚡ (fastest) | 🟡 (75-80%) | 1GB | Quick preview, low accuracy acceptable |
| **base** | ⚡⚡ | 🟡🟡 (80-85%) | 1GB | Fast processing, acceptable quality |
| **small** | ⚡ | 🟡🟡🟡 (85-90%) | 2GB | Default, good balance |
| **medium** | 🐢 | 🟢 (90-93%) | 5GB | High quality, longer processing |
| **large** | 🐢🐢 (slowest) | 🟢🟢 (93-95%+) | 10GB | Highest accuracy, slow |

**Recommended:**
- **Development:** `tiny` or `base` (fast iteration)
- **Production:** `small` or `medium` (quality + speed balance)
- **Critical accuracy:** `large` (if you have VRAM)

---

## API Integration

### Transcription Endpoint

**Location:** `backend/app/api/v1/endpoints/jobs.py`

```python
POST /api/v1/jobs
{
  "video_url": "...",
  "whisper_model": "small",      # or medium, large
  "language": "en",
  "translate_to": null,          # Optional language translation
  "include_emotions": false,     # true for Premium tier
  "target_duration": 30
}
```

### Job Status Response

```json
{
  "id": "job-123",
  "status": "processing",
  "current_step": 1,
  "current_step_name": "Transcribing video",
  "emotion_analysis_status": "completed",  // "completed", "failed", or "skipped"
  "emotion_analysis_error": null,
  "intermediate_keys": {
    "transcription": "s3://...",
    "emotions": "s3://...",  // null if not Premium
    "step_01.transcript": "s3://...",
    "step_01.metadata": "s3://..."
  }
}
```

---

## Troubleshooting

### AssemblyAI Issues

**Problem:** "AssemblyAI API key required but not provided"
- **Solution:** Set `ASSEMBLYAI_API_KEY` env var and restart backend

**Problem:** "AssemblyAI transcription failed"
- **Solution:** Check API key validity, check audio file format, verify internet connection

**Problem:** Speaker names not extracted
- **Solution:** Speakers must explicitly say "I'm NAME" or "I am NAME" in the audio

### Whisper Issues

**Problem:** "CUDA out of memory" (model loading fails)
- **Solution:** Use smaller model (tiny/base) or reduce batch size

**Problem:** Emotion analysis returns null
- **Solution:** Set `include_emotions=true` in job config, verify Google Cloud API is available

**Problem:** Wrong language transcribed
- **Solution:** Set correct `language` in job config (e.g., "es" for Spanish)

### Resume Issues

**Problem:** Resume from Step 2 fails
- **Solution:** Verify transcript.json exists in S3, check file permissions

**Problem:** Speaker names disappear after resume
- **Solution:** Ensure AssemblyAI output (with speakers) is downloaded correctly

---

## Cost Analysis

### Monthly Costs (100 videos, 5 minutes each)

**Whisper Only (Basic):**
- Cost: $0 (all local)
- Processing: ~833 GPU hours

**Whisper + Emotion (Premium):**
- Whisper: $0 (local)
- Google Cloud Speech: ~$75 (500 minutes × $0.15/minute)
- **Total:** ~$75/month

**AssemblyAI:**
- AssemblyAI: ~$125 (500 minutes × $0.025/minute)
- **Total:** ~$125/month

---

## Migration Guide: Whisper → AssemblyAI

To switch from Whisper to AssemblyAI:

1. **Obtain AssemblyAI API Key:**
   - Sign up at https://www.assemblyai.com
   - Generate API key from dashboard
   - Add to environment

2. **Update Configuration:**
   ```bash
   export ASSEMBLYAI_API_KEY="aai_xxxxxxxxxxxx"
   export ENABLE_ASSEMBLYAI_DIARIZATION="true"
   ```

3. **Restart Backend:**
   ```bash
   make restart
   ```

4. **Process New Jobs:**
   - New jobs will automatically use AssemblyAI
   - Old Whisper-generated jobs continue to work (unchanged)

5. **No Database Changes:**
   - Transcript format is forward-compatible
   - Resume mechanism works the same
   - No migrations required

---

## Future Enhancements

Potential integrations:
- [ ] Combine AssemblyAI diarization + Whisper emotion analysis
- [ ] Support multiple diarization providers (Pyannote, Google Speech, Rev AI)
- [ ] Real-time transcription with WebSocket streaming
- [ ] Custom Whisper fine-tuning for domain-specific accuracy
- [ ] Speaker verification/identification against enrollment data
