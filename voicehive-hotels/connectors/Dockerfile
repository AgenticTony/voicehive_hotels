# VoiceHive Hotels - PMS Connectors Service
# Security-hardened multi-stage Dockerfile with distroless runtime

ARG PYTHON_VERSION=3.11.6

# Build stage
FROM python:${PYTHON_VERSION}-slim as builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    libssl-dev \
    libffi-dev \
    python3-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create build directory and venv
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python build tools
RUN pip install --upgrade --no-cache-dir \
    pip==23.3.1 \
    setuptools==68.2.2 \
    wheel==0.41.3

# Copy requirements first for better caching
COPY requirements.txt requirements-dev.txt* ./
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir httpx[http2] orjson

# Compile Python files for faster startup
COPY . /app
RUN python -m compileall -o 2 /app

# Security scanning stage
FROM aquasec/trivy:latest as scanner
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app /app
RUN trivy fs --no-progress --security-checks vuln,config --exit-code 0 --severity CRITICAL,HIGH /opt/venv && \
    trivy fs --no-progress --security-checks vuln,config --exit-code 0 /app

# Final stage - distroless for minimal attack surface
FROM gcr.io/distroless/python3-debian12

# Security labels
LABEL maintainer="security@voicehive-hotels.eu"
LABEL org.opencontainers.image.source="https://github.com/voicehive/hotels"
LABEL org.opencontainers.image.description="VoiceHive Hotels PMS Connectors"
LABEL security.scan="trivy"
LABEL security.distroless="true"

# Copy Python virtual environment
COPY --from=builder /opt/venv /opt/venv

# Copy application with compiled bytecode
COPY --from=builder /app /app

# Set Python environment
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONHASHSEED=random
ENV PYTHONUTF8=1

# Security environment variables
ENV CONNECTOR_SECURITY_MODE=strict \
    CONNECTOR_RATE_LIMIT=100 \
    CONNECTOR_TIMEOUT=30 \
    CONNECTOR_MAX_RETRIES=3 \
    CONNECTOR_CIRCUIT_BREAKER=true \
    SSL_VERIFY=true \
    LOG_LEVEL=INFO

# Set working directory
WORKDIR /app

# Create temporary directory for runtime (distroless has limited filesystem)
# This will be mounted as tmpfs in Kubernetes
ENV TMPDIR=/tmp

# Non-root user (distroless provides this)
USER nonroot:nonroot

# Expose service port
EXPOSE 8081

# Health check endpoint
ENV HEALTH_CHECK_PATH=/health

# Entry point - using full path for security
ENTRYPOINT ["/opt/venv/bin/python"]

# Run the FastAPI app
CMD ["-m", "uvicorn", "connectors.api:app", "--host", "0.0.0.0", "--port", "8081", "--workers", "2"]

# Build arguments for metadata
ARG BUILD_DATE
ARG VCS_REF
ARG VERSION

LABEL org.opencontainers.image.created="${BUILD_DATE}"
LABEL org.opencontainers.image.revision="${VCS_REF}"
LABEL org.opencontainers.image.version="${VERSION}"
