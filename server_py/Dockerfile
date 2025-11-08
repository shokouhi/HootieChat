# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port (Cloud Run will set PORT env var)
EXPOSE 8080

# Use environment variable for port, default to 8080 for Cloud Run
ENV PORT=8080

# Run the server - use Python to read PORT env var
CMD python -c "import os; import uvicorn; port = int(os.environ.get('PORT', 8080)); uvicorn.run('server:app', host='0.0.0.0', port=port)"

