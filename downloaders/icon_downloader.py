import bz2
import logging
import re
import shutil
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

DWD_BASE = "https://opendata.dwd.de/weather/nwp/icon-eu/grib/{run:02d}/lpi_con_max/"


def download_icon_lpi(run_date: str, run_hour: int, fxx: int, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    date_str = run_date.replace("-", "")
    tag = f"icon_lpi_{date_str}_{run_hour:02d}z_f{fxx:03d}.grib2"
    out_path = out_dir / tag

    if out_path.exists():
        logger.info(f"[ICON] Already exists: {out_path.name}")
        return out_path

    base_url = DWD_BASE.format(run=run_hour)
    r = requests.get(base_url, timeout=30)
    r.raise_for_status()
    files = re.findall(r"icon-eu[^\">]+\.bz2", r.text)

    target = f"_{date_str}{run_hour:02d}_{fxx:03d}_LPI_CON_MAX"
    match = next((f for f in files if target in f), None)

    if not match:
        available = [f for f in files if "LPI_CON_MAX" in f][:3]
        raise FileNotFoundError(f"[ICON] F{fxx:03d} not found. Available: {available}")

    url = base_url + match
    out_gz = out_dir / match

    logger.info(f"[ICON] Downloading {match}")
    with requests.get(url, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        with open(out_gz, "wb") as f:
            shutil.copyfileobj(resp.raw, f)

    logger.info("[ICON] Decompressing ...")
    with bz2.open(out_gz, "rb") as src, open(out_path, "wb") as dst:
        shutil.copyfileobj(src, dst)
    out_gz.unlink()

    logger.info(f"[ICON] Done: {out_path.name}")
    return out_path