"""Probe Open-Meteo CHMI ALADIN: model ids, which convective variables return data, domain coverage,
and the values at lightning points of 21.11.2026 15-18 UTC."""
import json, urllib.request, urllib.parse, urllib.error
PTS = {"Vratsa": (43.20, 23.55), "Teteven": (42.92, 24.26), "Lovech": (43.14, 24.72), "Sofia": (42.70, 23.32),
       "Pirot": (43.15, 22.59), "Istanbul N": (41.30, 28.90), "Zonguldak": (41.45, 31.00), "Burgas": (42.50, 27.47),
       "Varna": (43.20, 27.90), "SW corner": (40.40, 21.20), "SE corner": (40.40, 31.20), "NE corner": (45.00, 31.20)}
VARS = ["precipitation", "rain", "showers", "snowfall", "cape", "lifted_index", "convective_inhibition",
        "weather_code", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high", "lightning_potential",
        "updraft", "freezing_level_height", "visibility", "wind_gusts_10m"]
MODELS = ["chmi_aladin_seamless", "chmi_aladin_central_europe", "chmi_aladin_europe", "chmi_aladin_central_europe_2km"]

import time
def get(model, lat, lon, variables):
    time.sleep(3)
    q = urllib.parse.urlencode({"latitude": lat, "longitude": lon, "hourly": ",".join(variables), "models": model,
                                "start_date": "2026-11-21", "end_date": "2026-11-21", "timezone": "UTC"})
    for attempt in range(4):
        try:
            req = urllib.request.Request("https://api.open-meteo.com/v1/forecast?" + q,
                                         headers={"User-Agent": "multiconvect-probe"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(30 * (attempt + 1)); continue
            try:
                return json.load(e)
            except Exception:
                return {"error": str(e)[:200]}
        except Exception as e:
            return {"error": str(e)[:200]}
    return {"error": "429 after retries"}

for m in MODELS:
    d = get(m, 43.20, 23.55, VARS)
    if "error" in d or "hourly" not in d:
        print(f"MODEL {m}: {d.get('reason') or d.get('error')}")
        continue
    h = d["hourly"]
    have = [v for v in VARS if v in h and any(x is not None for x in h[v])]
    print(f"MODEL {m}: grid point {d.get('latitude')},{d.get('longitude')}  variables with data: {have}")
print()
model = "chmi_aladin_seamless"
for name, (la, lo) in PTS.items():
    d = get(model, la, lo, VARS)
    if "hourly" not in d:
        print(name, d.get("reason") or d.get("error")); continue
    h = d["hourly"]; idx = [i for i, t in enumerate(h["time"]) if t[11:13] in ("14", "15", "16", "17", "18")]
    cover = any(x is not None for x in h["precipitation"])
    row = []
    for i in idx:
        cells = [f"{v[:6]}={h[v][i]}" for v in VARS if v in h and h[v][i] not in (None, 0, 0.0)]
        row.append(f"{h['time'][i][11:16]} " + " ".join(cells))
    print(f"--- {name} ({la},{lo}) data={'yes' if cover else 'NO'}")
    for r in row: print("   ", r)
