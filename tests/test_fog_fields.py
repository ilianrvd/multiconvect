"""Synthetic-grid tests for fog_fields.py. Run: python tests/test_fog_fields.py (or pytest)."""
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
import fog_fields as ff  # noqa: E402
import points_run as pr  # noqa: E402

RUN = datetime(2026, 11, 26, 6, tzinfo=timezone.utc)
DOMAIN = {"lat_min": 40.3, "lat_max": 45.1, "lon_min": 21.1, "lon_max": 31.3}
LAT = np.arange(35.0, 50.0 + 1e-9, 0.0625)
LON = np.arange(15.0, 40.0 + 1e-9, 0.0625)
FMAX = 3


def field(fn):
    la, lo = np.meshgrid(LAT, LON, indexing="ij")
    return fn(la, lo), LAT, LON


def make_grids():
    g = {("hsurf", 0): field(lambda la, lo: 100.0 + 0 * la)}
    for h in range(FMAX + 1):
        g[("t_2m", h)] = field(lambda la, lo: 273.15 + 5.0 + h + 0 * la)       # 5 + h degC
        g[("td_2m", h)] = field(lambda la, lo: 273.15 + 1.0 + 0 * la)
        g[("u_10m", h)] = field(lambda la, lo: 2.0 + 0 * la)                   # m/s
        g[("v_10m", h)] = field(lambda la, lo: -3.0 + 0 * la)
        g[("clcl", h)] = field(lambda la, lo: 42.0 + 0 * la)
    return g


def build(grids=None):
    arrays, info = ff.build_arrays(grids or make_grids(), RUN, FMAX, DOMAIN)
    return arrays, info, ff.build_meta(RUN, "2026-11-26T10:59:36Z", info)


def test_shapes_and_order():
    a, info, _m = build()
    ny, nx, nt = info["ny"], info["nx"], FMAX + 1
    assert a["t2m"].shape == (nt, ny, nx) and a["clcl"].dtype == np.int16
    assert a["hsurf"].shape == (ny, nx) and a["hsurf"].dtype == np.int16
    assert a["lat"].shape == (ny,) and a["lon"].shape == (nx,)
    assert np.all(np.diff(a["lat"]) > 0) and np.all(np.diff(a["lon"]) > 0)      # ascending
    assert a["lat"][0] >= DOMAIN["lat_min"] and a["lat"][-1] <= DOMAIN["lat_max"]
    assert a["lon"][0] >= DOMAIN["lon_min"] and a["lon"][-1] <= DOMAIN["lon_max"]
    assert a["lat"].dtype == np.float32 and a["valid_time"].dtype == np.int64


def test_valid_time():
    a, _i, _m = build()
    assert a["valid_time"][0] == int(RUN.timestamp())
    assert list(np.diff(a["valid_time"])) == [3600] * FMAX


def test_scaling_roundtrip():
    a, _i, m = build()
    v = m["vars"]
    assert np.allclose(ff.decode(a["t2m"][2], v["t2m"]["scale"], v["t2m"]["offset"]), 7.0, atol=0.006)
    assert np.allclose(ff.decode(a["td2m"][0], 0.01, 0), 1.0, atol=0.006)
    assert np.allclose(ff.decode(a["u10"][0], 0.01, 0), 2.0 * 1.94384, atol=0.006)   # kt
    assert np.allclose(ff.decode(a["v10"][0], 0.01, 0), -3.0 * 1.94384, atol=0.006)
    assert np.allclose(ff.decode(a["clcl"][0], 0.1, 0), 42.0, atol=0.06)
    assert np.allclose(ff.decode(a["hsurf"], 1.0, 0), 100.0)


def test_fill_for_missing():
    g = make_grids()
    del g[("t_2m", 2)]                                   # missing hour
    la, lo = np.meshgrid(LAT, LON, indexing="ij")
    bad = 273.15 + 5.0 + 0 * la
    bad[(la > 42) & (la < 43)] = np.nan                  # NaN cells
    g[("td_2m", 1)] = (bad, LAT, LON)
    a, _i, _m = build(g)
    assert np.all(a["t2m"][2] == ff.FILL) and not np.any(a["t2m"][1] == ff.FILL)
    assert np.any(a["td2m"][1] == ff.FILL) and np.any(a["td2m"][1] != ff.FILL)
    big = ff.encode(np.array([400.0, np.nan, -400.0]), 0.01, 0)      # out of int16 range -> fill
    assert list(big) == [ff.FILL] * 3


def test_meta_header_and_vars():
    _a, info, m = build()
    for k in ("schema", "generated_at", "source", "run", "cadence_min", "models", "vars", "grid"):
        assert k in m
    assert m["schema"] == "multiconvect.fog_fields/1.0" and m["cadence_min"] == 360
    assert m["models"]["icon_eu"]["file"] == "fog_fields_icon_eu.npz"
    assert set(m["vars"]) == {"t2m", "td2m", "u10", "v10", "clcl", "hsurf"}
    for spec in m["vars"].values():
        assert spec["fill"] == -32768 and spec["dtype"] == "int16" and {"units", "scale", "offset"} <= set(spec)
    assert m["vars"]["hsurf"]["static"] is True and m["vars"]["u10"]["units"] == "kt"
    assert m["grid"]["lat_order"] == "ascending" and m["grid"]["ny"] == info["ny"]


def test_run_equals_latest_points_run():
    _a, _i, m = build()
    rows = pr.build_rows(make_grids(), [("LBSF", 42.7, 23.4, 531)], RUN, FMAX)
    js = pr.build_json(rows, "2026-11-26T10:59:36Z")
    assert m["run"] == js["run"] == "2026-11-26T06:00:00Z"
    assert m["generated_at"] == js["generated_at"]


def test_write_files_atomic_and_readable():
    a, _i, m = build()
    with tempfile.TemporaryDirectory() as d:
        npz, meta = ff.write_files(d, a, m)
        z = np.load(npz)
        assert set(z.files) == {"lat", "lon", "valid_time", "hsurf", "t2m", "td2m", "u10", "v10", "clcl"}
        assert np.array_equal(z["t2m"], a["t2m"])
        assert json.load(open(meta))["run"] == m["run"]
        assert not list(Path(d).glob("*.tmp"))


def test_grids_must_share_lat_lon():
    g = make_grids()
    g[("clcl", 1)] = (g[("clcl", 1)][0], LAT + 0.01, LON)
    try:
        build(g)
    except ValueError:
        return
    raise AssertionError("different lat grid was accepted")


if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); n += 1; print("ok", k)
    print(n, "tests passed")
