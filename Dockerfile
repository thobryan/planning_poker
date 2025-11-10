FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=poker_site.settings \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --shell /bin/bash django \
    && mkdir -p /app/staticfiles /app/media \
    && chown -R django:django /app

USER django

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "poker_site.wsgi:application", "--bind=0.0.0.0:8000"]
