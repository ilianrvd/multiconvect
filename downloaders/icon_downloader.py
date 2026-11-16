import bz2
import logging
import re
import shutil
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

DWD_BASE = "https://opendata.dwd.de/weather/nwp/icon-eu/grib/{run:02d}/{field}/"


def download_icon_field(run_date: str, run_hour: int, fxx: int, out_dir: Path,
                        field: str = "lpi_con_max") -> Path:
    """Any ICON-EU single-level field from DWD (lpi_con_max, htop_con, ...)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    date_str = run_date.replace("-", "")
    prefix = "icon_lpi" if field == "lpi_con_max" else f"icon_{field}"
    out_path = out_dir / f"{prefix}_{date_str}_{run_hour:02d}z_f{fxx:03d}.grib2"

    if out_path.exists():
        logger.info(f"[ICON] Already exists: {out_path.name}")
        return out_path

    base_url = DWD_BASE.format(run=run_hour, field=field)
    r = requests.get(base_url, timeout=30)
    r.raise_for_status()
    files = re.findall(r"icon-eu[^\">]+\.bz2", r.text)

    target = f"_{date_str}{run_hour:02d}_{fxx:03d}_{field.upper()}"
    match = next((f for f in files if target in f), None)
    if not match:
        raise FileNotFoundError(f"[ICON] {field} F{fxx:03d} not found")

    out_gz = out_dir / match
    logger.info(f"[ICON] Downloading {match}")
    with requests.get(base_url + match, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        with open(out_gz, "wb") as f:
            shutil.copyfileobj(resp.raw, f)

    with bz2.open(out_gz, "rb") as src, open(out_path, "wb") as dst:
        shutil.copyfileobj(src, dst)
    out_gz.unlink()

    logger.info(f"[ICON] Done: {out_path.name}")
    return out_path


def download_icon_lpi(run_date: str, run_hour: int, fxx: int, out_dir: Path) -> Path:
    return download_icon_field(run_date, run_hour, fxx, out_dir, "lpi_con_max")
