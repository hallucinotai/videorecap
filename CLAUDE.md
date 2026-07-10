# Claude.md - Video Recap Agent

Project documentation for AI-powered video processing SaaS platform.

## 🎯 Project Overview

**Video Recap Agent** - Full-stack SaaS for AI-driven video transcription, analysis, and recap generation with voiceover narration.

### Key Features
- Video transcription (OpenAI Whisper - local, free)
- Multi-language translation (GPT-4)
- AI-generated recaps and key moment extraction
- Text-to-speech narration (OpenAI TTS)
- Web UI for uploading and managing videos
- Async job processing with Celery

## 🏗️ Tech Stack

### Backend
- **Framework**: FastAPI 0.115.6 + Uvicorn
- **Database**: PostgreSQL + SQLAlchemy ORM + Alembic
- **Task Queue**: Celery + Redis
- **Auth**: JWT + Google OAuth + bcrypt
- **AI/Processing**: OpenAI (GPT-4, Whisper, TTS), moviepy, pydub
- **Storage**: AWS S3 (boto3)
- **Payment**: Stripe
- **Email**: Resend (transactional emails)

### Frontend
- **Framework**: Next.js 14.2 + React 18.3
- **Styling**: Tailwind CSS + Radix UI
- **Auth**: Google OAuth (@react-oauth/google)
- **State**: React hooks + axios for API calls

### Infrastructure
- Docker (dev/prod/staging)
- Nginx reverse proxy
- Docker Compose orchestration
- Branch-based CI/CD deployments

## 📂 Project Structure

```
/
├── backend/                    # FastAPI application
│   ├── app/
│   │   ├── api/               # REST endpoints
│   │   ├── core/              # Auth, security, config
│   │   ├── models/            # SQLAlchemy models
│   │   ├── schemas/           # Pydantic request/response schemas
│   │   ├── services/          # Business logic
│   │   ├── processing/        # Video/audio processing
│   │   └── workers/           # Celery tasks
│   ├── alembic/               # Database migrations
│   ├── tests/                 # Test suite
│   ├── requirements.txt
│   ├── Dockerfile
│   └── Dockerfile.worker      # Celery worker container
│
├── frontend/                  # Next.js application
│   ├── src/
│   │   ├── app/
│   │   │   ├── (auth)/        # Login/signup routes
│   │   │   └── (dashboard)/   # Protected dashboard
│   │   ├── components/
│   │   │   ├── auth/
│   │   │   ├── layout/
│   │   │   ├── jobs/
│   │   │   └── upload/
│   │   ├── hooks/             # Custom React hooks
│   │   └── lib/               # Utilities
│   ├── package.json
│   ├── next.config.js
│   └── tailwind.config.ts
│
├── Python Scripts (Root)
│   ├── run_recap_workflow.py  # Main CLI (runs full workflow)
│   ├── resume_workflow.py     # Resume from checkpoints
│   ├── test_modular_workflow.py
│   ├── verify_paths.py
│   ├── modules/               # Modular processing pipeline
│   ├── scripts/               # Individual CLI tools
│   └── resume/                # Checkpoint-based resumption
│
├── Docker Compose
│   ├── docker-compose.yml     # Development
│   ├── docker-compose.dev.yml
│   ├── docker-compose.prod.yml
│   └── docker-compose.staging.yml
│
├── Configuration & Docs
│   ├── .env                   # Local environment (not in git)
│   ├── .env.example
│   ├── .env.staging.example
│   ├── .gitignore
│   ├── Makefile
│   ├── README.md
│   ├── SETUP.md
│   ├── QUICK_REFERENCE.md
│   ├── OUTPUT_PATHS.md
│   ├── DEPLOYMENT.md
│   └── IMPLEMENTATION_PLAN.md
```

## 🚀 Getting Started

### Prerequisites
```bash
# Check what's installed
python3 --version          # Python 3.7+
ffmpeg -version            # FFmpeg (video/audio processing)
docker --version           # Docker (for containerized deployment)
```

### Local Development

