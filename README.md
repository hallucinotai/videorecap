# Video Recap Agent

Full-stack SaaS for AI-driven video transcription, speaker enrichment, scene understanding, and recap generation with voiceover narration.

## Features

- **Speaker diarization** — AssemblyAI transcription with speakers (L0)
- **Enrichment pipeline** — L1 normalize → L2 identity / characters → LP attribution → L3 gender → L4 finalize (with optional HITL review)
- **Continuous person tracking** — L2.S1 YOLO + ByteTrack + ArcFace (falls back to sparse observation if deps missing)
- **Scene / event understanding** — optional GPT-4o vision describe before recap; injects into clip selection and narration
- **AI recaps** — clip selection + narration + OpenAI TTS + final muxed MP4
- **Web UI** — Next.js upload, jobs, billing, settings
- **Async jobs** — FastAPI + Celery + Redis + MinIO/S3

> **Note:** Root `run_recap_workflow.py` is a legacy local Whisper→recap CLI (no enrichment). Prefer the Docker product path or `scripts/enrichment/` for the full stack.

---

## Quick start (Docker — recommended)

### Prerequisites

- Docker Desktop (or Docker Engine + Compose)
- FFmpeg on the host is optional for local scripts; workers use container tooling

### 1. Configure environment

```bash
cp .env.example .env
# Set at least:
#   OPENAI_API_KEY=...
#   ASSEMBLYAI_API_KEY=...
#   ENABLE_ASSEMBLYAI_DIARIZATION=true
```

Useful local flags (see `.env.example` for full list):

```bash
DEBUG=true
KEEP_PIPELINE_WORKING_DIR=true
ENABLE_SCENE_UNDERSTANDING=true
L2_CHARACTER_TRACKING=continuous
MIN_TARGET_DURATION_SECONDS=10
MAX_TARGET_DURATION_SECONDS=300   # 5 minutes (configurable)
```

### 2. Start the stack

```bash
make dev
# or: docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

| Service   | URL |
|-----------|-----|
| Frontend  | http://localhost:3000 |
| API       | http://localhost:8000 |
| MinIO     | http://localhost:9000 |

```bash
make migrate          # apply DB migrations
make logs-worker      # follow Celery worker
make logs-backend     # follow API
```

### 3. Upload a video

1. Open http://localhost:3000 and sign up / log in
2. Go to **Upload**, set **Target Duration** (range comes from `/api/v1/meta`)
3. Start processing and watch the job page

If enrichment pauses for gender review, confirm suggestions in the UI and continue.

---

## Product pipeline

```
Upload → S3/MinIO
    ↓
Celery RecapPipeline
    ↓
[0] Download
[1] Transcribe (AssemblyAI) + enrichment L1→L4 / LP
      ↳ optional HITL enrichment review
[2] Translate (optional)
[3] Scene understanding (optional) → inject narration_context.scene_*
    → Clip selection + narration (uses transcript + scene + cast/gender)
[4] TTS
[5] Extract / merge clips
[6] Remove original audio
[7] Merge narration → final MP4
    ↓
results/{job_id}/recap_video_with_narration.mp4
```

Scene understanding feeds **both** clip selection and the final narration prompt via `narration_context.scene_summary` (and timed segments for clips). It does not rewrite speaker diarization from on-screen faces.

**Skipped by design:** auto-correcting “who spoke” from video / lip sync — on-screen presence is not the same as who spoke, and that collapses diarization. L2 stays observe-only; LP may propose attribution for review.

Details: [docs/RECAP_PIPELINE_WORKFLOW.md](docs/RECAP_PIPELINE_WORKFLOW.md)

---

## Local enrichment CLIs

Same enrichers as the product (`modules/enrichment/`), for debugging without the UI:

```bash
# L0 transcription
python scripts/enrichment/run_l0_transcribe.py --video assets/input_video.mp4

# L1 → L4 (+ LP) chain
python scripts/enrichment/run_enrichment_chain.py --video assets/input_video.mp4

# Scene understanding (optional inject into L4 for local recap tests)
python scripts/enrichment/run_scene_understanding.py \
  --run-name input_video \
  --video assets/input_video.mp4 \
  --inject-into output/transcriptions/input_video/layers/enrichment_L4.json
