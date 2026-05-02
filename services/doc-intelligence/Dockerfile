# Document Intelligence service (FastAPI + Sentence-Transformers).
#
# Mount the Oracle 26ai ATP wallet at runtime (not baked in):
#   docker run -v /secrets/sovdef26_wallet:/app/wallet:ro ...
# or via a Kubernetes Secret volume mounted at /app/wallet.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8002

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
