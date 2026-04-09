"""
SVG Converter — FastAPI application entry point.

Serves the single-page frontend and exposes POST /api/convert for
image-to-SVG conversion.
"""

import asyncio
import os

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.converter import convert_to_svg

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="SVG Converter", docs_url=None, redoc_url=None)

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

# ---------------------------------------------------------------------------
# MIME types accepted at the API boundary
# ---------------------------------------------------------------------------

_ALLOWED_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/gif",
    "image/bmp",
    "image/x-bmp",
    "image/x-ms-bmp",
    "image/webp",
    "image/tiff",
    "application/octet-stream",  # some browsers send this for unknown types
}

_MAX_BYTES = 10 * 1024 * 1024  # 10 MB


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(_STATIC_DIR, "index.html"))


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/convert")
async def convert(
    file: UploadFile = File(...),
    preset: str = Form("balanced"),
    remove_bg: bool = Form(False),
) -> Response:
    """
    Convert an uploaded image to SVG.

    Form fields:
        file      — Image file (PNG, JPG, GIF, BMP, WEBP, TIFF)
        preset    — "fast" | "balanced" | "high_quality"  (default: balanced)
        remove_bg — "true" | "false" — attempt white-background removal
    """
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in _ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.content_type!r}. "
                   "Please upload PNG, JPG, GIF, BMP, WEBP, or TIFF.",
        )

    data = await file.read()

    if len(data) > _MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail="File exceeds the 10 MB limit.",
        )

    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    if preset not in ("fast", "balanced", "high_quality"):
        preset = "balanced"

    loop = asyncio.get_event_loop()
    try:
        svg = await loop.run_in_executor(
            None,
            _sync_convert,
            data,
            preset,
            remove_bg,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Build a safe filename for the download
    stem = os.path.splitext(file.filename or "output")[0]
    safe_stem = "".join(c if c.isalnum() or c in "-_." else "_" for c in stem)

    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_stem}.svg"',
            "Cache-Control": "no-store",
        },
    )


def _sync_convert(data: bytes, preset: str, remove_bg: bool) -> str:
    """Thin synchronous wrapper so run_in_executor can call it directly."""
    return convert_to_svg(data, preset=preset, remove_bg=remove_bg)
