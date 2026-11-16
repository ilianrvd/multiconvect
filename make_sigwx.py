"""
make_sigwx.py
FIR SIGWX CB product from the hourly MultiConvect masks.
6-hour maps from the run's block until 24 UTC of the next day. HIGH = yellow, MED = green.
Label: "HH-HH / HIGH|MED / FLxxx". A moving zone is split into
consecutive period polygons (new one after ~50 km shift, min 2 h).
Experimental - not an official product.
"""
import logging
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import yaml
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import shapely

from classifier import get_polygons

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

COLORS = {
    "HIGH": ("#EDE53A", "#A59C00"),   # fill, edge
    "MED":  ("#90D890", "#2E8B2E"),
}
AIRPORTS = {
    "LBSF": (42.695, 23.406), "LBPD": (42.068, 24.851), "LBBG": (42.570, 27.515),
    "LBWN": (43.232, 27.825), "LBGO": (43.152, 25.713),
}
M_TO_FT = 3.28084


def load_frames(mask_dir):
    frames = {}
    for f in sorted(Path(mask_dir).glob("f*.npz")):
        d = np.load(f, allow_pickle=True)
        valid = datetime.fromisoformat(str(d["valid"]))
        frames[valid] = {k: d[k] for k in ("high", "med", "lat", "lon", "htop")}
        frames[valid]["run"] = str(d["run"])
    return frames


