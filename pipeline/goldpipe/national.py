"""Nasjonalt potensialkart (1 km-grid): weights of evidence + fuzzy gamma.

Bevislag (binære, én per 1 km-celle):
  E1 nærhet (< 5 km) til NGU-registrerte sulfid-/basemetall-mineraliseringer (WFS Basemetaller_samlet)
  E2 magnetisk anomali-gradient >= p80 (NGU GeofysikkWMS4, raster via GetMap, gråtone-gradient)
  E3 lineamenttetthet >= p80 (NGU BerggrunnWMS3 Lineamenter via GetMap)
  E4 relieff (maks−min innen 3×3 km) >= p60 og cellen er ikke hav (Copernicus DEM 30 m)
Trening D: celler med NGU-gullpunkt (WFS Gull).
"""
from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone

import numpy as np
import rasterio
from PIL import Image
from rasterio.warp import Resampling, reproject
from rasterio.transform import from_origin
from scipy.ndimage import distance_transform_edt, maximum_filter, minimum_filter, uniform_filter, sobel

from .cache import cached_get
from .paths import DATA_DIR
from .sources import ngu

COP = "https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM/Copernicus_DSM_COG_10_{lat}_00_{lon}_00_DEM.tif"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _grid(bbox, km):
    s, w, n, e = bbox
    lat0 = (s + n) / 2
    dlat = km / 111.0
    dlon = km / (111.0 * math.cos(math.radians(lat0)))
    H = int(math.ceil((n - s) / dlat)); W = int(math.ceil((e - w) / dlon))
    return from_origin(w, n, dlon, dlat), (H, W)


def _rasterize_points(pts, tr, shape):
    a = np.zeros(shape, bool)
    for lat, lon in pts:
        c = int((lon - tr.c) / tr.a); r = int((lat - tr.f) / tr.e)
        if 0 <= r < shape[0] and 0 <= c < shape[1]:
            a[r, c] = True
    return a


def _wms_gray(service, layers, bbox, shape):
    """GetMap som gråtone-array (0..255) i grid-oppløsning (maks 4096 px per akse -> flisvis)."""
    H, W = shape
    s, w, n, e = bbox
    out = np.zeros((H, W), np.float32)
    step = 2000
    for r0 in range(0, H, step):
        for c0 in range(0, W, step):
            r1, c1 = min(H, r0 + step), min(W, c0 + step)
            bb = [n - r1 * (n - s) / H, w + c0 * (e - w) / W, n - r0 * (n - s) / H, w + c1 * (e - w) / W]
            img = ngu.wms_image(service, layers, bb, c1 - c0, r1 - r0)
            a = np.asarray(img).astype(np.float32)
            gray = a[..., :3].mean(axis=2) * (a[..., 3] > 0)
            out[r0:r1, c0:c1] = gray
    return out


