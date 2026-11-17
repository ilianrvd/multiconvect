import logging
from pathlib import Path
import numpy as np

logger = logging.getLogger(__name__)


def read_gfs_cprat(path, domain: dict, like=None) -> tuple:
    """CPRAT in mm/h. path None (F000) -> zeros on the GFS grid of `like` (a previous read)."""
    import cfgrib
    if path is None:
        if like is None:
            raise RuntimeError("[GFS] no CPRAT at F000 and no grid to copy")
        _, lat, lon = like
        return np.zeros_like(lat, dtype=np.float32), lat, lon
    for ds in cfgrib.open_datasets(str(path)):
        for var in ds.data_vars:
            vals = ds[var].values.astype(np.float32)
            if vals.ndim != 2:
                continue
            lat = ds["latitude"].values
            lon = ds["longitude"].values
            if lat.ndim == 1:
                lon, lat = np.meshgrid(lon, lat)
            vals = np.where(np.isfinite(vals) & (vals > 0), vals * 3600.0, 0.0)  # kg m-2 s-1 -> mm/h
            vals, lat, lon = _crop(vals, lat, lon, domain)
            logger.info(f"[GFS] CPRAT: max={vals.max():.2f} mm/h")
            return vals, lat, lon
    raise RuntimeError("[GFS] CPRAT not found in file")


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
