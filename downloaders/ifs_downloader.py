import logging
from pathlib import Path
import numpy as np

logger = logging.getLogger(__name__)


def _download_single(run_date, run_hour, fxx, out_dir):
    from herbie import Herbie

    tag = f"ifs_{run_date.replace('-','')}_{run_hour:02d}z_f{fxx:03d}_mucape.grib2"
    out_path = out_dir / tag
    if out_path.exists():
        return out_path

    H = Herbie(f"{run_date} {run_hour:02d}:00", model="ifs", product="oper",
               fxx=fxx, save_dir=out_dir)
    local = H.download(":mucape:sfc:")
    if local is None:
        raise FileNotFoundError(f"[IFS] F{fxx:03d} download returned None")
    src = Path(local)
    if not src.exists():
        raise FileNotFoundError(f"[IFS] File not found: {src}")
    src.rename(out_path)
    return out_path


def download_ifs_mucape(run_date, run_hour, fxx, out_dir):
    """
    Downloads IFS MUCAPE. IFS is 3-hourly - for intermediate hours
    returns two adjacent files + weight for interpolation.
    Returns: (path_lo, path_hi, weight_hi) or (path, None, 0.0)
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    if fxx % 3 == 0:
        p = _download_single(run_date, run_hour, fxx, out_dir)
        logger.info(f"[IFS] Done: {p.name}")
        return p, None, 0.0

    # Intermediate hour - interpolation
    lo = (fxx // 3) * 3
    hi = lo + 3
    logger.info(f"[IFS] Interpolating F{fxx:03d} from F{lo:03d} and F{hi:03d}")
    p_lo = _download_single(run_date, run_hour, lo, out_dir)
    p_hi = _download_single(run_date, run_hour, hi, out_dir)
    w_hi = (fxx - lo) / 3.0
    return p_lo, p_hi, w_hi