import logging
from pathlib import Path
import numpy as np

logger = logging.getLogger(__name__)


def read_gfs_refc(path: Path, domain: dict) -> tuple:
    import cfgrib
    datasets = cfgrib.open_datasets(str(path))
    for ds in datasets:
        for var in ds.data_vars:
            vals = ds[var].values.astype(np.float32)
            valid = vals[~np.isnan(vals)]
            if len(valid) == 0:
                continue
            if -30 <= valid.max() <= 80:
                lat = ds["latitude"].values
                lon = ds["longitude"].values
                if lat.ndim == 1:
                    lon, lat = np.meshgrid(lon, lat)
                vals, lat, lon = _crop(vals, lat, lon, domain)
                logger.info(f"[GFS] REFC: min={np.nanmin(vals):.1f} max={np.nanmax(vals):.1f} dBZ")
                return vals, lat, lon

    raise RuntimeError("[GFS] REFC not found in file")


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