def blocks_from(run_time, last_valid):
    """6-hour blocks from the run's block until 24 UTC of the next day."""
    start = run_time.replace(minute=0, second=0, microsecond=0)
    start = start.replace(hour=(start.hour // 6) * 6)
    end = run_time.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=2)
    blocks = []
    b0 = start
    while b0 < end and b0 <= last_valid:
        blocks.append((b0, b0 + timedelta(hours=6)))
        b0 += timedelta(hours=6)
    return blocks


def hh(t, is_end=False):
    return "24" if (is_end and t.hour == 0) else f"{t.hour:02d}"


def to_fl(meters):
    if meters <= 0:
        return None
    return int(round(meters * M_TO_FT / 100 / 10) * 10)


SHIFT_KM = 50      # centroid shift that starts a new period polygon
MIN_HOURS = 2      # shorter pieces are merged into the neighbouring period
MIN_PIXELS = 10


def _centroid(mask, lat, lon):
    return float(lat[mask].mean()), float(lon[mask].mean())


def _dist_km(a, b):
    dy = (a[0] - b[0]) * 111.0
    dx = (a[1] - b[1]) * 111.0 * np.cos(np.radians((a[0] + b[0]) / 2))
    return float(np.hypot(dx, dy))


def track_segments(masks, hours, lat, lon):
    """
    Follow each convective zone hour by hour. A zone stays in the same
    period polygon while it stays in place; once its centroid moves more than
    SHIFT_KM from where the period started, a new period polygon begins.
    Returns a list of segments: {"hours": [...], "masks": {hour: bool array}}.
    """
    from scipy.ndimage import label, binary_dilation
    grow = np.ones((7, 7), dtype=bool)          # ~20 km link radius between hours
    tracks, active = [], []

    def new_seg(h, m):
        return {"hours": [h], "masks": {h: m}, "c0": _centroid(m, lat, lon)}

    for h in hours:
        lab, n = label(masks[h])
        comps = [lab == i for i in range(1, n + 1)]
        comps = [c for c in comps if c.sum() >= MIN_PIXELS]
        reach = [binary_dilation(t["last"], grow) for t in active]

        assigned, fresh = {}, []
        for c in comps:
            hit = next((i for i, r in enumerate(reach) if (r & c).any()), None)
            if hit is None:
                fresh.append(c)
            else:                                # merges/splits stay with one track
                assigned[hit] = assigned[hit] | c if hit in assigned else c

        nxt = []
        for i, m in assigned.items():
            t = active[i]
            seg = t["segs"][-1]
            if _dist_km(_centroid(m, lat, lon), seg["c0"]) > SHIFT_KM:
                t["segs"].append(new_seg(h, m))
            else:
                seg["hours"].append(h)
                seg["masks"][h] = m
            t["last"] = m
            nxt.append(t)
        for c in fresh:
            t = {"segs": [new_seg(h, c)], "last": c}
            tracks.append(t)
            nxt.append(t)
        active = nxt

    out = []
    for t in tracks:
        segs = t["segs"]
        i = 0
        while len(segs) > 1 and i < len(segs):   # merge too-short pieces
            if len(segs[i]["hours"]) < MIN_HOURS:
                j = i - 1 if i > 0 else i + 1
                segs[j]["hours"] = sorted(segs[j]["hours"] + segs[i]["hours"])
                segs[j]["masks"].update(segs[i]["masks"])
                segs.pop(i)
                i = 0
            else:
                i += 1
        out.extend(segs)
    return out


def segment_info(seg, frames):
    hrs = sorted(seg["hours"])
    win = f"{hh(hrs[0])}-{hh(hrs[-1] + timedelta(hours=1), True)}"
    tops = [float(frames[h]["htop"][m].max()) for h, m in seg["masks"].items() if m.any()]
    union = np.zeros_like(next(iter(seg["masks"].values())))
    for m in seg["masks"].values():
        union |= m
    return win, (to_fl(max(tops)) if tops else None), union


def plot_block(frames, b0, b1, cfg, out_path, run_label):
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature

    d = cfg["domain"]
    hours = [h for h in (b0 + timedelta(hours=i) for i in range(6)) if h in frames]

    fig = plt.figure(figsize=(14, 8.5))
    proj = ccrs.PlateCarree()
    ax = fig.add_subplot(1, 1, 1, projection=proj)
    m = 0.3
    ax.set_extent([d["lon_min"] - m, d["lon_max"] + m, d["lat_min"] - m, d["lat_max"] + m], crs=proj)
    ax.add_feature(cfeature.LAND, facecolor="#FFFFFF", zorder=0)
    ax.add_feature(cfeature.OCEAN, facecolor="#EAF2F8", zorder=0)
    ax.add_feature(cfeature.BORDERS, linewidth=1.2, edgecolor="#111111", zorder=3)
    ax.add_feature(cfeature.COASTLINE, linewidth=0.6, edgecolor="#555555", zorder=3)

    # LIMIT OF FORECAST
    bx = [d["lon_min"], d["lon_max"], d["lon_max"], d["lon_min"], d["lon_min"]]
    by = [d["lat_min"], d["lat_min"], d["lat_max"], d["lat_max"], d["lat_min"]]
    ax.plot(bx, by, color="#777777", linewidth=2, zorder=4)
    ax.text((d["lon_min"] + d["lon_max"]) / 2, d["lat_max"] - 0.08, "LIMIT OF FORECAST",
            ha="center", va="top", fontsize=9, color="#666666", zorder=4)

    for icao, (la, lo) in AIRPORTS.items():
        ax.plot(lo, la, marker="^", color="#333333", markersize=4, zorder=5)
        ax.text(lo + 0.05, la + 0.05, icao, fontsize=7, color="#333333", zorder=5)

    labels = []
    if hours:
        lat = frames[hours[0]]["lat"]
        lon = frames[hours[0]]["lon"]
        level_masks = {
            "MED":  {h: frames[h]["high"] | frames[h]["med"] for h in hours},
            "HIGH": {h: frames[h]["high"].copy() for h in hours},
        }
        polys = {"MED": [], "HIGH": []}
        for key in ("MED", "HIGH"):
            for seg in track_segments(level_masks[key], hours, lat, lon):
                win, fl, union = segment_info(seg, frames)
                for p in get_polygons(union, lat, lon):
                    polys[key].append((p, win, fl))
        high_union = shapely.union_all([p for p, _, _ in polys["HIGH"]]) if polys["HIGH"] else None

        for key, z in (("MED", 1), ("HIGH", 2)):
            fill, edge = COLORS[key]
            for p, win, fl in polys[key]:
                for g in ([p] if p.geom_type == "Polygon" else list(p.geoms)):
                    x, y = g.exterior.xy
                    ax.fill(x, y, facecolor=fill, alpha=0.5, edgecolor=edge,
                            linewidth=1.5, transform=proj, zorder=z)
                # MED arrow points to the green ring, not into the yellow core
                anchor = p
                if key == "MED" and high_union is not None:
                    ring = p.difference(high_union)
                    if not ring.is_empty:
                        anchor = ring
                labels.append((key, p, anchor.representative_point(),
                               f"{win} / {key} / {fl if fl else '---'}"))

    # HIGH labels above the zone, MED labels below
    for k, (key, p, c, txt) in enumerate(labels):
        x0, y0, x1, y1 = p.bounds
        step = 0.22 * (k % 3)                    # stagger neighbouring labels
        if key == "HIGH":
            tx, ty = c.x + 0.2, min(y1 + 0.35 + step, d["lat_max"] - 0.3)
        else:
            tx, ty = c.x - 0.8, max(y0 - 0.45 - step, d["lat_min"] + 0.15)
        ax.annotate(txt, xy=(c.x, c.y), xytext=(tx, ty), fontsize=9, zorder=6,
                    bbox=dict(boxstyle="square,pad=0.25", fc="white", ec="#888888"),
                    arrowprops=dict(arrowstyle="->", color="#444444", lw=0.8))

    ax.set_title(f"FIR SIGWX  CB  (experimental)   VALID {hh(b0)}-{hh(b1, True)} UTC "
                 f"{b0:%d.%m.%Y}   |   RUN {run_label}", fontsize=11)
    ax.legend(handles=[
        mpatches.Patch(facecolor=COLORS["HIGH"][0], edgecolor=COLORS["HIGH"][1], label="HIGH"),
        mpatches.Patch(facecolor=COLORS["MED"][0], edgecolor=COLORS["MED"][1], label="MED"),
    ], loc="lower right", fontsize=9, framealpha=0.9)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"SIGWX saved: {out_path.name}  ({len(labels)} labels)")


