FROM python:3.10-slim

WORKDIR /app

# Install system dependencies (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better layer caching
COPY requirements.txt .

# Install Python dependencies with optimizations
# Disable bytecode compilation for faster startup
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 8080

# Use gunicorn for production with optimized settings
# - Workers: 1 (Cloud Run handles scaling)
# - Threads: 4 (handle multiple requests per worker)
# - Timeout: 300s (allow time for ML loading on first request)
# - Preload: false (don't load ML libraries at startup)
CMD exec gunicorn --bind :8080 \
    --workers 1 \
    --threads 4 \
    --timeout 300 \
    --access-logfile - \
    --error-logfile - \
    api_server:app