# GPS Jamming Poller (Sovereign Proxy Pattern A — daily REST poll + H3 transform).
#
# Pulls https://gpsjam.org/data/YYYY-MM-DD.csv once a day, transforms the
# H3 hex cell index → polygon GeoJSON, classifies by NACp-low ratio, caches
# the result in 26ai osint_cache. The HTTP GET /api/osint/jamming/current
# serves out of the cache only — never proxies live to gpsjam.org.
#
# Runtime mounts:
#   - Oracle wallet at /app/wallet (read-only Kubernetes Secret)
# No vault key needed (gpsjam.org has no API key).
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

COPY requirements.txt ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# -------- runtime image --------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POLLER_PORT=8007

WORKDIR /app

COPY --from=builder /install /usr/local

COPY app ./app

RUN groupadd --gid 1000 appuser \
 && useradd --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin appuser \
 && chown -R 1000:1000 /app
USER 1000

EXPOSE 8007

ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8007"]
