"""Does CHMI ALADIN (Open-Meteo) ever give showers > 0? Sums over 21-23.11.2026 at a grid of points."""
import json, time, urllib.request, urllib.parse, urllib.error
lats = [41.5, 42.0, 42.5, 43.0, 43.5, 44.0, 44.5]
lons = [22.5, 23.5, 24.5, 25.5, 26.5, 27.5, 28.5]
la = ",".join(str(a) for a in lats for b in lons); lo = ",".join(str(b) for a in lats for b in lons)
for model in ("chmi_aladin_central_europe_2km", "icon_eu", "ecmwf_ifs025"):
    q = urllib.parse.urlencode({"latitude": la, "longitude": lo, "hourly": "precipitation,rain,showers",
                                "models": model, "start_date": "2026-11-21", "end_date": "2026-11-23", "timezone": "UTC"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request("https://api.open-meteo.com/v1/forecast?" + q,
                                        headers={"User-Agent": "multiconvect-probe"}), timeout=90) as r:
                data = json.load(r); break
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(30 * (attempt + 1)); continue
            print(model, e.read()[:200]); data = None; break
    if not data: continue
    data = data if isinstance(data, list) else [data]
    P = R = S = 0.0; n_sh = n_p = 0
    for d in data:
        h = d.get("hourly", {})
        for p, r, s in zip(h.get("precipitation", []), h.get("rain", []), h.get("showers", [])):
            P += p or 0; R += r or 0; S += s or 0
            n_p += (p or 0) > 0.1; n_sh += (s or 0) > 0.1
    print(f"{model:32s} points {len(data)}  sum precip {P:7.1f}  rain {R:7.1f}  showers {S:7.1f}  "
          f"hours precip>0.1: {n_p}  hours showers>0.1: {n_sh}")
    time.sleep(5)
