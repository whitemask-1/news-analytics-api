# Use an official Python runtime as a parent image
# Python 3.11-slim is a lightweight version that's perfect for production
FROM python:3.11-slim

# Set the working directory in the container
# All subsequent commands will run from this directory
WORKDIR /app

# Set environment variables
# PYTHONUNBUFFERED: Ensures Python output is sent straight to terminal (useful for logs)
# PYTHONDONTWRITEBYTECODE: Prevents Python from writing .pyc files to disk
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Copy requirements first for better Docker layer caching
# Docker caches layers, so if requirements don't change, this layer is reused
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code into the container
# We do this AFTER installing dependencies so that code changes don't invalidate the dependency layer
COPY ./app ./app

# Expose the port the app runs on
# This documents which port the container listens on at runtime
EXPOSE 8000

# Command to run the application
# uvicorn is the ASGI server that runs FastAPI
# --host 0.0.0.0 makes the server accessible outside the container
# --port 8000 specifies the port
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
