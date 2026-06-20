# VideoRecap Workflow with MinIO Storage

## Complete Pipeline with Step-by-Step Storage

### Step 1: Audio Extraction

| Step | Process | Model/Tool | Input | Output | Duration | Optional |
|------|---------|-----------|-------|--------|----------|----------|
| 1 | Audio Extraction | FFmpeg | `video.mp4` | `audio.wav` | ~30s | No |

**MinIO Storage Path:**
```
s3://videorecap/jobs/{job_id}/step_01_audio_extraction/
├── audio.wav (44.1kHz, stereo, 26.5 MB)
└── metadata.json
    {
      "duration": 300.5,
      "sample_rate": 44100,
      "channels": 2,
      "size_mb": 26.5
    }
```

---

### Step 2: Speech Recognition (Transcription)

| Step | Process | Model/Tool | Input | Output | Duration | Optional |
|------|---------|-----------|-------|--------|----------|----------|
| 2 | Speech Recognition | Whisper (OpenAI) | `audio.wav` | `transcript.json` (segments) | ~2-3 min | No |

**MinIO Storage Path:**
```
s3://videorecap/jobs/{job_id}/step_02_transcription/
├── transcript_raw.json (50-500 KB)
│   [
│     {
│       "start": 0.5,
│       "end": 5.2,
│       "text": "Hello everyone, welcome to the show",
│       "confidence": 0.98
│     },
│     {
│       "start": 5.2,
│       "end": 12.8,
│       "text": "Today we're discussing artificial intelligence",
│       "confidence": 0.95
│     }
│   ]
│
└── metadata.json
    {
      "model": "whisper-medium",
      "duration": 300.5,
      "total_segments": 127,
      "average_confidence": 0.96,
      "language": "en"
    }
```

**Enhancement from Step 1:**
- ❌ Audio removed from storage (not needed anymore)
- ✅ Transcript extracted with timestamps & confidence scores

---

### Step 3: Speaker Diarization

| Step | Process | Model/Tool | Input | Output | Duration | Optional |
|------|---------|-----------|-------|--------|----------|----------|
| 3 | Speaker Diarization | AssemblyAI | `audio.wav` | Speaker labels, names, corrections | ~1-2 min | No |

**MinIO Storage Path:**
```
s3://videorecap/jobs/{job_id}/step_03_diarization/
├── transcript_with_speakers.json (55-520 KB) [STEP 2 OUTPUT + NEW FIELDS]
│   [
│     {
│       "start": 0.5,
│       "end": 5.2,
│       "text": "Hello everyone, welcome to the show",
│       "confidence": 0.98,
│       "speaker_id": "speaker_001",  ← NEW
│       "speaker_name": null           ← NEW
│     }
│   ]
│
└── speaker_labels.json
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

**Enhancement from Step 2:**
- ✅ Added `speaker_id` to each segment
- ✅ Added `speaker_name` placeholder (null until corrected)
- ✅ Created speaker mapping with metadata

---

### Step 4: Merge Transcript & Diarization

| Step | Process | Model/Tool | Input | Output | Duration | Optional |
|------|---------|-----------|-------|--------|----------|----------|
| 4 | Merge Transcript & Diarization | Code | `transcript.json` + speaker labels | Enhanced transcript with `speaker_name` | <1s | No |

**MinIO Storage Path:**
```
s3://videorecap/jobs/{job_id}/step_04_transcript_merge/
├── transcript_enhanced.json (55-520 KB) [STEP 3 OUTPUT + CORRECTIONS]
│   [
│     {
│       "start": 0.5,
│       "end": 5.2,
│       "text": "Hello everyone, welcome to the show",
│       "confidence": 0.98,
│       "speaker_id": "speaker_001",
│       "speaker_name": "John",                     ← ENHANCED (was null)
│       "corrected_from": ["Speaker 1"]             ← NEW
│     }
│   ]
│
└── merge_report.json
    {
      "names_assigned": ["John", "Sarah"],
      "corrections_applied": 2,
      "ambiguous_speakers": 0,
      "quality_score": 0.98
    }
