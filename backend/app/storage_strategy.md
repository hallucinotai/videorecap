# MinIO Storage Strategy - Step-by-Step Enhancement Tracking

## Overview
Store intermediate outputs from each step in MinIO so you can:
- Track how data is enhanced at each stage
- Debug issues by examining outputs at any step
- Understand the transformation pipeline visually
- Validate quality at each checkpoint
- Rerun downstream steps without re-processing upstream ones

---

## Directory Structure in MinIO

```
s3://videorecap/
├── jobs/
│   └── {job_id}/
│       ├── step_01_audio_extraction/
│       │   └── audio.wav
│       │
│       ├── step_02_transcription/
│       │   ├── transcript_raw.json
│       │   └── metadata.json (confidence, duration, language)
│       │
│       ├── step_03_diarization/
│       │   ├── transcript_with_speakers.json
│       │   └── speaker_labels.json
│       │
│       ├── step_04_transcript_merge/
│       │   ├── transcript_enhanced.json
│       │   └── merge_report.json (corrections applied, confidence)
│       │
│       ├── step_05_emotion_analysis/ [OPTIONAL]
│       │   ├── emotions_raw.json
│       │   └── emotions_confidence.json
│       │
│       ├── step_06_emotion_merge/ [OPTIONAL]
│       │   ├── transcript_with_emotions.json
│       │   └── emotion_merge_report.json
│       │
│       ├── step_07_clip_selection/
│       │   ├── clip_timings.json
│       │   ├── clip_reasoning.json (why each clip selected)
│       │   └── clip_selection_raw.json (full LLM response)
│       │
│       ├── step_08_narration_generation/
│       │   ├── recap_text.txt
│       │   ├── narration_full.json (metadata)
│       │   └── narration_raw.json (full LLM response)
│       │
│       ├── step_09_recap_assembly/
│       │   └── recap_data.json
│       │       └── Unified structure with all outputs
│       │
│       ├── step_10_video_extraction/
│       │   ├── clip_segments/
│       │   │   ├── clip_001.mp4 (start-end from clip_timings[0])
│       │   │   ├── clip_002.mp4 (start-end from clip_timings[1])
│       │   │   └── ...
│       │   └── extraction_report.json
│       │
│       ├── step_11_video_merge/
│       │   ├── recap_video.mp4
│       │   └── merge_report.json (duration, transitions, quality)
│       │
│       ├── step_12_tts_generation/
│       │   ├── narration.mp3
│       │   └── tts_metadata.json (voice, speed, language, duration)
│       │
│       ├── step_13_audio_mixing/
│       │   ├── final_recap_video.mp4
│       │   └── audio_mix_report.json
│       │
│       └── logs/
│           ├── step_01_log.txt
│           ├── step_02_log.txt
│           └── ... (one log per step)
```

---

## Step-by-Step Output Details

### Step 1: Audio Extraction
```
MinIO Path: s3://videorecap/jobs/{job_id}/step_01_audio_extraction/
Files:
  - audio.wav (44.1kHz, stereo)

Metadata:
  - duration: 300.5 seconds
  - sample_rate: 44100
  - channels: 2
  - size: 26.5 MB
```

### Step 2: Speech Recognition (Transcription)
```
MinIO Path: s3://videorecap/jobs/{job_id}/step_02_transcription/

Files:
  - transcript_raw.json
  - metadata.json

Content Example (transcript_raw.json):
[
  {
    "start": 0.5,
    "end": 5.2,
    "text": "Hello everyone, welcome to the show",
    "confidence": 0.98
  },
  {
    "start": 5.2,
    "end": 12.8,
    "text": "Today we're discussing artificial intelligence",
    "confidence": 0.95
  },
  ...
]

metadata.json:
{
  "model": "whisper-medium",
  "duration": 300.5,
  "total_segments": 127,
  "average_confidence": 0.96,
  "language": "en",
  "timestamp": "2026-06-02T10:30:00Z"
}
```

