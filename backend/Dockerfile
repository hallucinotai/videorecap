FROM python:3.11-slim AS base

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip "setuptools<78" wheel

# Install CPU-only PyTorch first (avoids downloading ~1.5GB of CUDA packages)
RUN pip install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cpu

COPY backend/requirements.txt .
RUN pip install --no-cache-dir --no-build-isolation openai-whisper==20240930
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt

# Copy application code
COPY backend/ .

# Copy original CLI modules
COPY modules/ /app/modules/

ARG APP_VERSION="dev"
ENV APP_VERSION=$APP_VERSION

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
