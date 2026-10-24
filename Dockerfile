FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/pdflens
RUN useradd --create-home --uid 10001 appuser
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir '.[docling]'
COPY schemas ./schemas
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