### Step 3: Speaker Diarization
```
MinIO Path: s3://videorecap/jobs/{job_id}/step_03_diarization/

Files:
  - transcript_with_speakers.json (Step 2 + speaker labels)
  - speaker_labels.json (speaker mapping)

Content Example (transcript_with_speakers.json):
[
  {
    "start": 0.5,
    "end": 5.2,
    "text": "Hello everyone, welcome to the show",
    "confidence": 0.98,
    "speaker_id": "speaker_001",
    "speaker_name": null  # Not yet assigned
  },
  {
    "start": 5.2,
    "end": 12.8,
    "text": "Today we're discussing artificial intelligence",
    "confidence": 0.95,
    "speaker_id": "speaker_002",
    "speaker_name": null
  },
  ...
]

speaker_labels.json:
{
  "speaker_001": {
    "total_duration": 145.2,
    "segment_count": 42,
    "detected_gender": "male",
    "frequency_analysis": {}
  },
  "speaker_002": {
    "total_duration": 98.5,
    "segment_count": 28,
    "detected_gender": "female",
    "frequency_analysis": {}
  }
}
```

### Step 4: Transcript Merge (Speaker Name Assignment)
```
MinIO Path: s3://videorecap/jobs/{job_id}/step_04_transcript_merge/

Files:
  - transcript_enhanced.json (Step 3 + speaker names/corrections)
  - merge_report.json (what was corrected)

Content Example (transcript_enhanced.json):
[
  {
    "start": 0.5,
    "end": 5.2,
    "text": "Hello everyone, welcome to the show",
    "confidence": 0.98,
    "speaker_id": "speaker_001",
    "speaker_name": "John",
    "corrected_from": ["Speaker 1", "Unknown Speaker"]
  },
  {
    "start": 5.2,
    "end": 12.8,
    "text": "Today we're discussing artificial intelligence",
    "confidence": 0.95,
    "speaker_id": "speaker_002",
    "speaker_name": "Sarah",
    "corrected_from": ["Speaker 2"]
  },
  ...
]

merge_report.json:
{
  "names_assigned": ["John", "Sarah"],
  "corrections_applied": 2,
  "ambiguous_speakers": 0,
  "quality_score": 0.98
}
```

### Step 5: Emotion Analysis [OPTIONAL]
```
MinIO Path: s3://videorecap/jobs/{job_id}/step_05_emotion_analysis/

Files:
  - emotions_raw.json (emotion per segment)
  - emotions_confidence.json (confidence scores)

Content Example (emotions_raw.json):
[
  {
    "start": 0.5,
    "end": 5.2,
    "dominant_emotion": "joy",
    "intensity": 0.85,
    "emotions": {
      "joy": 0.85,
      "surprise": 0.10,
      "neutral": 0.05
    }
  },
  {
    "start": 5.2,
    "end": 12.8,
    "dominant_emotion": "neutral",
    "intensity": 0.45,
    "emotions": {
      "neutral": 0.45,
      "interest": 0.35,
      "confusion": 0.20
    }
  },
  ...
]
```

### Step 6: Emotion Merge [OPTIONAL]
```
MinIO Path: s3://videorecap/jobs/{job_id}/step_06_emotion_merge/

Files:
  - transcript_with_emotions.json (Step 4 + Step 5)
  - emotion_merge_report.json

Content Example (transcript_with_emotions.json):
[
  {
    "start": 0.5,
    "end": 5.2,
    "text": "Hello everyone, welcome to the show",
    "speaker_name": "John",
    "dominant_emotion": "joy",
    "intensity": 0.85,
    "emotions": { "joy": 0.85, "surprise": 0.10, "neutral": 0.05 }
  },
  ...
]
```

### Step 7: Clip Selection
```
MinIO Path: s3://videorecap/jobs/{job_id}/step_07_clip_selection/

Files:
  - clip_timings.json (selected clips)
  - clip_reasoning.json (why each clip selected)
  - clip_selection_raw.json (full LLM response)

Content Example (clip_timings.json):
{
  "clips": [
    {
      "start": 0.5,
      "end": 5.2,
      "reason": "Strong opening, high emotion"
    },
    {
      "start": 25.1,
      "end": 34.5,
      "reason": "Key revelation, plot turning point"
    },
    {
      "start": 120.3,
      "end": 135.8,
      "reason": "Emotional climax, high engagement"
    }
  ],
  "total_duration": 28.9,
  "target_duration": 30,
  "selection_method": "GPT-4o with emotion weighting"
}

clip_reasoning.json:
{
  "model": "gpt-4o",
  "prompt_version": "v4",
  "emotion_weighted": true,
  "target_duration": 30,
  "actual_duration": 28.9,
  "timestamp": "2026-06-02T10:35:12Z"
}

clip_selection_raw.json:
{
  Full LLM response with all details, reasoning, alternatives
}
```

