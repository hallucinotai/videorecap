# 🚀 Quick: Upgrade to Enterprise Locally (5 Minutes)

## TL;DR - Copy & Paste

### Step 1: Start Backend
```bash
cd /Volumes/Development/hallucinotai/videorecap
docker-compose up -d backend
```

### Step 2: Sign Up
```bash
curl -X POST http://localhost:8000/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{
    "email": "dev@example.com",
    "password": "testpass123",
    "full_name": "Dev"
  }'
```

Save the `access_token` from the response.

### Step 3: Upgrade
```bash
export TOKEN="your-access-token-from-step-2"

curl -X POST http://localhost:8000/api/v1/users/upgrade-to-enterprise \
  -H "Authorization: Bearer $TOKEN"
```

### Step 4: Verify
```bash
curl -X GET http://localhost:8000/api/v1/users/me \
  -H "Authorization: Bearer $TOKEN"
```

Should show `"tier": "enterprise"` ✅

### Step 5: Use It
Now submit a job with 180+ seconds:
```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "upload_id": "test-upload",
    "s3_key": "test/video.mp4",
    "original_filename": "video.mp4",
    "file_size_bytes": 50000000,
    "config": {
      "target_duration": 180
    }
  }'
```

---

## What Changed?

**New file:** `backend/app/api/v1/endpoints/users.py`
- 4 new dev endpoints for local tier management
- Can upgrade, downgrade, or check tier anytime

**Modified:** `backend/app/api/v1/router.py`
- Registered the new users endpoints

**Documentation:** `ENTERPRISE_LOCAL_SETUP.md`
- Full guide with examples and troubleshooting

---

## Available Tier Limits

| Tier | Max Duration | Features |
|------|------|----------|
| **free** | 30s | Basic voices, 7-day retention |
| **pro** | 120s | All voices, HD TTS, 30-day retention |
| **enterprise** | 3600s (unlimited) | Priority queue, custom branding, 90-day retention |

---

## Commands Reference

| What | Command |
|------|---------|
| Upgrade to enterprise | `POST /api/v1/users/upgrade-to-enterprise` |
| Set any tier | `POST /api/v1/users/set-tier/{free\|pro\|enterprise}` |
| View my tier | `GET /api/v1/users/me` |
| View all tiers | `GET /api/v1/users/tiers` |

---

## Frontend Users

If you want auto-upgrade in your frontend after login:

```javascript
// After login, add this:
const upgradeResponse = await fetch(
  'http://localhost:8000/api/v1/users/upgrade-to-enterprise',
  {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${accessToken}` }
  }
);
console.log('Tier:', (await upgradeResponse.json()).tier);
```

---

## Still Need Help?

See `ENTERPRISE_LOCAL_SETUP.md` for:
- Troubleshooting
- Getting JWT tokens
- Using with frontend
- Clean up & reset

---

Done! Enjoy testing 180+ second recaps locally! 🎉