```

**Enhancement from Step 3:**
- ✅ Assigned actual speaker names (John, Sarah, etc.)
- ✅ Added `corrected_from` tracking (what it was called before)
- ✅ Quality scoring on name assignments

---

### Step 5: Emotion Analysis [OPTIONAL]

| Step | Process | Model/Tool | Input | Output | Duration | Optional |
|------|---------|-----------|-------|--------|----------|----------|
| 5 | Emotion Analysis | Wav2Vec + Classifier | Audio segments | `emotions.json` (intensity, emotion type) | ~3-5 min | **YES** |

**MinIO Storage Path:**
```
s3://videorecap/jobs/{job_id}/step_05_emotion_analysis/
├── emotions_raw.json (100-800 KB) [NEW DATA STREAM]
│   [
│     {
│       "start": 0.5,
│       "end": 5.2,
│       "dominant_emotion": "joy",
│       "intensity": 0.85,
│       "emotions": {
│         "joy": 0.85,
│         "surprise": 0.10,
│         "neutral": 0.05
│       }
│     }
│   ]
│
└── emotions_confidence.json
    {
      "model": "wav2vec-emotion",
      "total_segments_analyzed": 127,
      "average_confidence": 0.82,
      "emotion_distribution": {
        "joy": 0.35,
        "neutral": 0.30,
        "interest": 0.20,
        "anger": 0.10,
        "sadness": 0.05
      }
    }
```

**Enhancement from Step 4:**
- ✅ NEW DATA: Emotional intensity per segment
- ✅ Emotion breakdown (% of each emotion)
- ✅ Confidence scores for emotion detection
- ⚠️ Step 4 unchanged (parallel processing)

---

### Step 6: Merge Emotions with Transcript [OPTIONAL]

| Step | Process | Model/Tool | Input | Output | Duration | Optional |
|------|---------|-----------|-------|--------|----------|----------|
| 6 | Merge Emotions with Transcript | Code | `transcript.json` + `emotions.json` | Transcript with emotion metadata | <1s | **YES** |

**MinIO Storage Path:**
```
s3://videorecap/jobs/{job_id}/step_06_emotion_merge/
├── transcript_with_emotions.json (155-1320 KB) [STEP 4 + STEP 5]
│   [
│     {
│       "start": 0.5,
│       "end": 5.2,
│       "text": "Hello everyone, welcome to the show",
│       "speaker_name": "John",
│       "corrected_from": ["Speaker 1"],
│       "dominant_emotion": "joy",              ← ADDED
│       "intensity": 0.85,                      ← ADDED
│       "emotions": {                           ← ADDED
│         "joy": 0.85,
│         "surprise": 0.10,
│         "neutral": 0.05
│       }
│     }
│   ]
│
└── emotion_merge_report.json
    {
      "segments_enriched": 127,
      "high_emotion_segments": 34,
      "emotional_arc": [
        {"segment": 0, "emotion": "joy"},
        {"segment": 10, "emotion": "neutral"},
        {"segment": 30, "emotion": "surprise"}
      ]
    }