### Step 8: Narration Generation
```
MinIO Path: s3://videorecap/jobs/{job_id}/step_08_narration_generation/

Files:
  - recap_text.txt (final narration script)
  - narration_full.json (metadata)
  - narration_raw.json (full LLM response)

Content Example (recap_text.txt):
John walks into the studio with palpable excitement. He greets everyone 
enthusiastically, setting a warm tone for what's to come. Then he dives 
into the topic of artificial intelligence — a subject that clearly fascinates 
him. Sarah joins in, adding technical depth to the discussion...

narration_full.json:
{
  "word_count": 218,
  "target_word_count": 220,
  "language": "English",
  "character_count": 1245,
  "estimated_duration_seconds": 28.5,
  "prompt_version": "v4",
  "model": "gpt-4o",
  "timestamp": "2026-06-02T10:35:45Z"
}
```

### Step 9: Recap Assembly
```
MinIO Path: s3://videorecap/jobs/{job_id}/step_09_recap_assembly/

Files:
  - recap_data.json (UNIFIED - all outputs combined)

Content Example (recap_data.json):
{
  "job_id": "{job_id}",
  "recap_text": "John walks into the studio...",
  "clip_timings": [
    {"start": 0.5, "end": 5.2},
    {"start": 25.1, "end": 34.5},
    {"start": 120.3, "end": 135.8}
  ],
  "total_duration": 28.9,
  "emotions_used": true,
  "clip_emotions": [
    {
      "start": 0.5,
      "end": 5.2,
      "dominant_emotion": "joy",
      "intensity": 0.85
    },
    ...
  ],
  "metadata": {
    "transcript_segments": 127,
    "speakers": ["John", "Sarah"],
    "language": "English",
    "processing_steps": [1, 2, 3, 4, 5, 6, 7, 8, 9],
    "timestamps": {
      "step_01_completed": "2026-06-02T10:30:15Z",
      "step_02_completed": "2026-06-02T10:33:45Z",
      ...
    }
  }
}
```

### Step 10: Video Clip Extraction
```
MinIO Path: s3://videorecap/jobs/{job_id}/step_10_video_extraction/

Files:
  - clip_segments/clip_001.mp4 (from start=0.5, end=5.2)
  - clip_segments/clip_002.mp4 (from start=25.1, end=34.5)
  - clip_segments/clip_003.mp4 (from start=120.3, end=135.8)
  - extraction_report.json

extraction_report.json:
{
  "total_clips_extracted": 3,
  "total_duration": 28.9,
  "clips": [
    {
      "clip_id": "001",
      "start": 0.5,
      "end": 5.2,
      "duration": 4.7,
      "resolution": "1920x1080",
      "codec": "h264",
      "file_size_mb": 3.2
    },
    ...
  ],
  "timestamp": "2026-06-02T10:36:20Z"
}
```

### Step 11: Video Merge
```
MinIO Path: s3://videorecap/jobs/{job_id}/step_11_video_merge/

Files:
  - recap_video.mp4 (merged video, no narration audio)
  - merge_report.json

recap_video.mp4:
  - Duration: 28.9 seconds
  - Resolution: 1920x1080
  - Codec: h264
  - Contains original audio (for reference)
  - Size: ~12 MB

merge_report.json:
{
  "total_duration": 28.9,
  "clips_merged": 3,
  "resolution": "1920x1080",
  "frame_rate": 30,
  "audio_preserved": true,
  "transitions": "direct_cut",
  "quality_check": "passed"
}
```

### Step 12: Text-to-Speech
```
MinIO Path: s3://videorecap/jobs/{job_id}/step_12_tts_generation/

Files:
  - narration.mp3 (voiceover audio)
  - tts_metadata.json

narration.mp3:
  - Duration: 28.5 seconds
  - Sample rate: 24000 Hz
  - Bitrate: 128 kbps
  - Voice: "nova"
  - Language: "en"
  - Size: ~445 KB

tts_metadata.json:
{
  "service": "openai",
  "voice": "nova",
  "speed": 1.0,
  "language": "English",
  "duration": 28.5,
  "word_count": 218,
  "file_size_kb": 445,
  "timestamp": "2026-06-02T10:36:50Z"
}
```

