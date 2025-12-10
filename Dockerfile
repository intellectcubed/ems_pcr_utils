# Dockerfile for PCR Utils - EMS Patient Care Report Processing
# Supports running both the email poller and PDF parser services

FROM python:3.11-slim

# Install system dependencies required for PyMuPDF, Pillow, and other packages
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    libmupdf-dev \
    mupdf-tools \
    libfreetype6-dev \
    libjpeg-dev \
    libopenjp2-7-dev \
    libtiff-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Build argument to control installation source
ARG INSTALL_FROM_GITHUB=false
ARG GITHUB_REPO=https://github.com/YOUR_USERNAME/pcr_utils.git
ARG GITHUB_BRANCH=main

# Install application based on build argument
RUN if [ "$INSTALL_FROM_GITHUB" = "true" ]; then \
        echo "Installing from GitHub: $GITHUB_REPO (branch: $GITHUB_BRANCH)"; \
        git clone --branch $GITHUB_BRANCH $GITHUB_REPO /tmp/pcr_utils && \
        cp -r /tmp/pcr_utils/src /app/ && \
        cp /tmp/pcr_utils/requirements.txt /app/ && \
        rm -rf /tmp/pcr_utils; \
    else \
        echo "Installing from local directory"; \
        mkdir -p /app/src; \
    fi

# Copy application files from local directory (only used if INSTALL_FROM_GITHUB=false)
COPY requirements.txt /app/
COPY src/ /app/src/

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Create directories for data persistence
RUN mkdir -p /data/watch /data/state /root/.pcr_utils

# Environment variables with defaults
ENV PYTHONUNBUFFERED=1 \
    WATCH_DIR=/data/watch \
    POLL_INTERVAL_SECONDS=30 \
    EMAIL_POLL_INTERVAL_SECONDS=300

# The CMD will be specified at runtime or in docker-compose
# Usage:
#   - For PCR parser: python -m src.pcr_utils.pcr_parser
#   - For Email poller: python -m src.pcr_utils.yahoo_mail_poller
CMD ["python", "-m", "src.pcr_utils.pcr_parser"]
