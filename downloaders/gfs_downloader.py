import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def download_gfs_cprat(run_date: str, run_hour: int, fxx: int, out_dir: Path):
    """GFS instantaneous convective precipitation rate (CPRAT). None at F000 (not in the file)."""
    from herbie import Herbie

    if fxx == 0:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"gfs_{run_date.replace('-','')}_{run_hour:02d}z_f{fxx:03d}_cprat.grib2"
    if out_path.exists():
        logger.info(f"[GFS] Already exists: {out_path.name}")
        return out_path

    logger.info(f"[GFS] Downloading CPRAT F{fxx:03d} ...")
    H = Herbie(f"{run_date} {run_hour:02d}:00", model="gfs", product="pgrb2.0p25",
               fxx=fxx, save_dir=out_dir)
    local = H.download(rf":CPRAT:surface:{fxx} hour fcst:")
    if local is None or not Path(local).exists():
        raise FileNotFoundError("[GFS] CPRAT download failed")
    Path(local).rename(out_path)
    logger.info(f"[GFS] Done: {out_path.name}")
    return out_path
