"""OpenStreetMap via Overpass: elver/bekker, fosser, stedsnavn, vannflater."""
from __future__ import annotations

from ..cache import cached_json

OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter", "https://overpass.private.coffee/api/interpreter"]


def _query(q: str):
    last = None
    for host in OVERPASS:
        try:
            return cached_json(host, data={"data": q}, timeout=300, retries=2, subdir="osm", min_bytes=50)
        except RuntimeError as e:
            last = e
    raise last


def _bbox_str(bbox):
    s, w, n, e = bbox
    return f"({s},{w},{n},{e})"


def waterways(bbox) -> list[dict]:
    """Alle waterway=river|stream som linjer, med tags og node-id-er (for nettverkstopologi)."""
    q = f'[out:json][timeout:180];(way["waterway"~"^(river|stream)$"]{_bbox_str(bbox)};);out tags geom;'
    d = _query(q)
    return [e for e in d["elements"] if e.get("type") == "way" and "geometry" in e]


def waterfalls(bbox) -> list[dict]:
    q = f'[out:json][timeout:120];(node["waterway"="waterfall"]{_bbox_str(bbox)};node["natural"="waterfall"]{_bbox_str(bbox)};);out;'
    return [e for e in _query(q)["elements"] if e.get("type") == "node" and "lat" in e]


def dams(bbox) -> list[dict]:
    q = f'[out:json][timeout:120];(way["waterway"="dam"]{_bbox_str(bbox)};node["waterway"="dam"]{_bbox_str(bbox)};way["waterway"="weir"]{_bbox_str(bbox)};node["waterway"="weir"]{_bbox_str(bbox)};);out center;'
    out = []
    for e in _query(q)["elements"]:
        if e.get("type") == "node":
            out.append({"lat": e["lat"], "lon": e["lon"], "tags": e.get("tags", {})})
        elif "center" in e:
            out.append({"lat": e["center"]["lat"], "lon": e["center"]["lon"], "tags": e.get("tags", {})})
    return out


def named_places(bbox) -> list[dict]:
    """Stedsnavn til å døpe kandidatpunkter: place=*, natural=* (bay, water, ...), landuse=farm* osv."""
    b = _bbox_str(bbox)
    q = (f'[out:json][timeout:180];(node["name"]["place"]{b};node["name"]["natural"]{b};'
         f'way["name"]["natural"~"^(water|bay|strait|wetland|beach|cliff|valley|gorge|peak)$"]{b};'
         f'node["name"]["waterway"]{b};way["name"]["landuse"="farmland"]{b};);out center;')
    out = []
    for e in _query(q)["elements"]:
        t = e.get("tags", {})
        if e.get("type") == "node":
            out.append({"name": t["name"], "lat": e["lat"], "lon": e["lon"], "kind": t.get("place") or t.get("natural") or t.get("waterway")})
        elif "center" in e:
            out.append({"name": t["name"], "lat": e["center"]["lat"], "lon": e["center"]["lon"], "kind": t.get("natural") or t.get("landuse")})
    return out


def water_polygons(bbox) -> list[dict]:
    """Innsjøer/vannflater (natural=water) som lukkede veier – brukes til å gate ut stilleflytende strekninger."""
    q = f'[out:json][timeout:180];(way["natural"="water"]{_bbox_str(bbox)};);out tags geom;'
    return [e for e in _query(q)["elements"] if e.get("type") == "way" and "geometry" in e]


def roads(bbox) -> list[dict]:
    """Kjørbare veier, traktorveier/stier og parkeringsplasser for adkomstvurdering."""
    b = _bbox_str(bbox)
    q = (f'[out:json][timeout:180];(way["highway"~"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|service|track|path|footway|bridleway)$"]{b};'
         f'node["amenity"="parking"]{b};way["amenity"="parking"]{b};);out tags geom;')
    out = []
    for e in _query(q)["elements"]:
        t = e.get("tags", {})
        if e.get("type") == "way" and "geometry" in e and t.get("highway"):
            out.append({"kind": "road" if t["highway"] not in ("path", "footway", "bridleway") else "path",
                        "highway": t["highway"], "name": t.get("name", ""), "geometry": e["geometry"]})
        elif t.get("amenity") == "parking":
            if e.get("type") == "node" and "lat" in e:
                out.append({"kind": "parking", "lat": e["lat"], "lon": e["lon"], "name": t.get("name", "")})
            elif e.get("geometry"):
                g = e["geometry"]
                out.append({"kind": "parking", "lat": sum(p["lat"] for p in g) / len(g), "lon": sum(p["lon"] for p in g) / len(g), "name": t.get("name", "")})
    return out
