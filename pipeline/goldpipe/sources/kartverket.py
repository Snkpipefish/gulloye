"""Kartverket: høydemodell (WCS 1.0.0, EPSG:25833), topo-WMTS, historiske kart (WMS)."""
from __future__ import annotations

import io
import math

import numpy as np
import rasterio
from PIL import Image
from rasterio.transform import from_origin

from ..cache import cached_get

WCS_DTM = "https://wcs.geonorge.no/skwms1/wcs.hoyde-dtm-nhm-25833"
WMS_HIST = "https://wms.geonorge.no/skwms1/wms.historiskekart"
WMTS_TOPO = "https://cache.kartverket.no/v1/wmts/1.0.0/{layer}/default/webmercator/{z}/{y}/{x}.png"
MAX_PX = 2000  # verifisert: 2000×2000 GeoTIFF ~9 s, 3000 gir timeout


def fetch_dtm(bbox_utm: tuple[float, float, float, float], res: float = 10.0):
    """Henter DTM (NHM, 25833) for bbox (minx, miny, maxx, maxy) i meter. Returnerer (array, transform).
    Store områder deles i fliser på maks MAX_PX piksler."""
    minx, miny, maxx, maxy = bbox_utm
    minx, miny = math.floor(minx / res) * res, math.floor(miny / res) * res
    maxx, maxy = math.ceil(maxx / res) * res, math.ceil(maxy / res) * res
    W, Hh = int(round((maxx - minx) / res)), int(round((maxy - miny) / res))
    out = np.full((Hh, W), np.nan, dtype=np.float32)
    nx, ny = math.ceil(W / MAX_PX), math.ceil(Hh / MAX_PX)
    for iy in range(ny):
        for ix in range(nx):
            c0, r0 = ix * MAX_PX, iy * MAX_PX
            c1, r1 = min(W, c0 + MAX_PX), min(Hh, r0 + MAX_PX)
            tx0, tx1 = minx + c0 * res, minx + c1 * res
            ty1, ty0 = maxy - r0 * res, maxy - r1 * res
            params = {
                "SERVICE": "WCS", "VERSION": "1.0.0", "REQUEST": "GetCoverage", "COVERAGE": "NHM_DTM_25833",
                "CRS": "EPSG:25833", "BBOX": f"{tx0},{ty0},{tx1},{ty1}", "WIDTH": c1 - c0, "HEIGHT": r1 - r0,
                "FORMAT": "GeoTIFF",
            }
            p = cached_get(WCS_DTM, params, suffix=".tif", subdir="dtm", timeout=600, min_bytes=1000)
            with rasterio.open(p) as d:
                a = d.read(1).astype(np.float32)
                if d.nodata is not None:
                    a[a == d.nodata] = np.nan
            a[a < -500] = np.nan
            out[r0:r1, c0:c1] = a[: r1 - r0, : c1 - c0]
    return out, from_origin(minx, maxy, res, res)


def sample_dtm(dtm: np.ndarray, transform, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Bilineær sampling av DTM i UTM-koordinater."""
    cols = (xs - transform.c) / transform.a
    rows = (ys - transform.f) / transform.e
    from scipy.ndimage import map_coordinates
    return map_coordinates(dtm, [rows, cols], order=1, mode="nearest")


def fill_nan(dtm: np.ndarray) -> np.ndarray:
    """Erstatter NaN (hav/manglende) med median – gjøres én gang før sampling."""
    if np.isnan(dtm).any():
        return np.where(np.isnan(dtm), np.nanmedian(dtm), dtm).astype(np.float32)
    return dtm


def amtskart_image(bbox, width: int = 1600) -> Image.Image:
    """Amtskart (1826–1917) som bilde for bbox [sør, vest, nord, øst] i EPSG:4326."""
    s, w, n, e = bbox
    # Piksler i høyden etter meter-forhold
    h = int(round(width * (n - s) / ((e - w) * math.cos(math.radians((n + s) / 2)))))
    params = {"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap", "LAYERS": "amt1", "STYLES": "",
              "CRS": "EPSG:4326", "BBOX": f"{s},{w},{n},{e}", "WIDTH": width, "HEIGHT": h,
              "FORMAT": "image/png", "TRANSPARENT": "FALSE"}
    p = cached_get(WMS_HIST, params, suffix=".png", subdir="amtskart", timeout=300, min_bytes=5000)
    return Image.open(p).convert("RGB")
