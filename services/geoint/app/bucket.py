"""
OCI Object Storage helper for the GEOINT service.

Uploads scene images to the bucket configured via env vars and returns the
object name written to ``satellite_scenes.image_uri``. Mirrors the graceful
degradation contract used by ``services.compliance.app.routers.live_checks``:
when the OCI SDK or instance principal is unavailable (e.g. virtual nodes
without IMDS), :func:`upload_scene_image` returns ``None`` instead of raising
so an upload still ingests detections + metadata into the database.

Required env (read at call time so unit tests can monkey-patch):
    OCI_BUCKET_NAMESPACE  Object Storage namespace (e.g. tenancy slug).
    OCI_BUCKET_NAME       Bucket name (default: ``sovdefence-images``).

Optional env:
    OCI_BUCKET_PREFIX     Prefix prepended to every object name.
                          Defaults to ``scenes``.
"""
from __future__ import annotations

import logging
import mimetypes
import os
import uuid
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_BUCKET_NAME = "sovdefence-images"
DEFAULT_PREFIX = "scenes"


def _bucket_config() -> tuple[str | None, str, str]:
    namespace = os.environ.get("OCI_BUCKET_NAMESPACE")
    bucket = os.environ.get("OCI_BUCKET_NAME", DEFAULT_BUCKET_NAME)
    prefix = os.environ.get("OCI_BUCKET_PREFIX", DEFAULT_PREFIX).strip("/")
    return namespace, bucket, prefix


def build_object_name(tenant_id: str, filename: str | None, prefix: str) -> str:
    """Build the bucket object name for a scene upload.

    Layout: ``<prefix>/tenant=<tenant>/<uuid>-<sanitised-filename>``.
    Hyphenated UUID guarantees uniqueness independent of DB-side ``scene_id``
    (which is generated *after* upload completes).
    """
    safe_name = (filename or "scene.bin").rsplit("/", 1)[-1]
    safe_name = "".join(ch if ch.isalnum() or ch in (".", "_", "-") else "_"
                        for ch in safe_name)[:120] or "scene.bin"
    parts = [p for p in (prefix, f"tenant={tenant_id}",
                         f"{uuid.uuid4().hex}-{safe_name}") if p]
    return "/".join(parts)


def _signer() -> Any:
    """Lazily build an InstancePrincipals signer.

    Imported inside the function so the FastAPI app stays importable in test
    environments where the ``oci`` SDK isn't installed.
    """
    import oci  # type: ignore[import-not-found]

    return oci.auth.signers.InstancePrincipalsSecurityTokenSigner()


def upload_scene_image(
    tenant_id: str,
    image_bytes: bytes,
    filename: str | None,
    content_type: str | None = None,
) -> str | None:
    """Upload ``image_bytes`` to the configured bucket.

    Returns the object name on success, or ``None`` if any step fails
    (missing config, SDK absent, IMDS unreachable, network error, ...).
    Callers persist whatever this returns into ``image_uri`` — ``NULL`` is a
    valid value meaning "image was processed but not persisted to bucket".
    """
    namespace, bucket, prefix = _bucket_config()
    if not namespace:
        logger.warning("OCI_BUCKET_NAMESPACE not set — skipping bucket upload")
        return None

    object_name = build_object_name(tenant_id, filename, prefix)
    ctype = (content_type
             or (mimetypes.guess_type(filename or "")[0] if filename else None)
             or "application/octet-stream")

    try:
        import oci  # type: ignore[import-not-found]

        client = oci.object_storage.ObjectStorageClient(
            config={}, signer=_signer())
        client.put_object(
            namespace_name=namespace,
            bucket_name=bucket,
            object_name=object_name,
            put_object_body=image_bytes,
            content_type=ctype,
        )
        logger.info("uploaded scene image to oci://%s/%s/%s (%d bytes)",
                    namespace, bucket, object_name, len(image_bytes))
        return object_name
    except Exception:  # pragma: no cover — depends on OCI runtime
        logger.exception(
            "OCI Object Storage upload failed (oci://%s/%s/%s) — continuing without image_uri",
            namespace, bucket, object_name,
        )
        return None
