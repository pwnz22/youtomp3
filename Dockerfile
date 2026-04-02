FROM python:3.11-slim

# Install only minimal ffmpeg (no X11/mesa/GUI deps)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create downloads directory
RUN mkdir -p downloads

# Run the bot
CMD ["python", "main.py"]
