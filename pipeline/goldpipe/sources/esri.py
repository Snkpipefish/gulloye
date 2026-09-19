"""Esri World Imagery-fliser (nøkkelfritt, krever attribusjon) til satellittsjekk-utsnitt."""
from __future__ import annotations

import math

from PIL import Image, ImageDraw

from ..cache import cached_get

TILE = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
ATTRIB = "Esri, Maxar, Earthstar Geographics, GIS User Community"


def _tile_xy(lat, lon, z):
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


def crop(lat: float, lon: float, z: int = 17, size: int = 512) -> tuple[Image.Image, float]:
    """Kvadratisk utsnitt sentrert på punktet. Returnerer (bilde, meter per piksel)."""
    fx, fy = _tile_xy(lat, lon, z)
    cx, cy = int(fx), int(fy)
    canvas = Image.new("RGB", (256 * 3, 256 * 3))
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            p = cached_get(TILE.format(z=z, x=cx + dx, y=cy + dy), suffix=".jpg", subdir="esri", min_bytes=500)
            canvas.paste(Image.open(p).convert("RGB"), ((dx + 1) * 256, (dy + 1) * 256))
    px = int((fx - cx + 1) * 256), int((fy - cy + 1) * 256)
    box = (px[0] - size // 2, px[1] - size // 2, px[0] + size // 2, px[1] + size // 2)
    img = canvas.crop(box)
    m_per_px = 156543.03 * math.cos(math.radians(lat)) / (2 ** z)
    return img, m_per_px


def annotate(img: Image.Image, m_per_px: float, title: str = "") -> Image.Image:
    d = ImageDraw.Draw(img)
    w, h = img.size
    c = (w // 2, h // 2)
    col = (255, 230, 0)
    d.ellipse((c[0] - 8, c[1] - 8, c[0] + 8, c[1] + 8), outline=col, width=2)
    d.line((c[0] - 22, c[1], c[0] - 10, c[1]), fill=col, width=2)
    d.line((c[0] + 10, c[1], c[0] + 22, c[1]), fill=col, width=2)
    d.line((c[0], c[1] - 22, c[0], c[1] - 10), fill=col, width=2)
    d.line((c[0], c[1] + 10, c[0], c[1] + 22), fill=col, width=2)
    bar = int(100 / m_per_px)
    d.rectangle((10, h - 18, 10 + bar, h - 14), fill=(255, 255, 255))
    d.text((10, h - 32), "100 m", fill=(255, 255, 255))
    if title:
        d.rectangle((0, 0, w, 18), fill=(0, 0, 0))
        d.text((6, 3), title, fill=(255, 255, 255))
    return img
