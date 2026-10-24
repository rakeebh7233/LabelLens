# Stage 1: build the frontend
FROM node:22-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime with Tesseract. opencv-python-headless needs no libGL or X libraries.
FROM python:3.12-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY --from=frontend /frontend/dist ./frontend_dist

# Run as an unprivileged user; the app never writes to disk.
RUN useradd --create-home --uid 1000 labellens
USER labellens

# OMP_THREAD_LIMIT=1: one thread per Tesseract process; the batch pool provides parallelism.
# PORT is set by hosts such as Render; 8000 locally.
ENV LABELLENS_FRONTEND_DIST=/app/frontend_dist \
    OMP_THREAD_LIMIT=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health', timeout=4)"
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
