import logging
import numpy as np
from scipy.ndimage import binary_dilation
from scipy.interpolate import RegularGridInterpolator as RGI
from scipy.ndimage import label

logger = logging.getLogger(__name__)


def regrid(src, lat_src, lon_src, lat_dst, lon_dst):
    lat_1d = lat_src[:, 0]
    lon_1d = lon_src[0, :]
    if lat_1d[-1] < lat_1d[0]:
        lat_1d = lat_1d[::-1]
        src = src[::-1, :]
    if lon_1d[-1] < lon_1d[0]:
        lon_1d = lon_1d[::-1]
        src = src[:, ::-1]
    interp = RGI((lat_1d, lon_1d), src, method="linear",
                 bounds_error=False, fill_value=0.0)
    pts = np.column_stack([lat_dst.ravel(), lon_dst.ravel()])
    return interp(pts).reshape(lat_dst.shape).astype(np.float32)


def classify(gfs, icon, ifs, lat, lon, cfg):
    thr = cfg["models"]
    expand = cfg.get("expand_pixels", 3)

    gfs_mask  = gfs  >= thr["gfs"]["threshold"]
    icon_mask = icon >= thr["icon"]["threshold"]
    ifs_mask  = ifs  >= thr["ifs"]["threshold"]

    struct   = np.ones((expand*2+1, expand*2+1), dtype=bool)
    icon_exp = binary_dilation(icon_mask, structure=struct)

    # HIGH = ICON + GFS + IFS
    high = icon_exp & gfs_mask & ifs_mask

    # MED = ICON + точно един (GFS или IFS), но не и двата
    med = icon_exp & (gfs_mask ^ ifs_mask)

    # LOW = само ICON (без GFS и без IFS)  ИЛИ  GFS+IFS без ICON
    low = (icon_exp & ~gfs_mask & ~ifs_mask) | (~icon_exp & gfs_mask & ifs_mask)

    logger.info(f"  HIGH={high.sum()}  MED={med.sum()}  LOW={low.sum()} pixels")

    return high, med, low

def get_polygons(mask, lat, lon, min_distance_deg=0.25, min_pixels=10):
    from shapely.geometry import MultiPoint, Polygon
    from shapely.ops import unary_union

    labeled, n = label(mask)
    if n == 0:
        return []

    # Групираме близки зони
    zone_hulls = []
    for i in range(1, n+1):
        pts_idx = np.where(labeled == i)
        if len(pts_idx[0]) < min_pixels:
            continue
        pts = list(zip(lon[pts_idx].tolist(), lat[pts_idx].tolist()))
        if len(pts) < 3:
            continue
        try:
            from shapely import concave_hull
            hull = concave_hull(MultiPoint(pts), ratio=0.3)
            zone_hulls.append(hull)
        except Exception:
            continue

    if not zone_hulls:
        return []

    # Обединяваме близки полигони (buffer + merge + buffer back)
    merged = []
    buf = min_distance_deg / 2
    buffered = [h.buffer(buf) for h in zone_hulls]
    union = unary_union(buffered)

    if union.geom_type == "Polygon":
        geoms = [union]
    else:
        geoms = list(union.geoms)

    for g in geoms:
        final = g.buffer(-buf * 0.3)
        if not final.is_empty and final.area > 0:
            merged.append(final)

    return merged