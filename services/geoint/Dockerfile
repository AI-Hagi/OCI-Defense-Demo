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
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Bake the baseline YOLOv8 nano weights into the image. OKE virtual nodes
# have no egress to github.com, so a runtime fetch (the ultralytics default)
# fails with "Retry limit reached".
RUN curl -fsSL -o /app/yolov8n.pt \
    https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n.pt
ENV YOLO_WEIGHTS=/app/yolov8n.pt

COPY app ./app

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
