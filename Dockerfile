FROM python:3.10-slim

# Install system dependencies (including support for image processing and libmagic)
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libjpeg-dev \
    zlib1g-dev \
    libmagic-dev \
    file \
    && rm -rf /var/lib/apt/lists/*

# Set up working directory
WORKDIR /app

# Copy requirements file
COPY requirements.txt .

# Install dependencies from requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# pytest so the core test suite can run inside the image:
#   docker compose run --rm --entrypoint python memento-mori -m pytest tests
# The browser layer (pytest-playwright) is deliberately NOT installed here —
# it needs a real Chromium and runs on the host or in CI instead.
RUN pip install --no-cache-dir pytest

# Copy application code
COPY . .

# Make the package importable even when the container runs from a
# different working directory (docker-compose uses /app/workspace)
ENV PYTHONPATH=/app

# Create directories for input/output
RUN mkdir -p /input /output

# Set the entrypoint
ENTRYPOINT ["python", "-m", "memento_mori.cli"]

# Default command if none provided
CMD ["--help"]