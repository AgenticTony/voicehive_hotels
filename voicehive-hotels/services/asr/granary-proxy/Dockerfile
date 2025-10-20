# NVIDIA Granary ASR Proxy Dockerfile
# Lightweight service for 25 EU language ASR using NeMo Parakeet-tdt

FROM python:3.11-slim

LABEL maintainer="VoiceHive Team"
LABEL description="NVIDIA Granary ASR Proxy with NeMo Parakeet-tdt-0.6b-v3"
LABEL version="1.0.0"

# Set working directory
WORKDIR /app

# Install system dependencies for audio processing
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    libsndfile1 \
    ffmpeg \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better Docker layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY server.py .

# Create cache directory for models
RUN mkdir -p /tmp/granary_models

# Expose the service port
EXPOSE 51052

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:51052/health')" \
    || exit 1

# Environment variables
ENV GRANARY_MODEL_NAME=nvidia/parakeet-tdt-0.6b-v3
ENV GRANARY_CACHE_DIR=/tmp/granary_models
ENV GRANARY_DEVICE=cpu
ENV GRANARY_BATCH_SIZE=1
ENV PYTHONUNBUFFERED=1

# Run the service
CMD ["python", "server.py"]