1. **Set up environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your OpenAI API key
   ```

2. **Backend**:
   ```bash
   cd backend
   pip install -r requirements.txt
   python -m uvicorn app.main:app --reload
   ```

3. **Frontend**:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

4. **Full Stack with Docker**:
   ```bash
   docker-compose up -d
   ```

### Test the Python Workflows

```bash
# Full workflow (transcription → recap → clips → TTS → merge)
python run_recap_workflow.py /path/to/video.mp4

# Resume from checkpoint (saves API costs)
python resume_workflow.py /path/to/video.mp4

# Individual steps
python scripts/01_transcribe.py /path/to/video.mp4
python scripts/03_generate_recap.py output/transcriptions/transcription.txt
```

## 🌿 Git Workflow

### Branches
- **main** - Production code, stable
- **staging** - CI/CD staging environment
- **audio-emotions** - Active development (emotion detection features)

### Deployments
- **main** → Production
- **staging** → Staging environment (separate Docker, Nginx, CI/CD)
- **Feature branches** → Deploy to staging for testing

## 🔧 Important Commands

### Backend
```bash
# Database migrations
cd backend
alembic upgrade head      # Apply migrations
alembic revision -m "message"  # Create new migration

# Celery tasks
celery -A app.workers.tasks inspect active   # View active tasks
celery -A app.workers.tasks purge            # Clear queue
```

### Frontend
```bash
npm run dev       # Development server (localhost:3000)
npm run build     # Production build
npm run lint      # ESLint check
```

### Python Workflows
```bash
# Test setup
python verify_paths.py
python test_modular_workflow.py

# Help
python run_recap_workflow.py --help
python resume_workflow.py --help
```

### Docker
```bash
docker-compose up -d              # Start all services
docker-compose logs -f backend    # View backend logs
docker-compose logs -f celery     # View Celery worker logs
docker ps                         # List running containers
```

## 📝 Key Files to Know

### Configuration
- `.env` - Environment variables (OpenAI API key, etc.)
- `backend/app/config.py` - FastAPI configuration
- `backend/app/core/security.py` - Auth/JWT logic
- `frontend/next.config.js` - Next.js build config

### Database
- `backend/alembic/versions/` - Migration scripts
- `backend/app/models/` - SQLAlchemy models (User, Job, Video, etc.)

### API Routes
- `backend/app/api/` - REST endpoints
  - `auth/` - Login, signup, OAuth
  - `videos/` - Video upload, listing
  - `jobs/` - Job status tracking
  - `health/` - Health checks

### Processing Logic
- `backend/app/services/` - Business logic
  - `video_service.py` - Video management
  - `job_service.py` - Job orchestration
- `backend/app/workers/` - Celery async tasks
  - `video_tasks.py` - Transcription, TTS, merging
  - `ai_tasks.py` - OpenAI API calls

## 🔐 Environment Variables

### Required
```bash
OPENAI_API_KEY=sk-...              # OpenAI API key
DATABASE_URL=postgresql://...      # PostgreSQL connection
REDIS_URL=redis://...              # Redis connection (Celery)
```

### Optional / product enrichment
```bash
GPT_MODEL=gpt-4                    # Default: gpt-4 (options: gpt-4-turbo, gpt-4o, gpt-3.5-turbo)
ASSEMBLYAI_API_KEY=...
ENABLE_ASSEMBLYAI_DIARIZATION=true
REQUIRE_ASSEMBLYAI_KEY=false
L2_CHARACTER_TRACKING=continuous
ENABLE_SCENE_UNDERSTANDING=true
MIN_TARGET_DURATION_SECONDS=10
MAX_TARGET_DURATION_SECONDS=300
KEEP_PIPELINE_WORKING_DIR=true
AWS_ACCESS_KEY_ID=...              # AWS S3 access
AWS_SECRET_ACCESS_KEY=...
AWS_S3_BUCKET_NAME=...
STRIPE_SECRET_KEY=...              # Stripe payment processing
RESEND_API_KEY=...                 # Transactional email service
GOOGLE_CLIENT_ID=...               # Google OAuth
GOOGLE_CLIENT_SECRET=...
```

Full reference: `backend/ENV_VARIABLES.md` and `.env.example`.

## 📊 API Endpoints

### Auth
- `POST /api/auth/signup` - Create account
- `POST /api/auth/login` - Email/password login
- `POST /api/auth/google` - Google OAuth
- `POST /api/auth/verify-otp` - Verify email with OTP

### Videos
- `POST /api/videos/upload` - Upload video
- `GET /api/videos` - List user's videos
- `GET /api/videos/{id}` - Get video details
- `DELETE /api/videos/{id}` - Delete video

### Jobs
- `GET /api/jobs` - List jobs
- `GET /api/jobs/{id}` - Get job status
- `POST /api/jobs/{id}/cancel` - Cancel job

## 🧪 Testing

### Backend
```bash
cd backend
pytest tests/
```

### Frontend
```bash
cd frontend
npm run lint
```

### Python Workflows
```bash
python test_modular_workflow.py
```

## 🐛 Troubleshooting

### Common Issues

**"OpenAI API error"**
```bash
# Check API key
cat .env | grep OPENAI_API_KEY

