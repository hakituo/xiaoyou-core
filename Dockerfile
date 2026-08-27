# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HF_ENDPOINT="https://hf-mirror.com"

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    ffmpeg \
    libsndfile1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy project metadata first (for better Docker layer caching)
COPY pyproject.toml ./

# Copy a minimal source layout so setuptools can discover packages
COPY core/ ./core/
COPY config/ ./config/
COPY memory/ ./memory/
COPY routers/ ./routers/

# Install Python dependencies from pyproject.toml (唯一权威源)
# Use mirror to speed up installation
RUN pip install --no-cache-dir . -i https://pypi.tuna.tsinghua.edu.cn/simple

# Copy the rest of the application
COPY . .

# Expose ports
# 8000: HTTP API
# 8080: C++ Scheduler (if running inside container or proxied)
EXPOSE 8000 8080

# Define volume for persistent data (ChromaDB, Models, Logs)
VOLUME ["/app/data", "/app/models", "/app/logs"]

# Command to run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

# Expose ports
# 8000: HTTP API
# 8080: C++ Scheduler (if running inside container or proxied)
EXPOSE 8000 8080

# Define volume for persistent data (ChromaDB, Models, Logs)
VOLUME ["/app/data", "/app/models", "/app/logs"]

# Command to run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
