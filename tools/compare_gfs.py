"""
Compare GFS REFC (composite reflectivity) with GFS CPRAT (convective precip rate)
for one run, with ICON LPI as reference. Output: compare/*.png
Usage: python tools/compare_gfs.py 2026-11-16 12 6 9 12 15 18
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import yaml
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from downloaders.icon_downloader import download_icon_lpi
from readers.icon_reader import read_icon_lpi

REFC_THR = 20.0     # current criterion, dBZ
CPRAT_THR = 0.5     # candidate, mm/h


def gfs_field(run, fxx, search, d):
    from herbie import Herbie
    H = Herbie(run, model="gfs", product="pgrb2.0p25", fxx=fxx, verbose=False)
    ds = H.xarray(search)
    if isinstance(ds, list):
        ds = ds[0]
    var = list(ds.data_vars)[0]
    da = ds[var]
    lon = da.longitude.values
    lon = np.where(lon > 180, lon - 360, lon)
    lat = da.latitude.values
    v = da.values
    la = (lat >= d["lat_min"] - 0.5) & (lat <= d["lat_max"] + 0.5)
    lo = (lon >= d["lon_min"] - 0.5) & (lon <= d["lon_max"] + 0.5)
    return v[np.ix_(la, lo)], lat[la], lon[lo]


def main():
    date, hour = sys.argv[1], int(sys.argv[2])
    steps = [int(x) for x in sys.argv[3:]] or [6, 9, 12, 15, 18]
    cfg = yaml.safe_load(open("config/config.yaml", encoding="utf-8"))
    d = cfg["domain"]
    run = f"{date} {hour:02d}:00"
    out = Path("compare")
    out.mkdir(exist_ok=True)
    base = datetime.strptime(run, "%Y-%m-%d %H:%M")
    proj = ccrs.PlateCarree()
    lines = []

    for f in steps:
        refc, lat, lon = gfs_field(run, f, ":REFC:entire atmosphere:", d)
        cprat, _, _ = gfs_field(run, f, rf":CPRAT:surface:{f} hour fcst:", d)
        cprat = cprat * 3600.0                                   # kg m-2 s-1 -> mm/h
        icon_file = download_icon_lpi(date, hour, f, Path("data/icon"))
        lpi, ilat, ilon = read_icon_lpi(icon_file, d)

        n_refc = int((refc >= REFC_THR).sum())
        n_cp = int((cprat >= CPRAT_THR).sum())
        valid = base + timedelta(hours=f)
        lines.append(f"{valid:%d.%m %H}Z  REFC>={REFC_THR:.0f}: {n_refc:5d} px   "
                     f"CPRAT>={CPRAT_THR}: {n_cp:5d} px   CPRAT max {cprat.max():.1f} mm/h")

        fig, axs = plt.subplots(1, 3, figsize=(21, 6), subplot_kw={"projection": proj})
        panels = [
            ("GFS REFC (dBZ) - now", lon, lat, refc, [5, 10, 20, 30, 40, 50], "YlGnBu", REFC_THR),
            ("GFS CPRAT (mm/h) - candidate", lon, lat, cprat, [0.1, 0.5, 1, 2, 5, 10], "YlOrRd", CPRAT_THR),
            ("ICON LPI (J/kg) - reference", ilon[0], ilat[:, 0], lpi, [2, 10, 25, 50, 100], "PuRd", 10),
        ]
        for ax, (title, x, y, v, lev, cmap, thr) in zip(axs, panels):
            ax.set_extent([d["lon_min"], d["lon_max"], d["lat_min"], d["lat_max"]], crs=proj)
            ax.add_feature(cfeature.BORDERS, linewidth=0.8)
            ax.add_feature(cfeature.COASTLINE, linewidth=0.6)
            cs = ax.contourf(x, y, v, levels=lev, cmap=cmap, extend="max", transform=proj)
            ax.contour(x, y, v, levels=[thr], colors="k", linewidths=1.2, transform=proj)
            plt.colorbar(cs, ax=ax, shrink=0.7)
            ax.set_title(title, fontsize=11)
        fig.suptitle(f"GFS {date} {hour:02d}z  +{f}h   valid {valid:%d.%m %H} UTC   "
                     f"(black line = threshold)", fontsize=13)
        fig.savefig(out / f"compare_f{f:03d}.png", dpi=90, bbox_inches="tight")
        plt.close(fig)
        print(lines[-1], flush=True)

    (out / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
