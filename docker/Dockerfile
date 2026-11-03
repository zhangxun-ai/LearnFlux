FROM python:3.11-slim

# The checked-in BBDown binary is Linux amd64. Keep the supported target explicit.
ARG TARGETARCH
RUN test "$TARGETARCH" = "amd64" || (echo "This Dockerfile currently requires linux/amd64" >&2; exit 1)

COPY --from=mwader/static-ffmpeg:latest /ffmpeg /usr/local/bin/ffmpeg
COPY --from=mwader/static-ffmpeg:latest /ffprobe /usr/local/bin/ffprobe
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git libgomp1 libportaudio2 \
    && apt-get clean
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src/ ./src/
COPY main.py ./
COPY BBDown/BBDown ./BBDown/BBDown
RUN chmod 755 /app/BBDown/BBDown \
    && uv sync --frozen --no-dev \
    && mkdir -p data/cache data/temp data/workspace data/logs config

EXPOSE 8000
ENTRYPOINT ["uv", "run", "--no-sync", "python", "main.py", "--start"]
