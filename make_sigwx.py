"""
make_sigwx.py
6-hour CB convection polygon maps from the hourly MultiConvect masks.
6-hour maps from the run's block until 24 UTC of the next day.
MED = ICON alone or GFS+IFS (light green), HIGH = ICON + GFS/IFS (dark green), OCNL yellow, FRQ orange.
Label: "HH-HH / HIGH|MED / FLxxx". A moving or spreading zone is split into
consecutive period polygons (overlap < 50 % with the start area, 50 km shift,
or 3 h if the zone changes; min 2 h).
Experimental - not an official product.
"""
import logging
import os
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
        # all three models (graded levels): ICON + GFS + IFS
        if "gfs_s" in d.files and "ifs_s" in d.files:
            frames[valid]["all3"] = d["gfs_s"] & d["ifs_s"]
            frames[valid]["gfs_s"] = d["gfs_s"]
            frames[valid]["ifs_s"] = d["ifs_s"]
        frames[valid]["run"] = str(d["run"])
    return frames


GRADED = False   # sigwx.graded: label level HIGH = ICON + GFS + IFS, MED = ICON + one of them


NEIGH_DEG = 0.25   # ~25 km tolerance: global models place convection coarsely
MODEL_COVER = 0.20 # a model "agrees" if its signal covers this share of the (buffered) area


MODEL_COVER_FRQ = 0.50  # FRQ cores: exact position less certain -> stricter


def graded_level(geom, masks, hours, frames, lat, lon, default, need=None):
    """HIGH if GFS and IFS both have convective precip over the area (with ~25 km tolerance)
    during its hours, MED if only one. Larger areas are more likely to contain both
    signals than small cores - the probability that CB occur somewhere in the area."""
    if not GRADED or "all3" not in frames[hours[0]]:
        return default
    inside = shapely.contains_xy(geom, lon.ravel(), lat.ravel()).reshape(lat.shape)
    near = shapely.contains_xy(geom.buffer(NEIGH_DEG), lon.ravel(), lat.ravel()).reshape(lat.shape)
    act_h = [h for h in hours if (masks[h] & inside).any()]
    if not act_h or not near.any():
        return default
    cover = {}
    for k in ("gfs_s", "ifs_s"):
        u = np.zeros_like(near)
        for h in act_h:
            u |= frames[h][k]
        cover[k] = float((u & near).sum()) / near.sum()
    logger.info(f"    graded: GFS {cover['gfs_s']:.0%} IFS {cover['ifs_s']:.0%} of area")
    return "HIGH" if min(cover.values()) >= (need or MODEL_COVER) else "MED"


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


SHIFT_KM = 100     # centroid shift that starts a new period polygon (growing zones shift easily)
KEEP_SHARE = 0.3   # new period when less than this share of the zone is inside the start footprint
STILL_SHARE = 0.8  # above this the zone counts as stationary (no 3 h cap)
MAX_HOURS = 3      # a changing zone is split at least every 3 hours
MIN_HOURS = 2      # shorter pieces are merged into the neighbouring period
MIN_PIXELS = 10
MIN_MED_KM2 = 2000  # smaller MED zones are dropped
INSIDE_SHARE = 0.5  # same-level polygons overlapping at least this share (of the smaller) are merged
NEST_SHARE = 0.8   # ...or merged regardless of time when this share lies inside
MAX_MED_LABELS = 5
MIN_DENSE_KM2 = 200   # smaller OCNL/FRQ parts are not drawn; every drawn part gets its own label
MIN_FRQ_KM2 = 1500    # smaller FRQ cores are shown as OCNL (yellow)
TOUCH_DEG = 0.15      # same-level zones closer than this (~15 km) with overlapping hours are merged


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


MED_ADJ_SHARE = 0.5  # MED periods following each other are merged above this overlap


def _win_adjacent(w1, w2):
    a0, a1 = _win_span(w1)
    b0, b1 = _win_span(w2)
    return a1 == b0 or b1 == a0 or _win_overlap(w1, w2)


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


MIN_CB_FL = 100   # lower "tops" are shallow showers, not CB - shown as ---


def _top(values):
    if not len(values):
        return None
    fl = to_fl(float(np.percentile(values, 90)))
    return fl if fl and fl >= MIN_CB_FL else None


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


