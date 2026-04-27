### Stage 1: builder — installs Python deps in a clean venv
FROM python:3.11-slim AS builder

# Build deps for any native packages that fall back to source build.
# shazamio-core ships prebuilt wheels for linux/amd64 + linux/arm64
# (manylinux_2_17), so no Rust is needed in normal builds.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

# Use a venv so the runtime stage can copy a clean tree
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

### Stage 2: runtime — minimal image, no build tools
FROM python:3.11-slim

# Runtime deps: only ffmpeg for yt-dlp post-processing
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy the prepared Python venv from the builder stage
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY . .

# Downloads dir is mounted as a volume in docker-compose, but ensure it exists
RUN mkdir -p downloads

CMD ["python", "main.py"]
