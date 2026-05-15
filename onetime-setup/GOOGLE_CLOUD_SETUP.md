# Google Cloud Setup Guide - Audio Emotions

Step-by-step walkthrough to set up Google Cloud Speech-to-Text API for emotion analysis.

---

## Prerequisites

- ✅ Google account (personal or work)
- ✅ gcloud CLI installed (see section 1 if not)
- ✅ Access to terminal/command line
- ✅ Credit card for GCP billing (free tier included, costs ~$0.16 per film)

---

## Section 1: Install Google Cloud CLI (If Needed)

### macOS
```bash
# Using Homebrew
brew install google-cloud-sdk

# Verify installation
gcloud --version
```

### Linux (Ubuntu/Debian)
```bash
# Add Google Cloud repo
echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | sudo tee -a /etc/apt/sources.list.d/google-cloud-sdk.list

# Import Google Cloud public key
curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key --keyring /usr/share/keyrings/cloud.google.gpg add -

# Update and install
sudo apt-get update && sudo apt-get install google-cloud-sdk

# Verify
gcloud --version
```

### Windows (PowerShell)
```powershell
# Using Chocolatey
choco install google-cloud-sdk

# Or download installer from:
# https://cloud.google.com/sdk/docs/install-sdk

# Verify
gcloud --version
```

---

## Section 2: Create Google Cloud Project

### Step 2.1: Initialize gcloud

```bash
# Login to Google account
gcloud auth login

# This opens a browser where you authorize gcloud to access your account
# Accept all permissions
```

### Step 2.2: Create New Project

```bash
# Create project
gcloud projects create videorecap-emotions \
  --name="Video Recap Emotions"

# Verify creation (takes a moment)
gcloud projects list
```

**Output should show:**
```
PROJECT_ID           NAME                  PROJECT_NUMBER
videorecap-emotions  Video Recap Emotions  123456789
```

### Step 2.3: Set as Active Project

```bash
# Set this as your active project
gcloud config set project videorecap-emotions

# Verify
gcloud config get-value project
# Output: videorecap-emotions
```

---

## Section 3: Enable Speech-to-Text API

### Step 3.1: Enable the API

```bash
# Enable Speech-to-Text API
gcloud services enable speech.googleapis.com

# This may take 30-60 seconds
# Output: Operation "enable [speech.googleapis.com]" finished successfully.
```

### Step 3.2: Verify Enablement

```bash
# List enabled services
gcloud services list --enabled

# You should see "speech.googleapis.com" in the list
```

---

## Section 4: Create Service Account

A service account is like a user account for applications (not humans).

### Step 4.1: Create Service Account

```bash
# Create service account
gcloud iam service-accounts create videorecap-sa \
  --display-name="Video Recap Service Account" \
  --description="Service account for audio emotion analysis"

# Verify creation
gcloud iam service-accounts list
```

**Output:**
```
DISPLAY_NAME                    EMAIL
Video Recap Service Account     videorecap-sa@videorecap-emotions.iam.gserviceaccount.com
```

### Step 4.2: Grant Permissions

The service account needs permission to use the Speech API.

```bash
# Grant Speech Admin role
gcloud projects add-iam-policy-binding videorecap-emotions \
  --member="serviceAccount:videorecap-sa@videorecap-emotions.iam.gserviceaccount.com" \
  --role="roles/speech.admin"

# Output: Updated IAM policy for project [videorecap-emotions]
```

---

## Section 5: Create and Download Service Account Key

### Step 5.1: Generate Key

```bash
# Create key file (JSON format, most compatible)
gcloud iam service-accounts keys create ~/videorecap-key.json \
  --iam-account=videorecap-sa@videorecap-emotions.iam.gserviceaccount.com

# Key downloaded to home directory
ls -lh ~/videorecap-key.json
```

**Output:**
```
-rw------- 1 user user 2.3K Jan 1 12:00 ~/videorecap-key.json
```

### Step 5.2: Verify Key Contents

```bash
# Check key structure (don't share this file!)
cat ~/videorecap-key.json | head -10

# Should show JSON like:
# {
#   "type": "service_account",
#   "project_id": "videorecap-emotions",
#   "private_key_id": "...",
#   "private_key": "-----BEGIN PRIVATE KEY-----...",
#   ...
# }
```

---

## Section 6: Configure Environment Variables

### Step 6.1: Set Permanent Environment Variable