SECTOR_TOPS = None   # [(polygon, min FL)] from config/sectors.geojson + sigwx.sector_min_top


def _load_sector_tops(cfg):
    global SECTOR_TOPS
    path = Path("config/sectors.geojson")
    if not path.exists():
        return
    import sector_table as st
    secs = st.load_sectors(path)
    mt = st.min_tops(secs, (cfg.get("sigwx") or {}).get("sector_min_top"))
    SECTOR_TOPS = [(g, mt[n]) for n, g in secs.items()]


def _min_top_for(geom):
    """Minimum TOP of the sector holding most of geom; outside all sectors: the nearest one."""
    best, best_a = None, 0.0
    for g, fl in SECTOR_TOPS:
        a = geom.intersection(g).area
        if a > best_a:
            best, best_a = fl, a
    if best is None:
        c = geom.representative_point()
        best = min(SECTOR_TOPS, key=lambda t: t[0].distance(c))[1]
    return best


def dense_info(p, masks, hours, frames, lat, lon, share):
    """Window and FL of an OCNL/FRQ part: only the hours in which active cells
    cover at least `share` of the part (else the single densest hour)."""
    inside = shapely.contains_xy(p, lon.ravel(), lat.ravel()).reshape(lat.shape)
    n = int(inside.sum())
    if n == 0:
        return None, None
    cov = {h: float((masks[h] & inside).sum()) / n for h in hours}
    present = [h for h in hours if cov[h] >= share]
    if not present:
        # large part (e.g. a wide yellow area): coverage of the whole part never reaches the
        # threshold, so take the hours with at least half of its peak coverage
        peak = max(cov.values())
        if peak == 0:
            return None, None
        present = [h for h in hours if cov[h] >= 0.5 * peak]
        present = [h for h in hours if present[0] <= h <= present[-1]]
    tops = []
    for h in present:
        v = frames[h]["htop"][masks[h] & inside]
        tops.extend(v[v > 0].tolist())
    if not tops:                      # ICON gives LPI but no HTOP in those cells: use the whole part
        for h in hours:
            v = frames[h]["htop"][inside]
            tops.extend(v[v > 0].tolist())
    win = f"{hh(present[0])}-{hh(present[-1] + timedelta(hours=1), True)}"
    return win, _top(tops)


BLOCK_GEOMS = {}   # b0 -> drawn HIGH / OCNL / FRQ geometry (for the sector table)
CLUSTER_DEG = 0.5  # OCNL/FRQ parts of one colour and period closer than this (~50 km) = one item


def _fill_with_holes(ax, poly, transform, **kw):
    from matplotlib.path import Path as MPath
    from matplotlib.patches import PathPatch
    verts, codes = [], []
    for ring in [poly.exterior] + list(poly.interiors):
        xy = np.asarray(ring.coords)
        verts.extend(xy.tolist())
        codes.extend([MPath.MOVETO] + [MPath.LINETO] * (len(xy) - 2) + [MPath.CLOSEPOLY])
    ax.add_patch(PathPatch(MPath(verts, codes), transform=transform, **kw))


ARROW_DEG = 0.5        # parts of one item closer than this share one label (several arrows)
YELLOW_LABEL_KM2 = 3000  # smaller yellow pieces (slivers around orange) get no label of their own


