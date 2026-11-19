FROM python:3.13-slim AS runtime
ARG INSTALL_WHISPERX=0
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HOME=/studio/data/hf-cache
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core libsndfile1 curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt /app/requirements.txt
COPY backend/requirements-video.txt /app/requirements-video.txt
COPY backend/requirements-clips.txt /app/requirements-clips.txt
RUN pip install --no-cache-dir -r requirements.txt -r requirements-video.txt
RUN if [ "$INSTALL_WHISPERX" = "1" ]; then pip install --no-cache-dir -r requirements-clips.txt; fi
# Chromium for optional news headline/excerpt screenshots.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN python -m playwright install --with-deps chromium && chmod -R a+rX /ms-playwright
COPY backend /app/backend
COPY agents /app/agents
COPY templates /app/templates
RUN useradd --uid 10001 --create-home studio && mkdir -p /studio && chown studio:studio /studio
USER studio
CMD ["uvicorn", "backend.api:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS test
USER root
RUN pip install --no-cache-dir pytest==8.4.2
COPY tests /app/tests
COPY scripts /app/scripts
USER studio
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
