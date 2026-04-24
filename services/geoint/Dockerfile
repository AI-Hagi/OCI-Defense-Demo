# GEOINT service (FastAPI + YOLOv8) for the Sovereign Defence Intelligence Platform.
#
# The Oracle 26ai ATP wallet must be mounted at runtime (never baked in):
#   docker run -v /secrets/sovdef26_wallet:/app/wallet:ro ...
# or via a Kubernetes Secret volume mounted at /app/wallet.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps for pillow + opencv (ultralytics pulls opencv-python-headless)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
