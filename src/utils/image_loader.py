from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

import httpx


async def load_image_as_base64(source: str) -> tuple[str, str]:
    """이미지를 base64로 로드. source는 파일 경로 또는 URL."""
    if source.startswith(("http://", "https://")):
        async with httpx.AsyncClient() as client:
            resp = await client.get(source, follow_redirects=True, timeout=30.0)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "image/png").split(";")[0]
            return base64.standard_b64encode(resp.content).decode(), content_type

    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {source}")
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    return base64.standard_b64encode(path.read_bytes()).decode(), mime
