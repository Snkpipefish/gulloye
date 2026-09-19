"""Kjører hele dypdykk-modellen for ett område."""
from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image
from pyproj import Transformer
from scipy.spatial import cKDTree

from . import candidates as C
from . import export as X
from . import network as N
from . import scoring as S
from . import catchment as CA
from .hydraulics import segment_hydraulics
from .paths import DATA_DIR
from .sources import esri, kartverket, ngu, osm
from .sources import sentinel as s2

FOSS_DROP = 3.0        # m fall per 100 m -> stryk/foss
BEDROCK_SPACING = 1500  # m mellom bergartsprøver langs elvene
MAX_BEDROCK_CALLS = 900


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _utm_bbox(bbox, tr):
    s, w, n, e = bbox
    xs, ys = tr.transform([w, e, w, e], [s, s, n, n])
    return min(xs), min(ys), max(xs), max(ys)


def _sample_bedrock(net: N.Network, min_up_m: float):
    """Setter fav_own per vei. Prøver bergarten hver BEDROCK_SPACING m på veier som modelleres."""
    calls = 0
    ways = sorted(net.ways.values(), key=lambda w: -(w.L_up_start + w.length))
    for w in ways:
        if w.L_up_start + w.length < min_up_m and w.length < 3000:
            continue
        n = max(1, int(w.length // BEDROCK_SPACING))
        idx = np.linspace(0, len(w.ll) - 1, n + 2)[1:-1].astype(int) if n > 1 else [len(w.ll) // 2]
        favs, names = [], []
        for i in idx:
            if calls >= MAX_BEDROCK_CALLS:
                break
            lat, lon = w.ll[i]
            try:
                name = ngu.bedrock_at(float(lat), float(lon)); calls += 1
            except RuntimeError:
                name = ""
            favs.append(ngu.bedrock_favourability(name)); names.append(name)
        if favs:
            w.fav_own = float(np.mean(favs))
            w.tags["_berg"] = max(names, key=len) if names else ""
    log(f"berggrunn: {calls} GetFeatureInfo-kall")


def run_area(slug: str, area: dict, skip_sentinel=False, skip_images=False) -> dict:
    t0 = time.time()
    bbox = area["bbox"]; epsg = 25833   # Kartverkets høydemodell leveres kun i EPSG:25833; dekker hele Norge
    out = DATA_DIR / "areas" / slug
    out.mkdir(parents=True, exist_ok=True)
    tr = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    inv = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)

    log(f"{slug}: henter OSM")
    # Elvenettet hentes med buffer (~20 km) slik at sideelvenes nedbørfelt oppstrøms bbox telles med.
    buf = area.get("osm_buffer_deg", 0.25)
    bbox_buf = [bbox[0] - buf * 0.55, bbox[1] - buf, bbox[2] + buf * 0.55, bbox[3] + buf]
    ways = osm.waterways(bbox_buf)
    falls = osm.waterfalls(bbox)
    water = osm.water_polygons(bbox)
    places = osm.named_places(bbox)
    osm_dams = osm.dams(bbox)
    roads = osm.roads(bbox)
    log(f"  {len(ways)} vassdragsveier, {len(falls)} fosser, {len(water)} vannflater, {len(places)} stedsnavn, {len(roads)} veier")

    net = N.build_network(ways, epsg)
    N.compute_upstream(net)
    min_up = N.MIN_UPSTREAM_KM * 1000
    log("  bergrunn langs elvene (NGU)")
    _sample_bedrock(net, min_up)
    N.compute_upstream(net)

    log("  DTM 10 m (Kartverket WCS)")
    dtm, dtm_tr = kartverket.fetch_dtm(_utm_bbox(bbox, tr))
    dtm = kartverket.fill_nan(dtm)
    log(f"  DTM {dtm.shape}")

    log("  nedbørfelt (Copernicus DEM, pyflwdir)")
    upa, upa_tr = CA.upstream_area_grid(bbox, epsg)

    gold = ngu.gold_points()
    gx, gy = tr.transform([p[1] for p in gold], [p[0] for p in gold])
    gold_tree = cKDTree(np.column_stack([gx, gy]))

    # --- oser: munningen (sluttnoden) til alle veier med >= 1,5 km oppstrøms nett.
    # Brukes for punkter på ANDRE elver (annet navn) innen 250 m, slik at sideelver som møter
    # hovedelva midt på en OSM-vei også fanges opp.
    conf_xy, conf_info = [], []
    for w in net.ways.values():
        tl = w.L_up_start + w.length
        if tl < 1500:
            continue
        conf_xy.append(w.xy[-1]); conf_info.append({"navn": w.name or "sideelv", "L": tl, "way": w.id, "name_norm": N._norm(w.name)})
    conf_tree = cKDTree(np.array(conf_xy)) if conf_xy else None
    fx, fy = tr.transform([f["lon"] for f in falls], [f["lat"] for f in falls]) if falls else ([], [])
    fall_tree = cKDTree(np.column_stack([fx, fy])) if falls else None
    dams = list(area.get("dams", []))
    for d in osm_dams:
        if all(C._hav(d["lat"], d["lon"], q["lat"], q["lon"]) > 300 for q in dams):
            dams.append({"name": d["tags"].get("name", "dam"), "lat": d["lat"], "lon": d["lon"], "year": None})

    # --- hvilke kjeder som modelleres
    chains: list[tuple[str, list[int], dict]] = []
    used: set[int] = set()
    for rv in area.get("rivers", []):
        for ch in N.chain_named(net, rv.get("osm_names", [rv["name"]])):
            if sum(net.ways[i].length for i in ch) < 500:
                continue
            chains.append((rv["name"], ch, rv)); used.update(ch)
    for w in net.ways.values():
        if w.id in used or (w.L_up_start + w.length) < min_up:
            continue
        chains.append((w.name or "bekk", [w.id], {}))
    log(f"  modellerer {len(chains)} elvekjeder")

    n_default = area.get("manning_n", 0.045)
    segs: list[dict] = []
    profiles: dict[str, dict] = {}
    for river, chain, rcfg in chains:
        rs = N.resample_chain(net, chain)
        if rs is not None:
            rs = N.clip_to_bbox(rs, bbox)
        if rs is None:
            continue
        xy, ll, ss = rs["xy"], rs["ll"], rs["s"]
        n_pts = len(ss)
        z_raw = kartverket.sample_dtm(dtm, dtm_tr, xy[:, 0], xy[:, 1])
        z = N.smooth_profile(z_raw)
        slope = N.slopes(z)
        drop = N.local_drop(z)
        kappa = N.curvature(xy)
        # oppstrøms lengde per punkt -> nedbørfelt
        L_up = np.array([net.ways[wid].L_up_start for wid in rs["way_id"]])
        # avstand innenfor egen vei
        s_way = np.zeros(n_pts); start = 0
        for i in range(1, n_pts):
            s_way[i] = s_way[i - 1] + 100 if rs["way_id"][i] == rs["way_id"][i - 1] else 0
        A_osm = (L_up + s_way) / 1000.0 / N.DRAINAGE_DENSITY
        A_dem = CA.sample_area(upa, upa_tr, xy[:, 0], xy[:, 1])
        # DEM-arealet må være monotont økende nedstrøms langs kjeden; OSM-lengde som nedre grense
        A_km2 = np.maximum(np.maximum.accumulate(A_dem), A_osm)
        qs = rcfg.get("q_spes_flom", area.get("q_spes_flom", 0.12))
        if "q_today" in rcfg:
            q_in = rcfg.get("q_today_in", rcfg["q_today"]); q_out = rcfg.get("q_today_out", rcfg["q_today"])
            Q = np.interp(ss, [0, ss[-1]], [q_in, q_out])
            qp_in = rcfg.get("q_pre_in", rcfg.get("q_pre", q_in)); qp_out = rcfg.get("q_pre_out", rcfg.get("q_pre", q_out))
            Q_pre = np.interp(ss, [0, ss[-1]], [qp_in, qp_out])
            for reach in rcfg.get("reaches", []):
                a = tr.transform(reach["from"][1], reach["from"][0]); b = tr.transform(reach["to"][1], reach["to"][0])
                ia = int(np.argmin(np.hypot(xy[:, 0] - a[0], xy[:, 1] - a[1])))
                ib = int(np.argmin(np.hypot(xy[:, 0] - b[0], xy[:, 1] - b[1])))
                lo, hi = min(ia, ib), max(ia, ib)
                if min(np.hypot(xy[ia, 0] - a[0], xy[ia, 1] - a[1]), np.hypot(xy[ib, 0] - b[0], xy[ib, 1] - b[1])) < 1500:
                    Q[lo:hi + 1] = reach["q_today"]
        else:
            Q = np.maximum(qs * A_km2, 0.05); Q_pre = Q.copy()
        wt = [net.ways[wid].width_tag for wid in rs["way_id"]]
        W_q = np.clip(3.0 * np.sqrt(Q), 2, 120)
        W_raw = N.channel_width_from_dtm(dtm, dtm_tr, xy, z_raw, kartverket.sample_dtm)
        juv = np.convolve(np.pad(S.gorge_score(W_raw, W_q), 2, mode="edge"), np.ones(5) / 5, mode="valid")
        W_dtm = np.clip(W_raw, np.maximum(3.0, 0.4 * W_q), 3.0 * W_q)
        W_dtm = np.convolve(np.pad(W_dtm, 2, mode="edge"), np.ones(5) / 5, mode="valid")
        W = np.array([w if w else wd for w, wd in zip(wt, W_dtm)])
        n_man = rcfg.get("manning_n", n_default)
        hyd = [segment_hydraulics(float(q), float(w), float(s), n_man, area.get("d50_coeff", 1.0), area.get("d50_exp", 0.5))
               for q, w, s in zip(Q, W, slope)]
        hyd_pre = [segment_hydraulics(float(q), float(w), float(s), n_man, area.get("d50_coeff", 1.0), area.get("d50_exp", 0.5))
                   for q, w, s in zip(Q_pre, W, slope)]
        tau = np.array([h["tau"] for h in hyd]); omega = np.array([h["omega"] for h in hyd])
        tau_c = np.array([h["tau_c"] for h in hyd]); M = np.array([h["M"] for h in hyd])
        # feller
        D = S.deposition(omega)
        R = S.retention(M)
        sving = S.bend_score(kappa)
        dcf, icf, os_ = np.full(n_pts, np.inf), np.zeros(n_pts, int), np.zeros(n_pts)
        if conf_tree is not None:
            chain_set = set(chain); rnorm = N._norm(river)
            dists, idxs = conf_tree.query(xy, k=6, distance_upper_bound=600)
            for i in range(n_pts):
                for d_, j in zip(np.atleast_1d(dists[i]), np.atleast_1d(idxs[i])):
                    if not np.isfinite(d_) or j >= len(conf_info):
                        continue
                    ci = conf_info[j]
                    if ci["way"] in chain_set or (ci["name_norm"] and ci["name_norm"] == rnorm):
                        continue
                    dcf[i] = d_; icf[i] = j; os_[i] = S.proximity_score(d_, 200.0); break
        foss = np.zeros(n_pts); foss_drop = np.zeros(n_pts)
        for j in np.where(drop >= FOSS_DROP)[0]:
            for i in range(j, min(n_pts, j + 4)):
                foss[i] = max(foss[i], math.exp(-(i - j) * 100 / 300.0))
                foss_drop[i] = max(foss_drop[i], drop[j])
        if fall_tree is not None:
            dfl, _ = fall_tree.query(xy, distance_upper_bound=400)
            foss = np.maximum(foss, np.where(np.isfinite(dfl), S.proximity_score(np.nan_to_num(dfl, posinf=1e9), 300.0), 0))
        lake = N.lake_mask(ll, water)
        gate = ((tau >= S.GATE_TAU * tau_c) & (omega >= S.GATE_OMEGA) & (~lake)).astype(float)
        fav_len = np.array([net.ways[wid].fav_up_start for wid in rs["way_id"]]) + np.array([net.ways[wid].fav_own for wid in rs["way_id"]]) * s_way
        frac_fav = np.clip(fav_len / np.maximum(L_up + s_way, 1.0), 0, 1)
        d_gold, _ = gold_tree.query(xy)
        B = S.source_multiplier(frac_fav, d_gold, A_km2)
        p_raw = S.combine(D, R, sving, os_, foss, gate, B, juv)
        for i in range(n_pts):
            if i == n_pts - 1:
                continue
            wid = rs["way_id"][i]
            segs.append({
                "elv": river, "km": round(ss[i] / 1000, 2), "lat": float(ll[i, 0]), "lon": float(ll[i, 1]),
                "line": [(float(ll[i, 1]), float(ll[i, 0])), (float(ll[i + 1, 1]), float(ll[i + 1, 0]))],
                "z": float(z[i]), "S": float(slope[i]), "Q": float(Q[i]), "w": float(W[i]), "w_q": float(W_q[i]), "h": hyd[i]["h"],
                "tau": float(tau[i]), "tau_c": float(tau_c[i]), "omega": float(omega[i]), "M": float(M[i]),
                "D": float(D[i]), "R": float(R[i]), "sving": float(sving[i]), "os": float(os_[i]),
                "os_navn": conf_info[icf[i]]["navn"] if conf_tree is not None and np.isfinite(dcf[i]) else "",
                "foss": float(foss[i]), "foss_drop": float(foss_drop[i]), "juv": float(juv[i]), "B": float(B[i]), "frac_fav": float(frac_fav[i]),
                "d_gull_km": float(d_gold[i] / 1000), "berg": net.ways[wid].tags.get("_berg", ""),
                "p_raw": float(p_raw[i]), "A_km2": float(A_km2[i]), "gate": float(gate[i]),
            })
        if "q_today" in rcfg and river not in profiles and n_pts > 20:
            marks = []
            for d in dams:
                dx, dy = tr.transform(d["lon"], d["lat"])
                i = int(np.argmin(np.hypot(xy[:, 0] - dx, xy[:, 1] - dy)))
                if np.hypot(xy[i, 0] - dx, xy[i, 1] - dy) < 400:
                    marks.append({"km": ss[i] / 1000, "name": d["name"]})
            profiles[river] = {"km": (ss / 1000).round(2).tolist(), "z": z.round(1).tolist(),
                               "Q_today": Q.round(1).tolist(), "Q_pre": Q_pre.round(1).tolist(),
                               "tau": tau.round(1).tolist(), "tau_pre": [round(h["tau"], 1) for h in hyd_pre],
                               "tau_c": tau_c.round(1).tolist(), "marks": marks, "_start": len(segs) - (n_pts - 1)}

    if not segs:
        raise RuntimeError("ingen segmenter")
    praw = np.array([s["p_raw"] for s in segs])
    P = S.normalize(praw)
    for s, p in zip(segs, P):
        s["P"] = float(p)
    for river, prof in profiles.items():
        st = prof.pop("_start"); n = len(prof["km"])
        prof["P"] = [round(segs[st + i]["P"], 1) for i in range(n)]
    log(f"  {len(segs)} segmenter, P>50: {(P > 50).sum()}")
    dbg = DATA_DIR.parent.parent.parent / "pipeline" / "out"; dbg.mkdir(exist_ok=True)
    (dbg / f"{slug}_segments_all.json").write_text(json.dumps([{k: v for k, v in s.items() if k != "line"} for s in segs], default=float), encoding="utf-8")

    # --- kandidater
    cands = C.pick_peaks(segs, n_max=20, min_sep=700)
    C.classify(cands)
    access = C.AccessIndex(roads, tr)
    for c in cands:
        c.update(access.describe(c["lat"], c["lon"]))
        pl = C.nearest_place(c["lat"], c["lon"], places, maxd=900.0)
        if pl and c["elv"].lower() in pl["name"].lower():
            c["navn"] = pl["name"]
        elif pl:
            c["navn"] = f"{pl['name']} ({c['elv']})"
        else:
            c["navn"] = f"{c['elv']}, km {c['km']:.1f}"
        c["hvorfor"] = C.why_text(c, dams)
    log("  kandidater: " + ", ".join(f"{c['rank']}{c['klasse']} {c['navn']} P={c['P']:.0f}" for c in cands))

    # --- Sentinel-2
    s2meta = None
    if not skip_sentinel:
        log("  Sentinel-2 (Earth Search)")
        try:
            res = s2.run(bbox)
            if res:
                z, s2tr, shape, s2meta = res
                X.anomaly_png(z["anomali"], out / "s2_anomaly.png")
                s2meta["bounds"] = {"south": bbox[0], "west": bbox[1], "north": bbox[2], "east": bbox[3]}
                (out / "s2_anomaly.json").write_text(json.dumps(s2meta, ensure_ascii=False, indent=1), encoding="utf-8")
                for c in cands:
                    col = int((c["lon"] - s2tr.c) / s2tr.a); row = int((c["lat"] - s2tr.f) / s2tr.e)
                    win = z["anomali"][max(0, row - 5):row + 6, max(0, col - 5):col + 6]
                    c["s2_anomali"] = float(np.nanmax(win)) if win.size and np.isfinite(win).any() else None
                    winf = z["feox"][max(0, row - 5):row + 6, max(0, col - 5):col + 6]
                    c["s2_feox_z"] = float(np.nanmax(winf)) if winf.size and np.isfinite(winf).any() else None
        except Exception as e:  # noqa: BLE001
            log(f"  Sentinel feilet: {e!r}")

    # --- bilder
    if not skip_images:
        log("  satellittutsnitt (Esri) og amtskart (Kartverket)")
        for c in cands:
            img, mpp = esri.crop(c["lat"], c["lon"])
            c["satsjekk"] = _auto_satcheck(img, mpp)
            esri.annotate(img, mpp, f"{c['rank']} {c['klasse']} – {c['navn']}").save(out / f"satcheck_{c['rank']}.jpg", quality=82)
        try:
            am = kartverket.amtskart_image(bbox, width=1600)
            s_, w_, n_, e_ = bbox
            pts = [((c["lon"] - w_) / (e_ - w_) * am.width, (n_ - c["lat"]) / (n_ - s_) * am.height, str(c["rank"]), c["klasse"]) for c in cands]
            X.draw_markers(am, pts).save(out / "amtskart.jpg", quality=80)
        except Exception as e:  # noqa: BLE001
            log(f"  amtskart feilet: {e!r}")

    # --- lodegull: NGU-punkter (gull + basemetaller) i området med S2-anomali og berggrunn
    lode = []
    s_, w_, n_, e_ = bbox
    for kind, pts in (("gull", gold), ("basemetall", ngu.basemetal_points())):
        for lat, lon in pts:
            if s_ <= lat <= n_ and w_ <= lon <= e_:
                rec = {"type": kind, "lat": lat, "lon": lon}
                if kind == "gull":
                    try:
                        rec.update(ngu.gold_point_info(lat, lon))
                    except RuntimeError:
                        pass
                if s2meta and "z" in dir():
                    col = int((lon - s2tr.c) / s2tr.a); row = int((lat - s2tr.f) / s2tr.e)
                    win = z["oh"][max(0, row - 8):row + 9, max(0, col - 8):col + 9]
                    rec["s2_oh_z"] = float(np.nanmax(win)) if win.size and np.isfinite(win).any() else None
                    win = z["feox"][max(0, row - 8):row + 9, max(0, col - 8):col + 9]
                    rec["s2_feox_z"] = float(np.nanmax(win)) if win.size and np.isfinite(win).any() else None
                lode.append(rec)
    X.lode_geojson(lode, out / "lode.geojson")

    # --- NVE Hydapi (valgfritt, krever NVE_HYDAPI_KEY)
    hydro = None
    try:
        from .sources import nve
        hydro = nve.area_stations(bbox)
        if hydro:
            (out / "hydro.json").write_text(json.dumps(hydro, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log(f"  NVE Hydapi hoppet over: {e!r}")

    # --- eksport
    X.segments_geojson(segs, out / "segments.geojson")
    X.candidates_geojson(cands, out / "candidates.geojson")
    X.gpx(cands, out / "points.gpx")
    X.kml(cands, area["name"], out / "points.kml")
    X.pdf(cands, area, out / "rapport.pdf")
    for river, prof in profiles.items():
        safe = river.lower().replace(" ", "_")
        (out / f"profile_{safe}.json").write_text(json.dumps(prof), encoding="utf-8")
        X.profile_plot(prof, area["name"], river, cands, out / f"profile_{safe}.png")
    meta = {
        "slug": slug, "name": area["name"], "region": area.get("region", ""), "bbox": bbox, "notes": area.get("notes", ""),
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stats": {"segmenter": len(segs), "kjeder": len(chains), "kandidater": len(cands),
                  "vassdragsveier_osm": len(ways), "dtm_px": list(dtm.shape)},
        "rivers": [{"name": r["name"], "q_today": r.get("q_today"), "q_pre": r.get("q_pre")} for r in area.get("rivers", [])],
        "dams": dams, "profiles": list(profiles.keys()), "sentinel": s2meta, "hydro": hydro, "lode": len(lode),
        "auto": bool(area.get("auto")),
        "candidates": [{k: v for k, v in c.items() if k != "line"} for c in cands],
        "sources": ["Kartverket NHM DTM 10 m (WCS)", "OpenStreetMap (Overpass)", "NGU BerggrunnWMS3 / MetallerWMS2",
                    "Copernicus Sentinel-2 L2A (Earth Search)", "Esri World Imagery", "Kartverket historiske kart (amtskart)"],
        "seconds": round(time.time() - t0),
    }
    (out / "area.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    log(f"{slug} ferdig på {meta['seconds']} s -> {out}")
    return meta


def _auto_satcheck(img: Image.Image, mpp: float) -> str:
    """Enkel automatisk bildeanalyse i 60 m radius: hvitt vann, grus, vegetasjon."""
    a = np.asarray(img).astype(int)
    h, w, _ = a.shape
    r = int(60 / mpp)
    c = a[h // 2 - r:h // 2 + r, w // 2 - r:w // 2 + r]
    R, G, B = c[..., 0], c[..., 1], c[..., 2]
    white = ((R > 200) & (G > 200) & (B > 200)).mean()
    gravel = ((R > 110) & (R >= G) & (G >= B) & (R - B < 90) & (R - B > 15)).mean()
    dark = ((R + G + B) < 150).mean()
    green = ((G > R + 10) & (G > B + 10)).mean()
    parts = []
    if white > 0.03:
        parts.append("hvitt vann/stryk synlig")
    if gravel > 0.10:
        parts.append("grus/sandbanke synlig")
    if dark > 0.35:
        parts.append("dypt/mørkt vann")
    if green > 0.6:
        parts.append("tett vegetasjon – elva delvis skjult")
    return "Automatisk bildeanalyse: " + (", ".join(parts) if parts else "ingen tydelige trekk") + "."


def render_images(slug: str, area: dict) -> None:
    """Regenererer satellittutsnitt og amtskart fra eksisterende area.json (uten å kjøre modellen)."""
    out = DATA_DIR / "areas" / slug
    meta = json.loads((out / "area.json").read_text(encoding="utf-8"))
    cands = meta["candidates"]; bbox = meta["bbox"]
    for c in cands:
        img, mpp = esri.crop(c["lat"], c["lon"])
        esri.annotate(img, mpp, f"{c['rank']} {c['klasse']} – {c['navn']}").save(out / f"satcheck_{c['rank']}.jpg", quality=82)
    am = kartverket.amtskart_image(bbox, width=1600)
    s_, w_, n_, e_ = bbox
    pts = [((c["lon"] - w_) / (e_ - w_) * am.width, (n_ - c["lat"]) / (n_ - s_) * am.height, str(c["rank"]), c["klasse"]) for c in cands]
    X.draw_markers(am, pts).save(out / "amtskart.jpg", quality=80)
    log(f"{slug}: {len(cands)} satellittutsnitt + amtskart regenerert")