```

**Enhancement from Step 4 (with Step 5 data):**
- ✅ Added emotion data to each transcript segment
- ✅ Now have full context: what was said + who said it + how they felt
- ✅ Ready for emotion-aware clip selection

---

### Step 7: Clip Selection (LLM Call 1)

| Step | Process | Model/Tool | Input | Output | Duration | Optional |
|------|---------|-----------|-------|--------|----------|----------|
| 7 | Clip Selection (LLM Call 1) | GPT-4o | Transcript + Emotions (opt) + target_duration | `clip_timings` (list of {start, end}) | ~10-15s | No |

**MinIO Storage Path:**
```
s3://videorecap/jobs/{job_id}/step_07_clip_selection/
├── clip_timings.json (1-5 KB) [NEW: SELECTION DECISIONS]
│   {
│     "clips": [
│       {
│         "start": 0.5,
│         "end": 5.2,
│         "reason": "Strong opening, high emotion (joy: 0.85)"
│       },
│       {
│         "start": 25.1,
│         "end": 34.5,
│         "reason": "Key revelation, plot turning point"
│       },
│       {
│         "start": 120.3,
│         "end": 135.8,
│         "reason": "Emotional climax, high engagement (surprise: 0.78)"
│       }
│     ],
│     "total_duration": 28.9,
│     "target_duration": 30
│   }
│
├── clip_reasoning.json
│   {
│     "model": "gpt-4o",
│     "prompt_version": "v4",
│     "emotion_weighted": true,
│     "selection_method": "video-editor-mindset"
│   }
│
└── clip_selection_raw.json
    {
      Full LLM response with all reasoning, alternatives, scores
    }
```

**Enhancement from Step 6:**
- ✅ NEW: Clip timings selected (which parts of video to use)
- ✅ Reasoning for each clip (why it was selected)
- ✅ Full LLM response for debugging/transparency
- ⚠️ Transcript unchanged (used as input)

---

### Step 8: Narration Generation (LLM Call 2)

| Step | Process | Model/Tool | Input | Output | Duration | Optional |
|------|---------|-----------|-------|--------|----------|----------|
| 8 | Narration Generation (LLM Call 2) | GPT-4o | Selected clips + Full transcript + Emotion guidance (opt) + Language | `recap_text` (narration script) | ~10-15s | No |

**MinIO Storage Path:**
```
s3://videorecap/jobs/{job_id}/step_08_narration_generation/
├── recap_text.txt (2-5 KB) [NEW: NARRATION SCRIPT]
│   John walks into the studio with palpable excitement. He greets
│   everyone enthusiastically, setting a warm tone for what's to come.
│   Then he dives into the topic of artificial intelligence — a subject
│   that clearly fascinates him. Sarah joins in, adding technical depth...
│
├── narration_full.json
│   {
│     "word_count": 218,
│     "target_word_count": 220,
│     "language": "English",
│     "character_count": 1245,
│     "estimated_duration_seconds": 28.5,
│     "prompt_version": "v4",
│     "model": "gpt-4o"
│   }
│
└── narration_raw.json
    {
      Full LLM response, including alternative phrasings, reasoning, feedback
    }
```

**Enhancement from Step 7:**
- ✅ NEW: Narration script written
- ✅ Ready to be converted to audio in Step 12
- ✅ Factually grounded (from Step 6 transcript + Step 7 clips)
- ⚠️ Clip timings unchanged (used as input)

---

### Step 9: Assemble Recap Data

| Step | Process | Model/Tool | Input | Output | Duration | Optional |
|------|---------|-----------|-------|--------|----------|----------|
| 9 | Assemble Recap Data | Code | All outputs from steps 7-8 | `recap_data.json` (unified structure) | <1s | No |

**MinIO Storage Path:**
```
s3://videorecap/jobs/{job_id}/step_09_recap_assembly/
└── recap_data.json (10-20 KB) [UNIFIED STRUCTURE - STEPS 4/6 + 7 + 8]
    {
      "job_id": "{job_id}",
      "recap_text": "John walks into the studio...",
      "clip_timings": [
        {"start": 0.5, "end": 5.2},
        {"start": 25.1, "end": 34.5},
        {"start": 120.3, "end": 135.8}
      ],
      "total_duration": 28.9,
      "target_duration": 30,
      "emotions_used": true,
      "clip_emotions": [
        {
          "start": 0.5,
          "end": 5.2,
          "dominant_emotion": "joy",
          "intensity": 0.85
        }
      ],
      "metadata": {
        "transcript_segments": 127,
        "speakers": ["John", "Sarah"],
        "language": "English",
        "processing_steps_completed": [1, 2, 3, 4, 5, 6, 7, 8, 9],
        "timestamps": {
          "step_01": "2026-06-02T10:30:15Z",
          "step_02": "2026-06-02T10:33:45Z",
          ...
        }
      }
    }
