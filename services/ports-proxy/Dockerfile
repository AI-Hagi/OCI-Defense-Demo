# Ports Proxy (Sovereign Proxy Pattern A — static-load with hybrid classifier).
#
# Pulls a one-shot OSM Overpass snapshot of ports into
# osint_cache(layer='ports'). Each OSM element is classified
# curated→OSM: the curated table (ports_curated) wins on a 5 km
# nearest-neighbor match; otherwise the OSM tags are mapped to a
# port_type. Browser fetches /api/osint/ports/current as a single
# GeoJSON FeatureCollection — no client-side propagation, no
# APScheduler refresh loop. /api/osint/ports/refresh re-runs the
# loader (X-Internal-Token auth) on operator demand.
FROM python:3.11-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PROXY_PORT=8011
WORKDIR /app
COPY --from=builder /install /usr/local
COPY app ./app
RUN groupadd --gid 1000 appuser \
 && useradd --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin appuser \
 && chown -R 1000:1000 /app
USER 1000
EXPOSE 8011
ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8011"]
