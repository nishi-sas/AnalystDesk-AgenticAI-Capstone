# AnalystDesk Phase 9C — single-process local research API.
# Deliberately do NOT package .env, data, evidence or local model caches.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/home/analyst/.cache/huggingface \
    HF_HUB_DISABLE_TELEMETRY=1 \
    OMP_NUM_THREADS=2 \
    HOME=/home/analyst

WORKDIR /app

# Torch / sentence-transformers need OpenMP. CPU-only PyTorch avoids enormous CUDA downloads.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements*.txt ./
COPY pyproject.toml ./
COPY src/ ./src/

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && python -m pip install --no-cache-dir \
       -r requirements-stage2b.txt \
       -r requirements-stage2c.txt \
       -r requirements-stage3d.txt \
       -r requirements-stage4a.txt \
       -r requirements-phase9a.txt \
       -r requirements-phase9b.txt \
    && python -m pip install --no-cache-dir -e . \
    && python -c "from analyst_desk.phase9_api import app; print('AnalystDesk API import OK')"

RUN useradd --create-home --shell /usr/sbin/nologin analyst \
    && mkdir -p /home/analyst/.cache/huggingface \
    && chown -R analyst:analyst /home/analyst
USER analyst

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=3).close()" || exit 1

CMD ["python", "-m", "uvicorn", "analyst_desk.phase9_api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