def _cluster(parts, dist):
    """Group polygons that lie within `dist` of each other; returns one (Multi)Polygon per group,
    largest groups first."""
    groups = []
    for p in sorted(parts, key=lambda g: -g.area):
        near = [g for g in groups if any(p.distance(x) <= dist for x in g)]
        merged = [p] + [x for g in near for x in g]
        groups = [g for g in groups if g not in near] + [merged]
    return [shapely.union_all(g) for g in sorted(groups, key=lambda g: -sum(x.area for x in g))]


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

    # ACC sectors (approximate outlines) for orientation
    sec_path = Path("config/sectors.geojson")
    if sec_path.exists():
        import sector_table as st
        for sname, sg in st.load_sectors(sec_path).items():
            x, y = sg.exterior.xy
            ax.plot(x, y, color="#3355AA", linewidth=0.7, alpha=0.6, transform=proj, zorder=4.5)
            c = sg.representative_point()
            ax.text(c.x, c.y, sname, fontsize=8, color="#3355AA", alpha=0.8, ha="center",
                    va="center", transform=proj, zorder=4.5)

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
                            dense.append((q, col, 4 if cls == "FRQ" else 3.5 if key == "HIGH" else 3,
                                          frozenset(seg["hours"])))
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
                        # touching (or overlapping) zones active at the same time, or one almost
                        # entirely inside the other; consecutive periods of a moving zone stay separate
                        # MED (light green): consecutive periods that mostly overlap are one
                        # zone that hardly moved - not worth two outlines
                        med_adj = (key == "MED" and share >= MED_ADJ_SHARE
                                   and _win_adjacent(a[1], b[1]))
                        if ((_win_overlap(a[1], b[1]) and a[0].distance(b[0]) <= TOUCH_DEG)
                                or share >= NEST_SHARE or med_adj):
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
            dense = [(q.difference(hu) if z == 3 else q, col, z, hs) for q, col, z, hs in dense]
        dense = [t for t in dense if not t[0].is_empty and t[0].area > 0
                 and any(t[0].intersects(q[0]) for k in ("MED", "HIGH") for q in polys[k])]

        def _parts(geom):
            return [x for x in ([geom] if geom.geom_type == "Polygon" else getattr(geom, "geoms", []))
                    if x.geom_type == "Polygon"]
        # one item per polygon part; small FRQ cores -> OCNL; tiny parts dropped
        items = []
        for q, col, z, hs in dense:
            for g in _parts(q):
                if col == "orange" and _area_km2(g) < MIN_FRQ_KM2:
                    col_g, z_g = "yellow", 3
                else:
                    col_g, z_g = col, z
                if _area_km2(g) >= MIN_DENSE_KM2:
                    items.append([g, col_g, z_g, set(hs)])
        # dense parts are kept per period like the zones: parts of one colour are merged only
        # when they are active in the same hours and lie within CLUSTER_DEG (one item = one label);
        # a moving system keeps
        # one item per period instead of one long swath
        changed = True
        while changed:
            changed = False
            for a_ in range(len(items)):
                for b_ in range(a_ + 1, len(items)):
                    A, B = items[a_], items[b_]
                    if A[1] == B[1] and A[3] & B[3] and A[0].distance(B[0]) <= CLUSTER_DEG:
                        A[0] = A[0].union(B[0]); A[2] = max(A[2], B[2]); A[3] |= B[3]
                        items.pop(b_); changed = True
                        break
                if changed:
                    break
        dense_items = [tuple(t) for t in items]
        # CB density shown only where the CB reach the traffic: an OCNL/FRQ part stays only if
        # its top (FL, as in its label) reaches the minimum TOP of the sector it mostly lies in
        # (sigwx.sector_min_top: Istanbul low, bordering sectors middle, north/west high;
        # outside the sectors the nearest sector's value). Parts below stay as their green zone.
        if SECTOR_TOPS is not None:
            act_m = {h: frames[h]["act"] for h in hours}
            kept = []
            for t in dense_items:
                _w, fl_t = dense_info(t[0], act_m, [h for h in hours if h in t[3]] or hours, frames, lat, lon,
                                      COV_FRQ if t[1] == "orange" else COV_OCNL)
                need = _min_top_for(t[0])
                if fl_t is not None and fl_t >= need:
                    kept.append(t)
                else:
                    logger.info(f"    {t[1]} part {_area_km2(t[0]):.0f} km2 dropped: FL{fl_t} < FL{need}")
            dense_items = kept
        for t in sorted(dense_items, key=lambda t: -t[0].area):
            logger.debug(f"    dense item {t[1]:6s} {_area_km2(t[0]):7.0f} km2  {min(t[3]):%H}-{max(t[3]):%H}")
        # drawing: one fill per colour, yellow with the orange cut out
        dense = []
        cu = {c: shapely.union_all([t[0] for t in dense_items if t[1] == c])
              for c in ("yellow", "orange") if any(t[1] == c for t in dense_items)}
        if "yellow" in cu and "orange" in cu:
            cu["yellow"] = cu["yellow"].difference(cu["orange"])
        for c, g in cu.items():
            if not g.is_empty:
                dense.append((g, c, 4 if c == "orange" else 3))

        inner = {"LOW": "MED", "MED": "HIGH"}
        unions = {k: shapely.union_all([q[0] for q in v]) if v else None for k, v in polys.items()}
        BLOCK_GEOMS[b0] = {"HIGH": unions["HIGH"],
                           "OCNL": next((t[0] for t in dense if t[1] == "yellow"), None),
                           "FRQ": next((t[0] for t in dense if t[1] == "orange"), None)}

        # own labels for OCNL / FRQ parts: hours and FL of the dense part itself
        act_masks = {h: frames[h]["act"] for h in hours}
        labelled_frq = []
        for q, col, z, hs in sorted(dense_items, key=lambda t: (-t[2], -t[0].area)):   # orange first
            for g in [q]:
                item_hours = [h for h in hours if h in hs] or hours
                win, fl = dense_info(g, act_masks, item_hours, frames, lat, lon,
                                     COV_FRQ if col == "orange" else COV_OCNL)
                if not win:
                    continue
                if col == "yellow":
                    # FRQ implies at least OCNL around it: the OCNL period covers the periods
                    # of the orange parts inside / next to it
                    for o, _t, o_win in labelled_frq:
                        if g.distance(o) <= 0.1:
                            win = _merge_win(win, o_win)
                hu = unions["HIGH"]
                lvl = "HIGH" if hu is not None and g.intersection(hu).area >= 0.5 * g.area else "MED"
                lvl = graded_level(g, act_masks, hours, frames, lat, lon, lvl,
                                   MODEL_COVER_FRQ if col == "orange" else None)
                txt = f"{win} / {lvl} / {fl if fl else '---'}"
                if col == "yellow" and any(g.intersects(o) and txt == t for o, t, _w in labelled_frq):
                    continue                     # same text as the orange core inside it
                if col == "orange":
                    labelled_frq.append((g, txt, win))
                anchor = g
                if col == "yellow" and labelled_frq:    # arrow into yellow, not into the orange core
                    rest = g.difference(shapely.union_all([o for o, _t, _w in labelled_frq]))
                    if not rest.is_empty and rest.area > 0.1 * g.area:
                        anchor = rest
                # parts of the item: every part gets an arrow; parts close to each other
                # (ARROW_DEG) share one label, distant parts get their own label (same text).
                # Yellow slivers left between orange cores are not labelled separately.
                min_part = MIN_DENSE_KM2 if col == "orange" else YELLOW_LABEL_KM2
                parts_ = sorted([x for x in ([anchor] if anchor.geom_type == "Polygon"
                                             else getattr(anchor, "geoms", [])) if x.geom_type == "Polygon"
                                 and _area_km2(x) >= min_part], key=lambda x: -x.area)
                if not parts_:
                    parts_ = [max(getattr(anchor, "geoms", [anchor]), key=lambda x: x.area)]
                while parts_:
                    main_ = parts_.pop(0)
                    near_ = ([x for x in parts_ if x.distance(main_) <= ARROW_DEG]
                             if col == "orange" else [])   # yellow: one label per visible piece
                    parts_ = [x for x in parts_ if x not in near_]
                    grp = [main_] + near_
                    labels.append(("DENSE", shapely.union_all(grp),
                                   [x.representative_point() for x in grp], txt))

        for key, z in (("LOW", 1), ("MED", 2), ("HIGH", 3)):
            # one fill per level (overlapping periods must not look darker), outline per period
            if polys[key]:
                fill, edge = COLORS[polys[key][0][3]]
                u = shapely.union_all([q[0] for q in polys[key]])
                for g in ([u] if u.geom_type == "Polygon" else
                          [x for x in getattr(u, "geoms", []) if x.geom_type == "Polygon"]):
                    x, y = g.exterior.xy
                    ax.fill(x, y, facecolor=fill, alpha=0.55, edgecolor="none",
                            transform=proj, zorder=z)
            for p, win, fl, col in polys[key]:
                fill, edge = COLORS[col]
                for g in ([p] if p.geom_type == "Polygon" else list(p.geoms)):
                    x, y = g.exterior.xy
                    ax.plot(x, y, color=edge, linewidth=1.5, transform=proj, zorder=z + 0.1)
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
                               f"{win} / {graded_level(p, level_masks['HIGH'], hours, frames, lat, lon, key) if key == 'HIGH' else key} / {fl if fl else '---'}"))

    if hours:
        for q, col, z in sorted(dense, key=lambda t: t[2]):
            fill, edge = COLORS[col]
            polys_ = [q] if q.geom_type == "Polygon" else [x for x in getattr(q, "geoms", []) if x.geom_type == "Polygon"]
            for g in polys_:                    # path with holes (yellow has orange cut out of it)
                _fill_with_holes(ax, g, proj, facecolor=fill, alpha=0.8, edgecolor="none", zorder=z)
        for q, col, z, hs in dense_items:       # outline per period, so each label has its polygon
            for g in ([q] if q.geom_type == "Polygon" else [x for x in getattr(q, "geoms", []) if x.geom_type == "Polygon"]):
                x, y = g.exterior.xy
                ax.plot(x, y, color=COLORS[col][1], linewidth=1.0, transform=proj, zorder=4.2)

    # HIGH labels above the zone, MED below, LOW left; shifted until they do not overlap
    placed = []

    def free_spot(tx, ty, txt, direction):
        """First free place near (tx, ty): steps in the preferred direction first, then the
        other way and sideways. Every candidate is kept inside the map before it is checked."""
        w, hgt = 0.08 * len(txt) + 0.15, 0.26
        x_lo, x_hi = d["lon_min"] + 0.05, d["lon_max"] - w - 0.05
        y_lo, y_hi = d["lat_min"] + 0.1, d["lat_max"] - hgt - 0.1

        def clamp(x, y):
            return min(max(x, x_lo), x_hi), min(max(y, y_lo), y_hi)

        def free(x, y):
            return not any(x < o[2] and o[0] < x + w and y < o[3] and o[1] < y + hgt for o in placed)

        # candidates ordered by how far the label (and so its arrow) moves
        cands = []
        for k in range(16):
            for sgn in (1, -1):
                dy = sgn * direction * k * 0.3
                for dx in (0, 0.8, -0.8, 1.6, -1.6, 3.2, -3.2):
                    cost = abs(dy) + 0.7 * abs(dx) + (0.2 if sgn < 0 else 0)
                    cands.append((cost, dx, dy))
        best = clamp(tx, ty)
        for _, dx, dy in sorted(cands):
            x, y = clamp(tx + dx, ty + dy)
            if free(x, y):
                best = (x, y)
                break
        placed.append((best[0], best[1], best[0] + w, best[1] + hgt))
        return best

    high_l = [t for t in labels if t[0] == "HIGH"]
    med_l = sorted([t for t in labels if t[0] == "MED"], key=lambda t: -t[1].area)[:MAX_MED_LABELS]
    dense_l = [t for t in labels if t[0] == "DENSE"]
    labels = dense_l + high_l + med_l
    for k, (key, p, c, txt) in enumerate(labels):
        extra = []
        if isinstance(c, list):                  # OCNL/FRQ item with several parts
            c, extra = c[0], c[1:]
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
        for e in extra:
            ax.annotate("", xy=(e.x, e.y), xytext=(tx, ty), zorder=6,
                        arrowprops=dict(arrowstyle="->", color="#444444", lw=0.8))

    ax.set_title(f"CB convection polygons, 6 h  (experimental)   VALID {hh(b0)}-{hh(b1, True)} UTC "
                 f"{b0:%d.%m.%Y}   |   RUN {run_label}", fontsize=11)
    ax.legend(handles=[
        mpatches.Patch(facecolor=COLORS[c][0], edgecolor=COLORS[c][1], label=t) for c, t in (
            ("orange", "FRQ"),
            ("yellow", "OCNL"),
            ("dark_green", "HIGH ISOL (ICON LPI>=20 + GFS/IFS)"),
            ("light_green", "MED ISOL (ICON or GFS+IFS)"),
        )
    ], loc="upper center", bbox_to_anchor=(0.5, -0.01), ncol=4, fontsize=9, frameon=False)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"SIGWX saved: {out_path.name}  ({len(labels)} labels)")


