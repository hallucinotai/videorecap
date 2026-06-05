# Environment Variables Reference

Complete documentation of all backend environment variables with possible values and descriptions.

## Application Configuration

| Variable | Type | Default | Possible Values | Description |
|----------|------|---------|-----------------|-------------|
| `DEBUG` | boolean | `false` | `true`, `false` | Enable debug endpoints for intermediate file downloads and detailed logging |
| `APP_NAME` | string | `Video Recap Agent` | Any string | Application display name |
| `APP_VERSION` | string | `dev` | Semantic version (e.g., `1.0.0`, `dev`) | Application version identifier |
| `API_V1_PREFIX` | string | `/api/v1` | Any path (e.g., `/api/v1`, `/v1`) | API base path prefix |

## Database

| Variable | Type | Default | Possible Values | Description |
|----------|------|---------|-----------------|-------------|
| `DATABASE_URL` | string | `postgresql+asyncpg://postgres:postgres@postgres:5432/video_recap` | PostgreSQL connection string | Full async PostgreSQL connection URL with credentials |

**Examples:**
- Local dev: `postgresql+asyncpg://postgres:password@localhost:5432/video_recap`
- Docker: `postgresql+asyncpg://postgres:password@postgres:5432/video_recap`
- Remote: `postgresql+asyncpg://user:pass@db.example.com:5432/video_recap`

## Redis

| Variable | Type | Default | Possible Values | Description |
|----------|------|---------|-----------------|-------------|
| `REDIS_URL` | string | `redis://redis:6379/0` | Redis connection string | Redis URL for caching and pub/sub (same as Celery broker for local setup) |

**Examples:**
- Local: `redis://localhost:6379/0`
- Docker: `redis://redis:6379/0`
- Remote: `redis://:password@redis.example.com:6379/0`

## Celery (Job Queue)

| Variable | Type | Default | Possible Values | Description |
|----------|------|---------|-----------------|-------------|
| `CELERY_BROKER_URL` | string | `redis://redis:6379/0` | Redis connection string | Message broker for Celery task queue |
| `CELERY_RESULT_BACKEND` | string | `redis://redis:6379/1` | Redis connection string | Backend for storing task results (different DB than broker) |

**Best Practice:** Use different Redis databases (0 for broker, 1 for results) to avoid data conflicts.

## S3 / Object Storage (MinIO or AWS S3)

| Variable | Type | Default | Possible Values | Description |
|----------|------|---------|-----------------|-------------|
| `S3_ENDPOINT` | string | `http://minio:9000` | S3-compatible endpoint URL | MinIO endpoint for local dev or AWS S3 endpoint for production |
| `S3_ACCESS_KEY` | string | `minioadmin` | Any string | AWS Access Key ID or MinIO username |
| `S3_SECRET_KEY` | string | `minioadmin` | Any string | AWS Secret Access Key or MinIO password |
| `S3_BUCKET` | string | `video-recaps` | Bucket name (lowercase alphanumeric + hyphens) | S3 bucket name for storing videos and intermediate files |
| `S3_REGION` | string | `us-east-1` | AWS region (e.g., `us-east-1`, `eu-west-1`, `ap-south-1`) | AWS region for S3 bucket |
| `S3_PUBLIC_ENDPOINT` | string | `` (empty) | Public S3 URL (e.g., `https://cdn.example.com`, `https://s3.amazonaws.com`) | Public URL for presigned download links (optional, leave empty for default) |

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

| Variable | Type | Default | Possible Values | Description |
|----------|------|---------|-----------------|-------------|
| `JWT_SECRET` | string | `change-me-in-production` | Random string (min 32 chars recommended) | Secret key for signing JWT tokens - change in production! |
| `JWT_ALGORITHM` | string | `HS256` | `HS256`, `HS512`, `RS256` | JWT signing algorithm (HS256 recommended for simple setups) |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | integer | `30` | Positive integer (15-120 typical) | Minutes until access token expires |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | integer | `7` | Positive integer (1-30 typical) | Days until refresh token expires |

**Generate secure JWT_SECRET:**
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## OAuth & Social Login

| Variable | Type | Default | Possible Values | Description |
|----------|------|---------|-----------------|-------------|
| `GOOGLE_CLIENT_ID` | string | `` (empty) | OAuth Client ID from Google Console | Enables Google login (leave empty to disable) |

**Get from:** https://console.cloud.google.com → Create OAuth 2.0 Client ID

## Stripe Billing

| Variable | Type | Default | Possible Values | Description |
|----------|------|---------|-----------------|-------------|
| `STRIPE_SECRET_KEY` | string | `` (empty) | Stripe API secret key | Stripe secret key for payment processing (leave empty to disable) |
| `STRIPE_WEBHOOK_SECRET` | string | `` (empty) | Stripe webhook signing secret | Secret for verifying Stripe webhook signatures |
| `STRIPE_PRICE_PRO` | string | `` (empty) | Stripe price ID (e.g., `price_123abc`) | Price ID for Pro tier subscription |
| `STRIPE_PRICE_ENTERPRISE` | string | `` (empty) | Stripe price ID (e.g., `price_456def`) | Price ID for Enterprise tier subscription |

**Get from:** https://dashboard.stripe.com → Developers → API keys & Webhooks

## AI & ML Models