def _dem(bbox, tr, shape):
    """Copernicus DEM 30 m -> 1 km-grid (gjennomsnitt). NaN der ingen data (hav)."""
    s, w, n, e = bbox
    dst = np.full(shape, np.nan, np.float32)
    for lat in range(int(math.floor(s)), int(math.ceil(n))):
        for lon in range(int(math.floor(w)), int(math.ceil(e))):
            url = COP.format(lat=f"N{lat:02d}", lon=f"E{lon:03d}")
            try:
                p = cached_get(url, suffix=".tif", subdir="copdem", timeout=300, min_bytes=10000)
            except RuntimeError:
                continue   # flis finnes ikke (hav)
            with rasterio.open(p) as d:
                # les i redusert oppløsning (~300 m) for å spare tid, så aggreger til 1 km
                sc = 10
                a = d.read(1, out_shape=(d.height // sc, d.width // sc), resampling=Resampling.average).astype(np.float32)
                src_tr = d.transform * d.transform.scale(d.width / a.shape[1], d.height / a.shape[0])
                tile = np.full(shape, np.nan, np.float32)
                reproject(a, tile, src_transform=src_tr, src_crs=d.crs, dst_transform=tr, dst_crs="EPSG:4326",
                          resampling=Resampling.average, dst_nodata=np.nan)
                m = np.isfinite(tile)
                dst[m] = tile[m]
    return dst


def wofe(evidence: list[np.ndarray], deposits: np.ndarray, study: np.ndarray):
    """Returnerer (posterior-sannsynlighet, tabell med W+, W-, C per lag)."""
    N = study.sum(); nD = (deposits & study).sum()
    prior = nD / N
    logit = np.full(study.shape, math.log(prior / (1 - prior)), np.float64)
    table = []
    for k, E in enumerate(evidence):
        E = E & study
        nED = (E & deposits).sum(); nE = E.sum()
        pE_D = (nED + 0.5) / (nD + 1); pE_nD = (nE - nED + 0.5) / (N - nD + 1)
        pnE_D = (nD - nED + 0.5) / (nD + 1); pnE_nD = (N - nD - (nE - nED) + 0.5) / (N - nD + 1)
        Wp = math.log(pE_D / pE_nD); Wm = math.log(pnE_D / pnE_nD)
        table.append({"lag": k, "W+": round(Wp, 3), "W-": round(Wm, 3), "C": round(Wp - Wm, 3), "celler": int(nE), "treff": int(nED)})
        logit += np.where(E, Wp, Wm) * study
    post = 1 / (1 + np.exp(-logit))
    return post, table, prior


def fuzzy_gamma(mus: list[np.ndarray], gamma=0.9):
    prod = np.ones_like(mus[0]); prod_c = np.ones_like(mus[0])
    for m in mus:
        prod *= m; prod_c *= (1 - m)
    return (prod ** (1 - gamma)) * ((1 - prod_c) ** gamma)


def run_national(cfg: dict):
    t0 = time.time()
    bbox = cfg["bbox"]; km = cfg.get("grid_km", 1)
    tr, shape = _grid(bbox, km)
    out = DATA_DIR / "national"; out.mkdir(parents=True, exist_ok=True)
    log(f"nasjonalt grid {shape} ({km} km)")

    log("  Copernicus DEM")
    dem = _dem(bbox, tr, shape)
    land = np.isfinite(dem) & (dem > 0.5)
    relief = maximum_filter(np.nan_to_num(dem, nan=0), 3) - minimum_filter(np.nan_to_num(dem, nan=0), 3)
    log(f"  land: {land.sum()} celler")

    log("  NGU punkter (WFS)")
    gold = ngu.gold_points(); base = ngu.basemetal_points(); metals = ngu.metal_points()
    D = _rasterize_points(gold, tr, shape) & land
    Bm = _rasterize_points(base, tr, shape)
    d_base = distance_transform_edt(~Bm) * km
    log(f"  gull: {len(gold)} pkt ({D.sum()} celler), basemetaller: {len(base)}")

    log("  NGU magnetikk og lineamenter (WMS)")
    mag = _wms_gray(ngu.GEOFYSIKK, "Magnetic_anomaly_compilation_norway_raster", bbox, shape)
    mag_grad = np.hypot(sobel(mag, 0), sobel(mag, 1))
    lin = _wms_gray(ngu.BERGGRUNN, "Lineamenter", bbox, shape) > 0
    lin_dens = uniform_filter(lin.astype(np.float32), 7)
    # Studieområde = land med NGU-dekning (magnetisk kompilasjon dekker Norge, ikke Sverige/Finland)
    norway = uniform_filter((mag > 0).astype(np.float32), 5) > 0.2
    land = land & norway
    D = D & land
    log(f"  studieområde Norge: {land.sum()} celler, gullceller: {D.sum()}")

    pcts = cfg.get("wofe", {}).get("percentiles", {})
    def thr(a, p):
        v = a[land]; return np.percentile(v, p) if v.size else np.inf
    E1 = (d_base < 3.0)
    E1b = (d_base >= 3.0) & (d_base < 10.0)
    E2 = mag_grad >= thr(mag_grad, pcts.get("magnetisk", 80))
    E3 = lin_dens >= thr(lin_dens, pcts.get("lineament", 80))
    E4 = relief >= thr(relief, 60)
    post, table, prior = wofe([E1, E1b, E2, E3, E4], D, land)
    names = ["nærhet basemetall-mineralisering < 3 km", "basemetall-mineralisering 3–10 km", "magnetisk gradient ≥ p80", "lineamenttetthet ≥ p80", "relieff ≥ p60"]
    for t, n in zip(table, names):
        t["navn"] = n
    log("  WofE: " + "; ".join(f"{t['navn']}: C={t['C']}" for t in table))

    # fuzzy: kontinuerlige medlemsfunksjoner
    def mm(a):
        v = a[land]; lo, hi = np.percentile(v, 5), np.percentile(v, 99)
        return np.clip((a - lo) / max(hi - lo, 1e-9), 0, 1)
    mus = [np.clip(1 - d_base / 15.0, 0, 1), mm(mag_grad), mm(lin_dens), mm(relief)]
    fz = fuzzy_gamma(mus, cfg.get("fuzzy_gamma", 0.9))
    score = 0.5 * mm(post) + 0.5 * mm(fz)
    score = np.where(land, score, 0)
    # kalibrering: andel av gullpunkter i topp 20 % av arealet
    v = score[land]; cut = np.percentile(v, 80)
    capture = float(((score >= cut) & D).sum() / max(D.sum(), 1))
    log(f"  topp 20 % av arealet fanger {100 * capture:.0f} % av NGU-gullpunktene")

    from .paths import PIPELINE_DIR
    (PIPELINE_DIR / "out").mkdir(exist_ok=True)
    np.savez_compressed(PIPELINE_DIR / "out" / "national_score.npz", score=score.astype(np.float32), land=land,
                        west=tr.c, north=tr.f, dlon=tr.a, dlat=-tr.e)

    # PNG (RGBA, gjennomsiktig under 0.35)
    t = np.clip((score - 0.35) / 0.65, 0, 1)
    rgba = np.zeros(shape + (4,), np.uint8)
    rgba[..., 0] = 255; rgba[..., 1] = (210 * (1 - t) + 40 * t).astype(np.uint8); rgba[..., 2] = (60 * (1 - t)).astype(np.uint8)
    rgba[..., 3] = np.where(score >= 0.35, (40 + 200 * t), 0).astype(np.uint8)
    Image.fromarray(rgba, "RGBA").save(out / "score_1km.png", optimize=True)

    # NGU-punkter beriket
    feats = []
    for lat, lon in gold:
        info = {}
        try:
            info = ngu.gold_point_info(lat, lon)
        except RuntimeError:
            pass
        r = int((lat - tr.f) / tr.e); c = int((lon - tr.c) / tr.a)
        sc = float(score[r, c]) if 0 <= r < shape[0] and 0 <= c < shape[1] else None
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
                      "properties": {"name": info.get("name", ""), "objtype": info.get("objtype", ""), "okey": info.get("okey"),
                                     "faktaark": info.get("faktaark"), "score": round(sc, 2) if sc is not None else None}})
    (out / "ngu_gull.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False), encoding="utf-8")
    polys = ngu.metal_polygons()
    pf = [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[round(lon, 4), round(lat, 4)] for lat, lon in ring[::max(1, len(ring) // 60)]] + [[round(ring[0][1], 4), round(ring[0][0], 4)]]]}, "properties": {}}
          for ring in polys if len(ring) >= 4]
    (out / "metaller_flater.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": pf}), encoding="utf-8")

    meta = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "grid_km": km, "shape": list(shape),
            "bounds": {"south": bbox[0], "west": bbox[1], "north": bbox[2], "east": bbox[3]},
            "prior": prior, "wofe": table, "capture_top20": capture, "n_gold": len(gold),
            "description": f"Weights of evidence (Bonham-Carter) over {km} km-grid trent på {len(gold)} NGU-gullpunkter, kombinert 50/50 med fuzzy gamma (γ={cfg.get('fuzzy_gamma', 0.9)}). "
                           f"Bevislag: {', '.join(names)}. Topp 20 % av arealet fanger {100 * capture:.0f} % av kjente gullpunkter. Kilder: NGU, Copernicus DEM.",
            "seconds": round(time.time() - t0)}
    (out / "national.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"nasjonalt ferdig på {meta['seconds']} s")
    return meta
