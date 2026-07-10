# Setup Guide

Complete setup instructions for new users.

## 📋 Prerequisites

### 1. Python
- Python 3.7 or higher
- Check: `python3 --version`

### 2. FFmpeg
Required for video/audio processing.

**macOS:**
```bash
brew install ffmpeg
```

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install ffmpeg
```

**Windows:**
1. Download from: https://ffmpeg.org/download.html
2. Add to PATH
3. Verify: `ffmpeg -version`

### 3. OpenAI API Key
1. Create account: https://platform.openai.com/signup
2. Get API key: https://platform.openai.com/api-keys
3. Add billing method (required for API access)

---

## 🚀 Installation Steps

### Step 1: Clone/Download Project
```bash
cd video_recap_agent
```

### Step 2: Install Python Dependencies
```bash
pip install -r requirements.txt
```

This installs:
- `openai` - GPT-4 and TTS API
- `openai-whisper` - Speech recognition
- `moviepy` - Video processing
- `python-dotenv` - Environment management
- Other supporting libraries

### Step 3: Configure Environment

```bash
# Copy example file
cp .env.example .env

# Edit with your API key
nano .env  # or use your preferred editor
```

Add your OpenAI API key:
```bash
OPENAI_API_KEY=sk-proj-...your-actual-key-here...
```

Optional: Change GPT model (default is gpt-4):
```bash
model=gpt-4-turbo  # or gpt-4o, gpt-3.5-turbo
```

### Step 4: Verify Setup
```bash
# Test paths and structure
python verify_paths.py

# Test module imports
python test_modular_workflow.py
```

---

## 🧪 Test Run

Try with a short test video:

```bash
python run_recap_workflow.py /path/to/test-video.mp4 --duration 10
```

Expected output:
```
✅ Step 1: Transcribing video...
✅ Step 2: Generating AI recap...
✅ Step 3: Extracting clips...
✅ Step 4: Generating TTS audio...
✅ Step 5: Merging audio and video...

📹 Final Output: output/videos/recap_video_with_narration.mp4
```

---

## ⚙️ Configuration Options

### `.env` File

Copy from [`.env.example`](.env.example). Full reference: [`backend/ENV_VARIABLES.md`](backend/ENV_VARIABLES.md).

**Required for product path:**
```bash
OPENAI_API_KEY=sk-proj-...
ASSEMBLYAI_API_KEY=...          # when ENABLE_ASSEMBLYAI_DIARIZATION=true
ENABLE_ASSEMBLYAI_DIARIZATION=true
```

**Common optional / local flags:**
```bash
model=gpt-4                       # GPT model hint for some CLI paths
DEBUG=true
KEEP_PIPELINE_WORKING_DIR=true

# L2 character tracking
L2_CHARACTER_TRACKING=continuous  # or sparse
L2_TRACKING_FRAME_STRIDE=5
L2_TRACKING_DEVICE=cpu

# Scene understanding (feeds clip + narration prompts)
ENABLE_SCENE_UNDERSTANDING=true
SCENE_VISION_MODEL=gpt-4o
SCENE_SAMPLE_FPS=0.5
SCENE_BATCH_FRAMES=8
# SCENE_MAX_DURATION=60           # smoke-test first N seconds

# Upload form + API duration limits (seconds)
MIN_TARGET_DURATION_SECONDS=10
MAX_TARGET_DURATION_SECONDS=300
```

After changing `.env` for Docker, recreate containers (restart alone may not reload env):
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --force-recreate backend worker
```

### Command Line Options

See `python run_recap_workflow.py --help` for all options:

```bash
--duration 30              # Recap length in seconds
--model small              # Whisper model (tiny/base/small/medium/large)
--voice nova               # TTS voice (alloy/echo/fable/onyx/nova/shimmer)
--translate English Tamil  # Translate transcript
--language en              # Source video language
--remove-original-audio    # Remove original audio before adding narration
--pad-with-black           # Pad with black frames if video is short
```

---

## 💰 API Costs

Approximate costs (as of 2024):

**Per 10-minute video:**
- Transcription (Whisper): Local, free
- AI Analysis (GPT-4): ~$0.10-0.30
- TTS Narration: ~$0.015 per 1000 characters
- **Total: ~$0.12-0.35 per video**

**Tips to reduce costs:**
- Use `gpt-3.5-turbo` instead of `gpt-4` (80% cheaper)
- Use `tts-1` instead of `tts-1-hd` (same price, but specify if needed)
- Skip translation if not needed

---

## 🛠️ Troubleshooting

### "Module not found" errors
```bash
# Reinstall dependencies
pip install -r requirements.txt --upgrade
```

### "OpenAI API error"
```bash
# Check API key is set
cat .env | grep OPENAI_API_KEY

# Test API key
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"
```

### "FFmpeg not found"
```bash
# Check FFmpeg installation
ffmpeg -version

# If not found, install:
# macOS: brew install ffmpeg
# Linux: sudo apt install ffmpeg
```

### "Out of memory" errors
```bash
# Use smaller Whisper model
python run_recap_workflow.py video.mp4 --model tiny

# Or process shorter videos first
```

### Audio/video sync issues
```bash
# Try regenerating with different duration
python run_recap_workflow.py video.mp4 --duration 15

# Or check original video format is supported
ffprobe video.mp4
```

---

## 📚 Next Steps

After successful setup:

1. **Read documentation:**
   - [README.md](README.md) - Full documentation
   - [QUICK_REFERENCE.md](QUICK_REFERENCE.md) - Command cheat sheet
   - [OUTPUT_PATHS.md](OUTPUT_PATHS.md) - File locations

2. **Try different options:**
   ```bash
   # Different duration
   python run_recap_workflow.py video.mp4 --duration 60
   
   # Different voice
   python run_recap_workflow.py video.mp4 --voice shimmer
   
   # With translation
   python run_recap_workflow.py video.mp4 --translate English Spanish
   ```

3. **Process your videos:**
   ```bash
   python run_recap_workflow.py /path/to/your/video.mp4
   ```

---

## ✅ Setup Checklist

- [ ] Python 3.7+ installed
- [ ] FFmpeg installed and in PATH
- [ ] Dependencies installed (`pip install -r requirements.txt`)
- [ ] OpenAI API key obtained
- [ ] `.env` file configured with API key
- [ ] Test run successful
- [ ] Read documentation

---

## 🆘 Getting Help

If you're stuck:

1. Check error message carefully
2. Review troubleshooting section above
3. Run `python verify_paths.py` to check setup
4. Try with a simple test video first
5. Check [OUTPUT_PATHS.md](OUTPUT_PATHS.md) for file locations

---

**Ready to start!** 🎉

```bash
python run_recap_workflow.py /path/to/your/video.mp4
```

