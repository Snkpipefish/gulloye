"""Eksport: GeoJSON, GPX, PDF, profilplott, PNG-overlegg, bilder."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def _r(v, n=2):
    if v is None:
        return None
    if isinstance(v, (float, np.floating)):
        return None if not np.isfinite(v) else round(float(v), n)
    if isinstance(v, (np.integer,)):
        return int(v)
    return v


def segments_geojson(segs: list[dict], path: Path):
    feats = []
    keys = ["P", "tau", "tau_c", "omega", "M", "D", "R", "sving", "os", "foss", "juv", "B", "Q", "w", "h", "S", "elv", "km"]
    for s in segs:
        if s.get("P", 0) < 1:
            continue
        feats.append({"type": "Feature",
                      "geometry": {"type": "LineString", "coordinates": [[round(x, 5), round(y, 5)] for x, y in s["line"]]},
                      "properties": {k: _r(s.get(k), 2 if k not in ("S",) else 5) for k in keys}})
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False), encoding="utf-8")


def candidates_geojson(cands: list[dict], path: Path):
    feats = []
    for c in cands:
        props = {k: _r(v) for k, v in c.items() if k not in ("line", "lat", "lon") and not isinstance(v, (np.ndarray, list, dict))}
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(c["lon"], 5), round(c["lat"], 5)]},
                      "properties": props})
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False, indent=0), encoding="utf-8")


def gpx(cands: list[dict], path: Path, creator="gulloye"):
    import xml.sax.saxutils as su
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             f'<gpx version="1.1" creator="{creator}" xmlns="http://www.topografix.com/GPX/1/1">']
    for c in cands:
        lines.append(f'  <wpt lat="{c["lat"]:.5f}" lon="{c["lon"]:.5f}"><name>{su.escape(f"{c["rank"]} {c["klasse"]} – {c["navn"]}")}</name>'
                     f'<desc>{su.escape(c["hvorfor"])}</desc></wpt>')
    lines.append("</gpx>")
    path.write_text("\n".join(lines), encoding="utf-8")


def pdf(cands: list[dict], area: dict, path: Path):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=14 * mm)
    ss = getSampleStyleSheet()
    small = ParagraphStyle("s", parent=ss["Normal"], fontSize=8, leading=10)
    story = [Paragraph(f"Gullpunkter i {area['name']} – modellert", ss["Title"]),
             Paragraph("Rangert etter modellindeks P (0–100). A = størst sjanse, B = god, C = lav men mulig. "
                       "Koordinater i WGS84 (nord, øst). Alluvialt gull tilhører grunneier: varsle grunneier og bruker "
                       "før vasking (mineralloven § 10). Bare håndredskap; over 500 m³ eller maskiner må meldes til DMF. "
                       "Modellen er en beregning, ikke en observasjon.", small), Spacer(1, 6)]
    rows = [["Nr", "Sted", "Nord / Øst", "P", "Hvorfor her"]]
    for c in cands:
        rows.append([str(c["rank"]), Paragraph(c["navn"], small), f"{c['lat']:.4f}\n{c['lon']:.4f}", f"{c['P']:.0f}", Paragraph(c["hvorfor"], small)])
    t = Table(rows, colWidths=[10 * mm, 42 * mm, 22 * mm, 10 * mm, 96 * mm], repeatRows=1)
    st = TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#333333")),
                     ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, -1), 8), ("VALIGN", (0, 0), (-1, -1), "TOP")])
    for i, c in enumerate(cands, 1):
        col = {"A": "#c0392b", "B": "#e67e22", "C": "#f1c40f"}[c["klasse"]]
        st.add("BACKGROUND", (0, i), (0, i), colors.HexColor(col))
    t.setStyle(st)
    story += [t, Spacer(1, 8), Paragraph("Kilder: Kartverket (DTM, historiske kart), NGU (berggrunn, mineralressurser), "
                                         "OpenStreetMap, Copernicus Sentinel-2, Esri World Imagery. Generert av GULLØYE.", small)]
    doc.build(story)


def profile_plot(prof: dict, area_name: str, river: str, cands: list[dict], path: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    km = np.array(prof["km"])
    fig, ax = plt.subplots(4, 1, figsize=(13, 11), sharex=True)
    ax[0].plot(km, prof["z"], color="#1f4e79"); ax[0].set_ylabel("Vannflate (m o.h.)")
    for m in prof.get("marks", []):
        for a in ax:
            a.axvline(m["km"], color="grey", ls="--", lw=0.8)
        ax[0].text(m["km"], ax[0].get_ylim()[1], m["name"], rotation=90, va="top", ha="right", fontsize=8, color="grey")
    ax[1].plot(km, prof["Q_today"], color="#c0392b", label="middelflom i dag (regulert)")
    ax[1].plot(km, prof["Q_pre"], color="#c0392b", ls="--", label="middelflom før regulering")
    ax[1].set_ylabel("Q (m³/s)"); ax[1].legend(fontsize=8)
    ax[2].semilogy(km, prof["tau"], color="#8e44ad", label="τ ved middelflom (i dag)")
    ax[2].semilogy(km, prof["tau_pre"], color="#8e44ad", ls=":", label="τ før regulering")
    ax[2].semilogy(km, prof["tau_c"], color="black", lw=0.9, label="τ_c bunn (Shields, D50 fra fall)")
    ax[2].set_ylabel("Skjærspenning (Pa)"); ax[2].legend(fontsize=8)
    ax[3].fill_between(km, prof["P"], color="#e59866", alpha=0.9); ax[3].set_ylabel("Indeks P (0–100)"); ax[3].set_ylim(0, 105)
    for c in cands:
        if c.get("elv") == river and c.get("km") is not None:
            ax[3].annotate(str(c["rank"]), (c["km"], min(100, c["P"] + 2)), ha="center", fontsize=9, fontweight="bold")
    ax[3].set_xlabel(f"km langs {river}")
    fig.suptitle(f"{river} gjennom {area_name}")
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)


def anomaly_png(z: np.ndarray, path: Path, vmin=1.0, vmax=4.0):
    """RGBA-PNG: gjennomsiktig under vmin, gul→rød mot vmax."""
    a = np.nan_to_num(z, nan=0.0)
    t = np.clip((a - vmin) / (vmax - vmin), 0, 1)
    rgba = np.zeros(a.shape + (4,), np.uint8)
    rgba[..., 0] = 255
    rgba[..., 1] = (230 * (1 - t)).astype(np.uint8)
    rgba[..., 2] = 0
    rgba[..., 3] = (np.where(a >= vmin, 90 + 165 * t, 0)).astype(np.uint8)
    Image.fromarray(rgba, "RGBA").save(path, optimize=True)


def draw_markers(img: Image.Image, pts: list[tuple[float, float, str, str]]) -> Image.Image:
    """pts: (x, y, label, klasse)"""
    from .sources.esri import _font
    d = ImageDraw.Draw(img)
    f = _font(14)
    col = {"A": (192, 57, 43), "B": (230, 126, 34), "C": (241, 196, 15)}
    for x, y, lab, k in pts:
        r = 14
        d.ellipse((x - r, y - r, x + r, y + r), fill=col.get(k, (200, 0, 0)), outline=(255, 255, 255), width=2)
        tw = d.textlength(lab, font=f)
        d.text((x - tw / 2, y - 8), lab, fill=(255, 255, 255), font=f)
    return img


def kml(cands: list[dict], area_name: str, path: Path):
    import xml.sax.saxutils as su
    col = {"A": "ff2b39c0", "B": "ff227ee6", "C": "ff0fc4f1"}   # KML aabbggrr
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
             f'<name>{su.escape("GULLØYE – " + area_name)}</name>']
    for k, c_ in col.items():
        lines.append(f'<Style id="k{k}"><IconStyle><color>{c_}</color><scale>1.1</scale></IconStyle></Style>')
    for c in cands:
        desc = su.escape(f"P={c['P']:.0f}. {c['hvorfor']} {c.get('adkomst', '')}")
        lines.append(f'<Placemark><name>{su.escape(f"{c["rank"]}{c["klasse"]} {c["navn"]}")}</name><styleUrl>#k{c["klasse"]}</styleUrl>'
                     f'<description>{desc}</description><Point><coordinates>{c["lon"]:.5f},{c["lat"]:.5f},0</coordinates></Point></Placemark>')
    lines.append('</Document></kml>')
    path.write_text("\n".join(lines), encoding="utf-8")


def lode_geojson(recs: list[dict], path: Path):
    feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(r["lon"], 5), round(r["lat"], 5)]},
              "properties": {k: _r(v) for k, v in r.items() if k not in ("lat", "lon")}} for r in recs]
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False), encoding="utf-8")


def all_points(areas: list[tuple[str, list[dict]]], gpx_path: Path, kml_path: Path):
    """Samlet GPX/KML for alle områder (til Gaia, Locus, Garmin)."""
    import xml.sax.saxutils as su
    g = ['<?xml version="1.0" encoding="UTF-8"?>', '<gpx version="1.1" creator="gulloye" xmlns="http://www.topografix.com/GPX/1/1">']
    k = ['<?xml version="1.0" encoding="UTF-8"?>', '<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>GULLØYE – alle områder</name>']
    for name, cands in areas:
        k.append(f'<Folder><name>{su.escape(name)}</name>')
        for c in cands:
            label = su.escape(f"{name} {c['rank']}{c['klasse']} {c['navn']}")
            desc = su.escape(f"P={c['P']:.0f}. {c['hvorfor']} {c.get('adkomst', '')}")
            g.append(f'  <wpt lat="{c["lat"]:.5f}" lon="{c["lon"]:.5f}"><name>{label}</name><desc>{desc}</desc><sym>{"Flag, Red" if c["klasse"] == "A" else "Flag, Blue"}</sym></wpt>')
            k.append(f'<Placemark><name>{label}</name><description>{desc}</description><Point><coordinates>{c["lon"]:.5f},{c["lat"]:.5f},0</coordinates></Point></Placemark>')
        k.append('</Folder>')
    g.append('</gpx>'); k.append('</Document></kml>')
    gpx_path.write_text("\n".join(g), encoding="utf-8"); kml_path.write_text("\n".join(k), encoding="utf-8")
