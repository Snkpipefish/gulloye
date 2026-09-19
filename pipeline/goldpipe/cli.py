import argparse
import json
from datetime import datetime, timezone

import yaml

from .paths import CONFIG_DIR, DATA_DIR


def load_areas(include_auto: bool = True):
    areas = yaml.safe_load((CONFIG_DIR / "areas.yaml").read_text(encoding="utf-8"))["areas"]
    auto = CONFIG_DIR / "areas_auto.yaml"
    if include_auto and auto.exists():
        areas.update(yaml.safe_load(auto.read_text(encoding="utf-8")).get("areas") or {})
    return areas


def write_index():
    areas = []
    order = list(load_areas().keys())
    paths = sorted((DATA_DIR / "areas").glob("*/area.json"), key=lambda p: order.index(p.parent.name) if p.parent.name in order else 99)
    for p in paths:
        m = json.loads(p.read_text(encoding="utf-8"))
        areas.append({"slug": m["slug"], "name": m["name"], "region": m.get("region", ""), "bbox": m["bbox"],
                      "generated": m["generated"], "kandidater": m["stats"]["kandidater"], "auto": m.get("auto", False)})
    # samlet GPX/KML
    from .export import all_points
    coll = []
    for a in areas:
        m = json.loads((DATA_DIR / "areas" / a["slug"] / "area.json").read_text(encoding="utf-8"))
        coll.append((a["name"], m["candidates"]))
    all_points(coll, DATA_DIR / "national" / "alle_punkter.gpx", DATA_DIR / "national" / "alle_punkter.kml")
    nat = DATA_DIR / "national" / "national.json"
    idx = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "areas": areas,
           "national": json.loads(nat.read_text(encoding="utf-8")) if nat.exists() else None}
    (DATA_DIR / "index.json").write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")
    print("index.json:", [a["slug"] for a in areas])


def main():
    ap = argparse.ArgumentParser(prog="goldpipe")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("--area", required=True); r.add_argument("--skip-sentinel", action="store_true"); r.add_argument("--skip-images", action="store_true")
    sub.add_parser("national")
    sub.add_parser("index")
    im = sub.add_parser("images"); im.add_argument("--area", default="all")
    au = sub.add_parser("auto"); au.add_argument("--n", type=int, default=12); au.add_argument("--run", action="store_true"); au.add_argument("--skip-sentinel", action="store_true")
    a = sub.add_parser("all"); a.add_argument("--skip-sentinel", action="store_true")
    rg = sub.add_parser("regression"); rg.add_argument("--area", default="rollag")
    args = ap.parse_args()
    areas = load_areas()
    if args.cmd == "run":
        from .area import run_area
        run_area(args.area, areas[args.area], skip_sentinel=args.skip_sentinel, skip_images=args.skip_images)
        write_index()
    elif args.cmd == "national":
        from .national import run_national
        run_national(yaml.safe_load((CONFIG_DIR / "national.yaml").read_text(encoding="utf-8")))
        write_index()
    elif args.cmd == "all":
        from .area import run_area
        from .national import run_national
        for slug, area in areas.items():
            run_area(slug, area, skip_sentinel=args.skip_sentinel)
        run_national(yaml.safe_load((CONFIG_DIR / "national.yaml").read_text(encoding="utf-8")))
        write_index()
    elif args.cmd == "index":
        write_index()
    elif args.cmd == "auto":
        from .autoareas import select
        ncfg = yaml.safe_load((CONFIG_DIR / "national.yaml").read_text(encoding="utf-8"))
        new = select(args.n, existing=load_areas(include_auto=False), national_cfg=ncfg)
        for slug, a in new.items():
            print(f"  {slug:28s} {a['name']:22s} bbox={a['bbox']} q_spes={a['q_spes_flom']}")
        if args.run:
            from .area import run_area
            for slug, a in new.items():
                try:
                    run_area(slug, a, skip_sentinel=args.skip_sentinel)
                except Exception as e:  # noqa: BLE001
                    print(f"!! {slug} feilet: {e!r}")
            write_index()
    elif args.cmd == "images":
        from .area import render_images
        for slug in (areas.keys() if args.area == "all" else [args.area]):
            render_images(slug, areas[slug])
    elif args.cmd == "regression":
        from .regression import check
        check(args.area)
