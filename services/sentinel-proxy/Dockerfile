# Sentinel-2 Proxy (Sovereign Proxy Pattern C — WMS reverse-proxy with OAuth2).
#
# Translates browser-side tile requests /api/osint/sentinel/tiles/{layer}/{z}/{x}/{y}.png
# into Sentinel Hub WMS GetMap calls signed with a Bearer token from the
# Copernicus Dataspace OAuth2 client-credentials flow.
#
# Runtime mounts:
#   - Oracle wallet at /app/wallet (read-only Kubernetes Secret) — for audit
# Vault auth: ExternalSecret projects sentinel-* keys via envFrom.
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
    PROXY_PORT=8008

WORKDIR /app

COPY --from=builder /install /usr/local

COPY app ./app

RUN groupadd --gid 1000 appuser \
 && useradd --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin appuser \
 && chown -R 1000:1000 /app
USER 1000

EXPOSE 8008

ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8008"]
