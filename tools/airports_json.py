"""
airports.json — MultiConvect convective signal around the airports, hourly 0-48 h.
For airport-nowcast. Per airport and hour:
  cat_25      none / MED / HIGH  — highest SIGWX level within 25 km
  lpi_max_25  max ICON LPI_CON_MAX within 25 km (J/kg, 0 = no signal)
  fl_max_25   max ICON HTOP_CON within 25 km where ICON/HIGH has a signal (FL, 0 = none)
  dens_50     none / ISOL / OCNL / FRQ — share of active cells within 50 km (HIGH present -> ISOL)
  dens_frac_50  that share (0..1)
  models_25   {icon, gfs, ifs}: signal within 25 km (ICON LPI >= 10, GFS CPRAT, IFS cp)
Silence is written explicitly (none / 0), missing hours are absent.
"""
import json, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import yaml

RULES_VERSION = "2026-11-23.1"
AIRPORTS = {  # coordinates as in airport-nowcast config/settings.py
    "LBSF": (42.6952, 23.4064), "LBBG": (42.5696, 27.5152), "LBWN": (43.2321, 27.8251),
    "LBPD": (42.0678, 24.8508), "LBGO": (43.1514, 25.7129),
}
R_CAT, R_DENS = 25.0, 50.0


def dist_km(lat, lon, la0, lo0):
    p = np.radians
    a = np.sin((p(lat) - p(la0)) / 2) ** 2 + np.cos(p(la0)) * np.cos(p(lat)) * np.sin((p(lon) - p(lo0)) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def main(out_path):
    cfg = yaml.safe_load(open("config/config.yaml", encoding="utf-8"))
    sw = cfg.get("sigwx") or {}
    ocnl, frq = sw.get("ocnl", 0.30), sw.get("frq", 0.60)
    icon_thr = cfg["models"]["icon"]["threshold"]
    files = sorted(Path("data/masks").glob("f*.npz"))
    if not files:
        print("airports.json: no masks"); return
    first = np.load(files[0], allow_pickle=True)
    lat, lon = first["lat"], first["lon"]
    near = {k: (dist_km(lat, lon, *v) <= R_CAT, dist_km(lat, lon, *v) <= R_DENS) for k, v in AIRPORTS.items()}
    run_init = datetime.fromisoformat(str(first["valid"])) - timedelta(hours=int(files[0].stem[1:]))
    out = {"run": str(first["run"]), "run_init_utc": run_init.strftime("%Y-%m-%dT%H:%MZ"),
           "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
           "rules_version": RULES_VERSION,
           "radius_km": {"cat": R_CAT, "dens": R_DENS},
           "thresholds": {"icon_lpi": icon_thr, "high_lpi": sw.get("high_lpi", 20), "act_lpi": sw.get("act_lpi", 20),
                          "ocnl": ocnl, "frq": frq,
                          "gfs_cprat_mmh": cfg["models"]["gfs"]["threshold"], "ifs_cp_mmh": cfg["models"]["ifs"]["threshold"]},
           "levels": {"MED": "ICON alone or GFS+IFS", "HIGH": "ICON LPI>=20 + GFS or IFS"},
           "airports": {k: {"lat": v[0], "lon": v[1], "hours": []} for k, v in AIRPORTS.items()}}
    for f in files:
        d = np.load(f, allow_pickle=True)
        valid = datetime.fromisoformat(str(d["valid"])).strftime("%Y-%m-%dT%H:%MZ")
        lpi = d["lpi"].astype(float)
        sig1 = d["sig1"] if "sig1" in d.files else (d["high"] | d["med"])
        sig2 = d["sig2"] if "sig2" in d.files else d["high"]
        gfs = d["gfs_s"] if "gfs_s" in d.files else None
        ifs = d["ifs_s"] if "ifs_s" in d.files else None
        for k, (n25, n50) in near.items():
            cat = "HIGH" if sig2[n25].any() else "MED" if sig1[n25].any() else "none"
            lmax = float(lpi[n25].max())
            sigcells = n25 & ((lpi >= icon_thr) | sig2)
            tops = d["htop"][sigcells]
            fl = int(round(tops.max() * 3.28084 / 1000) * 10) if tops.size and tops.max() > 0 else 0
            frac = float(d["act"][n50].mean())
            dens = ("FRQ" if frac >= frq else "OCNL" if frac >= ocnl else "ISOL") if sig2[n50].any() else "none"
            out["airports"][k]["hours"].append({
                "valid_utc": valid, "lead_h": int(f.stem[1:]), "cat_25": cat, "lpi_max_25": round(lmax, 1),
                "fl_max_25": fl, "dens_50": dens, "dens_frac_50": round(frac, 3),
                "models_25": {"icon": bool((lpi[n25] >= icon_thr).any()),
                              "gfs": bool(gfs[n25].any()) if gfs is not None else None,
                              "ifs": bool(ifs[n25].any()) if ifs is not None else None}})
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"airports.json: {len(files)} hours x {len(AIRPORTS)} airports -> {out_path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "docs/airports.json")