```bash
# For Bash/Zsh (most common)
echo 'export GOOGLE_APPLICATION_CREDENTIALS=~/videorecap-key.json' >> ~/.bashrc

# Or if using Zsh
echo 'export GOOGLE_APPLICATION_CREDENTIALS=~/videorecap-key.json' >> ~/.zshrc

# Reload shell config
source ~/.bashrc  # or source ~/.zshrc

# Verify
echo $GOOGLE_APPLICATION_CREDENTIALS
# Output: ~/videorecap-key.json
```

### Step 6.2: Add to Project .env File

```bash
# Navigate to project directory
cd /Volumes/Development/hallucinotai/videorecap

# Add to .env (if not already there)
echo "GOOGLE_APPLICATION_CREDENTIALS=~/videorecap-key.json" >> .env

# Verify
grep GOOGLE_APPLICATION_CREDENTIALS .env
```

---

## Section 7: Test Google Cloud Connection

### Step 7.1: Test with gcloud CLI

```bash
# Test Speech API connection
gcloud ml speech recognize gs://gapic-showcases-media/brooklyn_bridge.raw \
  --language-code=en-US

# Should return speech recognition results (or error if file doesn't exist, but that's OK)
# If you get auth errors, restart terminal and try again
```

### Step 7.2: Test with Python

```bash
# Install Google Cloud Speech library
pip install google-cloud-speech

# Test connection with Python
python << 'EOF'
from google.cloud import speech_v1
import os

# Check if credentials are set
creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
print(f"Credentials path: {creds_path}")
print(f"File exists: {os.path.exists(creds_path)}")

# Try to initialize client
try:
    client = speech_v1.SpeechClient()
    print("✅ Google Cloud Speech client initialized successfully!")
except Exception as e:
    print(f"❌ Error: {e}")
EOF
```

**Expected output:**
```
Credentials path: ~/videorecap-key.json
File exists: True
✅ Google Cloud Speech client initialized successfully!
```

---

## Section 8: Enable Billing (Required)

### Step 8.1: Set Up Billing Account

```bash
# List billing accounts
gcloud billing accounts list

# If no accounts, create one:
# Visit: https://console.cloud.google.com/billing/create
# Follow the steps to add a payment method
```

### Step 8.2: Link Billing to Project

```bash
# Get your billing account ID
BILLING_ACCOUNT_ID=$(gcloud billing accounts list --format='value(name)' | head -1)
echo "Billing Account: $BILLING_ACCOUNT_ID"

# Link project to billing account
gcloud billing projects link videorecap-emotions \
  --billing-account=$BILLING_ACCOUNT_ID

# Verify
gcloud billing projects describe videorecap-emotions
```

---

## Section 9: Set Up Budget Alerts (Recommended)

To avoid unexpected costs, set up budget alerts.

### Step 9.1: Create Budget via Console

```bash
# Open Google Cloud Console
echo "Open: https://console.cloud.google.com/billing/budgets"

# Follow these steps in the console:
# 1. Click "Create Budget"
# 2. Name: "Audio Emotions Budget"
# 3. Set budget amount: $50/month (or your preferred limit)
# 4. Set alerts: 50%, 90%, 100% of budget
# 5. Save
```

Or use the command line:
```bash
# Create budget via CLI (advanced)
gcloud billing budgets create \
  --billing-account=$BILLING_ACCOUNT_ID \
  --display-name="Audio Emotions Budget" \
  --budget-amount=50 \
  --threshold-rule=percent=50 \
  --threshold-rule=percent=90 \
  --threshold-rule=percent=100
```

---

## Section 10: Verify Everything Works

### Step 10.1: Test Emotion Analysis Module

```bash
# Create test script
cat > test_google_cloud.py << 'EOF'
import os
from google.cloud import speech_v1
import json

print("🔍 Google Cloud Setup Verification\n")

# 1. Check credentials
creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
print(f"✓ Credentials: {creds}")
print(f"✓ File exists: {os.path.exists(creds)}\n")

# 2. Initialize client
try:
    client = speech_v1.SpeechClient()
    print("✓ Speech client initialized\n")
except Exception as e:
    print(f"✗ Client error: {e}\n")
    exit(1)

# 3. Check project
try:
    # Load credentials to get project ID
    from google.oauth2 import service_account
    credentials = service_account.Credentials.from_service_account_file(creds)
    project_id = credentials.project_id
    print(f"✓ Project ID: {project_id}\n")
except Exception as e:
    print(f"✗ Project error: {e}\n")

print("✅ All checks passed! Google Cloud is ready.\n")
print("Next steps:")
print("1. Install emotion_analysis module")
print("2. Test with sample audio")
print("3. Integrate into pipeline")
EOF

python test_google_cloud.py
```

