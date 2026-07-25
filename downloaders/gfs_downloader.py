import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def download_gfs_refc(run_date: str, run_hour: int, fxx: int, out_dir: Path) -> Path:
    from herbie import Herbie

    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"gfs_{run_date.replace('-','')}_{run_hour:02d}z_f{fxx:03d}_refc.grib2"
    out_path = out_dir / tag

    if out_path.exists():
        logger.info(f"[GFS] Already exists: {out_path.name}")
        return out_path

    logger.info(f"[GFS] Downloading REFC F{fxx:03d} ...")
    H = Herbie(
        f"{run_date} {run_hour:02d}:00",
        model="gfs",
        product="pgrb2.0p25",
        fxx=fxx,
        save_dir=out_dir,
    )
    local = H.download(":REFC:entire atmosphere:")

    if local is None or not Path(local).exists():
        raise FileNotFoundError("[GFS] Download failed")

    Path(local).rename(out_path)
    logger.info(f"[GFS] Done: {out_path.name}")
    return out_path