FROM python:3.9-slim

# Install system dependencies
# p7zip-full provides the '7z' command
RUN apt-get update && apt-get install -y \
    p7zip-full \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Environment variables should be passed at runtime (via Koyeb secrets)
# But we can set defaults or placeholders if needed
ENV PYTHONUNBUFFERED=1

# Command to run the bot
CMD ["python", "bot.py"]
