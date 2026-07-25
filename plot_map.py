import logging
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Polygon as MplPolygon

logger = logging.getLogger(__name__)


def plot_map(high_polys, med_polys, low_polys, high_mask, med_mask, low_mask,
             lat, lon, cfg, valid_time, out_path):
    colors = cfg["viz"]["colors"]
    alpha  = cfg["viz"].get("alpha", 0.4)
    domain = cfg["domain"]

    try:
        import cartopy.crs as ccrs
        import cartopy.feature as cfeature
        HAS_CARTOPY = True
    except ImportError:
        HAS_CARTOPY = False

    fig = plt.figure(figsize=cfg["viz"]["figsize"])

    if HAS_CARTOPY:
        proj = ccrs.PlateCarree()
        ax = fig.add_subplot(1, 1, 1, projection=proj)
        ax.set_extent([domain["lon_min"], domain["lon_max"],
                       domain["lat_min"], domain["lat_max"]], crs=proj)
        ax.add_feature(cfeature.LAND,      facecolor="#f0ede6", zorder=0)
        ax.add_feature(cfeature.OCEAN,     facecolor="#d6eaf8", zorder=0)
        ax.add_feature(cfeature.BORDERS,   linewidth=0.8, edgecolor="#444444", zorder=2)
        transform = proj
    else:
        ax = fig.add_subplot(1, 1, 1)
        ax.set_xlim(domain["lon_min"], domain["lon_max"])
        ax.set_ylim(domain["lat_min"], domain["lat_max"])
        transform = None

    # Полигони
    for polys, color, zorder in [
        (low_polys,  colors["LOW"],  1),
        (med_polys,  colors["MED"],  2),
        (high_polys, colors["HIGH"], 3),
    ]:
        for poly in polys:
            _draw_polygon(ax, poly, color, alpha, zorder, transform)
    patches = [
        mpatches.Patch(facecolor=colors["HIGH"], alpha=0.7, label="HIGH (3 models)"),
        mpatches.Patch(facecolor=colors["MED"],  alpha=0.7, label="MED (2 models)"),
        mpatches.Patch(facecolor=colors["LOW"],  alpha=0.7, label="LOW (ICON only)"),
    ]
    ax.legend(handles=patches, loc="lower left", fontsize=9, framealpha=0.85)
   
    ax.set_title(f"Valid: {valid_time}", fontsize=10, pad=5)

    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=cfg["viz"]["dpi"], bbox_inches="tight")
    plt.close(fig)
    logger.info(f"Map saved: {out_path.name}")


def _draw_polygon(ax, poly, color, alpha, zorder, transform):
    geoms = [poly] if poly.geom_type == "Polygon" else list(poly.geoms)

    for geom in geoms:
        if geom.is_empty:
            continue
        x, y = geom.exterior.xy
        coords = np.column_stack([x, y])

        if transform is not None:
            ax.fill(x, y,
                    facecolor=color, alpha=alpha,
                    edgecolor=color, linewidth=1.5,
                    transform=transform, zorder=zorder)
        else:
            patch = MplPolygon(coords, closed=True,
                               facecolor=color, alpha=alpha,
                               edgecolor=color, linewidth=1.5,
                               zorder=zorder)
            ax.add_patch(patch)