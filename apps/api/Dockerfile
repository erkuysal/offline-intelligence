FROM python:3.14-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6 AS native-builder

RUN apt-get update \
    && apt-get install --no-install-recommends -y cmake gcc libc6-dev make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY native/vector_similarity ./native/vector_similarity
RUN cmake \
      -S native/vector_similarity \
      -B /tmp/vector-similarity-build \
      -DCMAKE_BUILD_TYPE=Release \
      -DBUILD_TESTING=OFF \
      -DCMAKE_INSTALL_PREFIX=/opt/oih-native \
    && cmake --build /tmp/vector-similarity-build --parallel \
    && cmake --install /tmp/vector-similarity-build


FROM python:3.14-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6

ARG OIH_SOURCE_REVISION=development
ARG OIH_SOURCE_DATE_EPOCH=0

LABEL org.opencontainers.image.revision="${OIH_SOURCE_REVISION}"
LABEL org.offline-intelligence-hub.source-date-epoch="${OIH_SOURCE_DATE_EPOCH}"

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/apps/api

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY environment.llama-build.yml environment.training.yml ./
COPY manage.py ./manage.py
COPY manage.py ./launcher.py
COPY delivery ./delivery
COPY evaluation ./evaluation
COPY training ./training
COPY config ./config
COPY migrations ./migrations
COPY apps/api ./apps/api
COPY scripts ./scripts
COPY --from=native-builder \
    /opt/oih-native/lib/liboih_vector_similarity.so \
    /app/apps/api/app/native/liboih_vector_similarity.so

RUN chmod +x ./scripts/docker/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./scripts/docker/entrypoint.sh"]
