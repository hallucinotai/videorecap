# Environment Variables Reference

Complete documentation of all backend environment variables with possible values, descriptions, and application usage.

## Critical Dependencies Overview

| Priority | Variables | Impact | What Breaks |
|----------|-----------|--------|------------|
| **CRITICAL** | `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `S3_*`, `OPENAI_API_KEY` | App startup + core features | **Everything** - app can't start or process videos |
| **HIGH** | `JWT_SECRET`, `CORS_ORIGINS` | User auth + frontend communication | User login broken, API requests blocked |
| **MEDIUM** | `RESEND_API_KEY`, `GOOGLE_CLIENT_ID`, `STRIPE_*` | Optional auth/billing features | Email signup, social login, billing disabled (graceful) |
| **LOW** | Feature flags, `MAX_UPLOAD_SIZE_BYTES`, `DELETE_INPUT_VIDEO_ON_COMPLETE` | User experience, storage | Feature visibility, storage costs, upload limits |

**Minimum to start:** DATABASE_URL, REDIS_URL, CELERY_BROKER_URL, CELERY_RESULT_BACKEND, S3_*, OPENAI_API_KEY, JWT_SECRET

**Minimum for users to access:** Add CORS_ORIGINS matching frontend URL

## Application Configuration

| Variable | Type | Default | Used By / Features | Impact if Missing/Invalid | Description |
|----------|------|---------|-----------------|----------|-------------|
| `DEBUG` | boolean | `false` | `/debug/*` endpoints, SQL logging, pipeline verbosity | DEBUG endpoints return 404, SQL queries not logged, intermediate file metadata hidden from API, detailed error traces not exposed | Enable debug endpoints for intermediate file downloads and detailed logging |
| `APP_NAME` | string | `Video Recap Agent` | `/meta` endpoint, UI display | UI shows generic app name | Application display name |
| `APP_VERSION` | string | `dev` | `/meta` endpoint, versioning | Wrong version info returned | Application version identifier |
| `API_V1_PREFIX` | string | `/api/v1` | All API endpoints | API endpoints unreachable at wrong prefix | API base path prefix |

## Database

| Variable | Type | Default | Used By / Features | Impact if Missing/Invalid | Description |
|----------|------|---------|-----------------|----------|-------------|
| `DATABASE_URL` | string | `postgresql+asyncpg://postgres:postgres@postgres:5432/video_recap` | User auth, job tracking, subscriptions, API keys, database migrations | **App fails to start**, connection errors, no persistent storage, migrations cannot run | Full async PostgreSQL connection URL with credentials (required for all features) |

**Used in:**
- `backend/app/db/session.py` - Creates async SQLAlchemy engine
- `backend/app/workers/tasks.py` - Converted to sync URL for Celery workers
- `backend/alembic/env.py` - Database migrations

**Examples:**
- Local dev: `postgresql+asyncpg://postgres:password@localhost:5432/video_recap`
- Docker: `postgresql+asyncpg://postgres:password@postgres:5432/video_recap`
- Remote: `postgresql+asyncpg://user:pass@db.example.com:5432/video_recap`

## Redis

| Variable | Type | Default | Used By / Features | Impact if Missing/Invalid | Description |
|----------|------|---------|-----------------|----------|-------------|
| `REDIS_URL` | string | `redis://redis:6379/0` | Rate limiting, WebSocket job progress, real-time updates, Whisper cache sync | **No rate limiting** (all requests allowed), WebSocket notifications fail, health checks fail, cache not synced across workers | Redis URL for rate limiting, real-time job progress pub/sub, and cache synchronization |

**Used in:**
- `backend/app/core/rate_limiter.py` - Rate limit tracking via sorted sets
- `backend/app/api/v1/endpoints/health.py` - Health check
- `backend/app/services/notification.py` - WebSocket pub/sub for job progress
- `backend/app/processing/transcription.py` - Whisper model cache invalidation
- `backend/app/workers/tasks.py` - Progress publishing to Celery

**Examples:**
- Local: `redis://localhost:6379/0`
- Docker: `redis://redis:6379/0`
- Remote: `redis://:password@redis.example.com:6379/0`

## Celery (Job Queue)

| Variable | Type | Default | Used By / Features | Impact if Missing/Invalid | Description |
|----------|------|---------|-----------------|----------|-------------|
| `CELERY_BROKER_URL` | string | `redis://redis:6379/0` | Background task queue, video processing pipeline | **Celery cannot start**, no background job processing, video pipeline completely non-functional | Message broker URL for Celery task queue (typically Redis database 0) |
| `CELERY_RESULT_BACKEND` | string | `redis://redis:6379/1` | Task result storage and retrieval, job status tracking | **Task results lost**, jobs not tracked, job resumption not possible | Backend URL for storing task results (typically Redis database 1, separate from broker) |

**Used in:**
- `backend/app/workers/celery_app.py` - Celery app initialization
- All background video processing tasks

**Best Practice:** Use different Redis databases (0 for broker, 1 for results) to avoid data conflicts.

**Impact if both missing:** The entire video recap pipeline is non-functional — no video processing can occur.

## S3 / Object Storage (MinIO or AWS S3)

| Variable | Type | Default | Used By / Features | Impact if Missing/Invalid | Description |
|----------|------|---------|-----------------|----------|-------------|
| `S3_ENDPOINT` | string | `http://minio:9000` | All video/file uploads, intermediate file storage, output retrieval | **Video uploads fail**, pipeline cannot save/restore intermediate files, job resumption not possible | S3-compatible endpoint URL (MinIO for local dev, AWS S3 for production) |
| `S3_ACCESS_KEY` | string | `minioadmin` | S3 authentication, file operations | **Access denied**, upload/download fails | AWS Access Key ID or MinIO username |
| `S3_SECRET_KEY` | string | `minioadmin` | S3 authentication, file operations | **Access denied**, upload/download fails | AWS Secret Access Key or MinIO password |
| `S3_BUCKET` | string | `video-recaps` | All S3 operations, file organization | **Bucket not found**, uploads fail | S3 bucket name for storing videos and intermediate files |
| `S3_REGION` | string | `us-east-1` | S3 API operations (AWS only) | May cause latency or errors in AWS | AWS region for S3 bucket (ignored by MinIO) |
| `S3_PUBLIC_ENDPOINT` | string | `` (empty) | Presigned download URLs for external clients | **Presigned URLs use internal endpoint**, fails for external clients (works for local dev) | Public URL for client-facing download links (optional; defaults to S3_ENDPOINT if empty) |

**Used in:**
- `backend/app/services/storage.py` - S3 client initialization, file uploads/downloads
- `backend/app/api/v1/endpoints/uploads.py` - Video upload validation and storage
- `backend/app/workers/pipeline.py` - Intermediate file uploads/downloads during processing

**Local Development (MinIO):**
```
S3_ENDPOINT=http://minio:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
```

**AWS S3:**
```
S3_ENDPOINT=https://s3.amazonaws.com
S3_ACCESS_KEY=AWS_ACCESS_KEY_ID
S3_SECRET_KEY=AWS_SECRET_ACCESS_KEY
S3_REGION=us-east-1
S3_PUBLIC_ENDPOINT=https://bucket-name.s3.amazonaws.com
```

## JWT Authentication

| Variable | Type | Default | Used By / Features | Impact if Missing/Invalid | Description |
|----------|------|---------|-----------------|----------|-------------|
| `JWT_SECRET` | string | `change-me-in-production` | User authentication tokens, API key encryption, token signing/verification | **Cannot create or validate JWT tokens**, users cannot authenticate, API keys cannot be encrypted/decrypted, default value is insecure | Secret key for signing/verifying JWT tokens AND encrypting user OpenAI API keys (CRITICAL: must be ≥32 chars in production) |
| `JWT_ALGORITHM` | string | `HS256` | JWT token encoding/decoding | Invalid algorithm causes token decode to fail | JWT signing algorithm (`HS256` recommended, or `HS512`, `RS256`) |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | integer | `30` | Session timeout for access tokens | Invalid values cause sessions to be too long or too short | Minutes until access token expires (15-120 typical) |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | integer | `7` | Session refresh window | Invalid values affect how long users stay logged in | Days until refresh token expires (1-30 typical) |

**Used in:**
- `backend/app/core/security.py` - Token encoding/decoding, API key encryption/decryption
- `backend/app/api/v1/endpoints/auth.py` - Login and token refresh

**Features Dependent:**
1. **User Authentication** - Access & refresh tokens for login sessions
2. **API Key Encryption** - Encrypts/decrypts user OpenAI API keys stored in database (via Fernet with PBKDF2 key derivation)
3. **Token Validation** - Verifies JWT tokens on protected endpoints

**Security Note:** The same JWT_SECRET is used for:
- Signing JWT tokens (auth)
- Deriving encryption key for API keys (data protection)

If compromised, both auth tokens AND encrypted API keys are at risk.

**Generate secure JWT_SECRET:**
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Production Considerations:**
- **Rotation Impact:** Changing JWT_SECRET logs out all users and breaks encrypted API keys
- **Leakage Impact:** Use separate secrets in dev/staging/prod
- **Minimum length:** 32 characters recommended

## OAuth & Social Login

| Variable | Type | Default | Used By / Features | Impact if Missing/Invalid | Description |
|----------|------|---------|-----------------|----------|-------------|
| `GOOGLE_CLIENT_ID` | string | `` (empty) | Google OAuth signin, `/meta` endpoint, frontend feature flag | **Google authentication disabled** (optional feature, no error), returned in `/meta` endpoint | OAuth Client ID for Google login (leave empty to disable) |

**Used in:**
- `backend/app/core/oauth.py` - Google OAuth token verification
- `backend/app/api/v1/endpoints/health.py` - Returned in `/meta` endpoint for frontend

**Get from:** https://console.cloud.google.com → Create OAuth 2.0 Client ID

**Note:** Optional feature - if empty, users can still sign up with email/password

## Stripe Billing

| Variable | Type | Default | Used By / Features | Impact if Missing/Invalid | Description |
|----------|------|---------|-----------------|----------|-------------|
| `STRIPE_SECRET_KEY` | string | `` (empty) | Customer creation, checkout sessions, billing endpoints | **Billing endpoints fail**, checkout sessions cannot be created | Stripe API secret key for payment processing (leave empty to disable billing) |
| `STRIPE_WEBHOOK_SECRET` | string | `` (empty) | Webhook signature verification, subscription updates | **Webhook verification fails** (security risk if wrong secret), subscriptions not updated | Secret for verifying Stripe webhook signatures (critical for security) |
| `STRIPE_PRICE_PRO` | string | `` (empty) | Stripe checkout, pricing display | **Pro tier not available**, wrong prices charged | Stripe price ID for Pro tier subscription (e.g., `price_123abc`) |
| `STRIPE_PRICE_ENTERPRISE` | string | `` (empty) | Stripe checkout, pricing display | **Enterprise tier not available**, wrong prices charged | Stripe price ID for Enterprise tier subscription (e.g., `price_456def`) |

**Used in:**
- `backend/app/services/billing_service.py` - Customer creation, checkout sessions, webhook verification

**Get from:** https://dashboard.stripe.com → Developers → API keys & Webhooks

**Features Dependent:** Billing/subscription management (optional feature)

**Security Note:** `STRIPE_WEBHOOK_SECRET` must match the one configured in Stripe dashboard webhooks. Mismatched secrets will cause webhook verification to fail silently.

## AI & ML Models

| Variable | Type | Default | Used By / Features | Impact if Missing/Invalid | Description |
|----------|------|---------|-----------------|----------|-------------|
| `OPENAI_API_KEY` | string | `` (empty, **REQUIRED**) | GPT-4o recap generation, TTS narration, translation (if enabled) | **ALL transcription and TTS fails**, entire video recap pipeline broken | API key for GPT-4o (recap generation), TTS (text-to-speech narration), and translation (CRITICAL - without this feature is completely broken) |
| `WHISPER_MODEL_SIZE` | string | `small` | `tiny`, `base`, `small`, `medium`, `large` | Transcription not available with invalid value | Whisper model size for audio transcription - larger = more accurate but slower/more GPU memory |

**Used in:**
- `backend/app/workers/tasks.py` - Whisper transcription, GPT-4o recap generation, TTS narration generation
- Can be overridden per-user if `ENABLE_USER_API_KEYS=true` (user provides their own key)

**Whisper Model Sizes:**
- `tiny`: ~39MB, fast, lowest accuracy (for casual content)
- `base`: ~140MB, balanced speed/accuracy
- `small`: ~466MB, recommended default, good quality
- `medium`: ~1.5GB, high accuracy, slower (for critical content)
- `large`: ~2.9GB, highest accuracy, slowest (for important content)

**Features Dependent:** 
- **Transcription** - Audio → Text (via Whisper)
- **Recap Generation** - Text → AI summary (via GPT-4o)
- **Text-to-Speech** - Text → MP3 narration (via OpenAI TTS)
- **Translation** - Multi-language support (via GPT-4o, if `ENABLE_TRANSLATION=true`)

**Fallback:** If `ENABLE_USER_API_KEYS=true`, system key is only used if user hasn't provided their own key

**Get OpenAI key from:** https://platform.openai.com/api-keys

## Email & OTP (Resend)

| Variable | Type | Default | Used By / Features | Impact if Missing/Invalid | Description |
|----------|------|---------|-----------------|----------|-------------|
| `RESEND_API_KEY` | string | `` (empty) | Email OTP verification, signup, password reset | **Email sending fails silently** (logs warning), OTP not delivered, user signup still proceeds without verification | API key for sending transactional emails via Resend (leave empty to disable email features) |
| `RESEND_FROM_EMAIL` | string | `Video Recap <noreply@hallucinotai.com>` | Sender email for all outgoing emails | **Wrong sender shown**, emails may be rejected or marked as spam | Sender email address for all transactional emails (format: `Display Name <email@domain.com>`) |
| `OTP_EXPIRY_MINUTES` | integer | `10` | OTP email validity window | Invalid values affect OTP validity window | Minutes until one-time password code expires (5-30 typical) |

**Used in:**
- `backend/app/services/email_service.py` - OTP email sending
- `backend/app/services/user_service.py` - OTP expiry calculation
- Displayed in OTP emails to users

**Features Dependent:** Email OTP verification on signup (optional - signup still works if email disabled)

**Graceful Degradation:** If `RESEND_API_KEY` is empty:
- Email sending logs a warning but doesn't fail
- User signup completes without email verification
- Password reset emails not sent
- Admin can enable later without user impact

**Get from:** https://resend.com → API Keys

**Email Format:** `Display Name <email@domain.com>` (must include domain name for SPF/DKIM validation)

## CORS (Cross-Origin Requests)

| Variable | Type | Default | Used By / Features | Impact if Missing/Invalid | Description |
|----------|------|---------|-----------------|----------|-------------|
| `CORS_ORIGINS` | JSON array | `["http://localhost:3000"]` | Frontend API communication, Stripe checkout redirects | **CORS requests blocked**, frontend cannot call API, Stripe checkout redirects to wrong URL | List of allowed frontend origins for CORS (JSON format) |

**Used in:**
- `backend/app/main.py` - FastAPI CORS middleware configuration
- `backend/app/services/billing_service.py` - Stripe redirect URLs (uses first origin)

**Examples:**
- Local dev: `["http://localhost:3000"]`
- Multiple origins: `["http://localhost:3000", "https://app.example.com", "https://staging.example.com"]`
- Allow all (not recommended): `["*"]`

**Security Note:** Each origin must exactly match the frontend URL including protocol and port
- ✅ Correct: `http://localhost:3000` (dev) vs `https://app.example.com` (prod)
- ❌ Wrong: `localhost:3000` (missing protocol), `http://localhost` (missing port)

## File Upload

| Variable | Type | Default | Used By / Features | Impact if Missing/Invalid | Description |
|----------|------|---------|-----------------|----------|-------------|
| `MAX_UPLOAD_SIZE_BYTES` | integer | `2147483648` (2GB) | Video upload validation, `/uploads` endpoint | **No file size limit enforced**, memory exhaustion possible, oversized uploads hang server | Maximum allowed video file size for uploads (in bytes) |

**Used in:**
- `backend/app/api/v1/endpoints/uploads.py` - File size validation before upload

**Common Values:**
- 1GB: `1073741824`
- 2GB: `2147483648` (default)
- 5GB: `5368709120`
- 10GB: `10737418240`

**Security Consideration:** Large values can cause OOM issues. Recommended maximum for typical servers: 5GB

## Storage & Cleanup

| Variable | Type | Default | Used By / Features | Impact if Missing/Invalid | Description |
|----------|------|---------|-----------------|----------|-------------|
| `DELETE_INPUT_VIDEO_ON_COMPLETE` | boolean | `true` | Post-pipeline cleanup, S3 storage management | **If false:** Original uploaded videos accumulate, storage costs increase significantly | Delete original upload after successful processing (output and intermediate files are always kept) |

**Used in:**
- `backend/app/workers/pipeline.py` - Post-pipeline cleanup step

**Storage Impact:**
- **true (recommended):** Original video deleted after processing, saves ~50% of storage costs
- **false:** Original video kept indefinitely, users can re-download input, higher storage costs

**Note:** Set to `false` to keep all files indefinitely for archival or user access to originals. Users can still download final output and intermediate files regardless of this setting.

## Feature Flags

| Variable | Type | Default | Used By / Features | Impact if Missing/Invalid | Description |
|----------|------|---------|-----------------|----------|-------------|
| `ENABLE_USER_API_KEYS` | boolean | `false` | User settings, API key management, system key fallback | **If true with no OPENAI_API_KEY:** All users must provide their own key (breaks if they don't) | Allow users to provide their own OpenAI API key instead of using the system key |
| `API_KEY_ALLOWED_EMAILS` | JSON array | `[]` | User API key settings, email-based access control | **If empty list:** All users allowed (when ENABLE_USER_API_KEYS=true); if non-empty: only whitelisted users can add keys | Users allowed to use API keys (empty = all allowed if enabled, non-empty = whitelist) |
| `ENABLE_TRANSLATION` | boolean | `false` | Translation endpoint, frontend feature flag, pipeline step | **If false:** Translation step skipped, feature hidden from UI | Enable multi-language translation of transcripts (via GPT-4o) |
| `ENABLE_BILLING` | boolean | `false` | Quota enforcement, billing endpoints, subscription checks, `/meta` endpoint | **If false:** Unlimited quotas, billing endpoints disabled (graceful degradation) | Enable Stripe billing and subscription tiers (requires `STRIPE_*` keys) |
| `BILLING_DISABLED_MESSAGE` | string | `Billing is not available yet. All features are currently free.` | User-facing messaging, settings page | Message shown to users, custom per deployment | Custom message shown when billing is disabled (user-friendly explanation) |
| `ENABLE_API_KEYS_MENU` | boolean | `true` | Frontend feature flag, settings menu visibility | **If false:** API keys menu hidden from UI | Show API keys settings menu in user settings (frontend-only feature flag) |

**Used in:**
- `backend/app/services/user_service.py` - User API key validation and storage
- `backend/app/core/permissions.py` - Quota enforcement (skipped if `ENABLE_BILLING=false`)
- `backend/app/api/v1/endpoints/health.py` - Returned in `/meta` endpoint for frontend
- `backend/app/services/billing_service.py` - Returns unlimited quotas if billing disabled

**Feature Flag Combinations:**

| Scenario | ENABLE_USER_API_KEYS | API_KEY_ALLOWED_EMAILS | OPENAI_API_KEY | Result |
|----------|---|---|---|---|
| System key only (default) | `false` | `[]` | Required | All users use system key |
| Optional user keys | `true` | `[]` | Optional | All users can add key, system key fallback |
| Whitelist user keys | `true` | `["user@ex.com"]` | Optional | Only whitelisted users can add key |
| Force user keys | `true` | `[]` | Empty | All users MUST provide their own key |

**Examples:**
- Allow all users to add API keys: `ENABLE_USER_API_KEYS=true` + `API_KEY_ALLOWED_EMAILS=[]`
- Whitelist specific users: `ENABLE_USER_API_KEYS=true` + `API_KEY_ALLOWED_EMAILS=["user@example.com", "admin@example.com"]`
- Default (system key only): `ENABLE_USER_API_KEYS=false` + `OPENAI_API_KEY=sk-...`

## Quick Reference by Environment

### Development (Local with Docker Compose)
```bash
DEBUG=true
DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/video_recap
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1
S3_ENDPOINT=http://minio:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_BUCKET=video-recaps
S3_REGION=us-east-1
OPENAI_API_KEY=sk-...your-key...
JWT_SECRET=dev-secret-change-me
CORS_ORIGINS=["http://localhost:3000"]
```

### Staging
```bash
DEBUG=false
DATABASE_URL=postgresql+asyncpg://user:pass@db-host:5432/video_recap
REDIS_URL=redis://:password@redis-host:6379/0
CELERY_BROKER_URL=redis://:password@redis-host:6379/0
CELERY_RESULT_BACKEND=redis://:password@redis-host:6379/1
S3_ENDPOINT=https://s3.amazonaws.com
S3_ACCESS_KEY=AWS_KEY_ID
S3_SECRET_KEY=AWS_SECRET
S3_BUCKET=staging-video-recaps
S3_REGION=us-east-1
S3_PUBLIC_ENDPOINT=https://staging-cdn.example.com
OPENAI_API_KEY=sk-...your-key...
JWT_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
CORS_ORIGINS=["https://staging.example.com"]
ENABLE_BILLING=false
RESEND_API_KEY=optional
```

### Production
```bash
DEBUG=false
DATABASE_URL=postgresql+asyncpg://user:secure-pass@db-host:5432/video_recap
REDIS_URL=redis://:secure-pass@redis-host:6379/0
CELERY_BROKER_URL=redis://:secure-pass@redis-host:6379/0
CELERY_RESULT_BACKEND=redis://:secure-pass@redis-host:6379/1
S3_ENDPOINT=https://s3.amazonaws.com
S3_ACCESS_KEY=AWS_KEY_ID
S3_SECRET_KEY=AWS_SECRET
S3_BUCKET=prod-video-recaps
S3_REGION=us-east-1
S3_PUBLIC_ENDPOINT=https://cdn.example.com
OPENAI_API_KEY=sk-...your-key...
JWT_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
GOOGLE_CLIENT_ID=optional
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_PRO=price_...
STRIPE_PRICE_ENTERPRISE=price_...
RESEND_API_KEY=your-api-key
RESEND_FROM_EMAIL=Video Recap <noreply@yourdomain.com>
CORS_ORIGINS=["https://app.example.com"]
ENABLE_BILLING=true
ENABLE_TRANSLATION=true
ENABLE_USER_API_KEYS=false
DELETE_INPUT_VIDEO_ON_COMPLETE=true
MAX_UPLOAD_SIZE_BYTES=5368709120
```

## Complete Variable Summary Table

| Variable | Category | Type | Required | Dev Default | Impact if Missing | When to Change |
|----------|----------|------|----------|---|---|---|
| DEBUG | Config | bool | No | false | Debug endpoints unavailable | Per environment |
| DATABASE_URL | Critical | string | **YES** | postgres:5432 | App won't start | Per environment |
| REDIS_URL | Critical | string | **YES** | redis:6379/0 | Rate limiting broken | Per environment |
| CELERY_BROKER_URL | Critical | string | **YES** | redis:6379/0 | No job processing | Per environment |
| CELERY_RESULT_BACKEND | Critical | string | **YES** | redis:6379/1 | Jobs not tracked | Per environment |
| S3_ENDPOINT | Critical | string | **YES** | minio:9000 | Uploads/downloads fail | Per environment |
| S3_ACCESS_KEY | Critical | string | **YES** | minioadmin | S3 auth fails | Per environment |
| S3_SECRET_KEY | Critical | string | **YES** | minioadmin | S3 auth fails | Per environment |
| S3_BUCKET | Critical | string | **YES** | video-recaps | Bucket not found | Per environment |
| S3_REGION | High | string | No | us-east-1 | Latency/errors (AWS) | Per environment |
| S3_PUBLIC_ENDPOINT | Medium | string | No | (empty) | Internal URLs only | Production only |
| OPENAI_API_KEY | Critical | string | **YES** | (empty) | Transcription/TTS fails | Per environment/user |
| JWT_SECRET | Critical | string | **YES** | change-me | Auth broken | Per environment, rotate regularly |
| JWT_ALGORITHM | Low | string | No | HS256 | Token verification fails | Rarely |
| JWT_ACCESS_TOKEN_EXPIRE_MINUTES | Low | int | No | 30 | Sessions too long/short | Per organization |
| JWT_REFRESH_TOKEN_EXPIRE_DAYS | Low | int | No | 7 | Refresh window wrong | Per organization |
| GOOGLE_CLIENT_ID | Medium | string | No | (empty) | Google login disabled | Optional feature |
| STRIPE_SECRET_KEY | Medium | string | No | (empty) | Billing disabled | Production with billing |
| STRIPE_WEBHOOK_SECRET | Medium | string | No | (empty) | Webhooks fail | Production with billing |
| STRIPE_PRICE_PRO | Medium | string | No | (empty) | Wrong price | Production with billing |
| STRIPE_PRICE_ENTERPRISE | Medium | string | No | (empty) | Wrong price | Production with billing |
| WHISPER_MODEL_SIZE | Low | string | No | small | Transcription quality | Per performance needs |
| RESEND_API_KEY | Medium | string | No | (empty) | Email disabled | If using email auth |
| RESEND_FROM_EMAIL | Medium | string | No | default | Sender shows wrong | If using email auth |
| OTP_EXPIRY_MINUTES | Low | int | No | 10 | OTP timeout wrong | Rare |
| CORS_ORIGINS | High | JSON | **YES** | localhost:3000 | Frontend API blocked | Per environment |
| MAX_UPLOAD_SIZE_BYTES | Low | int | No | 2GB | No upload limit | Per performance needs |
| DELETE_INPUT_VIDEO_ON_COMPLETE | Low | bool | No | true | Storage accumulates | Per business needs |
| ENABLE_USER_API_KEYS | Low | bool | No | false | Feature disabled | Per business needs |
| API_KEY_ALLOWED_EMAILS | Low | JSON | No | [] | All or none allowed | Per access control |
| ENABLE_TRANSLATION | Low | bool | No | false | Feature disabled | Per business needs |
| ENABLE_BILLING | Low | bool | No | false | Billing disabled | Production only |
| BILLING_DISABLED_MESSAGE | Low | string | No | default | Wrong message | Per UI needs |
| ENABLE_API_KEYS_MENU | Low | bool | No | true | Menu hidden | Rare |
| APP_NAME | Low | string | No | Video Recap Agent | Wrong app name | Rare |
| APP_VERSION | Low | string | No | dev | Wrong version | Per release |
| API_V1_PREFIX | Low | string | No | /api/v1 | Wrong API path | Rare |

## Tips & Best Practices

1. **Never commit `.env` files** - Always add `.env` to `.gitignore` ✅
2. **Use `.env.example`** - Keep it in git with placeholder values as template ✅
3. **Rotate secrets regularly** - Change JWT_SECRET, API keys every 90 days
4. **Use different values per environment** - Dev ≠ Staging ≠ Production ✅
5. **Validate on startup** - Check CRITICAL variables (DATABASE_URL, OPENAI_API_KEY) are set
6. **Document overrides** - If environment-specific, note why (e.g., "staging uses test API key")
7. **Use strong secrets** - Minimum 32 characters for JWT_SECRET, avoid default values in production
8. **Lock down S3** - Use IAM policies to restrict bucket access, not just credentials
9. **Monitor log output** - After setting variables, verify in logs that services connect successfully
10. **Test before deploying** - Verify all CRITICAL variables work before production deploy

## Troubleshooting

**"App won't start"**
- Check: DATABASE_URL, REDIS_URL, CELERY_BROKER_URL, CELERY_RESULT_BACKEND
- Verify: Database/Redis services are running
- Test: `psql "$DATABASE_URL"` (should connect)

**"Jobs don't process"**
- Check: CELERY_BROKER_URL, CELERY_RESULT_BACKEND, OPENAI_API_KEY
- Verify: Worker is running, Redis is accessible
- Test: `redis-cli -u "$REDIS_URL" ping` (should reply PONG)

**"Uploads fail"**
- Check: S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET
- Verify: MinIO/S3 service is running
- Test: `aws s3 ls --endpoint-url "$S3_ENDPOINT"` (should list buckets)

**"Frontend can't call API"**
- Check: CORS_ORIGINS matches your frontend URL exactly
- Verify: Protocol (http/https) and port (3000/80/443) are correct
- Test: Check browser console for CORS errors

**"Users can't login"**
- Check: JWT_SECRET is set and consistent
- Verify: DATABASE_URL connects to correct database
- Test: Check if tokens are being created in logs
