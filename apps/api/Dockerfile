FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/apps/api

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY manage.py ./manage.py
COPY manage.py ./launcher.py
COPY delivery ./delivery
COPY evaluation ./evaluation
COPY migrations ./migrations
COPY apps/api ./apps/api
COPY scripts ./scripts

RUN chmod +x ./scripts/docker/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./scripts/docker/entrypoint.sh"]