```

**Enhancement from Step 8:**
- ✅ UNIFIED: Single file with all outputs
- ✅ Ready for downstream steps (video extraction, TTS)
- ✅ Complete audit trail of processing
- ⚠️ No new data, just organized

---

### Step 10: Extract Video Clips

| Step | Process | Model/Tool | Input | Output | Duration | Optional |
|------|---------|-----------|-------|--------|----------|----------|
| 10 | Extract Video Clips | MoviePy | `video.mp4` + `clip_timings` | Multiple video segments (one per clip) | ~30-45s | No |

**MinIO Storage Path:**
```
s3://videorecap/jobs/{job_id}/step_10_video_extraction/
├── clip_segments/
│   ├── clip_001.mp4 (start: 0.5, end: 5.2, duration: 4.7s, 3.2 MB)
│   ├── clip_002.mp4 (start: 25.1, end: 34.5, duration: 9.4s, 6.8 MB)
│   ├── clip_003.mp4 (start: 120.3, end: 135.8, duration: 15.5s, 11.2 MB)
│   └── ... (one per clip)
│
└── extraction_report.json
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
        }
      ]
    }
```

**Enhancement from Step 9:**
- ✅ NEW: Individual video segments extracted (physical video files)
- ✅ Each clip is a standalone MP4 file
- ✅ Original audio preserved (will be replaced in Step 13)
- ⚠️ recap_data.json unchanged (used as input)

---

### Step 11: Merge Video Clips

| Step | Process | Model/Tool | Input | Output | Duration | Optional |
|------|---------|-----------|-------|--------|----------|----------|
| 11 | Merge Video Clips | MoviePy | Video segments (in order) | `recap_video.mp4` (no narration audio) | ~10-20s | No |

**MinIO Storage Path:**
```
s3://videorecap/jobs/{job_id}/step_11_video_merge/
├── recap_video.mp4 (28.9s, 1920x1080, 12 MB)
│   └── Contains: All clips concatenated in order
│   └── Audio: Original (preserved for reference)
│   └── Transitions: Direct cut
│
└── merge_report.json
    {
      "total_duration": 28.9,
      "clips_merged": 3,
      "resolution": "1920x1080",
      "frame_rate": 30,
      "audio_preserved": true,
      "transitions": "direct_cut",
      "quality_check": "passed",
      "file_size_mb": 12
    }
```

**Enhancement from Step 10:**
- ✅ NEW: Merged video (all clips combined into single file)
- ✅ Seamless transitions between clips
- ✅ Ready for audio overlay in Step 13
- ⚠️ Individual clip files still in storage (can delete after merge)

---

### Step 12: Text-to-Speech

| Step | Process | Model/Tool | Input | Output | Duration | Optional |
|------|---------|-----------|-------|--------|----------|----------|
| 12 | Text-to-Speech | OpenAI TTS / ElevenLabs / Google TTS | `recap_text` + language + voice settings | `narration.mp3` (audio file) | ~5-10s | No |

**MinIO Storage Path:**
```
s3://videorecap/jobs/{job_id}/step_12_tts_generation/
├── narration.mp3 (28.5s, 128 kbps, 445 KB)
│   └── Content: "John walks into the studio..."
│   └── Voice: "nova"
│   └── Language: "en"
│   └── Speed: 1.0x
│
└── tts_metadata.json
    {
      "service": "openai",
      "voice": "nova",
      "speed": 1.0,
      "language": "English",
      "duration": 28.5,
      "word_count": 218,
      "file_size_kb": 445,
      "model": "tts-1-hd",
      "timestamp": "2026-06-02T10:36:50Z"
    }
