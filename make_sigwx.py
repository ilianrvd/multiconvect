"""
make_sigwx.py
FIR SIGWX CB product from the hourly MultiConvect masks.
6-hour maps from the run's block until 24 UTC of the next day. HIGH = yellow, MED = green.
Label: "HH-HH / HIGH|MED / FLxxx"
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


def describe(poly, hours, frames, key):
    """Time window inside the block and max CB top (FL) for one polygon."""
    any_frame = frames[hours[0]]
    lon_f = any_frame["lon"].ravel()
    lat_f = any_frame["lat"].ravel()
    inside = shapely.contains_xy(poly, lon_f, lat_f)
    present, tops = [], []
    for h in hours:
        fr = frames[h]
        m = fr["high"] | fr["med"] if key == "MED" else fr["high"]
        sel = inside & m.ravel()
        if sel.any():
            present.append(h)
            tops.append(float(np.nanmax(fr["htop"].ravel()[sel])))
    if not present:
        return None, None
    win = f"{hh(present[0])}-{hh(present[-1] + timedelta(hours=1), True)}"
    fl = to_fl(max(tops)) if tops else None
    return win, fl


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
        hi = np.zeros_like(frames[hours[0]]["high"], dtype=bool)
        md = np.zeros_like(hi)
        for h in hours:
            hi |= frames[h]["high"]
            md |= frames[h]["high"] | frames[h]["med"]

        polys = {"MED": get_polygons(md, lat, lon), "HIGH": get_polygons(hi, lat, lon)}
        high_union = shapely.union_all(polys["HIGH"]) if polys["HIGH"] else None

        for key, z in (("MED", 1), ("HIGH", 2)):
            fill, edge = COLORS[key]
            for p in polys[key]:
                for g in ([p] if p.geom_type == "Polygon" else list(p.geoms)):
                    x, y = g.exterior.xy
                    ax.fill(x, y, facecolor=fill, alpha=0.55, edgecolor=edge,
                            linewidth=1.5, transform=proj, zorder=z)
                win, fl = describe(p, hours, frames, key)
                if not win:
                    continue
                # MED arrow points to the green ring, not into the yellow core
                anchor = p
                if key == "MED" and high_union is not None:
                    ring = p.difference(high_union)
                    if not ring.is_empty:
                        anchor = ring
                labels.append((key, p, anchor.representative_point(),
                               f"{win} / {key} / {fl if fl else '---'}"))

    # HIGH labels above the zone, MED labels below
    for key, p, c, txt in labels:
        x0, y0, x1, y1 = p.bounds
        if key == "HIGH":
            tx, ty = c.x + 0.2, min(y1 + 0.35, d["lat_max"] - 0.3)
        else:
            tx, ty = c.x - 0.8, max(y0 - 0.45, d["lat_min"] + 0.15)
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
