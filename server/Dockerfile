# ==========================================
# STAGE 1: BASE (Core Dependencies)
# ==========================================
FROM python:3.11-slim AS base
WORKDIR /app

COPY ./server/requirements.txt .

# Install CPU PyTorch first
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
# Install the rest of the requirements
RUN pip install --no-cache-dir -r requirements.txt


# ==========================================
# STAGE 2: PROD (Lightweight & Secure)
# ==========================================
FROM base AS prod

# Copy the actual app code into the container
# Copy both folders from the root context into the container
COPY ./server /app/server
COPY ./shared /app/shared
# Chainlit config + welcome page
COPY ./.chainlit /app/.chainlit
COPY ./chainlit.md /app/chainlit.md
ENV PYTHONPATH=/app

# Clean production execution without debug tools
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]


# ==========================================
# STAGE 3: DEV/TEST (Debugging Tools Added)
# ==========================================
FROM base AS dev

# Install OS-level debugging tools
RUN apt-get update && apt-get install -y \
    htop \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Install Python testing/debugging tools
# (It is best practice to keep these out of your main requirements.txt)
RUN pip install debugpy pytest

# Your custom debug/reload command
CMD ["sh", "-c", "if [ \"$DEBUG\" = \"1\" ]; then python -m debugpy --listen 0.0.0.0:5678 -m uvicorn server.main:app --host 0.0.0.0 --port 8000; else uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload; fi"]



# FROM python:3.11-slim

# WORKDIR /app

# COPY requirements.txt .

# #! Get the cpu torch version to avoid installing the cuda version which is not compatible with the base image 
# RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
# RUN pip install --no-cache-dir -r requirements.txt

# #! DEV IMAGE (this give the image the ability to run htop and other tools for debugging)
# RUN apt-get update && apt-get install -y \
#     htop \
#     procps \
#     && rm -rf /var/lib/apt/lists/*

    
# #CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# CMD ["sh", "-c", "if [ \"$DEBUG\" = \"1\" ]; then python -m debugpy --listen 0.0.0.0:5678 -m uvicorn server.main:app --host 0.0.0.0 --port 8000; else uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload; fi"]

