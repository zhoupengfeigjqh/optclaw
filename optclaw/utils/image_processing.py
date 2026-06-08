"""Image compression for reducing token usage when sending images to LLM."""

import io

from PIL import Image

from optclaw.log import setup_logging
logger = setup_logging(__name__)

MAX_DIMENSION = 2048
TARGET_BYTES = 20 * 1024


def compress_image(image_data: bytes) -> tuple[bytes, str]:
    """Compress image to fit within TARGET_BYTES, then encode as JPEG.

    Images already under the threshold are returned unchanged.
    Returns (bytes, mime_type).
    """
    original_size = len(image_data)

    if original_size <= TARGET_BYTES:
        mime = _guess_mime(image_data)
        logger.warning("image %d bytes, under threshold, skip", original_size)
        return image_data, mime

    img = Image.open(io.BytesIO(image_data))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    # Scale down huge images first
    w, h = img.size
    if w > MAX_DIMENSION or h > MAX_DIMENSION:
        img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)

    # Binary search quality to fit under target
    lo, hi = 5, 95
    best = None
    for _ in range(6):
        mid = (lo + hi) // 2
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=mid)
        size = buf.tell()
        if size <= TARGET_BYTES:
            best = buf.getvalue()
            lo = mid + 1
        else:
            hi = mid - 1

    if best is not None and len(best) <= TARGET_BYTES:
        logger.warning("image %d→%d bytes", original_size, len(best))
        return best, "image/jpeg"

    # Quality alone wasn't enough — scale down further
    while True:
        w2, h2 = img.size
        if w2 <= 1 and h2 <= 1:
            break
        img.thumbnail((w2 // 2, h2 // 2), Image.LANCZOS)
        for q in range(70, 0, -10):
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=q)
            if buf.tell() <= TARGET_BYTES:
                result = buf.getvalue()
                logger.warning("image %d→%d bytes", original_size, len(result))
                return result, "image/jpeg"

    result = best if best else io.BytesIO().getvalue()
    logger.warning("image %d→%d bytes, could not meet target", original_size, len(result))
    return result, "image/jpeg"


def _guess_mime(image_data: bytes) -> str:
    """Guess MIME type from image header bytes."""
    try:
        img = Image.open(io.BytesIO(image_data))
        fmt = img.format
        if fmt == "JPEG":
            return "image/jpeg"
        if fmt == "PNG":
            return "image/png"
        if fmt == "WEBP":
            return "image/webp"
        if fmt == "GIF":
            return "image/gif"
    except Exception:
        pass
    return "image/jpeg"
