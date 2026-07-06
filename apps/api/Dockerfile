FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/apps/api

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY migrations ./migrations
COPY apps/api ./apps/api
COPY scripts/docker_api_entrypoint.sh ./scripts/docker_api_entrypoint.sh

RUN chmod +x ./scripts/docker_api_entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./scripts/docker_api_entrypoint.sh"]

