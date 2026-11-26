"""manifest.json for the portal (docs/manifest.md in ilianrvd/ilianrvd.github.io).

Written at the end of every production run into the same deploy. Products are listed only when their file
was actually written in this run; each carries the generated_at and data_time (model run) of its own file.
Usage: python tools/manifest_json.py [site_dir]   (default docs)
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = "https://github.com/ilianrvd/multiconvect"
DOC = REPO + "/blob/main/docs/{}"
CADENCE_MIN = 360


def _load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def build_manifest(site_dir, now=None):
    site = Path(site_dir)
    now = now or datetime.now(timezone.utc)
    products, runs = [], []
    lp = _load(site / "latest_points.json")
    if lp and lp.get("generated_at") and lp.get("run"):
        products.append({"id": "latest_points", "path": "latest_points.json", "format": "json",
                         "schema": lp.get("schema", "multiconvect.latest_points/1.0"),
                         "doc": DOC.format("latest_points.md"), "cadence_min": CADENCE_MIN,
                         "generated_at": lp["generated_at"], "data_time": lp["run"]})
        runs.append(lp["run"])
    fm = _load(site / "fog_fields_meta.json")
    if fm and (site / "fog_fields_icon_eu.npz").exists() and fm.get("generated_at") and fm.get("run"):
        products.append({"id": "fog_fields", "path": "fog_fields_icon_eu.npz", "format": "npz",
                         "schema": fm["schema"], "meta": "fog_fields_meta.json",
                         "doc": DOC.format("fog_fields.md"), "cadence_min": CADENCE_MIN,
                         "generated_at": fm["generated_at"], "data_time": fm["run"]})
        runs.append(fm["run"])
    m = {"schema": "portal.manifest/1.0", "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
         "source": "MultiConvect", "id": "multiconvect",
         "name": {"bg": "MultiConvect", "en": "MultiConvect"},
         "description": {"bg": "Конвекция от ICON-EU, GFS и IFS; ICON-EU по точки и като мрежа",
                         "en": "Convection from ICON-EU, GFS and IFS; ICON-EU at points and as a grid"},
         "url": "https://ilianrvd.github.io/multiconvect/", "repo": REPO,
         "status": "experimental", "cadence_min": CADENCE_MIN}
    if runs:
        m["run"] = {"icon_eu": max(runs)}
    m["products"] = products
    return m


def main():
    site = Path(sys.argv[1] if len(sys.argv) > 1 else "docs")
    m = build_manifest(site)
    (site / "manifest.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"manifest.json: {len(m['products'])} products ({', '.join(p['id'] for p in m['products'])})")


if __name__ == "__main__":
    main()
