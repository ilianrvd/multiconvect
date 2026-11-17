"""
make_sigwx.py
FIR SIGWX CB product from the hourly MultiConvect masks.
6-hour maps from the run's block until 24 UTC of the next day.
MED = ICON alone or GFS+IFS (light green), HIGH = ICON + GFS/IFS (dark green), OCNL yellow, FRQ orange.
Label: "HH-HH / HIGH|MED / FLxxx". A moving or spreading zone is split into
consecutive period polygons (overlap < 50 % with the start area, 50 km shift,
or 3 h if the zone changes; min 2 h).
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

# Colour (fill, edge)
#   MED ISOL  (ICON alone, or GFS+IFS without ICON) -> light green
#   HIGH ISOL (ICON + GFS or IFS)                   -> dark green
#   OCNL (density of model-agreement cells)        -> yellow
#   FRQ                                            -> orange
COLORS = {
    "light_green": ("#C5E3A6", "#7BA85A"),
    "dark_green":  ("#5FA35C", "#2F7A2C"),
    "yellow":      ("#F2E04A", "#B8A000"),
    "orange":      ("#F59E2E", "#C06A00"),
}
# Density settings - overridden from config.yaml (section "sigwx")
COV_OCNL = 0.40    # mean share of active cells in a ~50 km window -> OCNL
COV_FRQ = 0.70     # -> FRQ
ACT_LPI = 25.0     # active cell: ICON LPI >= this AND GFS or IFS signal


def coverage_class(cov):
    return "FRQ" if cov >= COV_FRQ else "OCNL" if cov >= COV_OCNL else "ISOL"


def colour_for(level, cov_class):
    if cov_class == "FRQ":
        return "orange"
    if cov_class == "OCNL":
        return "yellow"
    return "light_green" if level == "MED" else "dark_green"


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
        # older files: no LOW mask / active cells
        frames[valid]["low"] = d["low"] if "low" in d.files else np.zeros_like(d["high"])
        if "lpi" in d.files and "other" in d.files:
            frames[valid]["lpi"] = d["lpi"].astype(np.float32)
            frames[valid]["other"] = d["other"]
            frames[valid]["act"] = (frames[valid]["lpi"] >= ACT_LPI) & d["other"]
        else:
            frames[valid]["act"] = d["act"] if "act" in d.files else d["high"]
        # SIGWX levels by number of models (older masks: old HIGH/MED definitions)
        frames[valid]["sig1"] = d["sig1"] if "sig1" in d.files else d["high"] | d["med"]
        frames[valid]["sig2"] = d["sig2"] if "sig2" in d.files else d["high"]
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
KEEP_SHARE = 0.5   # new period when less than this share of the zone is inside the start footprint
STILL_SHARE = 0.8  # above this the zone counts as stationary (no 3 h cap)
MAX_HOURS = 3      # a changing zone is split at least every 3 hours
MIN_HOURS = 2      # shorter pieces are merged into the neighbouring period
MIN_PIXELS = 10
MIN_MED_KM2 = 2000  # smaller MED zones are dropped
INSIDE_SHARE = 0.5  # same-level polygons overlapping at least this share (of the smaller) are merged
NEST_SHARE = 0.8   # ...or merged regardless of time when this share lies inside
MAX_MED_LABELS = 5
MIN_DENSE_KM2 = 500   # OCNL/FRQ parts at least this big get their own label  # label cap for MED zones (largest first); HIGH always labelled


def _merge_win(a, b):
    """'00-02' + '03-04' -> '00-04' (windows inside one 6 h block)."""
    a0, a1 = (int(x) for x in a.split("-"))
    b0, b1 = (int(x) for x in b.split("-"))
    if a1 < a0:
        a1 += 24
    if b1 < b0:
        b1 += 24
    lo, hi = min(a0, b0), max(a1, b1)
    return f"{lo % 24:02d}-{24 if hi % 24 == 0 and hi > lo else hi % 24:02d}"


def _win_span(win):
    a, b = (int(x) for x in win.split("-"))
    return a, (b + 24 if b <= a else b)


def _win_overlap(w1, w2):
    a0, a1 = _win_span(w1)
    b0, b1 = _win_span(w2)
    return a0 < b1 and b0 < a1


def _win_hours(win):
    a, b = (int(x) for x in win.split("-"))
    return (b - a) % 24 or 24


def _area_km2(p):
    lat0 = p.centroid.y
    return p.area * 111.0 * 111.0 * np.cos(np.radians(lat0))


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
        return {"hours": [h], "masks": {h: m}, "c0": _centroid(m, lat, lon), "m0": m}

    def starts_new_period(seg, m):
        if _dist_km(_centroid(m, lat, lon), seg["c0"]) > SHIFT_KM:
            return True
        share = float((m & seg["m0"]).sum()) / max(m.sum(), 1)
        if share < KEEP_SHARE:                   # zone has left / spread out of its start area
            return True
        return len(seg["hours"]) >= MAX_HOURS and share < STILL_SHARE

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
            if starts_new_period(seg, m):
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


DENS_WIN = 7        # ~50 km window on the ICON grid (0.0625 deg)


def _top(values):
    return to_fl(float(np.percentile(values, 90))) if len(values) else None


def segment_info(seg, frames):
    """Window, FL (90th pct), union mask and max local density of active cells."""
    from scipy.ndimage import uniform_filter
    hrs = sorted(seg["hours"])
    win = f"{hh(hrs[0])}-{hh(hrs[-1] + timedelta(hours=1), True)}"
    union = np.zeros_like(next(iter(seg["masks"].values())))
    dens = np.zeros(union.shape, dtype=np.float32)
    tops, n = [], 0
    for h, m in seg["masks"].items():
        if not m.any():
            continue
        union |= m
        v = frames[h]["htop"][m]
        tops.extend(v[v > 0].tolist())
        act = (frames[h]["act"] & m).astype(np.float32)
        dens += uniform_filter(act, size=DENS_WIN, mode="constant")
        n += 1
    dens /= max(n, 1)                              # mean over the period, not the worst hour
    return win, _top(tops), union, np.where(union, dens, 0.0)


def calib(seg, frames):
    """Calibration: max of the period-mean density for several LPI thresholds."""
    from scipy.ndimage import uniform_filter
    out = []
    for t in (10, 15, 20, 25):
        dens, n = None, 0
        for h, m in seg["masks"].items():
            fr = frames[h]
            if not m.any() or fr.get("lpi") is None:
                continue
            a = ((fr["lpi"] >= t) & fr["other"] & m).astype(np.float32)
            f = uniform_filter(a, size=DENS_WIN, mode="constant")
            dens = f if dens is None else dens + f
            n += 1
        out.append("--" if dens is None else f"{(dens / n).max():.0%}")
    return "/".join(out)


def poly_info(p, masks, hours, frames, lat, lon):
    """Window and FL for one polygon of a non-tracked (6 h) layer."""
    inside = shapely.contains_xy(p, lon.ravel(), lat.ravel()).reshape(lat.shape)
    present, tops = [], []
    for h in hours:
        sel = masks[h] & inside
        if sel.any():
            present.append(h)
            v = frames[h]["htop"][sel]
            tops.extend(v[v > 0].tolist())
    if not present:
        return None, None
    win = f"{hh(present[0])}-{hh(present[-1] + timedelta(hours=1), True)}"
    return win, _top(tops)


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
            "MED":  {h: frames[h]["sig1"] | frames[h]["sig2"] for h in hours},
            "HIGH": {h: frames[h]["sig2"].copy() for h in hours},
        }
        polys = {"LOW": [], "MED": [], "HIGH": []}   # (polygon, window, FL, colour)

        # LOW (ISOL) is not shown any more

        # MED / HIGH: tracked periods. Base zone in the ISOL colour, dense parts on top
        dense = []                                   # (polygon, colour) - no labels
        base_col = {"MED": "light_green", "HIGH": "dark_green"}
        for key in ("MED", "HIGH"):
            for seg in track_segments(level_masks[key], hours, lat, lon):
                if key == "MED" and len(seg["hours"]) < MIN_HOURS:   # short-lived MED zone
                    continue                                          # (HIGH kept even for 1 h)
                win, fl, union, dens = segment_info(seg, frames)
                seg_polys = get_polygons(union, lat, lon)
                if key == "MED":                       # drop small MED zones
                    seg_polys = [p for p in seg_polys if _area_km2(p) >= MIN_MED_KM2]
                for p in seg_polys:
                    polys[key].append((p, win, fl, base_col[key]))
                if not seg_polys:
                    continue
                zone = shapely.union_all(seg_polys)
                n = int(union.sum())
                parts = []
                for cls, lo_, hi_ in (("OCNL", COV_OCNL, COV_FRQ), ("FRQ", COV_FRQ, 9.9)):
                    sub = (dens >= lo_) & (dens < hi_) if cls == "OCNL" else dens >= lo_
                    share = float(sub.sum()) / max(n, 1)
                    parts.append(f"{cls}={share:.0%}")
                    col = colour_for(key, cls)
                    for q in get_polygons(sub, lat, lon, min_distance_deg=0.1, min_pixels=6):
                        q = q.intersection(zone)
                        if not q.is_empty and q.area > 0:
                            dense.append((q, col, 4 if cls == "FRQ" else 3.5 if key == "HIGH" else 3))
                logger.info(f"  {b0:%d.%m %H}z block  {key:4s} {win}  {' '.join(parts)}  "
                            f"maxdens[LPI>=10/15/20/25]={calib(seg, frames)}")

        # same-level polygons that overlap at least half (of the smaller one) are merged:
        # one outline (union), period widened to cover both, higher FL
        for key in ("MED", "HIGH"):
            items = [list(t) for t in polys[key]]
            changed = True
            while changed:
                changed = False
                items.sort(key=lambda t: -t[0].area)
                for i in range(len(items)):
                    for j in range(i + 1, len(items)):
                        a, b = items[i], items[j]
                        small = min(a[0].area, b[0].area)
                        if small <= 0:
                            continue
                        share = a[0].intersection(b[0]).area / small
                        # same place at the same time, or one almost entirely inside the other;
                        # consecutive periods of a moving zone stay separate
                        if (share >= INSIDE_SHARE and _win_overlap(a[1], b[1])) or share >= NEST_SHARE:
                            a[0] = a[0].union(b[0])
                            a[1] = _merge_win(a[1], b[1])
                            a[2] = max([x for x in (a[2], b[2]) if x] or [None])
                            items.pop(j)
                            changed = True
                            break
                    if changed:
                        break
            polys[key] = [tuple(t) for t in items]

        # MED dense parts are not drawn where a HIGH zone already is (yellow over yellow)
        if polys["HIGH"]:
            hu = shapely.union_all([q[0] for q in polys["HIGH"]])
            clipped = []
            for q, col, z in dense:
                if z == 3:                                   # MED OCNL / FRQ
                    q = q.difference(hu)
                if not q.is_empty and q.area > 0:
                    clipped.append((q, col, z))
            dense = clipped
        dense = [t for t in dense
                 if any(t[0].intersects(q[0]) for k in ("MED", "HIGH") for q in polys[k])]
        # one outline per colour: overlapping dense parts of different periods are merged
        merged, zs = {}, {}
        for q, col, z in dense:
            merged.setdefault(col, []).append(q)
            zs[col] = max(zs.get(col, 0), z)
        dense = [(shapely.union_all(v), col, zs[col]) for col, v in merged.items()]

        inner = {"LOW": "MED", "MED": "HIGH"}
        unions = {k: shapely.union_all([q[0] for q in v]) if v else None for k, v in polys.items()}

        # own labels for OCNL / FRQ parts: hours and FL of the dense part itself
        act_masks = {h: frames[h]["act"] for h in hours}
        labelled_frq = []
        for q, col, z in sorted(dense, key=lambda t: -t[2]):      # orange first
            for g in ([q] if q.geom_type == "Polygon" else
                      [x for x in getattr(q, "geoms", []) if x.geom_type == "Polygon"]):
                if _area_km2(g) < MIN_DENSE_KM2:
                    continue
                win, fl = poly_info(g, act_masks, hours, frames, lat, lon)
                if not win:
                    continue
                if col == "yellow" and any(g.intersects(o) for o in labelled_frq):
                    continue                     # yellow ring around a labelled orange core
                if col == "orange":
                    labelled_frq.append(g)
                hu = unions["HIGH"]
                lvl = "HIGH" if hu is not None and g.intersection(hu).area >= 0.5 * g.area else "MED"
                labels.append(("DENSE", g, g.representative_point(),
                               f"{win} / {lvl} / {fl if fl else '---'}"))

        for key, z in (("LOW", 1), ("MED", 2), ("HIGH", 3)):
            for p, win, fl, col in polys[key]:
                fill, edge = COLORS[col]
                for g in ([p] if p.geom_type == "Polygon" else list(p.geoms)):
                    x, y = g.exterior.xy
                    ax.fill(x, y, facecolor=fill, alpha=0.55, edgecolor=edge,
                            linewidth=1.5, transform=proj, zorder=z)
                if key == "LOW":
                    continue                     # LOW is background - no label
                # arrow points to the ring of this level, not into the inner one
                anchor = p
                if key in inner and unions[inner[key]] is not None:
                    ring = p.difference(unions[inner[key]])
                    if key == "LOW" and ring.area < 0.2 * p.area:
                        continue                 # LOW hidden under MED - no label
                    if not ring.is_empty:
                        anchor = ring
                if dense:                                # and not into a yellow/orange part
                    rest = anchor.difference(shapely.union_all([t[0] for t in dense]))
                    if not rest.is_empty and rest.area > 0.05 * anchor.area:
                        anchor = rest
                labels.append((key, p, anchor.representative_point(),
                               f"{win} / {key} / {fl if fl else '---'}"))

    if hours:
        for q, col, z in sorted(dense, key=lambda t: t[2]):
            fill, edge = COLORS[col]
            for g in ([q] if q.geom_type == "Polygon" else [x for x in getattr(q, "geoms", []) if x.geom_type == "Polygon"]):
                x, y = g.exterior.xy
                ax.fill(x, y, facecolor=fill, alpha=0.8, edgecolor=edge,
                        linewidth=1.0, transform=proj, zorder=z)

    # HIGH labels above the zone, MED below, LOW left; shifted until they do not overlap
    placed = []

    def free_spot(tx, ty, txt, direction):
        w, hgt = 0.075 * len(txt) + 0.1, 0.22
        for _ in range(12):
            box = (tx, ty, tx + w, ty + hgt)
            if not any(box[0] < o[2] and o[0] < box[2] and box[1] < o[3] and o[1] < box[3] for o in placed):
                break
            ty += direction * 0.26
        ty = min(max(ty, d["lat_min"] + 0.1), d["lat_max"] - 0.35)
        placed.append((tx, ty, tx + w, ty + hgt))
        return tx, ty

    high_l = [t for t in labels if t[0] == "HIGH"]
    med_l = sorted([t for t in labels if t[0] == "MED"], key=lambda t: -t[1].area)[:MAX_MED_LABELS]
    dense_l = [t for t in labels if t[0] == "DENSE"]
    labels = dense_l + high_l + med_l
    for k, (key, p, c, txt) in enumerate(labels):
        x0, y0, x1, y1 = p.bounds
        if key == "HIGH":
            tx, ty = free_spot(c.x + 0.2, y1 + 0.3, txt, +1)
        elif key == "MED":
            tx, ty = free_spot(c.x - 0.8, y0 - 0.5, txt, -1)
        else:                                    # OCNL / FRQ part: to the right
            tx, ty = free_spot(min(x1 + 0.4, d["lon_max"] - 2.0), c.y + 0.1, txt, +1)
        ax.annotate(txt, xy=(c.x, c.y), xytext=(tx, ty), fontsize=9, zorder=6,
                    bbox=dict(boxstyle="square,pad=0.25", fc="white", ec="#888888"),
                    arrowprops=dict(arrowstyle="->", color="#444444", lw=0.8))

    ax.set_title(f"FIR SIGWX  CB  (experimental)   VALID {hh(b0)}-{hh(b1, True)} UTC "
                 f"{b0:%d.%m.%Y}   |   RUN {run_label}", fontsize=11)
    ax.legend(handles=[
        mpatches.Patch(facecolor=COLORS[c][0], edgecolor=COLORS[c][1], label=t) for c, t in (
            ("orange", "FRQ"),
            ("yellow", "OCNL"),
            ("dark_green", "HIGH ISOL (ICON + GFS/IFS)"),
            ("light_green", "MED ISOL (ICON or GFS+IFS)"),
        )
    ], loc="upper center", bbox_to_anchor=(0.5, -0.01), ncol=4, fontsize=9, frameon=False)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"SIGWX saved: {out_path.name}  ({len(labels)} labels)")


def write_page(out_dir, items, run_label):
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M")   # cache-busting: same file names every run
    days = {}
    for f, t, day in items:
        days.setdefault(day, []).append(
            f'<figure><img src="{f}?v={stamp}" alt="{t}"><figcaption>{t}</figcaption></figure>')
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
<div class="meta">Run {run_label} &middot; 6 h blocks to 24 UTC next day &middot; light green = ICON alone or GFS+IFS, dark green = ICON + GFS/IFS, yellow = OCNL, orange = FRQ &middot; <a href="../">hourly maps</a></div>
{cards}</body></html>"""
    (out_dir / "index.html").write_text(html, encoding="utf-8")


def main():
    global COV_OCNL, COV_FRQ, ACT_LPI
    cfg = yaml.safe_load(open("config/config.yaml", encoding="utf-8"))
    sw = cfg.get("sigwx", {})
    COV_OCNL = sw.get("ocnl", COV_OCNL)
    COV_FRQ = sw.get("frq", COV_FRQ)
    ACT_LPI = sw.get("act_lpi", ACT_LPI)
    logger.info(f"SIGWX density: active = LPI>={ACT_LPI} + GFS/IFS, OCNL>={COV_OCNL:.0%}, FRQ>={COV_FRQ:.0%}")
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
