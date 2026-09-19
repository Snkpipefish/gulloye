"""Elvenett fra OSM + høyder fra DTM -> 100 m-segmenter med hydraulikk.

Retning: OSM-vassdrag tegnes nedstrøms. Nettverket er en DAG (sykler ignoreres).
Nedbørfelt estimeres fra samlet oppstrøms elvelengde: A ≈ L_opp / Dd (Dd = dreneringstetthet).
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
from pyproj import Transformer
from shapely.geometry import LineString, Point, Polygon
from shapely.strtree import STRtree

from .hydraulics import segment_hydraulics
from .sources.kartverket import sample_dtm

SEG_LEN = 100.0
DRAINAGE_DENSITY = 1.5   # km elv per km² (OSM/N50-kartlagte bekker i Norge)
MIN_UPSTREAM_KM = 1.5    # modeller bare veier med minst så mye oppstrøms nett


def _norm(name: str | None) -> str:
    return (name or "").strip().lower()


@dataclass
class Way:
    id: int
    name: str
    tags: dict
    xy: np.ndarray            # (n,2) UTM
    ll: np.ndarray            # (n,2) lat,lon
    node_keys: list
    length: float = 0.0
    width_tag: float | None = None
    L_up_start: float = 0.0   # oppstrøms lengde (m) ved startnoden
    fav_up_start: float = 0.0 # favorabel lengde oppstrøms
    fav_own: float = 0.4      # egen bergartsfavorabilitet (0..1)


@dataclass
class Network:
    ways: dict[int, Way]
    out_edges: dict = field(default_factory=dict)  # node_key -> [(way_id)]
    in_edges: dict = field(default_factory=dict)
    L_up: dict = field(default_factory=dict)       # node_key -> oppstrøms lengde (m)
    fav_up: dict = field(default_factory=dict)
    tr: Transformer | None = None


def build_network(osm_ways: list[dict], epsg: int) -> Network:
    tr = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    ways: dict[int, Way] = {}
    for w in osm_ways:
        g = w["geometry"]
        if len(g) < 2:
            continue
        lon = np.array([p["lon"] for p in g]); lat = np.array([p["lat"] for p in g])
        x, y = tr.transform(lon, lat)
        xy = np.column_stack([x, y])
        nodes = w.get("nodes") or [(round(p["lat"], 7), round(p["lon"], 7)) for p in g]
        tags = w.get("tags", {})
        wt = None
        try:
            wt = float(str(tags.get("width", "")).replace(",", ".").split()[0])
        except (ValueError, IndexError):
            wt = None
        way = Way(id=w["id"], name=tags.get("name", ""), tags=tags, xy=xy, ll=np.column_stack([lat, lon]),
                  node_keys=list(nodes), width_tag=wt)
        way.length = float(np.sum(np.hypot(np.diff(x), np.diff(y))))
        ways[way.id] = way
    net = Network(ways=ways, tr=tr)
    out_e, in_e = defaultdict(list), defaultdict(list)
    for wid, w in ways.items():
        out_e[w.node_keys[0]].append(wid)   # veien starter i startnoden (utgående)
        in_e[w.node_keys[-1]].append(wid)   # og ender i sluttnoden (innkommende)
    net.out_edges, net.in_edges = out_e, in_e
    return net


def compute_upstream(net: Network) -> None:
    """L_up[node] = sum over innkommende veier (len + L_up[startnode]). Iterativ DFS med syklusvern."""
    L_up: dict = {}
    fav_up: dict = {}
    ways = net.ways
    in_e = net.in_edges

    def solve(node):
        stack = [(node, 0)]
        onpath = set()
        while stack:
            n, state = stack[-1]
            if n in L_up:
                stack.pop(); continue
            if state == 0:
                onpath.add(n)
                stack[-1] = (n, 1)
                for wid in in_e.get(n, []):
                    s = ways[wid].node_keys[0]
                    if s not in L_up and s not in onpath:
                        stack.append((s, 0))
            else:
                tot, fav = 0.0, 0.0
                for wid in in_e.get(n, []):
                    w = ways[wid]
                    s = w.node_keys[0]
                    ls = L_up.get(s, 0.0); fs = fav_up.get(s, 0.0)
                    tot += w.length + ls
                    fav += w.length * w.fav_own + fs
                L_up[n] = tot; fav_up[n] = fav
                onpath.discard(n)
                stack.pop()

    for w in ways.values():
        for k in (w.node_keys[0], w.node_keys[-1]):
            if k not in L_up:
                solve(k)
    net.L_up, net.fav_up = L_up, fav_up
    for w in ways.values():
        w.L_up_start = L_up.get(w.node_keys[0], 0.0)
        w.fav_up_start = fav_up.get(w.node_keys[0], 0.0)


def chain_named(net: Network, names: list[str]) -> list[list[int]]:
    """Kjeder sammen veier med gitt navn til hovedløp (lengste sti fra kilde til utløp). Kan gi flere kjeder."""
    keys = {_norm(n) for n in names}
    sub = [w for w in net.ways.values() if _norm(w.name) in keys]
    if not sub:
        return []
    ids = {w.id for w in sub}
    succ = {w.id: [o for o in net.out_edges.get(w.node_keys[-1], []) if o in ids] for w in sub}
    pred = {w.id: [i for i in net.in_edges.get(w.node_keys[0], []) if i in ids] for w in sub}
    best: dict[int, tuple[float, list[int]]] = {}

    def longest(wid, seen):
        if wid in best:
            return best[wid]
        seen.add(wid)
        cand = (net.ways[wid].length, [wid])
        for s in succ[wid]:
            if s in seen:
                continue
            l, path = longest(s, seen)
            if l + net.ways[wid].length > cand[0]:
                cand = (l + net.ways[wid].length, [wid] + path)
        best[wid] = cand
        return cand

    import sys
    sys.setrecursionlimit(20000)
    chains = []
    used: set[int] = set()
    sources = [w.id for w in sub if not pred[w.id]] or [w.id for w in sub]
    sources.sort(key=lambda i: -net.ways[i].L_up_start)
    for s in sources:
        if s in used:
            continue
        l, path = longest(s, set())
        path = [p for p in path if p not in used]
        if not path:
            continue
        used.update(path)
        chains.append(path)
    chains.sort(key=lambda c: -sum(net.ways[i].length for i in c))
    return chains


def resample_chain(net: Network, chain: list[int], step: float = SEG_LEN):
    """Punkter hver `step` meter langs kjeden. Returnerer dict med xy, ll, s (m fra start), way_id per punkt."""
    pts = []
    for wid in chain:
        w = net.ways[wid]
        pts.append(w.xy if not pts else w.xy[1:] if np.allclose(w.xy[0], pts[-1][-1]) else w.xy)
    xy = np.vstack(pts)
    seg = np.hypot(np.diff(xy[:, 0]), np.diff(xy[:, 1]))
    s = np.concatenate([[0], np.cumsum(seg)])
    total = s[-1]
    if total < step:
        return None
    ss = np.arange(0, total, step)
    xs = np.interp(ss, s, xy[:, 0]); ys = np.interp(ss, s, xy[:, 1])
    # hvilken vei hvert punkt tilhører
    bounds = np.cumsum([net.ways[w].length for w in chain])
    way_idx = np.searchsorted(bounds, ss, side="right").clip(0, len(chain) - 1)
    inv = Transformer.from_crs(net.tr.target_crs, "EPSG:4326", always_xy=True)
    lon, lat = inv.transform(xs, ys)
    return {"xy": np.column_stack([xs, ys]), "ll": np.column_stack([lat, lon]), "s": ss,
            "way_id": np.array([chain[i] for i in way_idx])}


def smooth_profile(z: np.ndarray) -> np.ndarray:
    """Monotont ikke-økende nedstrøms (fjerner DTM-støy og bruer): løpende minimum fra start."""
    return np.minimum.accumulate(z)


def slopes(z: np.ndarray, step: float = SEG_LEN, half: int = 3, floor: float = 1e-4) -> np.ndarray:
    n = len(z)
    out = np.empty(n)
    for i in range(n):
        a, b = max(0, i - half), min(n - 1, i + half)
        out[i] = (z[a] - z[b]) / max((b - a) * step, step)
    return np.maximum(out, floor)


def local_drop(z: np.ndarray) -> np.ndarray:
    """Fall (m) over ett 100 m-segment (positivt = ned)."""
    d = -np.diff(z, append=z[-1])
    return np.maximum(d, 0)


def curvature(xy: np.ndarray, step: float = SEG_LEN, win: int = 2) -> np.ndarray:
    """|κ| (1/m) fra retningsendring over ±win segmenter."""
    d = np.diff(xy, axis=0)
    ang = np.arctan2(d[:, 1], d[:, 0])
    ang = np.concatenate([ang, ang[-1:]])
    n = len(ang)
    out = np.zeros(n)
    for i in range(n):
        a, b = max(0, i - win), min(n - 1, i + win)
        dth = np.angle(np.exp(1j * (ang[b] - ang[a])))
        out[i] = abs(dth) / max((b - a) * step, step)
    return out


def lake_mask(ll: np.ndarray, water_ways: list[dict]) -> np.ndarray:
    polys = []
    for w in water_ways:
        g = w["geometry"]
        if len(g) >= 4:
            try:
                p = Polygon([(pt["lon"], pt["lat"]) for pt in g])
                if p.is_valid and p.area > 2e-6:   # > ~2 ha
                    polys.append(p)
            except Exception:  # noqa: BLE001
                pass
    if not polys:
        return np.zeros(len(ll), bool)
    tree = STRtree(polys)
    out = np.zeros(len(ll), bool)
    for i, (lat, lon) in enumerate(ll):
        pt = Point(lon, lat)
        for j in tree.query(pt):
            if polys[j].contains(pt):
                out[i] = True; break
    return out


def clip_to_bbox(rs: dict, bbox) -> dict | None:
    """Beholder den sammenhengende delen av kjeden som ligger innenfor bbox (fra første punkt innenfor)."""
    s_, w_, n_, e_ = bbox
    ll = rs["ll"]
    inside = (ll[:, 0] >= s_) & (ll[:, 0] <= n_) & (ll[:, 1] >= w_) & (ll[:, 1] <= e_)
    if not inside.any():
        return None
    i0 = int(np.argmax(inside))
    after = np.where(~inside[i0:])[0]
    i1 = i0 + int(after[0]) if len(after) else len(ll)
    if i1 - i0 < 2:
        return None
    out = {k: v[i0:i1] for k, v in rs.items()}
    out["s"] = out["s"] - out["s"][0]
    return out


def channel_width_from_dtm(dtm, transform, xy: np.ndarray, z_water: np.ndarray, sample_fn,
                           half_m: float = 200.0, step_m: float = 10.0, dz: float = 1.5) -> np.ndarray:
    """Elvebredde fra DTM: tverrsnitt vinkelrett på løpet, teller sammenhengende piksler som ligger
    under vannflate + dz (m). Lavt relieff = bred elv/innsjø, juv = smal."""
    n = len(xy)
    d = np.gradient(xy, axis=0)
    norm = np.hypot(d[:, 0], d[:, 1]); norm[norm == 0] = 1
    nx, ny = -d[:, 1] / norm, d[:, 0] / norm
    offs = np.arange(step_m, half_m + step_m, step_m)
    widths = np.full(n, step_m)
    for sign in (1, -1):
        cnt = np.zeros(n)
        alive = np.ones(n, bool)
        for o in offs:
            px = xy[:, 0] + sign * nx * o; py = xy[:, 1] + sign * ny * o
            zz = sample_fn(dtm, transform, px, py)
            alive &= (zz <= z_water + dz)
            cnt += alive
        widths += cnt * step_m
    return widths