**Expected output:**
```
🔍 Google Cloud Setup Verification

✓ Credentials: ~/videorecap-key.json
✓ File exists: True

✓ Speech client initialized

✓ Project ID: videorecap-emotions

✅ All checks passed! Google Cloud is ready.
```

---

## Section 11: Troubleshooting

### Problem: "GOOGLE_APPLICATION_CREDENTIALS not found"

**Solution:**
```bash
# Check if variable is set
echo $GOOGLE_APPLICATION_CREDENTIALS

# If empty, reload shell config
source ~/.bashrc  # or ~/.zshrc

# Or set it manually
export GOOGLE_APPLICATION_CREDENTIALS=~/videorecap-key.json

# Verify
echo $GOOGLE_APPLICATION_CREDENTIALS
```

### Problem: "Permission denied" when accessing key file

**Solution:**
```bash
# Check file permissions
ls -l ~/videorecap-key.json

# Should be: -rw------- (only owner can read)
# If not, fix permissions:
chmod 600 ~/videorecap-key.json

# Verify
ls -l ~/videorecap-key.json
```

### Problem: "Service account does not have permission"

**Solution:**
```bash
# Re-grant permissions
PROJECT_ID="videorecap-emotions"
SA_EMAIL="videorecap-sa@videorecap-emotions.iam.gserviceaccount.com"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SA_EMAIL" \
  --role="roles/speech.admin"

# Wait 30 seconds for permissions to propagate
sleep 30

# Test again
python test_google_cloud.py
```

### Problem: "Billing not enabled"

**Solution:**
```bash
# Verify billing account is linked
gcloud billing projects describe videorecap-emotions

# Should show: billingAccountName: projects/.../billingAccounts/...

# If not, link it:
BILLING_ID=$(gcloud billing accounts list --format='value(name)' | head -1)
gcloud billing projects link videorecap-emotions --billing-account=$BILLING_ID
```

### Problem: "API not enabled"

**Solution:**
```bash
# Re-enable the API
gcloud services enable speech.googleapis.com

# Wait for it to complete
# Verify
gcloud services list --enabled | grep speech
```

---

## Section 12: Cost Monitoring

### Check Current Usage

```bash
# View current billing
gcloud billing accounts describe $(gcloud billing accounts list --format='value(name)' | head -1)

# Or open console
echo "Open: https://console.cloud.google.com/billing"
```

### Estimate Costs

```bash
# For audio emotion analysis:
# - Cost: $0.004 per 15-second audio block
# - 10-minute film = ~40 blocks = $0.16

# Examples:
# 10 films/month = $1.60
# 100 films/month = $16.00
# 500 films/month = $80.00
```

---

## Complete Setup Checklist

- [ ] gcloud CLI installed and `gcloud --version` works
- [ ] `gcloud auth login` successful
- [ ] Created project `videorecap-emotions`
- [ ] Enabled Speech-to-Text API
- [ ] Created service account `videorecap-sa`
- [ ] Granted Speech Admin role
- [ ] Downloaded key to `~/videorecap-key.json`
- [ ] Set `GOOGLE_APPLICATION_CREDENTIALS` environment variable
- [ ] Added to project `.env` file
- [ ] Installed `google-cloud-speech` package
- [ ] Test script `test_google_cloud.py` passes
- [ ] Billing account linked
- [ ] Budget alerts created (optional)

---

## Next Steps

Once setup is complete:

1. ✅ **Run test script** to verify everything works
2. 📦 **Install emotion_analysis module** from `backend/app/processing/`
3. 🧪 **Test with sample audio** (see AUDIO_EMOTIONS_QUICKSTART.md)
4. 🔧 **Integrate into pipeline** (see AUDIO_EMOTIONS_PHASE1.md)

---

## Quick Reference Commands

```bash
# List all gcloud commands
gcloud --help

# Check active project
gcloud config get-value project

# Switch projects
gcloud config set project <PROJECT_ID>

# List service accounts
gcloud iam service-accounts list

# List project permissions
gcloud projects get-iam-policy videorecap-emotions

# Check API status
gcloud services list --enabled

# View billing
gcloud billing accounts list

# Get credentials file location
echo $GOOGLE_APPLICATION_CREDENTIALS
```

---

## Security Notes

⚠️ **Important:**
- ✅ Keep `videorecap-key.json` private (like a password)
- ✅ Never commit it to git (already in `.gitignore`)
- ✅ Never share it in Slack, email, or public places
- ✅ If compromised, delete key and create a new one
- ✅ Rotate keys periodically (every 6-12 months)

---

**Setup complete!** You're ready to use Google Cloud Speech API. 🎉

Any issues? Run `test_google_cloud.py` and share the output for debugging!

