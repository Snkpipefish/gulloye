"""Velger nye dypdykk-områder automatisk fra det nasjonale potensialkartet.

1. Nasjonal score (1 km) glattes (5 km) og terskles til topp-andel.
2. Sammenhengende klynger rangeres etter summert score; klynger som overlapper
   eksisterende områder eller hverandre (min. avstand) hoppes over.
3. Hver klynge får et bbox (min 0,22° × 0,45°, maks 0,35° × 0,8°), navn fra
   største OSM-stedsnavn i bbox, og regionens spesifikke middelflom.
Resultatet skrives til config/areas_auto.yaml og kjøres som vanlige områder.
"""
from __future__ import annotations

import math

import numpy as np
import yaml
from scipy.ndimage import label, uniform_filter

from .paths import CONFIG_DIR, PIPELINE_DIR
from .sources import osm


def _q_spes(lat, lon, cfg):
    q = cfg.get("q_spes_flom", {})
    if lat >= 68.5 and lon > 22:
        return q.get("finnmark", 0.09)
    if lat >= 64:
        return q.get("nord", 0.18)
    if lon < 8 and lat < 64:
        return q.get("vest", 0.25)
    return q.get("default", 0.12)


def _name_for(bbox) -> tuple[str, str]:
    """(navn, region) fra OSM: største tettsted i bbox, og kommune/fylke om tilgjengelig."""
    s, w, n, e = bbox
    try:
        q = (f'[out:json][timeout:120];(node["place"~"^(city|town|village|hamlet)$"]({s},{w},{n},{e}););out;')
        els = osm._query(q)["elements"]
    except Exception:  # noqa: BLE001
        els = []
    rank = {"city": 0, "town": 1, "village": 2, "hamlet": 3}
    els = [x for x in els if x.get("tags", {}).get("name")]
    els.sort(key=lambda x: (rank.get(x["tags"].get("place"), 9), -int(x["tags"].get("population", "0") or 0)))
    if els:
        return els[0]["tags"]["name"], els[0]["tags"].get("is_in") or ""
    return f"{(s + n) / 2:.2f}N {(w + e) / 2:.2f}E", ""


def select(n_new: int = 12, existing: dict | None = None, national_cfg: dict | None = None, top_frac: float = 0.03,
           min_sep_deg: float = 0.6) -> dict:
    d = np.load(PIPELINE_DIR / "out" / "national_score.npz")
    score, land = d["score"], d["land"]
    west, north, dlon, dlat = float(d["west"]), float(d["north"]), float(d["dlon"]), float(d["dlat"])
    sm = uniform_filter(np.where(land, score, 0).astype(np.float32), 5)
    thr = np.percentile(sm[land], 100 * (1 - top_frac))
    lab, n = label(sm >= thr)
    clusters = []
    for i in range(1, n + 1):
        m = lab == i
        if m.sum() < 8:
            continue
        rows, cols = np.where(m)
        lat_c = north + (rows.mean() + 0.5) * (-dlat); lon_c = west + (cols.mean() + 0.5) * dlon
        clusters.append({"sum": float(sm[m].sum()), "lat": lat_c, "lon": lon_c, "cells": int(m.sum()),
                         "s": north - (rows.max() + 1) * dlat, "n": north - rows.min() * dlat,
                         "w": west + cols.min() * dlon, "e": west + (cols.max() + 1) * dlon})
    clusters.sort(key=lambda c: -c["sum"])
    taken = []
    for slug, a in (existing or {}).items():
        b = a["bbox"]; taken.append(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2))
    chosen = []
    for c in clusters:
        if any(math.hypot(c["lat"] - la, (c["lon"] - lo) * math.cos(math.radians(c["lat"]))) < min_sep_deg for la, lo in taken):
            continue
        # bbox: klyngens utstrekning, minst 0.22×0.45, maks 0.35×0.8 grader
        h = min(max(c["n"] - c["s"], 0.22), 0.35); w = min(max(c["e"] - c["w"], 0.45), 0.8)
        bbox = [round(float(c["lat"] - h / 2), 3), round(float(c["lon"] - w / 2), 3), round(float(c["lat"] + h / 2), 3), round(float(c["lon"] + w / 2), 3)]
        name, region = _name_for(bbox)
        slug = "auto-" + "".join(ch for ch in name.lower().replace("æ", "ae").replace("ø", "o").replace("å", "a") if ch.isalnum())[:20]
        if any(x["slug"] == slug for x in chosen):
            slug += f"-{len(chosen)}"
        chosen.append({"slug": slug, "name": name, "region": region, "bbox": bbox, "score_sum": round(float(c["sum"]), 1), "cells": int(c["cells"]),
                       "q_spes": float(_q_spes(c["lat"], c["lon"], national_cfg or {}))})
        taken.append((c["lat"], c["lon"]))
        if len(chosen) >= n_new:
            break
    areas = {}
    for x in chosen:
        areas[x["slug"]] = {"name": x["name"], "region": x["region"] or "automatisk valgt fra nasjonalt kart", "bbox": x["bbox"], "utm_epsg": 25833,
                            "manning_n": 0.045, "d50_coeff": 1.0, "d50_exp": 0.5, "q_spes_flom": x["q_spes"], "auto": True,
                            "rivers": [], "dams": [],
                            "notes": f"Automatisk valgt: klynge med {x['cells']} km²-celler i topp {100 * top_frac:.0f} % av nasjonal score (sum {x['score_sum']}). "
                                     "Ingen manuelle vannføringer – alle elver bruker spesifikk middelflom × nedbørfelt."}
    (CONFIG_DIR / "areas_auto.yaml").write_text(yaml.safe_dump({"areas": areas}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return areas
