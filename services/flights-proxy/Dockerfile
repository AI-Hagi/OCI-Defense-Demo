# Flights Proxy (Sovereign Proxy Pattern A — REST poll + hybrid classifier).
#
# Polls adsb.lol on REFRESH_MINUTES (default 2 min), classifies each aircraft
# as civil/mil via mil_aircraft_unified (curated > Mictronics community DB),
# persists two GeoJSON FeatureCollections in osint_cache: layer='flights-civil'
# and layer='flights-mil'. The browser fetches /api/osint/flights/{civil|mil}/current.
FROM python:3.11-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PROXY_PORT=8009
WORKDIR /app
COPY --from=builder /install /usr/local
COPY app ./app
RUN groupadd --gid 1000 appuser \
 && useradd --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin appuser \
 && chown -R 1000:1000 /app
USER 1000
EXPOSE 8009
ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8009"]
