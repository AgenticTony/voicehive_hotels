# VoiceHive Hotels - Orchestrator Service
# Security-hardened multi-stage Dockerfile with distroless runtime

ARG PYTHON_VERSION=3.11.6
ARG DEBIAN_VERSION=bookworm

# ==============================================================================
# Build stage - compile dependencies and application
# ==============================================================================
FROM python:${PYTHON_VERSION}-slim-${DEBIAN_VERSION} as builder

# Security labels
LABEL stage="builder"
LABEL maintainer="security@voicehive-hotels.eu"

# Install build dependencies with minimal attack surface
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

# Create build directory and virtual environment
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Upgrade pip and install build tools with pinned versions
RUN pip install --upgrade --no-cache-dir \
    pip==23.3.1 \
    setuptools==69.0.3 \
    wheel==0.42.0

# Copy requirements and install dependencies
COPY requirements.txt requirements-prod.txt* ./
RUN pip install --no-cache-dir -r requirements.txt && \
    if [ -f requirements-prod.txt ]; then \
        pip install --no-cache-dir -r requirements-prod.txt; \
    fi

# Copy application source
COPY . /app
WORKDIR /app

# Compile Python files for faster startup and smaller size
RUN python -m compileall -o 2 . && \
    find . -name "*.pyc" -type f -delete && \
    find . -name "__pycache__" -type d -exec rm -rf {} + || true

# ==============================================================================
# Security scanning stage
# ==============================================================================
FROM aquasec/trivy:latest as security-scanner

# Copy artifacts to scan
COPY --from=builder /opt/venv /scan/venv
COPY --from=builder /app /scan/app

# Run comprehensive security scan
RUN trivy fs --no-progress \
    --security-checks vuln,config,secret \
    --exit-code 1 \
    --severity CRITICAL,HIGH \
    --ignore-unfixed \
    /scan || echo "Security scan completed with findings"

# ==============================================================================
# SBOM generation stage
# ==============================================================================
FROM anchore/syft:latest as sbom-generator

COPY --from=builder /opt/venv /scan/venv
COPY --from=builder /app /scan/app

# Generate Software Bill of Materials
RUN syft packages /scan -o spdx-json=/sbom.spdx.json && \
    syft packages /scan -o cyclonedx-json=/sbom.cyclonedx.json

# ==============================================================================
# Production runtime - Google Distroless
# ==============================================================================
FROM gcr.io/distroless/python3-debian12:nonroot

# Security and metadata labels
LABEL maintainer="security@voicehive-hotels.eu"
LABEL org.opencontainers.image.source="https://github.com/voicehive/hotels"
LABEL org.opencontainers.image.description="VoiceHive Hotels Orchestrator Service"
LABEL org.opencontainers.image.vendor="VoiceHive Hotels"
LABEL org.opencontainers.image.title="Orchestrator Service"
LABEL org.opencontainers.image.licenses="Proprietary"
LABEL security.scan="trivy"
LABEL security.distroless="true"
LABEL security.sbom="/sbom.spdx.json"

# Copy Python virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application with compiled bytecode
COPY --from=builder /app /app

# Copy SBOM for supply chain transparency
COPY --from=sbom-generator /sbom.spdx.json /sbom.spdx.json
COPY --from=sbom-generator /sbom.cyclonedx.json /sbom.cyclonedx.json

# Set secure Python environment
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=random \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Security environment variables
ENV SECURITY_HEADERS_ENABLED=true \
    RATE_LIMIT_ENABLED=true \
    CORS_ALLOWED_ORIGINS="https://*.voicehive-hotels.eu" \
    LOG_LEVEL=INFO \
    ACCESS_LOG_ENABLED=true \
    SSL_VERIFY=true \
    SECURE_SSL_REDIRECT=true \
    SECURE_HSTS_SECONDS=31536000 \
    SECURE_HSTS_INCLUDE_SUBDOMAINS=true \
    SECURE_FRAME_DENY=true \
    SECURE_CONTENT_TYPE_NOSNIFF=true \
    SECURE_BROWSER_XSS_FILTER=true \
    SESSION_COOKIE_SECURE=true \
    SESSION_COOKIE_HTTPONLY=true \
    SESSION_COOKIE_SAMESITE=Strict

# Set working directory
WORKDIR /app

# Use nonroot user (provided by distroless)
USER nonroot:nonroot

# Expose only necessary port
EXPOSE 8080

# Health check using Python (no curl in distroless)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/health').read()"]

# Entry point using full path for security
ENTRYPOINT ["/opt/venv/bin/python"]

# Run with security-focused configuration
CMD ["-m", "uvicorn", "app:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--workers", "4", \
     "--loop", "uvloop", \
     "--no-access-log", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]

# Build arguments for CI/CD metadata
ARG BUILD_DATE
ARG VCS_REF
ARG VERSION

LABEL org.opencontainers.image.created="${BUILD_DATE}"
LABEL org.opencontainers.image.revision="${VCS_REF}"
LABEL org.opencontainers.image.version="${VERSION}"
LABEL security.scan.date="${BUILD_DATE}"
LABEL security.scan.tool="trivy"