```

**Enhancement from Step 8:**
- ✅ NEW: Audio narration generated (MP3 file)
- ✅ Natural-sounding voice (voice selected from options)
- ✅ Synchronized to recap_text
- ⚠️ Still needs to be mixed with video (Step 13)

---

### Step 13: Audio Mixing (FINAL)

| Step | Process | Model/Tool | Input | Output | Duration | Optional |
|------|---------|-----------|-------|--------|----------|----------|
| 13 | Audio Mixing | FFmpeg / MoviePy | `recap_video.mp4` + `narration.mp3` + optional original audio | `final_recap_video.mp4` (video + narration) | ~10-20s | No |

**MinIO Storage Path:**
```
s3://videorecap/jobs/{job_id}/step_13_audio_mixing/
├── final_recap_video.mp4 (28.9s, 1920x1080, 15 MB) [FINAL OUTPUT ✅]
│   └── Video Track: From Step 11 (recap_video.mp4)
│   └── Audio Track 1: Narration (100% volume) - From Step 12
│   └── Audio Track 2: Original audio (25% volume, ducked) - Optional
│   └── Duration: 28.9 seconds
│   └── Codec: H.264 + AAC
│
└── audio_mix_report.json
    {
      "narration_volume": 100,
      "original_audio_volume": 25,
      "final_duration": 28.9,
      "quality_check": "passed",
      "sync_verified": true,
      "file_size_mb": 15,
      "codec_video": "h264",
      "codec_audio": "aac",
      "timestamp": "2026-06-02T10:37:05Z"
    }
```

**Enhancement from Step 12:**
- ✅ FINAL: Complete video with narration + original audio mix
- ✅ Narration at 100%, original audio ducked to 25%
- ✅ Ready for delivery to user
- ✅ All intermediate files archived

---

## Storage Summary Table

| Step | Files Created | Total Size | Cumulative Size |
|------|---------------|-----------|-----------------|
| 1 | `audio.wav` | 26.5 MB | 26.5 MB |
| 2 | `transcript_raw.json` | 0.25 MB | 26.75 MB |
| 3 | `transcript_with_speakers.json` + `speaker_labels.json` | 0.3 MB | 27.05 MB |
| 4 | `transcript_enhanced.json` + `merge_report.json` | 0.3 MB | 27.35 MB |
| 5 | `emotions_raw.json` + `emotions_confidence.json` | 0.5 MB | 27.85 MB |
| 6 | `transcript_with_emotions.json` + `emotion_merge_report.json` | 0.5 MB | 28.35 MB |
| 7 | `clip_timings.json` + `clip_reasoning.json` + `clip_selection_raw.json` | 0.05 MB | 28.4 MB |
| 8 | `recap_text.txt` + `narration_full.json` + `narration_raw.json` | 0.05 MB | 28.45 MB |
| 9 | `recap_data.json` | 0.015 MB | 28.465 MB |
| 10 | `clip_segments/*.mp4` (3 clips) | 21.2 MB | 49.665 MB |
| 11 | `recap_video.mp4` | 12 MB | 61.665 MB |
| 12 | `narration.mp3` | 0.445 MB | 62.11 MB |
| 13 | `final_recap_video.mp4` | 15 MB | 77.11 MB |

---

## Cleanup Recommendations

### Keep for 30 Days:
- All steps 1-13 (full audit trail)

### Archive to Glacier After 30 Days:
- Steps 1-12 (intermediate files)
- Keep logs and metadata

### Keep Indefinitely:
- Step 13: `final_recap_video.mp4`
- Step 9: `recap_data.json` (metadata)
- All logs and reports

### Estimated Monthly Storage:
- 100 jobs × 77 MB = 7.7 GB (full pipeline)
- 100 jobs × 15 MB = 1.5 GB (final videos only, after cleanup)

