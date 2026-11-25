"""Per-point values from ICON-EU single-level GRIB fields (stage 2 of the archive-points plan).

Format: docs/archive_points.md in ilianrvd/fogNowcast. Raw model values only, no height correction.
"""
import json
import math
import urllib.request

import numpy as np

MS_TO_KT = 1.94384
KELVIN = 273.15


def load_points(points_json, stations_json):
    """Return [(id, lat, lon, elev_m)] for the airports and NTU stations."""
    out = []
    for p in points_json["points"]:
        out.append((p["id"], p["lat"], p["lon"], p["elev_m"]))
    for s in stations_json["stations"]:
        out.append((s["id"], s["lat"], s["lon"], s["elev_m"]))
    return out


def fetch_json(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def read_grid(path):
    """First 2D variable of a GRIB2 file as (values, lat1d, lon1d); lat ascending. NaN kept as NaN."""
    import cfgrib
    for ds in cfgrib.open_datasets(str(path)):
        for name in ds.data_vars:
            vals = ds[name].values.astype(np.float64)
            if vals.ndim != 2:
                continue
            lat = ds["latitude"].values
            lon = ds["longitude"].values
            if lat.ndim != 1 or lon.ndim != 1:
                raise RuntimeError(f"{path}: not a regular lat/lon grid (lat {lat.shape}, lon {lon.shape})")
            if lat[0] > lat[-1]:
                lat, vals = lat[::-1], vals[::-1, :]
            return name, vals, lat, lon, dict(ds[name].attrs)
    raise RuntimeError(f"No 2D field in {path}")


def bilinear(vals, lat, lon, plat, plon):
    """Bilinear value at (plat, plon) from the 4 surrounding cells. NaN if outside the grid or any corner is NaN."""
    if not (lat[0] <= plat <= lat[-1] and lon[0] <= plon <= lon[-1]):
        return float("nan")
    i = min(max(int(np.searchsorted(lat, plat) - 1), 0), len(lat) - 2)
    j = min(max(int(np.searchsorted(lon, plon) - 1), 0), len(lon) - 2)
    ty = (plat - lat[i]) / (lat[i + 1] - lat[i])
    tx = (plon - lon[j]) / (lon[j + 1] - lon[j])
    v = (vals[i, j] * (1 - ty) * (1 - tx) + vals[i, j + 1] * (1 - ty) * tx +
         vals[i + 1, j] * ty * (1 - tx) + vals[i + 1, j + 1] * ty * tx)
    return float(v)


def wind_from_uv(u_ms, v_ms):
    """Speed in kt and meteorological direction (from, deg 1-360) from u/v in m/s.
    Calm (< 1 kt) gives direction None. Interpolate u and v first, never the direction."""
    if math.isnan(u_ms) or math.isnan(v_ms):
        return None, None
    kt = math.hypot(u_ms, v_ms) * MS_TO_KT
    if kt < 1.0:
        return int(round(kt)), None
    d = (math.degrees(math.atan2(-u_ms, -v_ms)) + 360.0) % 360.0
    d = int(round(d)) % 360
    return int(round(kt)), (d if d else 360)


def round_or_none(x, nd):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(x, nd)
