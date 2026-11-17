import logging
import numpy as np

logger = logging.getLogger(__name__)


def _read_single(path):
    """Accumulated precipitation in m. Prefers convective (cp), falls back to total (tp)."""
    import cfgrib
    found = {}
    for ds in cfgrib.open_datasets(str(path)):
        for name in ("cp", "tp"):
            if name in ds.data_vars and name not in found:
                lat = ds["latitude"].values
                lon = ds["longitude"].values
                if lat.ndim == 1:
                    lon, lat = np.meshgrid(lon, lat)
                found[name] = (ds[name].values.astype(np.float32), lat, lon)
    for name in ("cp", "tp"):
        if name in found:
            return (*found[name], name)
    raise RuntimeError(f"[IFS] neither cp nor tp in {path}")


def read_ifs_precip(paths, domain):
    """Mean rate (mm/h) over the 3-hour window. Returns vals, lat, lon, field ('cp' or 'tp')."""
    path_lo, path_hi = paths
    hi, lat, lon, name = _read_single(path_hi)
    lo = np.zeros_like(hi)
    if path_lo is not None:
        lo, _, _, name_lo = _read_single(path_lo)
        if name_lo != name:
            raise RuntimeError(f"[IFS] field mismatch {name_lo}/{name}")
    vals = np.clip(np.nan_to_num(hi - lo), 0, None) * 1000.0 / 3.0
    vals, lat, lon = _crop(vals, lat, lon, domain)
    logger.info(f"[IFS] {name.upper()} rate (3h mean): max={vals.max():.2f} mm/h")
    return vals, lat, lon, name


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
