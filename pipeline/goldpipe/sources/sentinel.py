"""Sentinel-2 L2A via Earth Search STAC (nøkkelfritt). Båndratioer for jernoksid/hydroksyl."""
from __future__ import annotations

import json
import math

import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject, transform_bounds
from rasterio.windows import from_bounds

from ..cache import cached_get

STAC = "https://earth-search.aws.element84.com/v1/search"
BANDS = {"blue": 20, "green": 20, "red": 20, "nir": 20, "swir16": 20, "swir22": 20, "scl": 20}


def search(bbox, years=(2024, 2025), max_cloud=10, limit=40) -> list[dict]:
    s, w, n, e = bbox
    items = []
    for y in years:
        body = {"collections": ["sentinel-2-l2a"], "bbox": [w, s, e, n],
                "datetime": f"{y}-06-15T00:00:00Z/{y}-09-30T23:59:59Z",
                "query": {"eo:cloud_cover": {"lt": max_cloud}}, "limit": limit}
        p = cached_get(STAC, data=None, suffix=".json", subdir="stac", timeout=90) if False else None
        import requests
        r = requests.post(STAC, json=body, timeout=90)
        r.raise_for_status()
        items += r.json().get("features", [])
    # filtrer bort scener med mye nodata over området, sorter etter sky
    items = [i for i in items if i["properties"].get("s2:nodata_pixel_percentage", 0) < 60]
    items.sort(key=lambda i: (i["properties"].get("eo:cloud_cover", 100)))
    return items


def _grid(bbox, res_deg_lat=0.00018):
    s, w, n, e = bbox
    res_lon = res_deg_lat / math.cos(math.radians((s + n) / 2))
    H = int(math.ceil((n - s) / res_deg_lat)); W = int(math.ceil((e - w) / res_lon))
    from rasterio.transform import from_origin
    return from_origin(w, n, res_lon, res_deg_lat), (H, W)


def read_scene(item: dict, bbox, dst_transform, shape) -> dict[str, np.ndarray]:
    """Leser båndvinduer og reprojiserer til felles 4326-grid. NaN utenfor scenen."""
    out = {}
    for b in BANDS:
        href = item["assets"][b]["href"]
        with rasterio.open(href) as d:
            bnds = transform_bounds("EPSG:4326", d.crs, bbox[1], bbox[0], bbox[3], bbox[2])
            win = from_bounds(*bnds, d.transform).round_offsets().round_lengths()
            # klipp vinduet til datasettet
            from rasterio.windows import Window, intersection
            full = Window(0, 0, d.width, d.height)
            try:
                win = intersection(win, full)
            except Exception:  # noqa: BLE001
                return {}
            if win.width < 2 or win.height < 2:
                return {}
            arr = d.read(1, window=win).astype(np.float32)
            src_tr = d.window_transform(win)
            dst = np.full(shape, np.nan, np.float32)
            reproject(arr, dst, src_transform=src_tr, src_crs=d.crs, dst_transform=dst_transform, dst_crs="EPSG:4326",
                      resampling=Resampling.nearest if b == "scl" else Resampling.bilinear, src_nodata=0, dst_nodata=np.nan)
            out[b] = dst
    return out


def indices(sc: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    scl = sc["scl"]
    ok = np.isin(scl, [4, 5, 6, 7])              # vegetasjon, bart, vann, uklassifisert
    B2, B3, B4, B8, B11, B12 = (sc[k] for k in ("blue", "green", "red", "nir", "swir16", "swir22"))
    ndvi = (B8 - B4) / np.maximum(B8 + B4, 1)
    ndwi = (B3 - B8) / np.maximum(B3 + B8, 1)
    bare = ok & (ndvi < 0.55) & (ndwi < 0.0) & (B4 > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = {"feox": np.where(bare, B4 / np.maximum(B2, 1), np.nan),
             "oh": np.where(bare, B11 / np.maximum(B12, 1), np.nan),
             "fe2": np.where(bare, B11 / np.maximum(B8, 1), np.nan)}
    r["ndvi"] = np.where(ok, ndvi, np.nan)
    return r


def zscore(a: np.ndarray) -> np.ndarray:
    v = a[np.isfinite(a)]
    if v.size < 100:
        return np.full_like(a, np.nan)
    med = np.median(v); mad = np.median(np.abs(v - med)) * 1.4826
    return (a - med) / max(mad, 1e-6)


def crosta_pca(sc: dict[str, np.ndarray], mask: np.ndarray):
    """PCA på [B2,B4,B11,B12] (standardisert). Returnerer komponent som skiller jernoksid (B4 mot B2) og
    hydroksyl (B11 mot B12), som z-score."""
    X = np.column_stack([sc[k][mask] for k in ("blue", "red", "swir16", "swir22")])
    X = (X - X.mean(0)) / np.maximum(X.std(0), 1e-6)
    cov = np.cov(X, rowvar=False)
    vals, vecs = np.linalg.eigh(cov)
    res = {}
    for name, (i, j) in {"pca_feox": (0, 1), "pca_oh": (2, 3)}.items():
        # komponent med motsatt fortegn på de to båndene, størst |differanse|
        k = int(np.argmax(np.abs(vecs[i, :] - vecs[j, :]) * (np.sign(vecs[i, :]) != np.sign(vecs[j, :]))))
        v = vecs[:, k]
        if v[j] < v[i]:   # orienter slik at høy = mer jernoksid / mer hydroksyl
            v = -v
        s = X @ v
        full = np.full(mask.shape, np.nan, np.float32); full[mask] = s
        res[name] = zscore(full)
    return res


def run(bbox, max_scenes=4):
    """Median-kompositt av ratioer over ≤max_scenes scener. Returnerer (dict av arrays, transform, shape, meta)."""
    items = search(bbox)
    tr, shape = _grid(bbox)
    stacks: dict[str, list] = {"feox": [], "oh": [], "fe2": [], "ndvi": []}
    used = []
    per_tile: dict[str, int] = {}
    for it in items:
        tile = it["properties"].get("grid:code", "")
        if per_tile.get(tile, 0) >= 2:
            continue
        sc = read_scene(it, bbox, tr, shape)
        if not sc or np.isfinite(sc["red"]).mean() < 0.02:
            continue
        idx = indices(sc)
        for k in stacks:
            stacks[k].append(idx[k])
        used.append({"id": it["id"], "datetime": it["properties"]["datetime"], "cloud": it["properties"].get("eo:cloud_cover")})
        per_tile[tile] = per_tile.get(tile, 0) + 1
        if len(used) >= max_scenes:
            break
    if not used:
        return None
    with np.errstate(all="ignore"):
        comp = {k: np.nanmedian(np.stack(v), axis=0) for k, v in stacks.items()}
    z = {k: zscore(comp[k]) for k in ("feox", "oh", "fe2")}
    z["anomali"] = np.clip(np.nanmax(np.stack([z["feox"], z["oh"], z["fe2"]]), axis=0), 0, 4)
    z["ndvi"] = comp["ndvi"]
    return z, tr, shape, {"scener": used, "grid_res_deg": (tr.a, -tr.e)}
