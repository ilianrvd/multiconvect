"""Stage 2b: download ICON-EU fields for one run and extract per-point rows (docs/archive_points.md in fogNowcast).

Independent of run.py / forecast.yml: ICON-EU only, no GFS/IFS. Writes one CSV with the archive columns.
Usage: python tools/points_run.py [--date YYYY-MM-DD --run HH] [--fmax 30] [--out points_rows.csv]
"""
import argparse
import bz2
import csv
import logging
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import point_extract as pe  # noqa: E402

logger = logging.getLogger("points_run")
RAW = "https://raw.githubusercontent.com/ilianrvd/fogNowcast/main/static/"
BASE = "https://opendata.dwd.de/weather/nwp/icon-eu/grib/{run:02d}/{field}/"
HOURLY = ["t_2m", "td_2m", "u_10m", "v_10m", "clcl"]
COLUMNS = ["run", "valid", "lead_h", "point", "model", "t", "td", "wind_kt", "wind_dir",
           "cloud_low_pct", "model_elev_m"]
_listings = {}


def _listing(run_hour, field):
    key = (run_hour, field)
    if key not in _listings:
        r = requests.get(BASE.format(run=run_hour, field=field), timeout=30)
        r.raise_for_status()
        _listings[key] = re.findall(r'href="([^"?/][^"]*\.bz2)"', r.text)
    return _listings[key]


def _find(run_date, run_hour, field, fxx):
    ymdh = run_date.replace("-", "") + f"{run_hour:02d}"
    if field == "hsurf":
        tag = f"_{ymdh}_HSURF"
    else:
        tag = f"_{ymdh}_{fxx:03d}_{field.upper()}"
    return next((f for f in _listing(run_hour, field) if tag in f), None)


def run_complete(run_date, run_hour, fmax):
    """True when every hourly field of the last lead and hsurf are on the server."""
    try:
        return all(_find(run_date, run_hour, f, fmax) for f in HOURLY) and bool(_find(run_date, run_hour, "hsurf", 0))
    except requests.RequestException as e:
        logger.warning(f"listing failed: {e}")
        return False


