"""
Thin wrapper around Sentinel Hub WMS GetMap.

The WMS request shape (verified manually against the Bornholm bbox):

  GET {SENTINEL_WMS_BASE}/{INSTANCE_ID}
       ?SERVICE=WMS
       &REQUEST=GetMap
       &VERSION=1.3.0
       &LAYERS={layer}
       &STYLES=
       &CRS=EPSG:3857
       &BBOX={x_min},{y_min},{x_max},{y_max}
       &WIDTH={size}&HEIGHT={size}
       &FORMAT=image/png
       &TRANSPARENT=true
       &MAXCC={maxcc}
   Authorization: Bearer {token}

Returns the raw PNG bytes. The proxy streams those back to the browser
unchanged; we don't decode/recompress.
"""
from __future__ import annotations

from typing import Optional

import httpx
import structlog

from .settings import Settings

logger = structlog.get_logger(__name__)


class WmsError(RuntimeError):
    """Raised when the upstream WMS returns a non-PNG response."""

    def __init__(self, status: int, content_type: str, body_preview: str) -> None:
        super().__init__(
            f"WMS upstream status={status} content_type={content_type} body={body_preview[:200]}"
        )
        self.status = status
        self.content_type = content_type
        self.body_preview = body_preview


def build_wms_url(
    settings: Settings,
    layer: str,
    bbox_3857: tuple[float, float, float, float],
) -> str:
    """Compose the GetMap URL — public-facing details only, no auth."""
    x_min, y_min, x_max, y_max = bbox_3857
    base = settings.sentinel_wms_base.rstrip("/")
    return (
        f"{base}/{settings.sentinel_instance_id}"
        f"?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0"
        f"&LAYERS={layer}"
        f"&STYLES="
        f"&CRS=EPSG:3857"
        f"&BBOX={x_min:.3f},{y_min:.3f},{x_max:.3f},{y_max:.3f}"
        f"&WIDTH={settings.sentinel_tile_size}&HEIGHT={settings.sentinel_tile_size}"
        f"&FORMAT=image/png&TRANSPARENT=true"
        f"&MAXCC={settings.sentinel_maxcc}"
    )


async def fetch_tile(
    settings: Settings,
    token: str,
    layer: str,
    bbox_3857: tuple[float, float, float, float],
    client: Optional[httpx.AsyncClient] = None,
) -> bytes:
    """
    Issue one WMS GetMap call, return PNG bytes. Raises WmsError if the
    upstream returns a non-image response or non-200 status.
    """
    url = build_wms_url(settings, layer, bbox_3857)

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=30.0)

    try:
        resp = await client.get(  # type: ignore[union-attr]
            url, headers={"Authorization": f"Bearer {token}"}
        )
    finally:
        if owns_client:
            await client.aclose()  # type: ignore[union-attr]

    content_type = resp.headers.get("content-type", "")
    if resp.status_code != 200 or not content_type.startswith("image/"):
        raise WmsError(
            resp.status_code, content_type, resp.text if resp.text else ""
        )
    return resp.content


async def fetch_capabilities(
    settings: Settings, client: Optional[httpx.AsyncClient] = None
) -> str:
    """
    Pull the Sentinel Hub Configuration GetCapabilities XML. No auth needed
    for the public Configuration endpoint. Returns the raw XML.
    """
    base = settings.sentinel_wms_base.rstrip("/")
    url = (
        f"{base}/{settings.sentinel_instance_id}"
        f"?SERVICE=WMS&REQUEST=GetCapabilities&VERSION=1.3.0"
    )
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=15.0)
    try:
        resp = await client.get(url)  # type: ignore[union-attr]
    finally:
        if owns_client:
            await client.aclose()  # type: ignore[union-attr]
    if resp.status_code != 200:
        raise WmsError(resp.status_code, resp.headers.get("content-type", ""), resp.text)
    return resp.text


def parse_layers_from_capabilities(xml_text: str) -> list[dict]:
    """
    Extract a flat list of {name, title} for child <Layer> blocks.

    No xml.etree dependency — the GetCapabilities document is small enough
    that a regex pass beats pulling in lxml. We only care about the leaf
    Layer elements; the root <Layer> with the CRS list is filtered out by
    requiring a <Name>.
    """
    import re

    layers: list[dict] = []
    for block in re.findall(r"<Layer[^>]*>(.*?)</Layer>", xml_text, re.DOTALL):
        name_match = re.search(r"<Name>([^<]+)</Name>", block)
        if not name_match:
            continue
        title_match = re.search(r"<Title>([^<]+)</Title>", block)
        layers.append(
            {
                "name": name_match.group(1).strip(),
                "title": (title_match.group(1).strip() if title_match else ""),
            }
        )
    return layers
