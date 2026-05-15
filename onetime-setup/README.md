# 🎙️ One-Time Setup: Google Cloud Audio Emotions

This folder contains all files needed to set up Google Cloud Speech-to-Text API for audio emotion analysis.

**These are one-time setup files** - you only need to run them once to configure your Google Cloud environment.

---

## 📁 Files in This Folder

| File | Purpose | When to Use |
|------|---------|-----------|
| **SETUP_COMMANDS.sh** | Automated setup script | ⚡ Quick setup (5-10 min) |
| **GOOGLE_CLOUD_SETUP.md** | Detailed step-by-step guide | 📖 Manual setup with explanations (15-20 min) |
| **SETUP_NEXT_STEPS.md** | Quick reference commands | 🔍 If you prefer copy-pasting individual commands |

---

## 🚀 Quick Start (Choose One)

### Option 1: Automated (Recommended) ⚡

```bash
cd /Volumes/Development/hallucinotai/videorecap/onetime-setup
bash SETUP_COMMANDS.sh
```

**What happens:**
- Opens browser for Google authentication
- Creates GCP project automatically
- Enables Speech API
- Creates service account
- Downloads credentials
- Tests the setup
- Done in ~5-10 minutes

---

### Option 2: Manual (Step-by-Step) 📖

Open and follow:
```
onetime-setup/GOOGLE_CLOUD_SETUP.md
```

**What you get:**
- Detailed explanations for each step
- 12 comprehensive sections
- Troubleshooting for common issues
- Security best practices
- Cost monitoring setup
- Takes ~15-20 minutes

---

### Option 3: Copy-Paste Individual Commands 🔍

Open and follow:
```
onetime-setup/SETUP_NEXT_STEPS.md
```

**What you get:**
- Ready-to-copy commands
- Verification steps between each command
- Good for learning what each command does

---

## ✅ Verification

After setup completes, verify everything works:

```bash
python << 'EOF'
from google.cloud import speech_v1
import os

creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
print(f"✓ Credentials: {creds}")
print(f"✓ File exists: {os.path.exists(os.path.expanduser(creds))}")

client = speech_v1.SpeechClient()
print("✓ Google Cloud Speech client initialized!")
EOF
```

**Expected output:**
```
✓ Credentials: ~/videorecap-key.json
✓ File exists: True
✓ Google Cloud Speech client initialized!
```

---

## 💰 Cost Estimation

Google Cloud Speech-to-Text pricing:
- **Free tier**: $300 credits for first 90 days
- **Then**: $0.004 per 15-second audio block
- **Per film**: ~$0.16 for 10-minute film
- **Monthly**: ~$16 for 100 films/month

We recommend setting up budget alerts to prevent surprises.

---

## 🔑 What Gets Created

After setup, you'll have:

```
✅ Google Cloud Project: videorecap-emotions
✅ Service Account: videorecap-sa
✅ Credentials File: ~/videorecap-key.json (keep private!)
✅ Environment Variable: GOOGLE_APPLICATION_CREDENTIALS set
✅ Project .env: Updated with credentials path
✅ Python Package: google-cloud-speech installed
```

---

## ⚠️ Important Security Notes

- **Keep credentials private**: `~/videorecap-key.json` is like a password
- **Never commit to git**: Already in `.gitignore`
- **Never share**: Not in Slack, email, or public places
- **If compromised**: Delete key and create a new one immediately
- **Rotate periodically**: Every 6-12 months for security

---

## 🆘 Troubleshooting

### "gcloud: command not found"
```bash
brew install google-cloud-sdk
```

### "Billing account not found"
- Open: https://console.cloud.google.com/billing/create
- Add a credit card
- Activate the billing account

### "GOOGLE_APPLICATION_CREDENTIALS not set"
```bash
echo 'export GOOGLE_APPLICATION_CREDENTIALS=~/videorecap-key.json' >> ~/.zshrc
source ~/.zshrc
```

### "Authentication failed"
- Check credentials file exists: `ls ~/videorecap-key.json`
- Restart terminal
- Try setup again

**More help**: See **GOOGLE_CLOUD_SETUP.md Section 11** for detailed troubleshooting.

---

## ✨ Next Steps After Setup

Once Google Cloud is configured:

1. ✅ **Verify setup** - Run the verification command above
2. 📦 **Install emotion module** - `pip install google-cloud-speech`
3. 🧪 **Test with audio** - See AUDIO_EMOTIONS_QUICKSTART.md
4. 🔧 **Integrate into pipeline** - See AUDIO_EMOTIONS_PHASE1.md

---

## 📖 Related Documentation

- **AUDIO_EMOTIONS_PHASE1.md** - Complete Phase 1 implementation guide
- **AUDIO_EMOTIONS_QUICKSTART.md** - Quick start for emotion analysis
- **CLAUDE.md** - Project overview and architecture

---

## ❓ FAQ

**Q: Do I need to run this more than once?**  
A: No! This is a one-time setup. After completion, Google Cloud is configured forever (unless you delete the project).

**Q: Can I use a different Google account?**  
A: Yes! Just run `gcloud auth login` again with a different account.

**Q: What if I already have Google Cloud setup?**  
A: You can skip this folder and go directly to the emotion analysis integration.

**Q: How much will this cost?**  
A: With the free tier ($300 credits), you get ~2000 films worth of emotion analysis for free.

**Q: Can I delete these setup files after completion?**  
A: Yes! Once setup is done, these files are no longer needed. But keeping them is fine too.

---

**Ready to set up?** Choose your approach above and get started! 🚀

