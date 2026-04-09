"""
Image-to-SVG conversion pipeline.

Uses vtracer (Rust-based raster-to-vector engine) for high-quality tracing,
then scour for SVG cleanup and optimization.
"""

import io

from PIL import Image, ImageStat
from scour.scour import generateDefaultOptions, sanitizeOptions, scourString
import vtracer

# ---------------------------------------------------------------------------
# Quality presets — tuned for logo / brand mark use cases
# ---------------------------------------------------------------------------

PRESETS = {
    "fast": {
        "colormode": "color",
        "hierarchical": "cutout",
        "filter_speckle": 8,
        "color_precision": 4,
        "corner_threshold": 60,
        "length_threshold": 6.0,
        "splice_threshold": 45,
        "path_precision": 4,
        "scour_digits": 2,
    },
    "balanced": {
        "colormode": "color",
        "hierarchical": "cutout",
        "filter_speckle": 4,
        "color_precision": 6,
        "corner_threshold": 60,
        "length_threshold": 4.0,
        "splice_threshold": 45,
        "path_precision": 6,
        "scour_digits": 4,
    },
    "high_quality": {
        "colormode": "color",
        "hierarchical": "cutout",
        "filter_speckle": 2,
        "color_precision": 8,
        "corner_threshold": 60,
        "length_threshold": 2.0,
        "splice_threshold": 45,
        "path_precision": 8,
        "scour_digits": 5,
    },
}

# Keys that belong to vtracer (exclude internal keys like scour_digits)
_VTRACER_KEYS = {
    "colormode", "hierarchical", "filter_speckle", "color_precision",
    "corner_threshold", "length_threshold", "splice_threshold", "path_precision",
}

# Max dimension (px) before downscaling — keeps memory usage low on free-tier hosts
_MAX_DIM = 1024
# Min dimension (px) before upscaling — ensures vtracer has enough data for clean curves
_MIN_DIM = 256


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_grayscale(img: Image.Image) -> bool:
    """Return True if the image is essentially monochrome / grayscale."""
    rgb = img.convert("RGB")
    stat = ImageStat.Stat(rgb)
    r, g, b = stat.mean
    max_diff = max(abs(r - g), abs(g - b), abs(r - b))
    return max_diff < 10


def _has_white_background(img: Image.Image) -> bool:
    """Return True when 3+ of the 4 corner pixels are near-white."""
    w, h = img.size
    corners = [
        img.getpixel((0, 0)),
        img.getpixel((w - 1, 0)),
        img.getpixel((0, h - 1)),
        img.getpixel((w - 1, h - 1)),
    ]
    white_count = sum(1 for c in corners if all(v > 240 for v in c[:3]))
    return white_count >= 3


def _resize_for_tracing(img: Image.Image) -> Image.Image:
    """Ensure the image is within the sweet-spot size range for vtracer."""
    w, h = img.size
    longest = max(w, h)

    if longest < _MIN_DIM:
        scale = _MIN_DIM / longest
        new_w, new_h = int(w * scale), int(h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)
    elif longest > _MAX_DIM:
        scale = _MAX_DIM / longest
        new_w, new_h = int(w * scale), int(h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)

    return img


def _remove_white_background(img: Image.Image) -> Image.Image:
    """Make near-white pixels transparent (flood from corners)."""
    img = img.copy()
    pixels = img.load()
    w, h = img.size

    # Walk every pixel — for logo-sized images this is fast enough
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if r > 240 and g > 240 and b > 240:
                pixels[x, y] = (r, g, b, 0)

    return img


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def preprocess_image(file_bytes: bytes, remove_bg: bool = False) -> bytes:
    """
    Load any supported raster format, normalise it, and return PNG bytes
    ready for vtracer ingestion.

    Raises ValueError for unrecognised image data.
    """
    try:
        img = Image.open(io.BytesIO(file_bytes))
    except Exception as exc:
        raise ValueError(f"Cannot read image: {exc}") from exc

    # For animated formats (GIF, WEBP) use the first frame
    try:
        img.seek(0)
    except (AttributeError, EOFError):
        pass

    # Work in RGBA throughout
    img = img.convert("RGBA")

    # Normalise size
    img = _resize_for_tracing(img)

    # If the image is fully opaque, composite over white so vtracer background
    # is clean — unless the caller wants the background removed
    alpha = img.split()[-1]
    has_real_transparency = min(alpha.getdata()) < 255  # type: ignore[arg-type]

    if not has_real_transparency:
        # Fully opaque image (e.g. JPEG converted to RGBA)
        if remove_bg and _has_white_background(img):
            img = _remove_white_background(img)
        else:
            # Composite on white so vtracer does not add a background rectangle
            white = Image.new("RGBA", img.size, (255, 255, 255, 255))
            white.paste(img, mask=img.split()[-1])
            img = white
    else:
        # Image already has transparency (transparent PNG logo)
        if remove_bg and _has_white_background(img):
            img = _remove_white_background(img)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def convert_to_svg(
    image_bytes: bytes,
    preset: str = "balanced",
    remove_bg: bool = False,
) -> str:
    """
    Convert raw image bytes to an optimised SVG string.

    Args:
        image_bytes: Raw bytes of any PIL-supported image format.
        preset: One of "fast", "balanced", "high_quality".
        remove_bg: If True, attempt to remove near-white background pixels.

    Returns:
        UTF-8 SVG string.

    Raises:
        ValueError: If the image cannot be decoded.
        RuntimeError: If vtracer or scour fail.
    """
    params = PRESETS.get(preset, PRESETS["balanced"])

    # Preprocess to PNG bytes
    png_bytes = preprocess_image(image_bytes, remove_bg)

    # Auto-detect grayscale → use binary mode for sharper single-colour paths
    try:
        probe = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        if _is_grayscale(probe):
            params = {**params, "colormode": "binary"}
    except Exception:
        pass

    # Build vtracer kwargs (exclude internal keys)
    vtracer_kwargs = {k: v for k, v in params.items() if k in _VTRACER_KEYS}

    try:
        svg_str = vtracer.convert_raw_image_to_svg(png_bytes, **vtracer_kwargs)
    except Exception as exc:
        raise RuntimeError(f"vtracer conversion failed: {exc}") from exc

    # Clean and optimise with scour
    try:
        opts = generateDefaultOptions()
        opts.infilename = None
        opts.outfilename = None
        opts.strip_comments = True
        opts.strip_ids = False
        opts.shorten_ids = True
        opts.remove_metadata = True
        opts.remove_titles = True
        opts.remove_descriptions = True
        opts.strip_xml_prolog = False
        opts.newlines = True
        opts.digits = params["scour_digits"]
        opts = sanitizeOptions(opts)
        svg_str = scourString(svg_str, opts)
    except Exception as exc:
        # Scour failure is non-fatal — return raw vtracer output
        pass

    return svg_str
