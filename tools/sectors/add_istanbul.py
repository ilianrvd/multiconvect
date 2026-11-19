import sys, json; sys.path.insert(0, "/home/claude/sectors")
import numpy as np
from shapely.geometry import Polygon, mapping
from build_sectors import T, CX, CY
A = np.array([[CX[0], CX[1]], [CY[0], CY[1]]]); b = np.array([CX[2], CY[2]]); Ai = np.linalg.inv(A)
def ll(pts):
    out = []
    for p in pts:
        xy = Ai @ (np.array(p, float) - b); lon, lat = T.transform(xy[0], xy[1], direction="INVERSE")
        out.append((round(lon, 4), round(lat, 4)))
    return out
IST = {"I-WEST": [(547,455),(569,414),(616,407),(670,412),(718,411),(727,409),(765,487),(527,500),(547,455)],
       "I-EAST": [(727,409),(745,408),(800,400),(861,380),(906,354),(893,479),(765,487),(727,409)]}
fc = json.load(open("/home/claude/sectors/sectors.geojson"))
fc["features"] = [f for f in fc["features"] if not f["properties"]["name"].startswith("I-")]
for n, pts in IST.items():
    fc["features"].append({"type": "Feature", "properties": {"name": n, "fs": "ISTANBUL"},
                           "geometry": mapping(Polygon(ll(pts)))})
json.dump(fc, open("/home/claude/sectors/sectors.geojson", "w"), indent=1)
print([f["properties"]["name"] for f in fc["features"]])
