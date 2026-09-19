import argparse
import json
from datetime import datetime, timezone

import yaml

from .paths import CONFIG_DIR, DATA_DIR


def load_areas():
    return yaml.safe_load((CONFIG_DIR / "areas.yaml").read_text(encoding="utf-8"))["areas"]


def write_index():
    areas = []
    order = list(load_areas().keys())
    paths = sorted((DATA_DIR / "areas").glob("*/area.json"), key=lambda p: order.index(p.parent.name) if p.parent.name in order else 99)
    for p in paths:
        m = json.loads(p.read_text(encoding="utf-8"))
        areas.append({"slug": m["slug"], "name": m["name"], "region": m.get("region", ""), "bbox": m["bbox"],
                      "generated": m["generated"], "kandidater": m["stats"]["kandidater"]})
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
    elif args.cmd == "regression":
        from .regression import check
        check(args.area)
