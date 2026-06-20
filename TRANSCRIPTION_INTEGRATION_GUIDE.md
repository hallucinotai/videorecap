# Complete Transcription Integration Guide

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     User Submits Video Job                      │
│   POST /api/v1/jobs                                             │
│   { "include_emotions": true/false, "whisper_model": "..." }    │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
        ┌────────────────────────────────────┐
        │  Step 1: Transcription Service     │
        │  (backend/app/processing/          │
        │   transcription.py)                │
        └────┬─────────────────────┬─────────┘
             │                     │
             ▼                     ▼
    ┌──────────────┐      ┌────────────────────────┐
    │   Whisper    │      │  AssemblyAI (Priority) │
    │  (Local ML)  │      │  (Cloud API)           │
    │              │      │                        │
    │ Options:     │      │ ✅ Diarization        │
    │ • Basic      │      │ ✅ Speaker names       │
    │ • +Emotions  │      │ ✅ Confidence scores  │
    └──────────────┘      └────────────────────────┘
             │                     │
             └──────────┬──────────┘
                        ▼
        ┌────────────────────────────────────┐
        │  Transcript + Metadata             │
        │  Stored in S3/MinIO                │
        │  step_01_transcription/            │
        │  ├── transcript.json               │
        │  ├── emotions.json (optional)      │
        │  └── metadata.json                 │
        └────┬─────────────────────────────┬─┘
             │                             │
             ▼                             ▼
    ┌─────────────────────┐   ┌──────────────────────┐
    │  Step 3: Recap Gen  │   │  Resume from Step N  │
    │  (Clip selection)   │   │  (Download & reuse)  │
    │  Uses: speaker ID   │   │                      │
    │  + emotions         │   │  Format-agnostic     │
    └─────────────────────┘   └──────────────────────┘
```

---

## Code Flow: Request to Output

### 1. Job Submission

**User API Call:**
```bash
POST /api/v1/jobs HTTP/1.1
Content-Type: application/json

{
  "video_url": "https://example.com/video.mp4",
  "whisper_model": "small",
  "language": "en",
  "translate_to": null,
  "include_emotions": false,
  "target_duration": 30
}
```

**Location:** `backend/app/api/v1/endpoints/jobs.py`

### 2. Pipeline Initialization

**Code:** `backend/app/workers/tasks.py` → `recap_job_task()`

```python
from app.workers.pipeline import RecapPipeline

pipeline = RecapPipeline(
    job_id=job.id,
    job_config={
        "target_duration": 30,
        "whisper_model": "small",
        "language": "en",
        "translate_to": None,
        "include_emotions": False,
    },
    input_video_key=job.input_video_key,
    update_job_fn=update_job,
    publish_progress_fn=publish_progress,
)

result = pipeline.run()
```

### 3. Transcription Selection

**Code:** `backend/app/processing/transcription.py::transcribe_video_service()`

```python
def transcribe_video_service(
    video_path: str,
    working_dir: str,
    model_size: str = "small",
    language: str | None = None,
    include_emotions: bool = False,
    progress_callback: Callable | None = None,
) -> dict:
    """
    Wrapper around modules.transcription that handles backend selection.
    
    Priority:
    1. AssemblyAI (if enabled)
    2. Whisper + Emotions (if Premium)
    3. Basic Whisper
    """
    
    from modules.transcription import (
        transcribe_with_optional_emotions,
    )
    
    # Determine which backend to use
    tier = ""
    if settings.ENABLE_ASSEMBLYAI_DIARIZATION and settings.ASSEMBLYAI_API_KEY:
        tier = "AssemblyAI with SPEAKER DIARIZATION"
    elif include_emotions:
        tier = "PREMIUM (with emotion analysis)"
    else:
        tier = "BASIC (transcription only)"
    
    if progress_callback:
        progress_callback(step=1, message=f"Transcribing [{tier}]…")
    
    # Call the actual transcription function
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
        progress_callback(step=1, message="Transcription complete")
    
    return {
        "transcription_file": transcription_file,
        "emotions_file": emotions_file,
    }
