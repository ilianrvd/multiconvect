import argparse
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

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
    from downloaders.gfs_downloader  import download_gfs_refc
    from downloaders.ifs_downloader  import download_ifs_mucape
    from readers.gfs_reader  import read_gfs_refc
    from readers.icon_reader import read_icon_lpi
    from readers.ifs_reader  import read_ifs_mucape
    from classifier import classify, get_polygons, regrid
    from plot_map   import plot_map

    data_dir = Path(cfg["paths"]["data"])
    out_dir  = Path(cfg["paths"]["output"]) / "maps"

    logger.info(f"Run: {run_date} {run_hour:02d}z  F{fxx:03d}")

    logger.info("[1/4] Downloading ...")
    gfs_file  = download_gfs_refc(run_date, run_hour, fxx, data_dir / "gfs")
    icon_file = download_icon_lpi(run_date, run_hour, fxx, data_dir / "icon")
    ifs_file  = download_ifs_mucape(run_date, run_hour, fxx, data_dir / "ifs")

    logger.info("[2/4] Reading ...")
    gfs,  lat_gfs,  lon_gfs  = read_gfs_refc(gfs_file,  cfg["domain"])
    icon, lat_icon, lon_icon = read_icon_lpi(icon_file, cfg["domain"])
    ifs,  lat_ifs,  lon_ifs  = read_ifs_mucape(ifs_file, cfg["domain"])

    logger.info("[3/4] Regridding ...")
    gfs_r = regrid(gfs, lat_gfs, lon_gfs, lat_icon, lon_icon)
    ifs_r = regrid(ifs, lat_ifs, lon_ifs, lat_icon, lon_icon)

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
    out_path = out_dir / f"convection_{run_date.replace('-','')}_{run_hour:02d}z_f{fxx:03d}.png"
    plot_map(high_polys, med_polys, low_polys, high_mask, med_mask, low_mask,
             ocnl_mask, lat_icon, lon_icon, cfg, valid_time, out_path)


def find_latest_run(cfg, max_back_hours=24):
    """Намира последния run с наличен IFS."""
    from downloaders.ifs_downloader import download_ifs_mucape
    from herbie import Herbie

    now = datetime.now(timezone.utc)
    for back in range(0, max_back_hours + 1, 6):
        candidate = now - timedelta(hours=back)
        run_hour = (candidate.hour // 6) * 6
        date_str = candidate.strftime("%Y-%m-%d")
        try:
            H = Herbie(f"{date_str} {run_hour:02d}:00", model="ifs",
                       product="oper", fxx=48)
            if H.grib is not None:
                logger.info(f"Latest available run: {date_str} {run_hour:02d}z")
                return date_str, run_hour
        except Exception:
            continue
    raise RuntimeError("No available IFS run found")

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