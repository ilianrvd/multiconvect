import logging
from pathlib import Path
import numpy as np

logger = logging.getLogger(__name__)


def _read_single(path, domain):
    import cfgrib
    datasets = cfgrib.open_datasets(str(path))
    for ds in datasets:
        if "mucape" in ds.data_vars:
            vals = ds["mucape"].values.astype(np.float32)
            lat = ds["latitude"].values
            lon = ds["longitude"].values
            if lat.ndim == 1:
                lon, lat = np.meshgrid(lon, lat)
            vals = np.where(vals < 0, 0.0, vals)
            return vals, lat, lon
    raise RuntimeError(f"[IFS] mucape not found in {path}")


def read_ifs_mucape(paths, domain):
    """
    paths е tuple (path_lo, path_hi, weight_hi) от downloader-а.
    Ако path_hi е None - директно четене. Иначе - интерполация.
    """
    path_lo, path_hi, w_hi = paths

    vals_lo, lat, lon = _read_single(path_lo, domain)

    if path_hi is not None:
        vals_hi, _, _ = _read_single(path_hi, domain)
        vals = (1.0 - w_hi) * vals_lo + w_hi * vals_hi
        logger.info(f"[IFS] MUCAPE (interp w={w_hi:.2f}): max={np.nanmax(vals):.1f} J/kg")
    else:
        vals = vals_lo
        logger.info(f"[IFS] MUCAPE: max={np.nanmax(vals):.1f} J/kg")

    vals, lat, lon = _crop(vals, lat, lon, domain)
    return vals, lat, lon


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