# Test API
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"
```

**"FFmpeg not found"**
```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg
```

**"Module not found"**
```bash
# Reinstall dependencies
pip install -r requirements.txt --upgrade

# Backend
cd backend && pip install -r requirements.txt

# Frontend
cd frontend && npm install
```

**Database connection errors**
```bash
# Check PostgreSQL is running
psql -U postgres -d videorecap -c "SELECT 1"

# Check migrations are applied
cd backend && alembic upgrade head
```

**Celery worker not processing tasks**
```bash
# Check Redis
redis-cli ping

# Inspect Celery
celery -A app.workers.tasks inspect active

# Restart worker
docker-compose restart celery
```

## 📚 Documentation Files

- **README.md** - Feature overview and quick start
- **SETUP.md** - Detailed setup guide for new users
- **QUICK_REFERENCE.md** - CLI command cheatsheet
- **OUTPUT_PATHS.md** - Output file locations
- **DEPLOYMENT.md** - Deployment procedures
- **IMPLEMENTATION_PLAN.md** - Original architecture/design
- **FIX_DURATION_ISSUE.md** - Known issues and fixes

## 🔄 Development Workflow

1. **Create feature branch** from `main`
2. **Make changes** locally (backend + frontend as needed)
3. **Test locally** with Docker Compose
4. **Create PR** to `main`
5. **Deploy to staging** via `staging` branch
6. **Merge to main** after approval

## 📈 Performance Notes

- Backend memory limit: 1GB (Docker)
- Celery worker: Async task processing (never blocks API)
- FFmpeg: Local video processing (CPU-bound)
- OpenAI API: Includes retry backoff for rate limiting
- Database: PostgreSQL with connection pooling

## 🎬 Video Processing Pipeline

```
Video Input
    ↓
[Transcribe] → transcription.txt (Whisper)
    ↓
[Translate] → translated_transcription.txt (GPT-4, optional)
    ↓
[AI Recap] → recap_data.json + recap_text.txt (GPT-4)
    ↓
[Extract Clips] → recap_video.mp4 (moviepy)
    ↓
[Remove Audio] → recap_video_no_audio.mp4 (optional)
    ↓
[Generate TTS] → recap_narration.mp3 (OpenAI TTS)
    ↓
[Merge Audio] → recap_video_with_narration.mp4 ✨
```

## 🚀 Deployment

### Staging
```bash
# Push to staging branch (triggers CI/CD)
git push origin feature-branch:staging
```

### Production
```bash
# Merge to main (triggers production deployment)
git push origin feature-branch:main
```

See `DEPLOYMENT.md` for detailed procedures.

## 📞 Getting Help

1. Check relevant documentation (README, SETUP, QUICK_REFERENCE)
2. Review recent git commits for context
3. Check backend/frontend logs: `docker-compose logs -f`
4. Test individual components in isolation
5. Use `--help` on CLI scripts for options

## 📚 Reference Documents

- **CODEBASE_Q&A.md** - Comprehensive Q&A documenting pipeline mechanics, edge cases, and improvement areas (12 questions with detailed answers and implementation suggestions)
- **AUDIO_EMOTIONS_PHASE1.md** - Complete Phase 1 implementation guide for audio emotion detection using Google Cloud Speech API (setup, code structure, integration, testing, costs)

---

**Last Updated**: 2026-05-15
**Active Branch**: audio-emotions
**Repository**: hallucinotai/videorecap
