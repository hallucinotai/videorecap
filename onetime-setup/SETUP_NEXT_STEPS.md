# Next Steps - Continue Setup

Google Cloud SDK is installed. Now complete the setup by running these commands.

---

## Step 1: Authenticate with Google

```bash
gcloud auth login
```

**What happens:**
- Browser opens to Google login
- Accept permissions
- Returns to terminal

---

## Step 2: Create Google Cloud Project

```bash
gcloud projects create videorecap-emotions --name="Video Recap Emotions"
```

**Expected output:**
```
Create in progress for [videorecap-emotions].
Waiting for [operations/cp.xxx] to finish...done.
```

---

## Step 3: Set Active Project

```bash
gcloud config set project videorecap-emotions
```

**Verify:**
```bash
gcloud config get-value project
# Output: videorecap-emotions
```

---

## Step 4: Enable Speech-to-Text API

```bash
gcloud services enable speech.googleapis.com
```

**Expected output:**
```
Operation "enable [speech.googleapis.com]" finished successfully.
```

---

## Step 5: Create Service Account

```bash
gcloud iam service-accounts create videorecap-sa \
  --display-name="Video Recap Service Account"
```

**Expected output:**
```
Created service account [videorecap-sa].
```

---

## Step 6: Grant Permissions

```bash
gcloud projects add-iam-policy-binding videorecap-emotions \
  --member="serviceAccount:videorecap-sa@videorecap-emotions.iam.gserviceaccount.com" \
  --role="roles/speech.admin"
```

**Expected output:**
```
Updated IAM policy for project [videorecap-emotions].
```

---

## Step 7: Create and Download Key

```bash
gcloud iam service-accounts keys create ~/videorecap-key.json \
  --iam-account=videorecap-sa@videorecap-emotions.iam.gserviceaccount.com
```

**Expected output:**
```
created key [xxxxx] of type [json] as [/Users/username/videorecap-key.json]
```

**Verify:**
```bash
ls -lh ~/videorecap-key.json
```

---

## Step 8: Set Environment Variable

```bash
export GOOGLE_APPLICATION_CREDENTIALS=~/videorecap-key.json
```

**Verify:**
```bash
echo $GOOGLE_APPLICATION_CREDENTIALS
# Output: ~/videorecap-key.json
```

---

## Step 9: Add to Project .env

```bash
cd /Volumes/Development/hallucinotai/videorecap
echo "GOOGLE_APPLICATION_CREDENTIALS=~/videorecap-key.json" >> .env
```

**Verify:**
```bash
grep GOOGLE_APPLICATION_CREDENTIALS .env
```

---

## Step 10: Install Python Package

```bash
pip install google-cloud-speech
```

**Expected output:**
```
Successfully installed google-cloud-speech-2.21.0
```

---

## Step 11: Test Connection

```bash
python << 'EOF'
from google.cloud import speech_v1
import os

creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
print(f"Credentials: {creds}")
print(f"File exists: {os.path.exists(creds)}")

client = speech_v1.SpeechClient()
print("✓ Google Cloud Speech client initialized!")
EOF
```

**Expected output:**
```
Credentials: ~/videorecap-key.json
File exists: True
✓ Google Cloud Speech client initialized!
```

---

**That's it! You're done with Google Cloud setup.** 🎉

Next, run the emotion analysis test!
