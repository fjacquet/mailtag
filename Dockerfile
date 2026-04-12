# syntax=docker/dockerfile:1

# Stage 1: Build dependencies with uv
FROM python:3.13-slim AS builder

RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./

# Create override file to exclude Apple Silicon-only MLX dependencies
RUN printf '%s\n' \
    'mlx>=0.0.0  ; sys_platform == "never"' \
    'mlx-lm>=0.0.0  ; sys_platform == "never"' \
    'sentence-transformers>=0.0.0  ; sys_platform == "never"' \
    'einops>=0.0.0  ; sys_platform == "never"' \
    > /tmp/overrides.txt

# Install runtime deps only (no dev, no MLX)
RUN uv sync --no-dev --no-install-project --override /tmp/overrides.txt

# Copy source and install the project itself
COPY src/ src/
RUN uv sync --no-dev --no-editable --override /tmp/overrides.txt

# Stage 2: Runtime
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --gid 1000 mailtag \
    && useradd --uid 1000 --gid mailtag --create-home mailtag

WORKDIR /app

# Copy installed venv from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application source and config
COPY src/ src/
COPY config.toml ./

# Create directories for runtime data (volumes will overlay these)
RUN mkdir -p db data logs \
    && chown -R mailtag:mailtag /app

# Add venv to PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV MLX_ENABLED=false

USER mailtag

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "src/main.py", "serve", "--host", "0.0.0.0"]
