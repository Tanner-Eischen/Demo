FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY worker/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

ARG INSTALL_PLAYWRIGHT=0
RUN if [ "$INSTALL_PLAYWRIGHT" = "1" ]; then \
      pip install --no-cache-dir playwright==1.50.0 && \
      playwright install --with-deps chromium; \
    fi

COPY backend/app /app/backend/app
COPY worker /app/worker
COPY schemas /app/schemas
COPY prompts /app/prompts

ENV PYTHONPATH=/app

CMD ["python", "worker/worker.py"]