| Variable | Type | Default | Possible Values | Description |
|----------|------|---------|-----------------|-------------|
| `OPENAI_API_KEY` | string | `` (empty, **required**) | OpenAI API key (sk-...) | API key for GPT-4o (recap generation) and TTS (narration) - required to use the app |
| `WHISPER_MODEL_SIZE` | string | `small` | `tiny`, `base`, `small`, `medium`, `large` | Whisper model size for transcription - larger = more accurate but slower |

**Whisper Model Sizes:**
- `tiny`: Fast, lowest accuracy, ~39MB
- `base`: Balanced, ~140MB
- `small`: Recommended default, ~466MB
- `medium`: High accuracy, slower, ~1.5GB
- `large`: Highest accuracy, slowest, ~2.9GB

**Get OpenAI key from:** https://platform.openai.com/api-keys

## Email & OTP (Resend)

| Variable | Type | Default | Possible Values | Description |
|----------|------|---------|-----------------|-------------|
| `RESEND_API_KEY` | string | `` (empty) | Resend API key | API key for sending transactional emails via Resend (leave empty to disable) |
| `RESEND_FROM_EMAIL` | string | `Video Recap <noreply@hallucinotai.com>` | Email address with display name | Sender email for all transactional emails |
| `OTP_EXPIRY_MINUTES` | integer | `10` | Positive integer (5-30 typical) | Minutes until OTP code expires |

**Get from:** https://resend.com → API Keys

**Email Format:** `Display Name <email@domain.com>`

## CORS (Cross-Origin Requests)

| Variable | Type | Default | Possible Values | Description |
|----------|------|---------|-----------------|-------------|
| `CORS_ORIGINS` | JSON array | `["http://localhost:3000"]` | List of allowed origins (JSON format) | Frontend domains allowed to make API requests |

**Examples:**
- Local dev: `["http://localhost:3000"]`
- Multiple origins: `["http://localhost:3000", "https://app.example.com", "https://staging.example.com"]`
- Allow all (not recommended): `["*"]`

## File Upload

| Variable | Type | Default | Possible Values | Description |
|----------|------|---------|-----------------|-------------|
| `MAX_UPLOAD_SIZE_BYTES` | integer | `2147483648` (2GB) | Positive integer in bytes | Maximum allowed video file size for uploads |

**Common Values:**
- 1GB: `1073741824`
- 2GB: `2147483648` (default)
- 5GB: `5368709120`
- 10GB: `10737418240`

## Storage & Cleanup

| Variable | Type | Default | Possible Values | Description |
|----------|------|---------|-----------------|-------------|
| `DELETE_INPUT_VIDEO_ON_COMPLETE` | boolean | `true` | `true`, `false` | Delete original upload after successful processing - output and intermediate files are kept |

**Note:** Set to `false` to keep all files indefinitely (uses more storage).

## Feature Flags

| Variable | Type | Default | Possible Values | Description |
|----------|------|---------|-----------------|-------------|
| `ENABLE_USER_API_KEYS` | boolean | `false` | `true`, `false` | Allow users to provide their own OpenAI API key instead of using system key |
| `API_KEY_ALLOWED_EMAILS` | JSON array | `[]` | Empty array or list of emails | Users allowed to use API keys (empty = all if ENABLE_USER_API_KEYS is true) |
| `ENABLE_TRANSLATION` | boolean | `false` | `true`, `false` | Enable multi-language translation of transcripts |
| `ENABLE_BILLING` | boolean | `false` | `true`, `false` | Enable Stripe billing and subscription tiers (requires STRIPE_* keys) |
| `BILLING_DISABLED_MESSAGE` | string | `Billing is not available yet. All features are currently free.` | Any string | Message shown to users when billing is disabled |
| `ENABLE_API_KEYS_MENU` | boolean | `true` | `true`, `false` | Show API keys settings menu in user settings |

**Examples:**
- Allow all users to add API keys: `ENABLE_USER_API_KEYS=true` + `API_KEY_ALLOWED_EMAILS=[]`
- Whitelist specific users: `ENABLE_USER_API_KEYS=true` + `API_KEY_ALLOWED_EMAILS=["user@example.com", "admin@example.com"]`

## Summary by Environment

### Development (Local)
```
DEBUG=true
DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/video_recap
REDIS_URL=redis://redis:6379/0
S3_ENDPOINT=http://minio:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
OPENAI_API_KEY=sk-...your-key...
JWT_SECRET=dev-secret-change-me
CORS_ORIGINS=["http://localhost:3000"]
```

### Staging/Production
```
DEBUG=false
DATABASE_URL=postgresql+asyncpg://user:pass@db-host:5432/video_recap
REDIS_URL=redis://:password@redis-host:6379/0
S3_ENDPOINT=https://s3.amazonaws.com
S3_ACCESS_KEY=AWS_KEY_ID
S3_SECRET_KEY=AWS_SECRET
S3_REGION=us-east-1
S3_PUBLIC_ENDPOINT=https://cdn.example.com
OPENAI_API_KEY=sk-...your-key...
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
JWT_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
CORS_ORIGINS=["https://app.example.com"]
ENABLE_BILLING=true
```

## Tips

1. **Never commit `.env` files** - Always add `.env` to `.gitignore`
2. **Use `.env.example`** - Keep `.env.example` in git with placeholder values as reference
3. **Rotate secrets regularly** - Change JWT_SECRET, API keys periodically
4. **Use different values per environment** - Dev, staging, and production should have different secrets
5. **Validate on startup** - Check required variables like OPENAI_API_KEY are set
