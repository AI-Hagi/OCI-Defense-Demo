# UC4 Chat Service — LLM tool-calling orchestrator (Step 1: HTTP only).
#
# Drives a Cohere Command R+ chat loop over the existing UC4 backends
# (flights-proxy, ais-multiplexer, jamming-poller, osint-fusion ORDS proxy).
# Every tool invocation goes through this service so the audit_log row is
# written before the upstream call leaves the cluster.
FROM python:3.11-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CHAT_PORT=8013
WORKDIR /app
COPY --from=builder /install /usr/local
COPY app ./app
RUN groupadd --gid 1000 appuser \
 && useradd --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin appuser \
 && chown -R 1000:1000 /app
USER 1000
EXPOSE 8013
ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8013"]