def write_page(out_dir, items, run_label):
    days = {}
    for f, t, day in items:
        days.setdefault(day, []).append(
            f'<figure><img src="{f}" alt="{t}"><figcaption>{t}</figcaption></figure>')
    cards = "".join(f'<h2>{day}</h2><div class="grid">{"".join(c)}</div>' for day, c in days.items())
    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FIR SIGWX CB</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0f1419;color:#e0e0e0;margin:0;padding:16px}}
h1{{font-size:20px;margin:0 0 4px}} h2{{font-size:16px;margin:24px 0 10px;color:#8ab4d8}} .meta{{color:#7a8899;font-size:13px;margin-bottom:16px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,520px),1fr));gap:16px}}
figure{{margin:0;background:#1a2332;border-radius:10px;overflow:hidden}}
img{{width:100%;display:block;background:#fff}} figcaption{{padding:8px 12px;font-size:13px;color:#aab}}
a{{color:#8ab4d8}}
</style></head><body>
<h1>FIR SIGWX CB &mdash; experimental</h1>
<div class="meta">Run {run_label} &middot; 6 h blocks to 24 UTC next day &middot; HIGH = 3 models, MED = ICON + 1 &middot; <a href="../">hourly maps</a></div>
{cards}</body></html>"""
    (out_dir / "index.html").write_text(html, encoding="utf-8")


def main():
    cfg = yaml.safe_load(open("config/config.yaml", encoding="utf-8"))
    frames = load_frames(Path(cfg["paths"]["data"]) / "masks")
    if not frames:
        raise SystemExit("No masks in data/masks - run run.py first")
    run_time = min(frames)
    run_label = frames[run_time]["run"]
    out_dir = Path(cfg["paths"]["output"]) / "sigwx"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("sigwx_*.png"):
        old.unlink()
    items = []
    for i, (b0, b1) in enumerate(blocks_from(run_time, max(frames)), 1):
        name = f"sigwx_{i}.png"
        plot_block(frames, b0, b1, cfg, out_dir / name, run_label)
        items.append((name, f"{hh(b0)}-{hh(b1, True)} UTC", f"{b0:%d.%m.%Y}"))
    write_page(out_dir, items, run_label)


if __name__ == "__main__":
    main()
