"""ICON-EU grid fields for fogNowcast: fog_fields_icon_eu.npz + fog_fields_meta.json.

Format: docs/fog_fields.md. Values are int16 (scale/offset/fill from the meta file), lat ascending,
missing value = fill. Built from the GRIB fields that tools/points_run.py already downloaded and read.
"""
import json
import os
from datetime import timedelta
from pathlib import Path

import numpy as np

SCHEMA = "multiconvect.fog_fields/1.0"
MODEL = "icon_eu"
NPZ_NAME = "fog_fields_icon_eu.npz"
META_NAME = "fog_fields_meta.json"
CADENCE_MIN = 360
MS_TO_KT = 1.94384
KELVIN = 273.15
FILL = -32768

# key -> (DWD field, units, scale, offset, converter from the GRIB value)
VARS = {
    "t2m":   ("t_2m",   "degC", 0.01, 0.0, lambda x: x - KELVIN),
    "td2m":  ("td_2m",  "degC", 0.01, 0.0, lambda x: x - KELVIN),
    "u10":   ("u_10m",  "kt",   0.01, 0.0, lambda x: x * MS_TO_KT),
    "v10":   ("v_10m",  "kt",   0.01, 0.0, lambda x: x * MS_TO_KT),
    "clcl":  ("clcl",   "%",    0.1,  0.0, lambda x: x),
}
STATIC = {"hsurf": ("hsurf", "m", 1.0, 0.0, lambda x: x)}


def load_domain(config_path="config/config.yaml"):
    import yaml
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)["domain"]


def encode(x, scale, offset):
    """float array -> int16 with FILL for NaN / non-finite / out of int16 range."""
    x = np.asarray(x, dtype=np.float64)
    with np.errstate(invalid="ignore"):
        raw = np.rint((x - offset) / scale)
    bad = ~np.isfinite(raw) | (raw < -32767) | (raw > 32767)
    raw = np.where(bad, FILL, raw)
    return raw.astype(np.int16)


def decode(raw, scale, offset):
    raw = np.asarray(raw)
    return np.where(raw == FILL, np.nan, raw.astype(np.float64) * scale + offset)


def _crop_idx(lat, lon, d):
    if lat[0] > lat[-1]:
        raise ValueError("lat must be ascending")
    ri = np.where((lat >= d["lat_min"]) & (lat <= d["lat_max"]))[0]
    ci = np.where((lon >= d["lon_min"]) & (lon <= d["lon_max"]))[0]
    if not len(ri) or not len(ci):
        raise ValueError("domain outside the grid")
    return slice(ri[0], ri[-1] + 1), slice(ci[0], ci[-1] + 1)


def build_arrays(grids, run_dt, fmax, domain):
    """grids: {(dwd_field, fxx): (vals, lat, lon)}; hsurf at ("hsurf", 0). Returns (arrays, grid_info)."""
    ref = next((grids[(v[0], 0)] for v in VARS.values() if grids.get((v[0], 0)) is not None), None)
    if ref is None:
        raise RuntimeError("no hourly field at f000, nothing to write")
    _v, lat, lon = ref
    rs, cs = _crop_idx(lat, lon, domain)
    lat_c, lon_c = lat[rs], lon[cs]
    ny, nx = len(lat_c), len(lon_c)
    nt = fmax + 1
    arrays = {"lat": lat_c.astype(np.float32), "lon": lon_c.astype(np.float32),
              "valid_time": np.array([int((run_dt + timedelta(hours=h)).timestamp()) for h in range(nt)],
                                     dtype=np.int64)}
    def check(g):
        if g[1].shape != lat.shape or g[2].shape != lon.shape or not (np.array_equal(g[1], lat) and np.array_equal(g[2], lon)):
            raise ValueError("grids do not share one lat/lon")
    for key, (field, _u, scale, offset, conv) in VARS.items():
        out = np.full((nt, ny, nx), FILL, dtype=np.int16)
        for h in range(nt):
            g = grids.get((field, h))
            if g is None:
                continue
            check(g)
            out[h] = encode(conv(g[0][rs, cs]), scale, offset)
        arrays[key] = out
    for key, (field, _u, scale, offset, conv) in STATIC.items():
        g = grids.get((field, 0))
        if g is None:
            arrays[key] = np.full((ny, nx), FILL, dtype=np.int16)
        else:
            check(g)
            arrays[key] = encode(conv(g[0][rs, cs]), scale, offset)
    info = {"lat_min": float(lat_c[0]), "lat_max": float(lat_c[-1]), "lon_min": float(lon_c[0]),
            "lon_max": float(lon_c[-1]), "step_deg": round(float(lat_c[1] - lat_c[0]), 5),
            "ny": ny, "nx": nx, "hours": nt, "lat_order": "ascending"}
    return arrays, info


def build_meta(run_dt, generated_at, info):
    vars_ = {}
    for key, (_f, units, scale, offset, _c) in VARS.items():
        vars_[key] = {"units": units, "scale": scale, "offset": offset, "fill": FILL, "dtype": "int16"}
    for key, (_f, units, scale, offset, _c) in STATIC.items():
        vars_[key] = {"units": units, "scale": scale, "offset": offset, "fill": FILL, "dtype": "int16",
                      "static": True}
    return {"schema": SCHEMA, "generated_at": generated_at, "source": "MultiConvect",
            "run": run_dt.strftime("%Y-%m-%dT%H:%M:%SZ"), "cadence_min": CADENCE_MIN,
            "models": {MODEL: {"file": NPZ_NAME, "time_step_h": 1, "interpolated_hours": []}},
            "grid": info, "vars": vars_}


def write_files(out_dir, arrays, meta):
    """Both files or none: written under temporary names, then renamed."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tmp_npz, tmp_meta = out / (NPZ_NAME + ".tmp"), out / (META_NAME + ".tmp")
    try:
        with open(tmp_npz, "wb") as f:
            np.savez_compressed(f, **arrays)
        with open(tmp_meta, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp_npz, out / NPZ_NAME)
        os.replace(tmp_meta, out / META_NAME)
    finally:
        for t in (tmp_npz, tmp_meta):
            if t.exists():
                t.unlink()
    return out / NPZ_NAME, out / META_NAME
