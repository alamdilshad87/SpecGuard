# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
# The pip cache mount keeps downloaded wheels between builds, so a retry after a dropped
# connection resumes instead of starting over; timeout/retries help on slow links.
RUN --mount=type=cache,target=/root/.cache/pip pip install --default-timeout=120 --retries 10 -r requirements.txt

# Bake the embedding model into the image so the API starts fast and works offline.
ENV SPECGUARD_EMBEDDING_CACHE_DIR=/opt/models
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/opt/models')"

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app

EXPOSE 8000
# Apply migrations, then serve.
CMD ["sh", "-c", "python -m app.migrate && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
