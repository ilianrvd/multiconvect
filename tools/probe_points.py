"""Probe: which ICON-EU fields exist at DWD, do they reach f030, what do the files look like,
and what do the per-point values look like. Prints only, writes nothing to the repo."""
import bz2
import re
import shutil
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import point_extract as pe  # noqa: E402

RAW = "https://raw.githubusercontent.com/ilianrvd/fogNowcast/main/static/"
BASE = "https://opendata.dwd.de/weather/nwp/icon-eu/grib/{run:02d}/"
FIELDS = ["t_2m", "td_2m", "u_10m", "v_10m", "clcl", "hsurf"]
LEADS = [0, 1, 30]


def listing(url):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return re.findall(r'href="([^"?/][^"]*)"', r.text)


def download(run_date, run_hour, field, fxx, out):
    d = BASE.format(run=run_hour) + field + "/"
    files = listing(d)
    ymdh = run_date.replace("-", "") + f"{run_hour:02d}"
    if field == "hsurf":
        cand = [f for f in files if "HSURF" in f.upper() and f.endswith(".bz2")]
    else:
        cand = [f for f in files if f"_{ymdh}_{fxx:03d}_{field.upper()}" in f and f.endswith(".bz2")]
    if not cand:
        print(f"  MISSING {field} f{fxx:03d}: {len(files)} files in dir, e.g. {files[:3]}")
        return None
    gz = out / cand[0]
    with requests.get(d + cand[0], stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(gz, "wb") as f:
            shutil.copyfileobj(r.raw, f)
    path = out / (cand[0][:-4])
    with bz2.open(gz, "rb") as s, open(path, "wb") as t:
        shutil.copyfileobj(s, t)
    print(f"  OK {cand[0]} ({path.stat().st_size/1e6:.1f} MB)")
    return path


def main(run_date, run_hour):
    out = Path("probe_points"); out.mkdir(exist_ok=True)
    print("== top-level directory (fields) ==")
    top = listing(BASE.format(run=run_hour))
    print(" ", [t for t in top if t.rstrip("/") in FIELDS or "hsurf" in t.lower()], "... of", len(top))
    pts = pe.load_points(pe.fetch_json(RAW + "points.json"), pe.fetch_json(RAW + "correction_stations.json"))
    print(f"== points: {len(pts)}")
    grids = {}
    for fld in FIELDS:
        for fxx in ([0] if fld == "hsurf" else LEADS):
            print(f"-- {fld} f{fxx:03d}")
            p = download(run_date, run_hour, fld, fxx, out)
            if not p:
                continue
            name, vals, lat, lon, attrs = pe.read_grid(p)
            print(f"  var={name} shape={vals.shape} lat {lat[0]:.4f}..{lat[-1]:.4f} lon {lon[0]:.4f}..{lon[-1]:.4f} "
                  f"dlat={lat[1]-lat[0]:.5f} units={attrs.get('GRIB_units')} min={vals.min():.2f} max={vals.max():.2f}")
            grids[(fld, fxx)] = (vals, lat, lon)
    print("== per-point values (bilinear), f000 and f030 ==")
    for fxx in (0, 30):
        print(f"-- f{fxx:03d}")
        try:
            t, td, u, v, cl = (grids[(k, fxx)] for k in ("t_2m", "td_2m", "u_10m", "v_10m", "clcl"))
            hs = grids[("hsurf", 0)]
        except KeyError as e:
            print("  skipped, missing", e); continue
        for pid, la, lo, el in pts:
            tv = pe.bilinear(*t, la, lo); tdv = pe.bilinear(*td, la, lo)
            kt, d = pe.wind_from_uv(pe.bilinear(*u, la, lo), pe.bilinear(*v, la, lo))
            print(f"  {pid:8s} t={tv - pe.KELVIN if tv > 150 else tv:6.1f} td={tdv - pe.KELVIN if tdv > 150 else tdv:6.1f} "
                  f"wind={kt}kt/{d} cl={pe.bilinear(*cl, la, lo):5.1f} model_elev={pe.bilinear(*hs, la, lo):7.1f} point_elev={el}")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