```

### 4. Backend Selection Logic

**Code:** `modules/transcription.py::transcribe_with_optional_emotions()`

```python
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
    Select transcription backend based on configuration.
    
    Flow:
    1. Check if AssemblyAI is enabled → Use it
    2. Else check if emotions requested → Use Whisper+Emotions
    3. Else use Basic Whisper
    """
    
    # PRIORITY 1: AssemblyAI with Speaker Diarization
    if enable_assemblyai_diarization and assemblyai_api_key:
        print("🎤 Using AssemblyAI with SPEAKER DIARIZATION")
        transcript_file = transcribe_video_with_assemblyai(
            video_path,
            output_dir,
            api_key=assemblyai_api_key,
            language_code=assemblyai_language_code
        )
        return transcript_file, None
    
    # PRIORITY 2: Whisper + Emotion Analysis (Premium)
    if include_emotions:
        print("🎙️ Using PREMIUM tier (with emotion analysis)")
        return transcribe_video_with_emotions(
            video_path,
            output_dir,
            model_size,
            language,
            skip_emotions_on_error=True
        )
    
    # PRIORITY 3: Basic Whisper (Free/Default)
    print("📝 Using BASIC tier (transcription only)")
    transcript_file = transcribe_video(video_path, output_dir, model_size, language)
    return transcript_file, None
```

### 5a. AssemblyAI Backend

**Code:** `modules/transcription.py::transcribe_video_with_assemblyai()`

```python
def transcribe_video_with_assemblyai(
    video_path,
    output_dir="output/transcriptions",
    api_key=None,
    language_code="en"
):
    """
    Transcribe with AssemblyAI including:
    - Speaker diarization (who spoke)
    - Speaker name extraction (from "I'm..." phrases)
    - Self-correction detection (name changes)
    - Confidence scores
    """
    
    import assemblyai as aai
    from moviepy.editor import VideoFileClip
    
    # Step 1: Extract audio
    video = VideoFileClip(video_path)
    temp_audio = f"{temp_dir}/extracted_audio.wav"
    video.audio.write_audiofile(temp_audio, verbose=False, logger=None)
    video.close()
    
    # Step 2: Configure AssemblyAI with speaker diarization
    aai.settings.api_key = api_key
    config = aai.TranscriptionConfig(
        speaker_labels=True,
        speech_models=["universal-3-pro"],
        language_code=language_code,
    )
    
    # Step 3: Transcribe
    transcriber = aai.Transcriber()
    transcript = transcriber.transcribe(temp_audio, config=config)
    
    # Step 4: Extract speaker names
    # Strategy: Find all "I'm NAME" or "I am NAME" patterns
    # Count frequency per speaker, use most frequent name
    speaker_names = {}
    speaker_name_counts = {}
    
    for segment in transcript.utterances:
        speaker_id = segment.speaker
        if speaker_id not in speaker_name_counts:
            speaker_name_counts[speaker_id] = {}
        
        # Extract name mentions: "I'm John" → "John"
        matches = re.finditer(r"[Ii](?:'m| am) ([A-Z][a-z]+)", segment.text)
        for match in matches:
            name = match.group(1)
            speaker_name_counts[speaker_id][name] = speaker_name_counts[speaker_id].get(name, 0) + 1
    
    # Choose most frequent name (handles self-corrections)
    for speaker_id, names_dict in speaker_name_counts.items():
        if names_dict:
            speaker_names[speaker_id] = max(names_dict, key=names_dict.get)
    
    # Step 5: Build output structure
    transcript_data = {}
    speakers_info = {}
    
    for i, segment in enumerate(transcript.utterances):
        speaker_id = segment.speaker
        
        # Add segment with speaker info
        transcript_data[str(i)] = {
            "text": segment.text.strip(),
            "start": float(segment.start / 1000),
            "end": float(segment.end / 1000),
            "speaker": speaker_id,
            "speaker_name": speaker_names.get(speaker_id),
            "speaker_confidence": float(segment.confidence) if segment.confidence else 0.0,
        }
        
        # Track speaker stats
        if speaker_id not in speakers_info:
            speakers_info[speaker_id] = {
                "speaker_id": speaker_id,
                "name": speaker_names.get(speaker_id),
                "total_words": 0,
                "total_duration_seconds": 0.0,
                "confidence_scores": []
            }
        
        speakers_info[speaker_id]["total_words"] += len(segment.text.split())
        speakers_info[speaker_id]["total_duration_seconds"] += (segment.end - segment.start) / 1000
        if segment.confidence:
            speakers_info[speaker_id]["confidence_scores"].append(float(segment.confidence))
    
    # Calculate averages and detect corrections
    for speaker_id, info in speakers_info.items():
        info["avg_confidence"] = (
            sum(info["confidence_scores"]) / len(info["confidence_scores"])
            if info["confidence_scores"] else 0.0
        )
        del info["confidence_scores"]
        
        # Flag if speaker corrected themselves
        if speaker_id in speaker_name_counts and len(speaker_name_counts[speaker_id]) > 1:
            info["corrected_from"] = [
                n for n in speaker_name_counts[speaker_id].keys() 
                if n != info["name"]
            ]
    
    # Step 6: Save output
    output_structure = {
        "metadata": {
            "provider": "assemblyai",
            "speaker_diarization_enabled": True,
            "language_code": language_code,
        },
        "speakers": speakers_info,
        "segments": transcript_data
    }
    
    json_file = f"{output_dir}/transcription.json"
    with open(json_file, "w") as f:
        json.dump(output_structure, f, indent=2)
    
    print(f"✅ AssemblyAI transcription complete!")
    print(f"   Speakers identified: {len(speakers_info)}")
    print(f"   Segments: {len(transcript_data)}")
    
    return json_file
```

### 5b. Whisper + Emotions Backend

**Code:** `modules/transcription.py::transcribe_video_with_emotions()`

```python
def transcribe_video_with_emotions(
    video_path,
    output_dir="output/transcriptions",
    model_size="small",
    language=None,
    skip_emotions_on_error=True
):
    """
    Whisper transcription + Google Cloud emotion analysis.
    """
    
    import whisper
    from google.cloud import speech_v1
    from moviepy.editor import VideoFileClip
    
    # Step 1: Extract audio
    video = VideoFileClip(video_path)
    temp_audio = f"{temp_dir}/extracted_audio.wav"
    video.audio.write_audiofile(temp_audio, verbose=False, logger=None)
    video.close()
    
    # Step 2: Transcribe with Whisper
    print(f"Transcribing with Whisper ({model_size})...")
    model = whisper.load_model(model_size)
    result = model.transcribe(temp_audio, language=language, verbose=True)
    
    # Step 3: Extract segments
    transcript_data = []
    for segment in result["segments"]:
        transcript_data.append({
            "start": segment["start"],
            "end": segment["end"],
            "text": segment["text"].strip(),
            "confidence": segment.get("confidence", 0.0),
        })
    
    # Step 4: Emotion analysis via Google Cloud Speech
    print("Analyzing emotions...")
    client = speech_v1.SpeechClient()
    
    emotions_data = []
    
    try:
        with open(temp_audio, "rb") as audio_file:
            content = audio_file.read()
        
        audio = speech_v1.RecognitionAudio(content=content)
        config = speech_v1.RecognitionConfig(
            encoding=speech_v1.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
            language_code=language or "en-US",
        )
        
        response = client.recognize(config=config, audio=audio)
        
        # Extract emotion data from Google Cloud response
        # (This is simplified; actual implementation depends on API response)
        for result_item in response.results:
            for alternative in result_item.alternatives:
                # Parse emotion metadata if available
                if hasattr(alternative, 'confidence'):
                    emotions_data.append({
                        "start": 0,  # Would need time info from Google Cloud
                        "end": 1,
                        "dominant_emotion": "neutral",
                        "intensity": 0.5,
                        "emotions": {"neutral": 1.0}
                    })
    
    except Exception as e:
        print(f"Emotion analysis failed: {e}")
        if not skip_emotions_on_error:
            raise
        emotions_data = None
    
    # Step 5: Save outputs
    json_file = f"{output_dir}/transcription.json"
    with open(json_file, "w") as f:
        json.dump(transcript_data, f, indent=2)
    
    emotions_file = None
    if emotions_data:
        emotions_file = f"{output_dir}/emotions.json"
        with open(emotions_file, "w") as f:
            json.dump(emotions_data, f, indent=2)
    
    return json_file, emotions_file
```

### 5c. Basic Whisper Backend

**Code:** `modules/transcription.py::transcribe_video()`

```python
def transcribe_video(
    video_path,
    output_dir="output/transcriptions",
    model_size="small",
    language=None
):
    """
    Basic Whisper transcription (no emotion analysis).
    """
    
    import whisper
    from moviepy.editor import VideoFileClip
    
    # Step 1: Extract audio
    print("Extracting audio from video...")
    video = VideoFileClip(video_path)
    temp_audio = f"{temp_dir}/extracted_audio.wav"
    video.audio.write_audiofile(temp_audio, verbose=False, logger=None)
    video.close()
    
    # Step 2: Load Whisper model (cached in memory for reuse)
    print(f"Loading Whisper model '{model_size}'...")
    model = whisper.load_model(model_size)
    
    # Step 3: Transcribe
    print("Transcribing audio...")
    options = {"verbose": True}
    if language:
        options["language"] = language
    
    result = model.transcribe(temp_audio, **options)
    
    # Step 4: Extract segments
    transcript_data = []
    for segment in result["segments"]:
        transcript_data.append({
            "start": segment["start"],
            "end": segment["end"],
            "text": segment["text"].strip(),
        })
    
    # Step 5: Save
    json_file = f"{output_dir}/transcription.json"
    with open(json_file, "w") as f:
        json.dump(transcript_data, f, indent=2)
    
    print(f"✅ Transcription complete!")
    print(f"   Segments: {len(transcript_data)}")
    print(f"   Output: {json_file}")
    
    return json_file
```

---

## 6. Storage & Resumption

### Save to MinIO

**Code:** `backend/app/workers/pipeline.py:173`

```python
# After transcription completes, save to step storage
keys = self.step_storage.upload_step_output(
    step_num=1,
    files_dict={"transcript": transcription_file},
    metadata={
        "model": model_size if not is_assemblyai else "assemblyai",
        "language": language,
        "include_emotions": include_emotions,
    }
)
intermediate_keys.update(keys)

# Also save with old key for backward compatibility
self._upload_intermediate(
    intermediate_keys,
    "transcription",
    transcription_file
)
```

**S3 Structure:**
```
s3://videorecap/jobs/JOB_ID/step_01_transcription/
├── transcript.json       (AssemblyAI: with speakers; Whisper: without)
├── emotions.json         (only if Whisper + Premium)
└── metadata.json
```

### Resume from Later Step

**Code:** `backend/app/workers/pipeline.py:113`

```python
# Download previously saved transcript
if resume_from_step >= 2:
    if "translation" in intermediate_keys:
        active_transcription = self._download_intermediate(
            intermediate_keys,
            "translation",
            f"{working_dir}/output/transcriptions/translated.json"
        )
    if not active_transcription and "transcription" in intermediate_keys:
        active_transcription = self._download_intermediate(
            intermediate_keys,
            "transcription",
            f"{working_dir}/output/transcriptions/transcription.json"
        )
    
    # Download emotions if available
    if include_emotions and "emotions" in intermediate_keys:
        emotions_file = self._download_intermediate(
            intermediate_keys,
            "emotions",
            f"{working_dir}/output/transcriptions/emotions.json"
        )
```

---

## 7. Usage in Downstream Steps

### Step 3: Recap Generation

**Code:** `backend/app/processing/video_processing.py`

```python
def generate_recap_service(
    transcript_file,
    working_dir,
    target_duration=30,
    narration_language="English",
    emotions_file=None,
    progress_callback=None,
):
    """
    Uses transcript (any format: AssemblyAI, Whisper+Emotions, or Basic Whisper)
    to generate clips and narration.
    """
    
    # Load transcript (format-agnostic)
    with open(transcript_file, 'r') as f:
        transcript_data = json.load(f)
    
    # Load emotions if available
    emotions_data = None
    if emotions_file and os.path.exists(emotions_file):
        with open(emotions_file, 'r') as f:
            emotions_data = json.load(f)
    
    # Call LLM to generate clips and narration
    # The LLM sees:
    # - All transcript text
    # - Speaker names (if AssemblyAI)
    # - Emotion data (if Premium + Whisper)
    
    result = generate_recap_suggestions(
        transcript_data,
        target_duration,
        narration_language,
        emotions_data,
    )
    
    return {
        "recap_data_file": recap_data_file,
    }
```

---

## Configuration Reference

### Environment Variables

```bash
# Whisper settings
WHISPER_MODEL=small                          # tiny/base/small/medium/large
REDIS_URL=redis://redis:6379               # For cache invalidation

# AssemblyAI settings
ENABLE_ASSEMBLYAI_DIARIZATION=false         # Set true to use AssemblyAI
ASSEMBLYAI_API_KEY=aai_xxxxxxxxxxxx         # AssemblyAI API key
ASSEMBLYAI_LANGUAGE_CODE=en                 # Language code

# Emotion analysis (Premium)
OPENAI_API_KEY=sk_xxxxxxxxxxxx              # For Google Cloud or OpenAI APIs
GOOGLE_CLOUD_SPEECH_API_KEY=xxxx            # For emotion analysis
```

### Backend Configuration File

**Location:** `backend/app/config.py`

```python
class Settings(BaseSettings):
    # Transcription
    WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "small")
    REDIS_URL: str | None = os.getenv("REDIS_URL")
    
    # AssemblyAI
    ENABLE_ASSEMBLYAI_DIARIZATION: bool = os.getenv("ENABLE_ASSEMBLYAI_DIARIZATION", "false").lower() == "true"
    ASSEMBLYAI_API_KEY: str = os.getenv("ASSEMBLYAI_API_KEY", "")
    ASSEMBLYAI_LANGUAGE_CODE: str = os.getenv("ASSEMBLYAI_LANGUAGE_CODE", "en")
    
    # Emotion analysis
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
```

---

## Testing Checklist

- [ ] **Basic Whisper:** Submit job with `include_emotions=false`, no AssemblyAI key
- [ ] **Whisper + Emotions:** Set `OPENAI_API_KEY`, submit with `include_emotions=true`
- [ ] **AssemblyAI:** Set `ASSEMBLYAI_API_KEY`, set `ENABLE_ASSEMBLYAI_DIARIZATION=true`
- [ ] **Resume:** Stop job, verify transcript in S3, resume from step 3
- [ ] **Backends don't interfere:** Whisper works with old code, switch to AssemblyAI doesn't break resume

---

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| AssemblyAI not used when enabled | API key missing or `ENABLE_ASSEMBLYAI_DIARIZATION=false` | Check env vars, restart backend |
| Emotion analysis returns null | `include_emotions=false` in job request | Ensure job config has `include_emotions: true` |
| Speaker names not extracted | Speakers didn't say "I'm..." in audio | Confirm audio has self-introductions |
| Resume fails at step 2 | Transcript.json not in S3 | Check S3 paths, verify step 1 completed |
| Whisper model load fails | Out of memory with large model | Switch to smaller model (tiny/base) |
