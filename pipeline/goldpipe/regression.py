"""Sammenligner modellens kandidater med prototypen (GPX fra Cowork-analysen)."""
import json
import re

from .candidates import _hav
from .paths import DATA_DIR, REFERENCE_DIR


def check(slug="rollag", tol_m=300.0):
    ref = (REFERENCE_DIR / slug / "gullpunkter_rollag.gpx").read_text(encoding="utf-8")
    refs = [(float(a), float(b), n) for a, b, n in re.findall(r'<wpt lat="([\d.]+)" lon="([\d.]+)"><name>([^<]+)', ref)]
    cands = json.loads((DATA_DIR / "areas" / slug / "candidates.geojson").read_text(encoding="utf-8"))["features"]
    segs = json.loads((DATA_DIR / "areas" / slug / "segments.geojson").read_text(encoding="utf-8"))["features"]
    hits = 0
    print(f"Referanse: {len(refs)} punkter, modell: {len(cands)} kandidater, {len(segs)} segmenter (P>=1)")
    for lat, lon, name in refs:
        d_c = min((_hav(lat, lon, f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0]), f["properties"]["rank"]) for f in cands)
        best_seg = max((f["properties"]["P"] for f in segs
                        if _hav(lat, lon, f["geometry"]["coordinates"][0][1], f["geometry"]["coordinates"][0][0]) < tol_m), default=0)
        ok = d_c[0] <= tol_m
        hits += ok
        print(f"  {'OK ' if ok else '-- '} {name[:45]:45s} nærmeste kandidat {d_c[0]:5.0f} m (nr {d_c[1]}), beste P innen {tol_m:.0f} m: {best_seg:5.1f}")
    a_refs = [r for r in refs if " A " in r[2]]
    a_hits = sum(1 for lat, lon, n in a_refs if min(_hav(lat, lon, f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0]) for f in cands) <= tol_m)
    print(f"Treff: {hits}/{len(refs)} totalt, {a_hits}/{len(a_refs)} av A-punktene innen {tol_m:.0f} m")
    return hits, len(refs)