def find_latest_run(fmax, now=None, max_back_h=36):
    now = now or datetime.now(timezone.utc)
    t = now.replace(minute=0, second=0, microsecond=0)
    t -= timedelta(hours=t.hour % 6)
    for _ in range(max_back_h // 6 + 1):
        _listings.clear()
        d = t.strftime("%Y-%m-%d")
        if run_complete(d, t.hour, fmax):
            return d, t.hour
        logger.info(f"run {d} {t.hour:02d}z not complete yet")
        t -= timedelta(hours=6)
    raise RuntimeError("No complete ICON-EU run found")


def _download(args):
    run_date, run_hour, field, fxx, out = args
    name = _find(run_date, run_hour, field, fxx)
    if not name:
        return (field, fxx), None
    path = out / name[:-4]
    if not path.exists():
        for attempt in range(3):
            try:
                with requests.get(BASE.format(run=run_hour, field=field) + name, stream=True, timeout=120) as r:
                    r.raise_for_status()
                    with open(out / name, "wb") as f:
                        shutil.copyfileobj(r.raw, f)
                with bz2.open(out / name, "rb") as s, open(path, "wb") as t:
                    shutil.copyfileobj(s, t)
                (out / name).unlink()
                break
            except (requests.RequestException, OSError, EOFError) as e:
                logger.warning(f"{name} attempt {attempt + 1}: {e}")
        else:
            return (field, fxx), None
    return (field, fxx), path


def download_run(run_date, run_hour, fmax, out):
    out.mkdir(parents=True, exist_ok=True)
    jobs = [(run_date, run_hour, f, x, out) for f in HOURLY for x in range(fmax + 1)]
    jobs.append((run_date, run_hour, "hsurf", 0, out))
    with ThreadPoolExecutor(max_workers=6) as ex:
        return dict(ex.map(_download, jobs))


def build_rows(grids, points, run_dt, fmax):
    """grids: {(field, fxx): (vals, lat, lon)}, hsurf at (hsurf, 0). Returns list of dict rows."""
    run_s = run_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    hs = grids.get(("hsurf", 0))
    rows = []
    for fxx in range(fmax + 1):
        valid = (run_dt + timedelta(hours=fxx)).strftime("%Y-%m-%dT%H:%M:%SZ")
        g = {f: grids.get((f, fxx)) for f in HOURLY}
        for pid, la, lo, _el in points:
            def val(f):
                return pe.bilinear(*g[f], la, lo) if g[f] is not None else float("nan")
            t, td = val("t_2m"), val("td_2m")
            kt, d = pe.wind_from_uv(val("u_10m"), val("v_10m"))
            cl = val("clcl")
            me = pe.bilinear(*hs, la, lo) if hs is not None else float("nan")
            rows.append({
                "run": run_s, "valid": valid, "lead_h": fxx, "point": pid, "model": "icon_eu",
                "t": pe.round_or_none(t - pe.KELVIN, 1), "td": pe.round_or_none(td - pe.KELVIN, 1),
                "wind_kt": kt, "wind_dir": d,
                "cloud_low_pct": None if cl != cl else int(round(min(max(cl, 0.0), 100.0))),
                "model_elev_m": pe.round_or_none(me, 1)})
    return rows


def build_json(rows, generated_at):
    """latest_points.json (docs/archive_points.md): one run, per point a series by hour."""
    runs = {r["run"] for r in rows}
    if len(runs) != 1:
        raise ValueError(f"expected one run, got {runs}")
    points = {}
    for r in rows:
        p = points.setdefault(r["point"], {"id": r["point"], "model_elev_m": r["model_elev_m"], "series": []})
        if p["model_elev_m"] is None:
            p["model_elev_m"] = r["model_elev_m"]
        p["series"].append({"valid": r["valid"], "lead_h": r["lead_h"], "t": r["t"], "td": r["td"],
                            "wind_kt": r["wind_kt"], "wind_dir": r["wind_dir"],
                            "cloud_low_pct": r["cloud_low_pct"]})
    return {"generated_at": generated_at, "source": "MultiConvect", "run": runs.pop(), "model": "icon_eu",
            "units": {"t": "degC", "td": "degC", "wind_kt": "kt", "wind_dir": "deg",
                      "cloud_low_pct": "%", "model_elev_m": "m"},
            "points": list(points.values())}


def write_json(rows, path):
    import json
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(build_json(rows, gen), f, ensure_ascii=False, separators=(",", ":"))


def write_csv(rows, path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(COLUMNS)
        for r in rows:
            w.writerow(["" if r[c] is None else r[c] for c in COLUMNS])


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date"); ap.add_argument("--run", type=int)
    ap.add_argument("--fmax", type=int, default=30)
    ap.add_argument("--out", default="points_rows.csv")
    ap.add_argument("--json", help="also write latest_points.json to this path")
    ap.add_argument("--data", default="data/points_icon")
    a = ap.parse_args()
    if a.date is None or a.run is None:
        a.date, a.run = find_latest_run(a.fmax)
    logger.info(f"ICON-EU run {a.date} {a.run:02d}z, f000-f{a.fmax:03d}")
    pts = pe.load_points(pe.fetch_json(RAW + "points.json"), pe.fetch_json(RAW + "correction_stations.json"))
    files = download_run(a.date, a.run, a.fmax, Path(a.data))
    grids = {}
    for k, p in files.items():
        if p is None:
            logger.warning(f"missing {k}")
            continue
        _n, vals, lat, lon, _at = pe.read_grid(p)
        grids[k] = (vals, lat, lon)
    run_dt = datetime.strptime(f"{a.date} {a.run:02d}", "%Y-%m-%d %H").replace(tzinfo=timezone.utc)
    rows = build_rows(grids, pts, run_dt, a.fmax)
    write_csv(rows, a.out)
    if a.json:
        write_json(rows, a.json)
        logger.info(f"latest_points.json -> {a.json}")
    empty = sum(1 for r in rows if r["t"] is None)
    logger.info(f"{len(rows)} rows ({len(pts)} points x {a.fmax + 1} h), rows without t: {empty} -> {a.out}")
    if empty == len(rows):
        sys.exit("no values extracted")


if __name__ == "__main__":
    main()
