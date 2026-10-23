FROM python:3.11-slim

WORKDIR /app

# Install curl for healthcheck probe and system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies for trusted control plane
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code and reports
COPY . .

# Expose HTTP API port
EXPOSE 8080

# Run FastAPI server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
