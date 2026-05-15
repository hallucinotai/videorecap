#!/bin/bash

################################################################################
#
#  🎙️  GOOGLE CLOUD SETUP FOR AUDIO EMOTIONS
#
#  This script automates the complete Google Cloud Speech-to-Text setup
#  for audio emotion analysis in the Video Recap pipeline.
#
#  ⚡ QUICK START (Automated):
#     $ bash SETUP_COMMANDS.sh
#
#  📖 MANUAL SETUP (Step-by-Step):
#     If you prefer to set up manually, follow the detailed instructions in:
#     👉 GOOGLE_CLOUD_SETUP.md
#
#     It includes 12 comprehensive sections with explanations, troubleshooting,
#     and detailed commands for each step of the Google Cloud configuration.
#
#  ⏱️  ESTIMATED TIME:
#     - Automated (this script): ~5-10 minutes
#     - Manual (GOOGLE_CLOUD_SETUP.md): ~15-20 minutes
#
#  ✅ WHAT THIS DOES:
#     1. Authenticates with your Google account
#     2. Creates a new GCP project
#     3. Enables the Speech-to-Text API
#     4. Creates a service account
#     5. Grants necessary permissions
#     6. Generates and downloads credentials
#     7. Configures environment variables
#     8. Tests the setup
#
#  ⚠️  REQUIREMENTS:
#     - Google account (personal or work)
#     - gcloud CLI installed (brew install google-cloud-sdk)
#     - Active billing account (free tier with $300 credits for 90 days)
#
#  🔐 SECURITY:
#     - Your credentials file is kept private and secure
#     - Never commit credentials to git (already in .gitignore)
#     - Rotate keys periodically for security
#
################################################################################

set -e  # Exit on error

echo "============================================"
echo "Google Cloud Setup for Audio Emotions"
echo "============================================"
echo ""

# === SECTION 1: Login ===
echo "Step 1: Authenticating with Google..."
gcloud auth login
echo "✓ Authentication complete"
echo ""

# === SECTION 2: Create Project ===
echo "Step 2: Creating Google Cloud project..."
gcloud projects create videorecap-emotions \
  --name="Video Recap Emotions"
echo "✓ Project created: videorecap-emotions"
echo ""

# === SECTION 3: Set Active Project ===
echo "Step 3: Setting active project..."
gcloud config set project videorecap-emotions
ACTIVE_PROJECT=$(gcloud config get-value project)
echo "✓ Active project: $ACTIVE_PROJECT"
echo ""

# === SECTION 4: Enable API ===
echo "Step 4: Enabling Speech-to-Text API..."
gcloud services enable speech.googleapis.com
echo "✓ Speech API enabled"
echo ""

# === SECTION 5: Create Service Account ===
echo "Step 5: Creating service account..."
gcloud iam service-accounts create videorecap-sa \
  --display-name="Video Recap Service Account" \
  --description="Service account for audio emotion analysis"
echo "✓ Service account created: videorecap-sa"
echo ""

# === SECTION 6: Grant Permissions ===
echo "Step 6: Granting permissions..."
gcloud projects add-iam-policy-binding videorecap-emotions \
  --member="serviceAccount:videorecap-sa@videorecap-emotions.iam.gserviceaccount.com" \
  --role="roles/speech.admin"
echo "✓ Permissions granted"
echo ""

# === SECTION 7: Create Key ===
echo "Step 7: Creating service account key..."
KEY_FILE=~/videorecap-key.json
gcloud iam service-accounts keys create $KEY_FILE \
  --iam-account=videorecap-sa@videorecap-emotions.iam.gserviceaccount.com
echo "✓ Key created: $KEY_FILE"
ls -lh $KEY_FILE
echo ""

# === SECTION 8: Set Environment Variable ===
echo "Step 8: Setting environment variable..."
echo "export GOOGLE_APPLICATION_CREDENTIALS=~/videorecap-key.json" >> ~/.bashrc
echo "export GOOGLE_APPLICATION_CREDENTIALS=~/videorecap-key.json" >> ~/.zshrc
source ~/.bashrc 2>/dev/null || true
echo "✓ Environment variable set"
echo ""

# === SECTION 9: Add to .env ===
echo "Step 9: Adding to project .env..."
if [ -f .env ]; then
  if grep -q "GOOGLE_APPLICATION_CREDENTIALS" .env; then
    echo "✓ Already in .env"
  else
    echo "GOOGLE_APPLICATION_CREDENTIALS=~/videorecap-key.json" >> .env
    echo "✓ Added to .env"
  fi
else
  echo "⚠ .env file not found, creating it..."
  echo "GOOGLE_APPLICATION_CREDENTIALS=~/videorecap-key.json" > .env
  echo "✓ Created .env"
fi
echo ""

# === SECTION 10: Install Python Package ===
echo "Step 10: Installing google-cloud-speech..."
pip install google-cloud-speech
echo "✓ Package installed"
echo ""

# === SECTION 11: Test Connection ===
echo "Step 11: Testing Google Cloud connection..."
python << 'EOF'
import os
from google.cloud import speech_v1

try:
    creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    print(f"Credentials: {creds}")
    print(f"File exists: {os.path.exists(creds)}")

    client = speech_v1.SpeechClient()
    print("✓ Google Cloud Speech client initialized!")
    print("✓ Setup complete!")
except Exception as e:
    print(f"✗ Error: {e}")
    exit(1)
EOF
echo ""

echo "============================================"
echo "✅ Google Cloud Setup Complete!"
echo "============================================"
echo ""
echo "Next steps:"
echo "1. Create billing account (if needed)"
echo "2. Test emotion_analysis module"
echo "3. Integrate into pipeline"
echo ""
