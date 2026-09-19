"""NVE Hydapi: målte vannføringer. Krever gratis API-nøkkel (https://hydapi.nve.no) i miljøvariabelen NVE_HYDAPI_KEY.
Uten nøkkel returneres None og siden viser bare modellert middelflom."""
from __future__ import annotations

import os

import requests

API = "https://hydapi.nve.no/api/v1"


def _key():
    return os.environ.get("NVE_HYDAPI_KEY")


def area_stations(bbox, max_n: int = 4) -> dict | None:
    key = _key()
    if not key:
        return None
    h = {"X-API-Key": key, "Accept": "application/json"}
    r = requests.get(f"{API}/Stations", params={"Active": 1, "Parameter": 1001}, headers=h, timeout=60)
    r.raise_for_status()
    s_, w_, n_, e_ = bbox
    st = [x for x in r.json().get("data", []) if s_ <= (x.get("latitude") or 0) <= n_ and w_ <= (x.get("longitude") or 0) <= e_]
    st = st[:max_n]
    out = []
    for x in st:
        sid = x["stationId"]
        try:
            o = requests.get(f"{API}/Observations", params={"StationId": sid, "Parameter": 1001, "ResolutionTime": "day", "ReferenceTime": "P30D/"},
                             headers=h, timeout=60).json()
            obs = (o.get("data") or [{}])[0].get("observations") or []
            last = obs[-1] if obs else None
        except Exception:  # noqa: BLE001
            last = None
        out.append({"stationId": sid, "name": x.get("stationName"), "river": x.get("riverName"), "lat": x.get("latitude"), "lon": x.get("longitude"),
                    "q_last": last.get("value") if last else None, "t_last": last.get("time") if last else None,
                    "url": f"https://sildre.nve.no/station/{sid}"})
    return {"stations": out, "note": "Døgnmiddel vannføring (m³/s) fra NVE Hydapi (parameter 1001)."}
