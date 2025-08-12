# Use an official, lean Python runtime as the base
FROM python:3.11-slim

# Set the working directory inside the container
WORKDIR /app

# Install system dependencies. 'build-essential' is needed for compiling
# some Python packages that have C extensions.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy your requirements file first and install dependencies.
# This layer is cached by Docker, speeding up future builds if requirements don't change.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application's code into the container
COPY . .

# The command to run your application.
# It uses the command from your Procfile/run.py and exposes the app on port 8080,
# which Fly.io will automatically map to the public ports 80 and 443.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]