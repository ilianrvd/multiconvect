"""
Per-run summary of the model signals, for the periodic review of model weights.
For every 6-h block of the run and every area (whole domain + each ACC sector):
cell-hours with ICON LPI>=10 / >=20, GFS, IFS, agreement, active cells and HTOP p90 (FL).
Appends to stats/YYYY-MM.csv (kept on the `stats` branch by the workflow).
"""
import csv, json, sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import shape

MASKS = Path("data/masks")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "stats")
FIELDS = ["run", "block", "area", "hours", "cells", "icon10", "icon20", "gfs", "ifs",
          "icon20_gfs", "icon20_ifs", "all3", "act", "htop_p90_fl"]


def main():
    frames = {}
    for f in sorted(MASKS.glob("f*.npz")):
        d = np.load(f, allow_pickle=True)
        frames[datetime.fromisoformat(str(d["valid"]))] = d
    if not frames:
        return
    first = frames[min(frames)]
    run = str(first["run"])
    lat, lon = first["lat"], first["lon"]
    areas = {"DOMAIN": np.ones(lat.shape, bool)}
    sec = Path("config/sectors.geojson")
    if sec.exists():
        for ft in json.load(open(sec, encoding="utf-8"))["features"]:
            areas[ft["properties"]["name"]] = shapely.contains_xy(shape(ft["geometry"]), lon, lat)

    t0 = min(frames).replace(hour=(min(frames).hour // 6) * 6)
    rows = []
    while t0 <= max(frames):
        hours = [h for h in (t0 + timedelta(hours=i) for i in range(6)) if h in frames]
        for name, m in areas.items():
            acc = dict.fromkeys(FIELDS[5:13], 0)
            tops = []
            for h in hours:
                d = frames[h]
                lpi = d["lpi"].astype(float)
                g = d["gfs_s"] if "gfs_s" in d.files else np.zeros_like(m)
                i = d["ifs_s"] if "ifs_s" in d.files else np.zeros_like(m)
                i10, i20 = (lpi >= 10) & m, (lpi >= 20) & m
                act = d["act"] & m
                acc["icon10"] += int(i10.sum()); acc["icon20"] += int(i20.sum())
                acc["gfs"] += int((g & m).sum()); acc["ifs"] += int((i & m).sum())
                acc["icon20_gfs"] += int((i20 & g).sum()); acc["icon20_ifs"] += int((i20 & i).sum())
                acc["all3"] += int((i20 & g & i).sum()); acc["act"] += int(act.sum())
                v = d["htop"][act]
                tops.extend(v[v > 0].tolist())
            fl = int(round(np.percentile(tops, 90) * 3.28084 / 1000) * 10) if tops else ""
            rows.append({"run": run, "block": f"{t0:%Y-%m-%d %H}", "area": name, "hours": len(hours),
                         "cells": int(m.sum()), **acc, "htop_p90_fl": fl})
        t0 += timedelta(hours=6)

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{min(frames):%Y-%m}.csv"
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)
    print(f"summary: {len(rows)} rows -> {path}")


if __name__ == "__main__":
    main()