### Step 13: Audio Mixing (Final)
```
MinIO Path: s3://videorecap/jobs/{job_id}/step_13_audio_mixing/

Files:
  - final_recap_video.mp4 (FINAL OUTPUT with narration)
  - audio_mix_report.json

final_recap_video.mp4:
  - Duration: 28.9 seconds
  - Resolution: 1920x1080
  - Audio Tracks:
    ├─ Track 1: Narration (100% volume)
    └─ Track 2: Original audio (25% volume, ducked)
  - Codec: h264
  - Size: ~15 MB

audio_mix_report.json:
{
  "narration_volume": 100,
  "original_audio_volume": 25,
  "final_duration": 28.9,
  "quality_check": "passed",
  "sync_verified": true,
  "timestamp": "2026-06-02T10:37:05Z"
}
```

### Logs Directory
```
MinIO Path: s3://videorecap/jobs/{job_id}/logs/

Files:
  - step_01_log.txt
  - step_02_log.txt
  - ...
  - step_13_log.txt
  - process_summary.txt

Each log contains:
  - Start time
  - End time
  - Duration
  - Status (success/failure)
  - Errors (if any)
  - Key metrics
```

---

## Enhancement Progression Example

### Comparing outputs across steps:

**Step 2 → Step 3 (What got added):**
```diff
Step 2 Output:
  [{"start": 0.5, "end": 5.2, "text": "Hello everyone", "confidence": 0.98}]

Step 3 Output:
  [{"start": 0.5, "end": 5.2, "text": "Hello everyone", "confidence": 0.98,
    "speaker_id": "speaker_001",  # ← ADDED
    "speaker_name": null           # ← ADDED
  }]
```

**Step 3 → Step 4 (What got added):**
```diff
Step 3 Output:
  [{"speaker_id": "speaker_001", "speaker_name": null}]

Step 4 Output:
  [{"speaker_id": "speaker_001", "speaker_name": "John",    # ← ENHANCED
    "corrected_from": ["Speaker 1"]                           # ← ADDED
  }]
```

**Step 4 → Step 6 (What got added via optional Step 5):**
```diff
Step 4 Output:
  [{"speaker_name": "John", "text": "Hello everyone"}]

Step 6 Output:
  [{"speaker_name": "John", "text": "Hello everyone",
    "dominant_emotion": "joy",              # ← ADDED
    "intensity": 0.85,                      # ← ADDED
    "emotions": {...}                       # ← ADDED
  }]
```

**Step 7 → Step 8 (Transformation):**
```
Step 7 Output (Clip timings):
[
  {"start": 0.5, "end": 5.2},
  {"start": 25.1, "end": 34.5}
]

Step 8 Output (Narration):
"John walks into the studio with enthusiasm. He greets everyone
warmly, setting the tone. Then he dives into AI discussion..."
```

---

## MinIO Access Patterns

### View all steps for a job:
```bash
aws s3 ls s3://videorecap/jobs/{job_id}/ --recursive
```

### View specific step:
```bash
aws s3 ls s3://videorecap/jobs/{job_id}/step_02_transcription/
```

### Download specific output:
```bash
aws s3 cp s3://videorecap/jobs/{job_id}/step_04_transcript_merge/transcript_enhanced.json .
```

### Compare two steps:
```bash
aws s3 cp s3://videorecap/jobs/{job_id}/step_03_diarization/transcript_with_speakers.json step3.json
aws s3 cp s3://videorecap/jobs/{job_id}/step_04_transcript_merge/transcript_enhanced.json step4.json
diff step3.json step4.json
```

---

## Benefits of Step-by-Step Storage

✅ **Debugging**: Identify exactly which step introduced an issue  
✅ **Quality Control**: Validate outputs at each checkpoint  
✅ **Reprocessing**: Re-run Step 8 without re-doing Steps 1-7  
✅ **Learning**: See how prompts shape narration  
✅ **Testing**: A/B test different prompts on same transcript  
✅ **Transparency**: Show users how their video was processed  
✅ **Audit Trail**: Complete history of all transformations  
✅ **Performance**: Cache intermediate outputs, skip unchanged steps  

---

## Storage Recommendations

### Keep All Steps For:
- First 30 days
- Jobs with quality issues
- Customer inquiries

### Archive After 30 Days:
- Keep only Step 13 (final output)
- Archive steps 1-12 to glacier storage
- Keep metadata/logs for auditing

### Cleanup Policy:
- Delete intermediate files older than 90 days
- Keep final videos indefinitely (or per customer agreement)
- Keep logs for 1 year for audit

