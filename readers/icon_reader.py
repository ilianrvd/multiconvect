import logging
from pathlib import Path
import numpy as np

logger = logging.getLogger(__name__)


def read_icon_lpi(path: Path, domain: dict) -> tuple:
    import cfgrib
    datasets = cfgrib.open_datasets(str(path))
    for ds in datasets:
        if "LPI_CON_MAX" in ds.data_vars:
            vals = ds["LPI_CON_MAX"].values.astype(np.float32)
            lat = ds["latitude"].values
            lon = ds["longitude"].values
            if lat.ndim == 1:
                lon, lat = np.meshgrid(lon, lat)
            vals = np.where(vals < 0, 0.0, vals)
            vals, lat, lon = _crop(vals, lat, lon, domain)
            logger.info(f"[ICON] LPI: max={np.nanmax(vals):.2f} J/kg")
            return vals, lat, lon

    raise RuntimeError("[ICON] LPI_CON_MAX not found in file")


def _crop(vals, lat, lon, d):
    mask = ((lat >= d["lat_min"]) & (lat <= d["lat_max"]) &
            (lon >= d["lon_min"]) & (lon <= d["lon_max"]))
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    if not len(rows) or not len(cols):
        return vals, lat, lon
    r0, r1 = rows[0], rows[-1]+1
    c0, c1 = cols[0], cols[-1]+1
    return vals[r0:r1, c0:c1], lat[r0:r1, c0:c1], lon[r0:r1, c0:c1]