"""Image compression for reducing token usage when sending images to LLM."""

import io
import re
import secrets
from pathlib import Path

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


def compress_images_in_dir(image_dir: Path, existing: set[Path] | None = None,
                            randomize_name: bool = False) -> dict[str, str]:
    """Compress newly created images in a directory after pymupdf4llm extraction.

    Returns a dict mapping old filename → new filename for updating markdown
    references (e.g. when PNG is converted to JPEG, or names are randomized).
    """
    if existing is None:
        existing = set()

    replacements: dict[str, str] = {}
    for img_path in sorted(image_dir.iterdir()):
        if img_path in existing or not img_path.is_file():
            continue
        if img_path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            continue
        try:
            data = img_path.read_bytes()
            compressed, mime = compress_image(data)
            new_suffix = ".jpg" if mime == "image/jpeg" else img_path.suffix.lower()

            if randomize_name:
                # Extract base name from pymupdf4llm naming:
                # "test.pdf-0001-01.png" → "test.pdf"
                old_stem = img_path.stem
                base = re.sub(r'-\d{4}-\d{2}$', '', old_stem)
                while True:
                    stem = secrets.token_hex(4)
                    new_path = img_path.with_name(f"{base}_{stem}{new_suffix}")
                    if not new_path.exists():
                        break
            else:
                new_path = img_path.with_suffix(new_suffix)

            if new_path != img_path:
                new_path.write_bytes(compressed)
                img_path.unlink()
                replacements[img_path.name] = new_path.name
            elif compressed != data:
                img_path.write_bytes(compressed)
        except Exception:
            logger.warning("Failed to compress %s", img_path, exc_info=True)

    return replacements
