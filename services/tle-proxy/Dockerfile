# TLE Proxy (Sovereign Proxy Pattern A — REST poll, no aggregation).
#
# Pulls three CelesTrak catalogs (stations / resource / active) every
# TLE_REFRESH_HOURS (default 6) and persists each as a separate row in
# osint_cache: layer='satellites-stations', 'satellites-resource',
# 'satellites-active'. The browser fetches the raw TLE blob and runs
# the orbit propagation client-side via satellite.js — backend stays
# light (no per-second math, no H3, no classifier).
FROM python:3.11-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PROXY_PORT=8010
WORKDIR /app
COPY --from=builder /install /usr/local
COPY app ./app
RUN groupadd --gid 1000 appuser \
 && useradd --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin appuser \
 && chown -R 1000:1000 /app
USER 1000
EXPOSE 8010
ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
