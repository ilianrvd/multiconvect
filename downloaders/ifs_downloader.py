import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_LAG_RUNS = 2        # how many older IFS runs to fall back to
SEARCH = ":(?:cp|tp):sfc:"   # convective precip; total precip only as a fallback


def _download_single(run_date, run_hour, fxx, out_dir):
    from herbie import Herbie

    out_path = out_dir / f"ifs_{run_date.replace('-','')}_{run_hour:02d}z_f{fxx:03d}_prec.grib2"
    if out_path.exists():
        return out_path
    H = Herbie(f"{run_date} {run_hour:02d}:00", model="ifs", product="oper",
               fxx=fxx, save_dir=out_dir)
    if H.grib is None:
        raise FileNotFoundError(f"[IFS] {run_date} {run_hour:02d}z F{fxx:03d} not published yet")
    local = H.download(SEARCH)
    if local is None or not Path(local).exists():
        raise FileNotFoundError(f"[IFS] download failed F{fxx:03d}")
    Path(local).rename(out_path)
    return out_path


def download_ifs_precip(run_date, run_hour, fxx, out_dir):
    """
    IFS precipitation is accumulated from the run start and 3-hourly.
    Returns (path_lo, path_hi) for the 3-hour window that contains fxx, both from the
    SAME run (path_lo None when the window starts at step 0). If the window is not
    out yet, an older run is used for the same valid times.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    hi = max(3, -(-fxx // 3) * 3)
    lo = hi - 3
    base = datetime.strptime(f"{run_date} {run_hour:02d}", "%Y-%m-%d %H")
    for lag in range(MAX_LAG_RUNS + 1):
        r = base - timedelta(hours=6 * lag)
        d, h = r.strftime("%Y-%m-%d"), r.hour
        try:
            p_hi = _download_single(d, h, hi + 6 * lag, out_dir)
            p_lo = _download_single(d, h, lo + 6 * lag, out_dir) if lo + 6 * lag > 0 else None
            if lag:
                logger.info(f"[IFS] F{fxx:03d} taken from older run {r:%Y-%m-%d %H}z")
            return p_lo, p_hi
        except Exception:
            continue
    raise FileNotFoundError(f"[IFS] F{fxx:03d} not available in last {MAX_LAG_RUNS + 1} runs")
