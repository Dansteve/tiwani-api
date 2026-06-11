# tiwani-api container for Google Cloud Run (see Docs/Deploy.md).
# Cloud Run injects $PORT (default 8080); uvicorn binds to it. Build context is this repo;
# .dockerignore keeps venv / tests / secrets out of the image.
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
