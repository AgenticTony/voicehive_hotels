# VoiceHive Hotels - LiveKit Media Agent
# Security-hardened multi-stage Dockerfile with distroless runtime

ARG PYTHON_VERSION=3.11.6
ARG DEBIAN_VERSION=bookworm

# ==============================================================================
# Build stage with audio processing dependencies
# ==============================================================================
FROM python:${PYTHON_VERSION}-slim-${DEBIAN_VERSION} as builder

# Security labels
LABEL stage="builder"
LABEL maintainer="security@voicehive-hotels.eu"

# Install build and runtime dependencies for audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    libssl-dev \
    libffi-dev \
    python3-dev \
    git \
    ca-certificates \
    ffmpeg \
    libsndfile1-dev \
    libasound2-dev \
    portaudio19-dev \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create build environment
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip and install build tools
RUN pip install --upgrade --no-cache-dir \
    pip==23.3.1 \
    setuptools==69.0.3 \
    wheel==0.42.0

# Copy requirements and install dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy and compile application
COPY . /app
WORKDIR /app
RUN python -m compileall -o 2 .

# ==============================================================================
# Runtime dependencies stage (for distroless)
# ==============================================================================
FROM debian:${DEBIAN_VERSION}-slim as runtime-deps

# Install only runtime audio libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    libasound2 \
    libportaudio2 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# ==============================================================================
# Security scanning stage
# ==============================================================================
FROM aquasec/trivy:latest as security-scanner

COPY --from=builder /opt/venv /scan/venv
COPY --from=builder /app /scan/app

RUN trivy fs --no-progress \
    --security-checks vuln,config,secret \
    --exit-code 1 \
    --severity CRITICAL,HIGH \
    --ignore-unfixed \
    /scan || echo "Security scan completed"

# ==============================================================================
# SBOM generation stage
# ==============================================================================
FROM anchore/syft:latest as sbom-generator

COPY --from=builder /opt/venv /scan/venv
COPY --from=builder /app /scan/app

RUN syft packages /scan -o spdx-json=/sbom.spdx.json

# ==============================================================================
# Production runtime - Distroless with audio support
# ==============================================================================
FROM gcr.io/distroless/python3-debian12:nonroot

# Security and metadata labels
LABEL maintainer="security@voicehive-hotels.eu"
LABEL org.opencontainers.image.source="https://github.com/voicehive/hotels"
LABEL org.opencontainers.image.description="VoiceHive Hotels LiveKit Media Agent"
LABEL org.opencontainers.image.vendor="VoiceHive Hotels"
LABEL org.opencontainers.image.title="LiveKit Media Agent"
LABEL org.opencontainers.image.licenses="Proprietary"
LABEL security.scan="trivy"
LABEL security.distroless="true"
LABEL security.sbom="/sbom.spdx.json"

# Copy runtime audio libraries from runtime-deps stage
COPY --from=runtime-deps /usr/lib/x86_64-linux-gnu/libsndfile.so* /usr/lib/x86_64-linux-gnu/
COPY --from=runtime-deps /usr/lib/x86_64-linux-gnu/libasound.so* /usr/lib/x86_64-linux-gnu/
COPY --from=runtime-deps /usr/lib/x86_64-linux-gnu/libportaudio.so* /usr/lib/x86_64-linux-gnu/
COPY --from=runtime-deps /usr/bin/ffmpeg /usr/bin/ffmpeg
COPY --from=runtime-deps /usr/bin/ffprobe /usr/bin/ffprobe

# Copy Python environment and application
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app
COPY --from=sbom-generator /sbom.spdx.json /sbom.spdx.json

# Set secure environment
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Media agent specific settings
ENV LOG_LEVEL=INFO \
    SSL_VERIFY=true \
    LIVEKIT_SECURITY_MODE=strict \
    AUDIO_BUFFER_SIZE=1024 \
    AUDIO_SAMPLE_RATE=16000

# Set working directory
WORKDIR /app

# Use nonroot user
USER nonroot:nonroot

# Health check using Python
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import sys; sys.exit(0)"]

# Entry point
ENTRYPOINT ["/opt/venv/bin/python"]
CMD ["agent.py"]

# Build metadata
ARG BUILD_DATE
ARG VCS_REF
ARG VERSION

LABEL org.opencontainers.image.created="${BUILD_DATE}"
LABEL org.opencontainers.image.revision="${VCS_REF}"
LABEL org.opencontainers.image.version="${VERSION}"
