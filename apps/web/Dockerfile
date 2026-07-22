FROM node:22-alpine@sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2 AS build

WORKDIR /app

COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci

COPY apps/web ./
RUN npm run build

FROM nginx:1.30.3-alpine@sha256:0d3b80406a13a767339fbe2f41406d6c7da727ab89cf8fae399e81f780f814d1

ARG OIH_SOURCE_REVISION=development
ARG OIH_SOURCE_DATE_EPOCH=0

LABEL org.opencontainers.image.revision="${OIH_SOURCE_REVISION}"
LABEL org.offline-intelligence-hub.source-date-epoch="${OIH_SOURCE_DATE_EPOCH}"

COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD wget -q -O /dev/null http://127.0.0.1/web-health || exit 1
