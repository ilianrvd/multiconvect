import argparse
import copy
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/run.log", mode="a", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


def load_cfg(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def run(cfg, run_date, run_hour, fxx):
    from downloaders.icon_downloader import download_icon_lpi
    from downloaders.gfs_downloader  import download_gfs_cprat
    from downloaders.ifs_downloader  import download_ifs_precip
    from readers.gfs_reader  import read_gfs_cprat
    from readers.icon_reader import read_icon_lpi
    from readers.ifs_reader  import read_ifs_precip
    from classifier import classify, get_polygons, regrid
    from plot_map   import plot_map

    data_dir = Path(cfg["paths"]["data"])
    out_dir  = Path(cfg["paths"]["output"]) / "maps"

    logger.info(f"Run: {run_date} {run_hour:02d}z  F{fxx:03d}")

    logger.info("[1/4] Downloading ...")
    gfs_file  = download_gfs_cprat(run_date, run_hour, fxx, data_dir / "gfs")
    icon_file = download_icon_lpi(run_date, run_hour, fxx, data_dir / "icon")
    ifs_file  = download_ifs_precip(run_date, run_hour, fxx, data_dir / "ifs")

    logger.info("[2/4] Reading ...")
    icon, lat_icon, lon_icon = read_icon_lpi(icon_file, cfg["domain"])
    ifs,  lat_ifs,  lon_ifs, ifs_field = read_ifs_precip(ifs_file, cfg["domain"])

    logger.info("[3/4] Regridding ...")
    if gfs_file is None:                       # F000: no CPRAT in GFS
        gfs_r = np.zeros_like(icon)
    else:
        gfs, lat_gfs, lon_gfs = read_gfs_cprat(gfs_file, cfg["domain"])
        gfs_r = regrid(gfs, lat_gfs, lon_gfs, lat_icon, lon_icon)
    ifs_r = regrid(ifs, lat_ifs, lon_ifs, lat_icon, lon_icon)

    # total precip (fallback) needs a higher threshold than convective precip
    cfg = copy.deepcopy(cfg)
    if ifs_field == "tp":
        cfg["models"]["ifs"]["threshold"] = cfg["models"]["ifs"].get("tp_threshold", 1.0)
        logger.warning("[IFS] cp not available - using tp")

    high_mask, med_mask, low_mask = classify(gfs_r, icon, ifs_r, lat_icon, lon_icon, cfg)

    logger.info("[4/4] Building polygons ...")
    high_polys = get_polygons(high_mask, lat_icon, lon_icon)
    med_polys  = get_polygons(med_mask,  lat_icon, lon_icon)
    low_polys  = get_polygons(low_mask,  lat_icon, lon_icon)

    from classifier import subtract_polys
    low_polys = subtract_polys(low_polys, med_polys + high_polys)
    med_polys = subtract_polys(med_polys, high_polys)   
    logger.info(f"  HIGH={len(high_polys)} poly  MED={len(med_polys)}  LOW={len(low_polys)}")

    from classifier import density_coverage
    ocnl_mask = density_coverage(icon, cfg, lpi_threshold=25, cov_pct=65)

    base = datetime.strptime(f"{run_date} {run_hour:02d}", "%Y-%m-%d %H")
    valid_dt = base + timedelta(hours=fxx)
    valid_time = valid_dt.strftime("%Y-%m-%d %H:00 UTC")

    # SIGWX: hourly masks + convective top (ICON HTOP_CON)
    try:
        from downloaders.icon_downloader import download_icon_field
        from readers.icon_reader import read_icon_field
        htop_file = download_icon_field(run_date, run_hour, fxx, data_dir / "icon", "htop_con")
        htop, _, _ = read_icon_field(htop_file, cfg["domain"])
        if htop.shape != icon.shape:
            raise ValueError(f"HTOP shape {htop.shape} != LPI {icon.shape}")
    except Exception as e:
        logger.warning(f"[ICON] HTOP_CON F{fxx:03d}: {e}")
        htop = np.zeros_like(icon)
    mask_dir = data_dir / "masks"
    mask_dir.mkdir(parents=True, exist_ok=True)
    thr = cfg["models"]
    other = (gfs_r >= thr["gfs"]["threshold"]) | (ifs_r >= thr["ifs"]["threshold"])
    act = (icon >= thr["icon"]["threshold"]) & other
    # SIGWX levels: number of models with a convective signal (ICON widened as in classify)
    from scipy.ndimage import binary_dilation
    e = cfg.get("expand_pixels", 3)
    icon_exp = binary_dilation(icon >= thr["icon"]["threshold"], structure=np.ones((2*e+1, 2*e+1), bool))
    gfs_s = gfs_r >= thr["gfs"]["threshold"]
    ifs_s = ifs_r >= thr["ifs"]["threshold"]
    # HIGH: ICON (only lightning-related field) + GFS or IFS
    # MED:  ICON alone, or GFS + IFS convective precip without ICON (single GFS/IFS = TCU/SHRA, not shown)
    sig2 = icon_exp & (gfs_s | ifs_s)
    sig1 = sig2 | icon_exp | (gfs_s & ifs_s)
    np.savez_compressed(mask_dir / f"f{fxx:03d}.npz", high=high_mask, med=med_mask,
                        low=low_mask, act=act, sig1=sig1, sig2=sig2, other=other, lpi=icon.astype(np.float16),
                        lat=lat_icon, lon=lon_icon, htop=htop,
                        valid=valid_dt.isoformat(),
                        run=f"{run_date[8:10]}.{run_date[5:7]} {run_hour:02d}z")
    out_path = out_dir / f"convection_{run_date.replace('-','')}_{run_hour:02d}z_f{fxx:03d}.png"
    plot_map(high_polys, med_polys, low_polys, high_mask, med_mask, low_mask,
             ocnl_mask, lat_icon, lon_icon, cfg, valid_time, out_path)


def _icon_ready(date_str, run_hour, fxx=48):
    import requests
    url = f"https://opendata.dwd.de/weather/nwp/icon-eu/grib/{run_hour:02d}/lpi_con_max/"
    tag = f"_{date_str.replace('-','')}{run_hour:02d}_{fxx:03d}_LPI_CON_MAX"
    try:
        return tag in requests.get(url, timeout=30).text
    except Exception:
        return False


def find_latest_run(cfg, max_back_hours=24):
    """Latest run where GFS and ICON have the full 48h. IFS fills in by itself."""
    from herbie import Herbie

    now = datetime.now(timezone.utc)
    for back in range(0, max_back_hours + 1, 6):
        c = now - timedelta(hours=back)
        run_hour = (c.hour // 6) * 6
        date_str = c.strftime("%Y-%m-%d")
        try:
            H = Herbie(f"{date_str} {run_hour:02d}:00", model="gfs",
                       product="pgrb2.0p25", fxx=48)
            if H.grib is not None and _icon_ready(date_str, run_hour):
                logger.info(f"Latest available run: {date_str} {run_hour:02d}z")
                return date_str, run_hour
        except Exception:
            continue
    raise RuntimeError("No available GFS+ICON run found")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--date",   default=None)
    parser.add_argument("--run",    type=int, default=None)
    parser.add_argument("--fxx",    type=int, default=None)
    parser.add_argument("--fmax",   type=int, default=48)
    parser.add_argument("--auto",   action="store_true")
    args = parser.parse_args()

    cfg = load_cfg(args.config)
    Path("logs").mkdir(exist_ok=True)

    if args.auto or args.date is None:
        run_date, run_hour = find_latest_run(cfg)
    else:
        run_date, run_hour = args.date, args.run or 0
    maps_dir = Path(cfg["paths"]["output"]) / "maps"
    if maps_dir.exists():
        for old in maps_dir.glob("convection_*.png"):
            old.unlink()
        logger.info("Cleared old maps")
    for old in (Path(cfg["paths"]["data"]) / "masks").glob("f*.npz"):
        old.unlink()

    if args.fxx is not None:
        run(cfg, run_date, run_hour, args.fxx)
    else:
        for fxx in range(0, args.fmax + 1):
            try:
                run(cfg, run_date, run_hour, fxx)
            except Exception as e:
                logger.error(f"F{fxx:03d} failed: {e}")
if __name__ == "__main__":
    main()