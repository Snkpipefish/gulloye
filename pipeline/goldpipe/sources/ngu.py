"""NGU: metallforekomster (WMS/WFS/GetFeatureInfo), berggrunn (GetFeatureInfo), rasterlag (GetMap)."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from PIL import Image

from ..cache import cached_get, cached_text

METALLER = "https://geo.ngu.no/mapserver/MetallerWMS2"
BERGGRUNN = "https://geo.ngu.no/mapserver/BerggrunnWMS3"
GEOFYSIKK = "https://geo.ngu.no/mapserver/GeofysikkWMS4"
GEOKJEMI = "https://geo.ngu.no/mapserver/GeokjemiWMS"
FAKTAARK = "https://aps.ngu.no/pls/oradb/minres_deposit_fakta.Main?p_objid={okey}&p_spraak=N"

# Bergarter som gir kildescore (orogent gull / kvartsganger / grønnstein). Nøkkelord i lowercase.
FAVOURABLE = ["kvartsitt", "grønnstein", "gronnstein", "amfibolitt", "metabasalt", "basalt", "gabbro",
              "glimmerskifer", "fyllitt", "grafittskifer", "kvartsskifer", "metavulkan", "vulkan",
              "grønnskifer", "gronnskifer", "diabas", "sulfid", "jernformasjon", "konglomerat", "sandstein"]
UNFAVOURABLE = ["kalkstein", "marmor", "leirskifer"]


def _wfs_points(typename: str) -> list[tuple[float, float]]:
    """WFS 2.0 GetFeature (GML) -> liste av (lat, lon). NGU leverer kun geometri."""
    p = cached_get(METALLER, {"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature", "TYPENAMES": typename,
                              "SRSNAME": "EPSG:4326", "COUNT": 20000}, suffix=".gml", subdir="ngu", min_bytes=500)
    txt = p.read_text(encoding="utf-8", errors="replace")
    pts = []
    for m in re.finditer(r"<gml:pos>([-\d.]+)\s+([-\d.]+)</gml:pos>", txt):
        pts.append((float(m.group(1)), float(m.group(2))))
    return pts


def _wfs_polygons(typename: str) -> list[list[tuple[float, float]]]:
    """WFS polygoner -> liste av ytre ringer [(lat, lon), ...]."""
    p = cached_get(METALLER, {"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature", "TYPENAMES": typename,
                              "SRSNAME": "EPSG:4326", "COUNT": 20000}, suffix=".gml", subdir="ngu", min_bytes=500)
    txt = p.read_text(encoding="utf-8", errors="replace")
    rings = []
    for m in re.finditer(r"<gml:exterior>.*?<gml:posList[^>]*>([^<]+)</gml:posList>", txt, flags=re.S):
        nums = [float(x) for x in m.group(1).split()]
        rings.append(list(zip(nums[0::2], nums[1::2])))
    return rings


def gold_points() -> list[tuple[float, float]]:
    return _wfs_points("ms:Gull")


def metal_points() -> list[tuple[float, float]]:
    return _wfs_points("ms:Punkt_Metaller")


def basemetal_points() -> list[tuple[float, float]]:
    return _wfs_points("ms:Basemetaller_samlet")


def metal_polygons() -> list[list[tuple[float, float]]]:
    return _wfs_polygons("ms:Areal_Metaller")


def _gfi(service: str, layer: str, lat: float, lon: float, d: float = 0.01, info_format="text/plain") -> str:
    params = {"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetFeatureInfo", "LAYERS": layer, "QUERY_LAYERS": layer,
              "CRS": "EPSG:4326", "BBOX": f"{lat - d},{lon - d},{lat + d},{lon + d}", "WIDTH": 101, "HEIGHT": 101,
              "I": 50, "J": 50, "INFO_FORMAT": info_format, "FEATURE_COUNT": 5, "STYLES": ""}
    return cached_text(service, params, subdir="gfi", timeout=60, min_bytes=10)


def gold_point_info(lat: float, lon: float) -> dict:
    """Navn/type/okey for et gullpunkt via GetFeatureInfo (text/plain)."""
    txt = _gfi(METALLER, "Gull", lat, lon, d=0.004)
    info = {}
    for key in ("okey", "name", "objtype", "websub_ntext", "sted_verif"):
        m = re.search(rf"{key} = '([^']*)'", txt)
        if m:
            info[key] = m.group(1)
    if "okey" in info:
        info["faktaark"] = FAKTAARK.format(okey=info["okey"])
    return info


def bedrock_at(lat: float, lon: float) -> str:
    """Bergartsnavn (regionalt nivå 1:250 000) ved punkt, eller '' hvis ukjent."""
    txt = _gfi(BERGGRUNN, "Berggrunn_regional_hovedbergarter", lat, lon, d=0.004, info_format="application/vnd.ogc.gml")
    # MapServer GML: <ms:hovedbergart>...</ms:hovedbergart> e.l. – ta alle tekstfelt som ikke er geometri
    fields = re.findall(r"<(\w+)>([^<]{1,300})</\1>", txt)
    vals = {k.lower(): v.strip() for k, v in fields}
    main = vals.get("hovedbergart_tekst", "")
    unit = vals.get("bergartsenhet_tekst", "")
    tect = vals.get("tektoniskenhet_tekst", "")
    return " | ".join(x for x in (main, unit, tect) if x)


def bedrock_favourability(name: str) -> float:
    """0..1: hvor gunstig bergarten er som gullkilde."""
    n = name.lower()
    if any(k in n for k in UNFAVOURABLE):
        return 0.1
    if any(k in n for k in FAVOURABLE):
        return 1.0
    if "gneis" in n or "granitt" in n:
        return 0.35
    return 0.4 if n else 0.4


def wms_image(service: str, layers: str, bbox, width: int, height: int, crs="EPSG:4326", transparent="TRUE") -> Image.Image:
    """GetMap som PIL-bilde. bbox = [sør, vest, nord, øst] (4326)."""
    s, w, n, e = bbox
    params = {"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap", "LAYERS": layers, "STYLES": "", "CRS": crs,
              "BBOX": f"{s},{w},{n},{e}", "WIDTH": width, "HEIGHT": height, "FORMAT": "image/png", "TRANSPARENT": transparent}
    p = cached_get(service, params, suffix=".png", subdir="wms", timeout=300, min_bytes=1000)
    return Image.open(p).convert("RGBA")
