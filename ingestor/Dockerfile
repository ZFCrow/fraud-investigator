# ==========================================
# 1. Base Stage: Core Dependencies
# ==========================================
FROM python:3.11-slim AS base

WORKDIR /app/ingestor
COPY ./ingestor/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt 


# ==========================================
# STAGE 2: PROD (Lightweight & Secure)
# ==========================================
FROM base AS prod

# Bake the source code permanently into the image
COPY ./shared /app/shared
COPY ./ingestor /app/ingestor

# Run the script directly without debugpy overhead
CMD ["python", "main.py"] 


# ==========================================
# STAGE 3: DEV/TEST (Debugging Tools Added)
#! DEV IMAGE (this give the image the ability to run htop and other tools for debugging)
# ==========================================
FROM base AS dev

RUN apt-get update && apt-get install -y \
    htop \
    procps \
    && rm -rf /var/lib/apt/lists/*

CMD ["sh", "-c", "if [ \"$DEBUG\" = \"1\" ]; then python -m debugpy --listen 0.0.0.0:5678 main.py; else python main.py; fi"]