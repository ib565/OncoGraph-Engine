FROM python:3.13-slim

LABEL maintainer="OncoGraph Team"
LABEL description="OncoGraph Backend API - Knowledge graph Q&A for oncology research"

WORKDIR /app

# Install system dependencies for compiling Python packages
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files first (for Docker layer caching)
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .
RUN pip install --no-cache-dir -e .

EXPOSE 8000

ENV PYTHONUNBUFFERED=1

# Uses PORT env var if set (Render), otherwise defaults to 8000 (local dev)
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
