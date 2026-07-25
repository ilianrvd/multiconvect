import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def download_ifs_mucape(run_date: str, run_hour: int, fxx: int, out_dir: Path) -> Path:
    from herbie import Herbie

    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"ifs_{run_date.replace('-','')}_{run_hour:02d}z_f{fxx:03d}_mucape.grib2"
    out_path = out_dir / tag

    if out_path.exists():
        logger.info(f"[IFS] Already exists: {out_path.name}")
        return out_path

    logger.info(f"[IFS] Downloading MUCAPE F{fxx:03d} ...")
    H = Herbie(
        f"{run_date} {run_hour:02d}:00",
        model="ifs",
        product="oper",
        fxx=fxx,
        save_dir=out_dir,
    )
    local = H.download(":mucape:sfc:")

    if local is None:
        raise FileNotFoundError("[IFS] Download returned None")

    src = Path(local)
    if not src.exists():
        raise FileNotFoundError(f"[IFS] File not found: {src}")

    src.rename(out_path)
    logger.info(f"[IFS] Done: {out_path.name}")
    return out_path