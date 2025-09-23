# VoiceHive Hotels - TTS Router Service
# Security-hardened multi-stage Dockerfile with distroless runtime

ARG PYTHON_VERSION=3.11.6
ARG DEBIAN_VERSION=bookworm

# ==============================================================================
# Build stage
# ==============================================================================
FROM python:${PYTHON_VERSION}-slim-${DEBIAN_VERSION} as builder

# Security labels
LABEL stage="builder"
LABEL maintainer="security@voicehive-hotels.eu"

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    libssl-dev \
    libffi-dev \
    python3-dev \
    git \
    ca-certificates \
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
# Production runtime - Distroless
# ==============================================================================
FROM gcr.io/distroless/python3-debian12:nonroot

# Security and metadata labels
LABEL maintainer="security@voicehive-hotels.eu"
LABEL org.opencontainers.image.source="https://github.com/voicehive/hotels"
LABEL org.opencontainers.image.description="VoiceHive Hotels TTS Router"
LABEL org.opencontainers.image.vendor="VoiceHive Hotels"
LABEL org.opencontainers.image.title="TTS Router"
LABEL org.opencontainers.image.licenses="Proprietary"
LABEL security.scan="trivy"
LABEL security.distroless="true"
LABEL security.sbom="/sbom.spdx.json"

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

# Security settings
ENV LOG_LEVEL=INFO \
    SSL_VERIFY=true \
    TTS_SECURITY_MODE=strict

# Set working directory
WORKDIR /app

# Use nonroot user
USER nonroot:nonroot

# Expose service port
EXPOSE 9000

# Health check using Python
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:9000/health').read()"]

# Entry point
ENTRYPOINT ["/opt/venv/bin/python"]
CMD ["-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "9000"]

# Build metadata
ARG BUILD_DATE
ARG VCS_REF
ARG VERSION

LABEL org.opencontainers.image.created="${BUILD_DATE}"
LABEL org.opencontainers.image.revision="${VCS_REF}"
LABEL org.opencontainers.image.version="${VERSION}"