def write_page(out_dir, items, run_label, xlsx_link=""):
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M")   # cache-busting: same file names every run
    days = {}
    for f, t, day, table in items:
        days.setdefault(day, []).append(
            f'<figure><img src="{f}?v={stamp}" alt="{t}"><figcaption>{t}{table}</figcaption></figure>')
    cards = "".join(f'<h2>{day}</h2><div class="grid">{"".join(c)}</div>' for day, c in days.items())
    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CB convection polygons, 6 h</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0f1419;color:#e0e0e0;margin:0;padding:16px}}
h1{{font-size:20px;margin:0 0 4px}} h2{{font-size:16px;margin:24px 0 10px;color:#8ab4d8}} .meta{{color:#7a8899;font-size:13px;margin-bottom:16px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,520px),1fr));gap:16px}}
figure{{margin:0;background:#1a2332;border-radius:10px;overflow:hidden}}
img{{width:100%;display:block;background:#fff}} figcaption{{padding:8px 12px;font-size:13px;color:#aab}}
a{{color:#8ab4d8}}
table.sect{{border-collapse:collapse;margin-top:8px;font-size:12px;width:100%}}
table.sect th,table.sect td{{border:1px solid #33415a;padding:3px 6px;text-align:center}}
table.sect th{{color:#8ab4d8;font-weight:600}} .sect.none{{margin-top:6px;color:#667}}
</style></head><body>
<h1>CB convection polygons, 6-hour maps &mdash; experimental</h1>
<div class="meta">Run {run_label} &middot; 6 h blocks to 24 UTC next day &middot; light green = ICON alone or GFS+IFS, dark green = ICON + GFS/IFS, yellow = OCNL, orange = FRQ &middot; <a href="../">hourly maps</a>{xlsx_link}</div>
{cards}</body></html>"""
    (out_dir / "index.html").write_text(html, encoding="utf-8")


def main():
    global COV_OCNL, COV_FRQ, ACT_LPI, GRADED
    cfg = yaml.safe_load(open("config/config.yaml", encoding="utf-8"))
    sw = cfg.get("sigwx", {})
    COV_OCNL = sw.get("ocnl", COV_OCNL)
    GRADED = bool(sw.get("graded", GRADED))
    _load_sector_tops(cfg)
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
    blocks = blocks_from(run_time, max(frames))
    for i, (b0, b1) in enumerate(blocks, 1):
        plot_block(frames, b0, b1, cfg, out_dir / f"sigwx_{i}.png", run_label)

    # sector table (ACC sectors, if the sector file is there)
    # sector table (ACC sectors): kept for the run's day and the next day; blocks this run
    # does not cover are taken over from the previous run's state (prev_sectors_state.json)
    xlsx_link = ""
    sec_path = Path("config/sectors.geojson")
    if sec_path.exists():
        import json
        import sector_table as st
        sectors = st.load_sectors(sec_path)
        min_top = st.min_tops(sectors, (cfg.get("sigwx") or {}).get("sector_min_top"))
        logger.info("Sector min TOP: " + ", ".join(f"{k} {v}" for k, v in min_top.items()))
        prev_path = Path("prev_sectors_state.json")
        state = {}
        if prev_path.exists():
            try:
                state = json.loads(prev_path.read_text(encoding="utf-8"))
                logger.info("Sector state from previous run: " + "; ".join(
                    f"{d} {','.join(sorted(v))}" for d, v in state.items()))
            except Exception as e:
                logger.warning(f"Sector state not readable: {e}")
        for b0, b1 in blocks:
            rows = st.block_rows(frames, BLOCK_GEOMS.get(b0, {}), b0, sectors, hh, to_fl, MIN_CB_FL,
                                 min_top)
            state.setdefault(f"{b0:%d.%m.%Y}", {})[f"{hh(b0)}-{hh(b1, True)}"] = {"run": run_label, "rows": rows}
        day0 = run_time.replace(hour=0)
        keep = [f"{day0 + timedelta(days=k):%d.%m.%Y}" for k in (0, 1)]
        state = {d: state.get(d, {}) for d in keep}
        # not linked from the page; the names can be made private with the SECTORS_NAME secret
        base = (os.environ.get("SECTORS_NAME") or "sectors").strip()
        for old in list(out_dir.glob("*.xlsx")) + list(out_dir.glob("*_state.json")):
            old.unlink()
        (out_dir / f"{base}_state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        st.write_xlsx(state, out_dir / f"{base}.xlsx")
        logger.info(f"Sector table: {', '.join(keep)}")

    items = [(f"sigwx_{i}.png", f"{hh(b0)}-{hh(b1, True)} UTC", f"{b0:%d.%m.%Y}", "")
             for i, (b0, b1) in enumerate(blocks, 1)]
    write_page(out_dir, items, run_label, xlsx_link)


if __name__ == "__main__":
    main()
