# AIS Multiplexer service (Sovereign Proxy Pattern B — WebSocket fan-out).
#
# Connects to wss://stream.aisstream.io/v0/stream (free tier, key from OCI Vault),
# normalises PositionReport frames, fans out to N browser WebSocket clients,
# and writes batched audit_events rows into Oracle 26ai ATP.
#
# Runtime mounts:
#   - Oracle wallet at /app/wallet (read-only Kubernetes Secret)
# Vault auth: Workload Identity / Instance Principal (no API keys in image).
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
    MULTIPLEXER_PORT=8001

WORKDIR /app

COPY --from=builder /install /usr/local

COPY app ./app

# Non-root user (UID 1000 matches OKE virtual-node default).
RUN groupadd --gid 1000 appuser \
 && useradd --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin appuser \
 && chown -R 1000:1000 /app
USER 1000

EXPOSE 8001

ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
