"""Tests for tools/manifest_json.py. Run: python tests/test_manifest.py (or pytest)."""
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import manifest_json as mj  # noqa: E402

NOW = datetime(2026, 11, 26, 11, 0, 5, tzinfo=timezone.utc)
REQUIRED = {"schema", "generated_at", "source", "id", "name", "description", "url", "repo",
            "status", "cadence_min", "products"}


def site(lp=True, ff=True, npz=True):
    d = Path(tempfile.mkdtemp())
    if lp:
        (d / "latest_points.json").write_text(json.dumps(
            {"schema": "multiconvect.latest_points/1.0", "generated_at": "2026-11-26T10:59:36Z",
             "source": "MultiConvect", "run": "2026-11-26T06:00:00Z", "cadence_min": 360}))
    if ff:
        (d / "fog_fields_meta.json").write_text(json.dumps(
            {"schema": "multiconvect.fog_fields/1.0", "generated_at": "2026-11-26T10:59:36Z",
             "source": "MultiConvect", "run": "2026-11-26T06:00:00Z", "cadence_min": 360}))
    if npz:
        (d / "fog_fields_icon_eu.npz").write_bytes(b"x")
    return d


def test_both_products():
    m = mj.build_manifest(site(), NOW)
    assert REQUIRED <= set(m) and m["schema"] == "portal.manifest/1.0" and m["id"] == "multiconvect"
    assert m["generated_at"] == "2026-11-26T11:00:05Z" and m["status"] == "experimental" and m["cadence_min"] == 360
    ids = {p["id"]: p for p in m["products"]}
    assert set(ids) == {"latest_points", "fog_fields"}
    assert ids["latest_points"]["format"] == "json" and ids["fog_fields"]["format"] == "npz"
    assert ids["fog_fields"]["schema"] == "multiconvect.fog_fields/1.0"
    for p in m["products"]:
        assert p["cadence_min"] == 360 and p["generated_at"] == "2026-11-26T10:59:36Z"
        assert p["data_time"] == "2026-11-26T06:00:00Z" and p["doc"].startswith("https://github.com/")
    assert m["run"] == {"icon_eu": "2026-11-26T06:00:00Z"}


def test_product_listed_only_if_written():
    m = mj.build_manifest(site(ff=False, npz=False), NOW)
    assert [p["id"] for p in m["products"]] == ["latest_points"]
    m = mj.build_manifest(site(lp=False, npz=False), NOW)        # meta without the npz: not listed
    assert m["products"] == [] and "run" not in m
    m = mj.build_manifest(site(lp=False, ff=False, npz=False), NOW)
    assert m["products"] == [] and REQUIRED <= set(m)


def test_broken_json_is_ignored():
    d = site()
    (d / "latest_points.json").write_text("{not json")
    m = mj.build_manifest(d, NOW)
    assert [p["id"] for p in m["products"]] == ["fog_fields"]


if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); n += 1; print("ok", k)
    print(n, "tests passed")
