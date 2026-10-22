import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_LAG_RUNS = 2  # how many older IFS runs to fall back to


def _download_single(run_date, run_hour, fxx, out_dir):
    from herbie import Herbie

    tag = f"ifs_{run_date.replace('-','')}_{run_hour:02d}z_f{fxx:03d}_mucape.grib2"
    out_path = out_dir / tag
    if out_path.exists():
        return out_path

    H = Herbie(f"{run_date} {run_hour:02d}:00", model="ifs", product="oper",
               fxx=fxx, save_dir=out_dir)
    if H.grib is None:
        raise FileNotFoundError(f"[IFS] {run_date} {run_hour:02d}z F{fxx:03d} not published yet")
    local = H.download(":mucape:sfc:")
    if local is None or not Path(local).exists():
        raise FileNotFoundError(f"[IFS] download failed F{fxx:03d}")
    Path(local).rename(out_path)
    return out_path


def _get_step(run_date, run_hour, fxx, out_dir):
    """Same valid time; if the step is not out yet, take it from an older run."""
    base = datetime.strptime(f"{run_date} {run_hour:02d}", "%Y-%m-%d %H")
    for lag in range(MAX_LAG_RUNS + 1):
        r = base - timedelta(hours=6 * lag)
        f = fxx + 6 * lag
        try:
            p = _download_single(r.strftime("%Y-%m-%d"), r.hour, f, out_dir)
            if lag:
                logger.info(f"[IFS] F{fxx:03d} taken from older run {r:%Y-%m-%d %H}z F{f:03d}")
            return p
        except Exception:
            continue
    raise FileNotFoundError(f"[IFS] F{fxx:03d} not available in last {MAX_LAG_RUNS + 1} runs")


def download_ifs_mucape(run_date, run_hour, fxx, out_dir):
    """
    IFS open data is 3-hourly. Returns (path_lo, path_hi, weight_hi)
    or (path, None, 0.0) when the step exists directly.
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    if fxx % 3 == 0:
        p = _get_step(run_date, run_hour, fxx, out_dir)
        logger.info(f"[IFS] Done: {p.name}")
        return p, None, 0.0

    lo = (fxx // 3) * 3
    hi = lo + 3
    logger.info(f"[IFS] Interpolating F{fxx:03d} from F{lo:03d} and F{hi:03d}")
    p_lo = _get_step(run_date, run_hour, lo, out_dir)
    p_hi = _get_step(run_date, run_hour, hi, out_dir)
    return p_lo, p_hi, (fxx - lo) / 3.0