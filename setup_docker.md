# Docker Deployment Guide for PCR Utils

This guide covers deploying the PCR Utils application using Docker. The application consists of two services:
1. **Email Poller** - Monitors Yahoo Mail for fax attachments
2. **PCR Parser** - Processes PDF files and saves to Supabase database

## Table of Contents
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Installation Methods](#installation-methods)
  - [Method 1: Install from GitHub](#method-1-install-from-github)
  - [Method 2: Install from Local Directory](#method-2-install-from-local-directory)
- [Configuration](#configuration)
- [Running the Services](#running-the-services)
- [Managing the Services](#managing-the-services)
- [Troubleshooting](#troubleshooting)
- [Advanced Usage](#advanced-usage)

---

## Prerequisites

- Docker Engine 20.10+ ([Install Docker](https://docs.docker.com/engine/install/))
- Docker Compose 2.0+ (included with Docker Desktop)
- Yahoo Mail app-specific password ([Generate here](https://login.yahoo.com/account/security/app-passwords))
- Supabase account with URL and API key

---

## Quick Start

```bash
# 1. Clone repository (or download)
git clone https://github.com/YOUR_USERNAME/pcr_utils.git
cd pcr_utils

# 2. Create data directories
mkdir -p data/watch data/state

# 3. Copy and configure environment file
cp .env.example .env
nano .env  # Edit with your credentials

# 4. Build and start services
docker-compose up -d

# 4.1. Rebuild email-poller service with updated code
docker-compose build --no-cache email-poller   

# 5. View logs
docker-compose logs -f

# 6. Shut down
docker-compose down
```

---

## Installation Methods

### Method 1: Install from GitHub

This method builds the Docker image directly from your GitHub repository without needing to clone it locally.

#### Step 1: Create docker-compose.yml

Create a `docker-compose.yml` file with the following content:

```yaml
version: '3.8'

services:
  email-poller:
    build:
      context: .
      dockerfile: Dockerfile
      args:
        INSTALL_FROM_GITHUB: "true"
        GITHUB_REPO: "https://github.com/YOUR_USERNAME/pcr_utils.git"
        GITHUB_BRANCH: "main"
    image: pcr-utils:latest
    container_name: pcr-email-poller
    command: python -m src.pcr_utils.yahoo_mail_poller
    env_file:
      - .env
    environment:
      - WATCH_DIR=/data/watch
      - EMAIL_POLL_INTERVAL_SECONDS=${EMAIL_POLL_INTERVAL_SECONDS:-300}
    volumes:
      - ./data/watch:/data/watch
      - ./data/state:/root/.pcr_utils
    restart: unless-stopped

  pcr-parser:
    build:
      context: .
      dockerfile: Dockerfile
      args:
        INSTALL_FROM_GITHUB: "true"
        GITHUB_REPO: "https://github.com/YOUR_USERNAME/pcr_utils.git"
        GITHUB_BRANCH: "main"
    image: pcr-utils:latest
    container_name: pcr-parser
    command: python -m src.pcr_utils.pcr_parser
    env_file:
      - .env
    environment:
      - WATCH_DIR=/data/watch
      - POLL_INTERVAL_SECONDS=${POLL_INTERVAL_SECONDS:-30}
    volumes:
      - ./data/watch:/data/watch
    restart: unless-stopped
    depends_on:
      - email-poller
```

#### Step 2: Download Dockerfile

Download the Dockerfile from your repository:

```bash
curl -o Dockerfile https://raw.githubusercontent.com/YOUR_USERNAME/pcr_utils/main/Dockerfile
```

#### Step 3: Create Environment File

```bash
# Download example environment file
curl -o .env.example https://raw.githubusercontent.com/YOUR_USERNAME/pcr_utils/main/.env.example

# Copy and edit
cp .env.example .env
nano .env
```

#### Step 4: Create Data Directories

```bash
mkdir -p data/watch data/state
```

#### Step 5: Build and Run

```bash
docker-compose up -d
```

---

### Method 2: Install from Local Directory

This method uses your local copy of the repository.

#### Step 1: Clone Repository

```bash
git clone https://github.com/YOUR_USERNAME/pcr_utils.git
cd pcr_utils
```

#### Step 2: Create Data Directories

```bash
mkdir -p data/watch data/state
```

#### Step 3: Configure Environment

```bash
cp .env.example .env
nano .env  # Edit with your credentials
```

#### Step 4: Build and Run

```bash
docker-compose up -d
```

---

## Configuration

### Required Environment Variables

Edit your `.env` file with the following required variables:

```bash
# OpenAI API Configuration
OPENAI_API_KEY=sk-...your_key_here

# Supabase Configuration
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_key_here

# Yahoo Mail Configuration
YAHOO_EMAIL=your_email@yahoo.com
YAHOO_PASSWORD=your_app_specific_password

# Watch Directory (internal path - don't change)
WATCH_DIR=/data/watch

# Poll Intervals
POLL_INTERVAL_SECONDS=30              # PDF parser check interval
EMAIL_POLL_INTERVAL_SECONDS=300       # Email poller check interval (5 minutes)
```

### Optional Environment Variables

```bash
# Email save directory (defaults to WATCH_DIR)
EMAIL_SAVE_DIR=/data/watch
```

### Getting Yahoo App Password

1. Go to [Yahoo Account Security](https://login.yahoo.com/account/security/app-passwords)
2. Click "Generate app password"
3. Select "Other App" and name it "PCR Utils"
4. Copy the generated password to your `.env` file

---

## Running the Services

### Start All Services

```bash
# Start in detached mode (background)
docker-compose up -d

# Start in foreground (see logs)
docker-compose up
```

### Start Individual Services

```bash
# Start only email poller
docker-compose up -d email-poller

# Start only PCR parser
docker-compose up -d pcr-parser
```

### Stop Services

```bash
# Stop all services
docker-compose down

# Stop but keep volumes
docker-compose stop
```

### Restart Services

```bash
# Restart all services
docker-compose restart

# Restart specific service
docker-compose restart email-poller
docker-compose restart pcr-parser
```

---

## Managing the Services

### View Logs

```bash
# View logs from all services
docker-compose logs

# Follow logs in real-time
docker-compose logs -f

# View logs from specific service
docker-compose logs email-poller
docker-compose logs pcr-parser

# View last 50 lines
docker-compose logs --tail=50
```

### Check Service Status

```bash
# List running containers
docker-compose ps

# View detailed service info
docker inspect pcr-email-poller
docker inspect pcr-parser
```

### Access Container Shell

```bash
# Access email poller container
docker exec -it pcr-email-poller /bin/bash

# Access PCR parser container
docker exec -it pcr-parser /bin/bash
```

### View Data Directories

```bash
# Watch directory (PDFs are temporarily stored here)
ls -la data/watch/

# State directory (email tracking state)
ls -la data/state/

# Error directory (failed PDFs)
ls -la data/watch/errors/
```

---

## Troubleshooting

### Services Won't Start

**Check logs for errors:**
```bash
docker-compose logs email-poller
docker-compose logs pcr-parser
```

**Common issues:**
- Missing environment variables - verify `.env` file
- Invalid credentials - check Yahoo password and OpenAI API key
- Port conflicts - ensure no other services using the same ports

### Email Poller Issues

**Yahoo authentication fails:**
```bash
# Check if using app-specific password (not regular password)
docker-compose logs email-poller | grep "IMAP error"
```

**Not finding emails:**
```bash
# Check email search criteria
docker exec -it pcr-email-poller python -c "
from src.pcr_utils.yahoo_mail_poller import YahooMailPoller
print(f'Subject filter: {YahooMailPoller.TARGET_SUBJECT}')
print(f'Sender filter: {YahooMailPoller.TARGET_SENDER}')
"
```

**State file issues:**
```bash
# View current state
cat data/state/email_state.json

# Reset state (will reprocess last 15 emails)
rm data/state/email_state.json
docker-compose restart email-poller
```

### PCR Parser Issues

**PDFs not being processed:**
```bash
# Check watch directory
ls -la data/watch/*.pdf

# Check parser logs
docker-compose logs pcr-parser | grep "Processing"
```

**Database save failures:**
```bash
# Verify Supabase credentials
docker-compose logs pcr-parser | grep "DATABASE"

# Check if PDFs moved to error directory
ls -la data/watch/errors/
```

### Rebuild Containers

If you've updated the code:

```bash
# Rebuild and restart
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### Reset Everything

```bash
# Stop and remove containers, volumes, and images
docker-compose down -v
docker rmi pcr-utils:latest

# Remove data (caution: deletes state and PDFs)
rm -rf data/

# Start fresh
mkdir -p data/watch data/state
docker-compose up -d --build
```

---

## Advanced Usage

### Running Single Service Manually

```bash
# Build image
docker build -t pcr-utils .

# Run email poller only
docker run -d \
  --name pcr-email-poller \
  --env-file .env \
  -v $(pwd)/data/watch:/data/watch \
  -v $(pwd)/data/state:/root/.pcr_utils \
  pcr-utils \
  python -m src.pcr_utils.yahoo_mail_poller

# Run PCR parser only
docker run -d \
  --name pcr-parser \
  --env-file .env \
  -v $(pwd)/data/watch:/data/watch \
  pcr-utils \
  python -m src.pcr_utils.pcr_parser
```

### Custom Build from GitHub Branch

```bash
docker build \
  --build-arg INSTALL_FROM_GITHUB=true \
  --build-arg GITHUB_REPO=https://github.com/YOUR_USERNAME/pcr_utils.git \
  --build-arg GITHUB_BRANCH=development \
  -t pcr-utils:dev .
```

### Override Poll Intervals

```bash
# Edit docker-compose.yml or use environment variable override
EMAIL_POLL_INTERVAL_SECONDS=60 POLL_INTERVAL_SECONDS=10 docker-compose up -d
```

### View Resource Usage

```bash
# Monitor container resource usage
docker stats pcr-email-poller pcr-parser

# View container details
docker inspect pcr-email-poller
```

### Export Logs

```bash
# Export logs to file
docker-compose logs > pcr-utils.log

# Export specific service logs
docker-compose logs email-poller > email-poller.log
docker-compose logs pcr-parser > pcr-parser.log
```

### Automated Startup on System Boot

Docker Compose services with `restart: unless-stopped` will automatically start when Docker daemon starts.

**Enable Docker to start on boot:**

```bash
# Linux (systemd)
sudo systemctl enable docker

# macOS/Windows
# Docker Desktop starts automatically by default
```

---

## Service Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Yahoo Mail (IMAP)                       │
│                SC911@mailfax.comm.somerset.nj.us            │
└────────────────────────┬────────────────────────────────────┘
                         │
                         │ IMAP/SSL
                         │ (polls every 5 min)
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Email Poller Container                         │
│  - Monitors for READ emails with fax subject                │
│  - Downloads PDF attachments                                │
│  - Tracks processed emails in state file                    │
└────────────────────────┬────────────────────────────────────┘
                         │
                         │ Saves PDFs to
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              Shared Watch Directory                         │
│              /data/watch                                    │
└────────────────────────┬────────────────────────────────────┘
                         │
                         │ Monitored by
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              PCR Parser Container                           │
│  - Polls watch directory (every 30 sec)                     │
│  - Parses PDFs using OpenAI Vision API                      │
│  - Saves to Supabase database                               │
│  - Deletes processed PDFs                                   │
│  - Moves failed PDFs to errors/                             │
└────────────────────────┬────────────────────────────────────┘
                         │
                         │ Saves to
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                     Supabase Database                       │
└─────────────────────────────────────────────────────────────┘
```

---

## Production Deployment Tips

1. **Use Docker Secrets** for sensitive credentials instead of `.env` file
2. **Set up log rotation** to prevent disk space issues
3. **Monitor container health** using Docker health checks
4. **Set resource limits** in docker-compose.yml
5. **Use a process manager** like systemd to ensure Docker daemon starts on boot
6. **Regular backups** of the state file (`data/state/email_state.json`)
7. **Monitor disk space** in watch directory in case of parser failures

---

## Support

For issues and questions:
- Check logs: `docker-compose logs -f`
- Review error directory: `ls -la data/watch/errors/`
- Verify environment variables: `docker-compose config`
- GitHub Issues: https://github.com/YOUR_USERNAME/pcr_utils/issues
