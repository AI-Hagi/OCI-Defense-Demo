#!/usr/bin/env bash
# =============================================================================
#  Upload trained YOLOv8 weights to the sovdefence-images bucket.
# -----------------------------------------------------------------------------
#  Usage:
#      bash scripts/upload-yolo-weights.sh \
#          runs/runs/mil-v1/weights/best.pt \
#          models/yolov8n-military-v1.pt
#
#  Args:
#      $1   local path to .pt file (default: runs/runs/mil-v1/weights/best.pt)
#      $2   object name in bucket (default: models/yolov8n-military-v1.pt)
#
#  Required env (or fall back to OCI CLI defaults via instance principal):
#      OCI_CLI_AUTH=instance_principal   when run on the dev VM
# =============================================================================
set -euo pipefail
IFS=$'\n\t'

LOCAL="${1:-runs/runs/mil-v1/weights/best.pt}"
OBJECT="${2:-models/yolov8n-military-v1.pt}"
BUCKET="${OCI_BUCKET_NAME:-sovdefence-images}"

[[ -f "$LOCAL" ]] || { echo "ERROR: weights file not found: $LOCAL" >&2; exit 1; }

NAMESPACE="$(oci os ns get --query data --raw-output)"
echo "[upload] $LOCAL  ->  oci://$NAMESPACE/$BUCKET/$OBJECT"
oci os object put \
    --namespace-name "$NAMESPACE" \
    --bucket-name "$BUCKET" \
    --name "$OBJECT" \
    --file "$LOCAL" \
    --force \
    --content-type application/octet-stream

echo "[upload] done"
oci os object head \
    --namespace-name "$NAMESPACE" \
    --bucket-name "$BUCKET" \
    --name "$OBJECT" \
    --query 'data."content-length"' --raw-output | xargs -I{} echo "[upload] size: {} bytes"