```

Outputs land under `output/transcriptions/<run-name>/` (e.g. `layers/enrichment_L4.json`, `layers/scene_understanding.json`).

---

## Configuration highlights

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | GPT, TTS, scene vision |
| `ASSEMBLYAI_API_KEY` / `ENABLE_ASSEMBLYAI_DIARIZATION` | Speaker diarization |
| `ENABLE_SCENE_UNDERSTANDING` | Pre-recap GPT-4o scene describe |
| `SCENE_BOUNDARY_MODE` | `fixed` (time batches) or `pyscenedetect` (shot detect + merge) |
| `SCENE_SAMPLE_FPS` / `SCENE_BATCH_FRAMES` / `SCENE_MAX_DURATION` | Scene sampling |
| `SCENE_DETECT_THRESHOLD` / `SCENE_MIN_DURATION_SEC` / `SCENE_MAX_DURATION_SEC` | PySceneDetect merge knobs |
| `L2_CHARACTER_TRACKING` | `continuous` (YOLO/ByteTrack) or `sparse` |
| `MIN_TARGET_DURATION_SECONDS` / `MAX_TARGET_DURATION_SECONDS` | Upload form + API validation (exposed on `GET /api/v1/meta`) |
| `DEBUG` / `KEEP_PIPELINE_WORKING_DIR` | Intermediate downloads + keep worker temp dirs |

Full template: [.env.example](.env.example) · Full reference: [backend/ENV_VARIABLES.md](backend/ENV_VARIABLES.md)

---

## Project structure

```
├── backend/                 # FastAPI + Celery workers
├── frontend/                # Next.js UI
├── modules/                 # Shared processing + enrichment
│   ├── enrichment/          # L0–L4, LP
│   ├── scene_understanding.py
│   ├── video_processing.py  # Recap clip + narration
│   └── ...
├── scripts/enrichment/      # Local enrichment runners
├── scripts/                 # Lab / prototype CLIs (tracking, VLMs, etc.)
├── docker-compose*.yml
├── Makefile
└── output/                  # Local CLI / enrichment artifacts
```

---

## Documentation

| Doc | Topic |
|-----|--------|
| [Architecture.md](Architecture.md) | Systems, workflow diagram, models (LLM/VLM/STT/TTS), OSS vs SaaS credits |
| [SETUP.md](SETUP.md) | Detailed setup |
| [backend/ENV_VARIABLES.md](backend/ENV_VARIABLES.md) | Full environment variable reference |
| [.env.example](.env.example) | Local / Docker env template |
| [QUICK_REFERENCE.md](QUICK_REFERENCE.md) | CLI cheat sheet |
| [docs/RECAP_PIPELINE_WORKFLOW.md](docs/RECAP_PIPELINE_WORKFLOW.md) | Upload → recap product flow |
| [TECH_STACK.md](TECH_STACK.md) | Stack and diagrams |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Deploy procedures |
| [OUTPUT_PATHS.md](OUTPUT_PATHS.md) | Output locations |
| [CODEBASE_Q&A.md](CODEBASE_Q&A.md) | Pipeline Q&A |
| [CLAUDE.md](CLAUDE.md) | Agent-oriented project notes |
| [Cursor.md](Cursor.md) | Cursor / skills setup |
| [resume/README.md](resume/README.md) | Legacy Whisper CLI resume helpers |

---

## Makefile / Docker commands

```bash
make dev              # start dev stack
make down             # stop
make migrate          # alembic upgrade
make logs-worker      # worker logs
make logs-backend     # API logs
make test             # backend pytest in container
```

---

## Debugging jobs

With `DEBUG=true`, job responses include intermediate download URLs (transcription, enrichment layers, recap data, TTS, etc.).

```bash
curl -s http://localhost:8000/api/v1/jobs/{job_id} | jq '.intermediate_keys_detailed'
make logs-worker
```

---

## Agent skills

Project skills live in [`.agents/skills/`](.agents/skills/):

- [docs-router](.agents/skills/docs-router/SKILL.md) — keep README as the doc root
- [fallow](.agents/skills/fallow/SKILL.md) — JS/TS code health
- [frontend-design](.agents/skills/frontend-design/SKILL.md) — UI design guidance

---

## Troubleshooting

**Docker not running** — start Docker Desktop, then `make dev`.

**Migration `DuplicateColumnError`** — schema may already match a later revision; stamp carefully (e.g. `alembic stamp 008`) only if the column already exists.

**L2 continuous tracking falls back to sparse** — worker image may lack `ultralytics` / `insightface`; install in the worker image or set `L2_CHARACTER_TRACKING=sparse`.

**OpenAI / AssemblyAI errors** — confirm keys in `.env` and recreate backend/worker so they reload env:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --force-recreate backend worker
```

**Legacy Whisper CLI** — `python run_recap_workflow.py video.mp4` still works for a simple local smoke test but does **not** run enrichment or scene understanding.

---

## License

Part of the Hallucinot / Autogen project family.
