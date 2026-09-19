"""Nedbørfeltareal fra Copernicus DEM 30 m med pyflwdir (D8, fylte søkk).

DEM-fliser rundt området (buffer) reprojiseres til områdets UTM-sone i 60 m og
flow accumulation beregnes. A(km²) hentes ved å ta maks oppstrøms areal i et lite
vindu rundt hvert elvepunkt (slik at punktet «snapper» til DEM-kanalen).
"""
from __future__ import annotations

import math
import time

import numpy as np
import pyflwdir
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject

from .cache import cached_get

COP = "https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM/Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM.tif"
RES = 60.0


def _tile(lat: int, lon: int):
    url = COP.format(lat=f"N{lat:02d}", lon=f"E{lon:03d}")
    try:
        return cached_get(url, suffix=".tif", subdir="copdem", timeout=600, min_bytes=10000)
    except RuntimeError:
        return None


def upstream_area_grid(bbox, epsg: int, buffer_deg=(0.5, 1.0), res: float = RES):
    """Returnerer (uparea km² array, transform) i EPSG:{epsg} for bbox + buffer (lat, lon)."""
    t0 = time.time()
    s, w, n, e = bbox
    bs, bw, bn, be = s - buffer_deg[0], w - buffer_deg[1], n + buffer_deg[0], e + buffer_deg[1]
    from pyproj import Transformer
    tr = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    xs, ys = tr.transform([bw, be, bw, be], [bs, bs, bn, bn])
    minx, maxx = math.floor(min(xs) / res) * res, math.ceil(max(xs) / res) * res
    miny, maxy = math.floor(min(ys) / res) * res, math.ceil(max(ys) / res) * res
    W, H = int((maxx - minx) / res), int((maxy - miny) / res)
    dst_tr = from_origin(minx, maxy, res, res)
    dem = np.full((H, W), np.nan, np.float32)
    for lat in range(int(math.floor(bs)), int(math.ceil(bn))):
        for lon in range(int(math.floor(bw)), int(math.ceil(be))):
            p = _tile(lat, lon)
            if p is None:
                continue
            with rasterio.open(p) as d:
                a = d.read(1).astype(np.float32)
                tile = np.full((H, W), np.nan, np.float32)
                reproject(a, tile, src_transform=d.transform, src_crs=d.crs, dst_transform=dst_tr, dst_crs=f"EPSG:{epsg}",
                          resampling=Resampling.average, dst_nodata=np.nan)
                m = np.isfinite(tile)
                dem[m] = tile[m]
    dem = np.where(np.isfinite(dem), dem, -9999).astype(np.float32)
    dem[dem <= 0] = 0.0   # hav -> 0 m, slik at alt drenerer dit
    flw = pyflwdir.from_dem(data=dem, nodata=-9999, transform=dst_tr, latlon=False)
    upa = flw.upstream_area(unit="km2").astype(np.float32)
    upa[upa < 0] = 0
    print(f"    nedbørfelt: {H}x{W} celler à {res:.0f} m på {time.time() - t0:.0f} s", flush=True)
    return upa, dst_tr


def sample_area(upa: np.ndarray, tr, xs: np.ndarray, ys: np.ndarray, win: int = 1) -> np.ndarray:
    """Maks oppstrøms areal (km²) i (2·win+1)² vindu rundt hvert punkt."""
    cols = ((xs - tr.c) / tr.a).astype(int)
    rows = ((ys - tr.f) / tr.e).astype(int)
    H, W = upa.shape
    out = np.zeros(len(xs), np.float32)
    for i, (r, c) in enumerate(zip(rows, cols)):
        r0, r1 = max(0, r - win), min(H, r + win + 1)
        c0, c1 = max(0, c - win), min(W, c + win + 1)
        if r1 > r0 and c1 > c0:
            out[i] = upa[r0:r1, c0:c1].max()
    return out
