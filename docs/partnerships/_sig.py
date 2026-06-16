"""Shared signature helper for the partnership/beta letters.

Save the scanned signature to SIG_RAW (see below). This module trims the
paper background to transparent (keeps only the dark ink), autocrops to the
strokes, and returns a reportlab Image flowable sized for a signature block.
If the raw file is absent it returns None so the letter falls back to a
plain signature rule.
"""
from __future__ import annotations

from pathlib import Path

# Where the operator saves the scanned signature.
SIG_RAW = Path(r"C:\Users\HP\Downloads\signature.png")
SIG_CLEAN = Path(__file__).parent / "_signature_clean.png"

# Pixels brighter than this (0-255 luminance) are treated as paper → made
# transparent. The ink is dark; the paper is light, so a high threshold keeps
# only the strokes even on tinted/photographed paper.
_PAPER_LUMA = 165


def _clean() -> tuple[int, int] | None:
    """Make paper transparent + autocrop. Returns (w, h) of the cleaned PNG."""
    if not SIG_RAW.exists():
        return None
    from PIL import Image

    img = Image.open(SIG_RAW).convert("RGBA")
    px = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b, _ = px[x, y]
            if (0.299 * r + 0.587 * g + 0.114 * b) > _PAPER_LUMA:
                px[x, y] = (255, 255, 255, 0)  # transparent paper
            else:
                px[x, y] = (40, 40, 90, 255)   # normalise ink to dark ink-blue
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)
    img.save(SIG_CLEAN)
    return img.size


def signature_image(target_width: float = 150):
    """Return a reportlab Image of the cleaned signature, or None if no file.

    Args:
        target_width: rendered width in points; height keeps aspect ratio.
    """
    size = _clean()
    if size is None:
        return None
    from reportlab.platypus import Image as RLImage

    w, h = size
    return RLImage(str(SIG_CLEAN), width=target_width,
                   height=target_width * h / w)
