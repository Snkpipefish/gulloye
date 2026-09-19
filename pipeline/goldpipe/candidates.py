"""Velger kandidatpunkter (A/B/C) fra segmentene og lager «hvorfor her»-tekst."""
from __future__ import annotations

import math

import numpy as np


def _hav(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def pick_peaks(segs: list[dict], n_max=15, min_sep=800.0) -> list[dict]:
    """Lokale maksima i P med minsteavstand (m) mellom valgte punkter."""
    # hopp over de to første segmentene i hver kjede (start-artefakter: ufullstendig helning/avsetning)
    order = sorted((i for i in range(len(segs)) if segs[i].get("km", 1) >= 0.2), key=lambda i: -segs[i]["P"])
    chosen: list[dict] = []
    for i in order:
        s = segs[i]
        if s["P"] <= 0:
            break
        if all(_hav(s["lat"], s["lon"], c["lat"], c["lon"]) >= min_sep for c in chosen):
            chosen.append(dict(s))
        if len(chosen) >= n_max:
            break
    return chosen


def classify(cands: list[dict]) -> None:
    for r, c in enumerate(cands, 1):
        c["rank"] = r
        if r <= 9 and c["P"] >= 70:
            c["klasse"] = "A"
        elif c["P"] >= 45:
            c["klasse"] = "B"
        else:
            c["klasse"] = "C"


def nearest_place(lat, lon, places, maxd=450.0):
    best, bd = None, maxd
    for p in places:
        d = _hav(lat, lon, p["lat"], p["lon"])
        if d < bd:
            best, bd = p, d
    return best


def why_text(c: dict, dams: list[dict]) -> str:
    parts = []
    if c.get("foss_drop", 0) >= 3:
        parts.append(f"Foss/stryk rett oppstrøms ({c['foss_drop']:.0f} m fall på 100 m) – fossekulp og fjell i dagen.")
    elif c.get("foss", 0) > 0.4:
        parts.append("Bratt stryk like oppstrøms – kulper og fjellsprekker.")
    if c.get("os", 0) > 0.5 and c.get("os_navn"):
        parts.append(f"Os: {c['os_navn']} kommer inn her – grus og tyngre materiale legges i osen og bankehodet nedenfor.")
    elif c.get("os", 0) > 0.5:
        parts.append("Sideelv kommer inn her – os med grusavsetning.")
    if c.get("sving", 0) > 0.5:
        parts.append("Skarp sving – grav på innersvingen og bak store steiner.")
    if c.get("D", 0) > 0.3:
        parts.append(f"Strømeffekten faller {100 * c['D']:.0f} % over strekningen – tungt materiale slipper her.")
    M = c.get("M", 0)
    if 0.8 < M < 4:
        parts.append(f"τ = {c['tau']:.0f} Pa ≈ {M:.1f}× terskelen: sand og grus flyttes ved flom, gull blir liggende (retensjon).")
    elif M >= 4:
        parts.append(f"τ = {c['tau']:.0f} Pa, {M:.0f}× terskelen: sterk strøm – let i sprekker på tvers av strømmen, helt ned til fjell.")
    if c.get("berg"):
        parts.append(f"Berggrunn: {c['berg'].split(' | ')[0]} ({100 * c.get('frac_fav', 0):.0f} % gunstig oppstrøms).")
    if c.get("d_gull_km") is not None and c["d_gull_km"] < 8:
        parts.append(f"NGU-registrert gullforekomst {c['d_gull_km']:.1f} km unna.")
    for d in dams:
        dd = _hav(c["lat"], c["lon"], d["lat"], d["lon"])
        if dd < 2500 and d.get("year"):
            parts.append(f"Regulert ({d['name']}, {d['year']}) – minstevann og gammelt elveleie tilgjengelig.")
            break
    return " ".join(parts) if parts else "Kombinasjon av strømfall, terskelnær skjærspenning og feller."


class AccessIndex:
    """Avstand til nærmeste bilvei, sti og parkering (m) for et punkt."""

    def __init__(self, roads: list[dict], tr):
        import numpy as np
        from scipy.spatial import cKDTree
        self.trees = {}
        for kind in ("road", "path", "parking"):
            pts, info = [], []
            for r in roads:
                if r["kind"] != kind:
                    continue
                if kind == "parking":
                    x, y = tr.transform(r["lon"], r["lat"]); pts.append((x, y)); info.append(r.get("name", ""))
                else:
                    g = r["geometry"]
                    xs, ys = tr.transform([p["lon"] for p in g], [p["lat"] for p in g])
                    # tett opp linjene til ~25 m
                    for i in range(len(xs) - 1):
                        n = max(1, int(math.hypot(xs[i + 1] - xs[i], ys[i + 1] - ys[i]) // 25))
                        for k in range(n):
                            f = k / n; pts.append((xs[i] + f * (xs[i + 1] - xs[i]), ys[i] + f * (ys[i + 1] - ys[i])))
                            info.append(r.get("name") or r.get("highway", ""))
            self.trees[kind] = (cKDTree(np.array(pts)), info) if pts else None
        self.tr = tr

    def describe(self, lat, lon) -> dict:
        x, y = self.tr.transform(lon, lat)
        out = {}
        for kind, key in (("road", "d_vei_m"), ("path", "d_sti_m"), ("parking", "d_parkering_m")):
            t = self.trees.get(kind)
            if t is None:
                out[key] = None; continue
            d, i = t[0].query((x, y))
            out[key] = round(float(d))
            if kind == "road":
                out["vei_navn"] = t[1][i]
        d = out.get("d_vei_m")
        if d is None:
            out["adkomst"] = "Ukjent adkomst (ingen veidata)."
        elif d < 150:
            out["adkomst"] = f"Lett: bilvei {d} m unna" + (f" ({out['vei_navn']})" if out.get("vei_navn") else "") + "."
        elif d < 600:
            out["adkomst"] = f"Kort gange: bilvei {d} m unna."
        elif d < 2000:
            out["adkomst"] = f"Gange {d / 1000:.1f} km fra nærmeste bilvei."
        else:
            out["adkomst"] = f"Avsides: {d / 1000:.1f} km fra bilvei – planlegg dagstur."
        if out.get("d_parkering_m") is not None and out["d_parkering_m"] < 1500:
            out["adkomst"] += f" Parkering {out['d_parkering_m']} m unna."
        return out
