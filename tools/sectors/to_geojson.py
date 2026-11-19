import sys, json
sys.path.insert(0, "/home/claude/sectors")
import numpy as np, shapely
from shapely.geometry import Polygon, mapping
from skimage import measure
from build_sectors import build, T, CX, CY

A = np.array([[CX[0], CX[1]], [CY[0], CY[1]]]); b = np.array([CX[2], CY[2]])
Ainv = np.linalg.inv(A)
def px_to_ll(px, py):
    xy = (Ainv @ (np.vstack([px, py]) - b[:, None]))
    lon, lat = T.transform(xy[0], xy[1], direction="INVERSE")
    return lon, lat

a, barrier, regions = build()
feats = []
for name, m in regions.items():
    # grow into the barrier lines so neighbours touch, then trace the outline
    from scipy import ndimage
    mm = ndimage.binary_dilation(m, iterations=3) & (m | barrier)
    c = max(measure.find_contours(np.pad(mm, 1).astype(float), 0.5), key=len) - 1
    poly = Polygon(np.c_[c[:, 1], c[:, 0]]).simplify(1.5)
    lon, lat = px_to_ll(*np.array(poly.exterior.coords).T)
    g = Polygon(np.c_[np.round(lon, 4), np.round(lat, 4)])
    feats.append({"type": "Feature", "properties": {"name": name, "fs": "SOFIA" if name[0] == "S" else "VARNA"},
                  "geometry": mapping(g)})
    print(name, len(g.exterior.coords), "pts", f"{g.area * 111 * 111 * np.cos(np.radians(g.centroid.y)):.0f} km2",
          f"centroid {g.centroid.y:.2f}N {g.centroid.x:.2f}E")
json.dump({"type": "FeatureCollection",
           "properties": {"source": "digitised from BULATSA FIR SIGWX map screenshot, approx. +-5 km; replace with Eurocontrol sector data"},
           "features": feats}, open("/home/claude/sectors/sectors.geojson", "w"), indent=1)
