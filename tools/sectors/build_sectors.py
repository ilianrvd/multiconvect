"""Digitise ACC sectors from a sector map screenshot (approximate).
Georeference by airports (LCC + affine), barriers = blue sector/FIR lines + manual
segments closing gaps, regions by flood fill from the sector label points."""
import json, sys
import numpy as np, pyproj
from PIL import Image, ImageDraw
from scipy import ndimage

IMG = "/home/claude/sectors/sectors_map.png"
PTS = {"LRBS": (510.7, 8.1, 44.503, 26.102), "LBWN": (712.9, 208.1, 43.232, 27.825),
       "LBSF": (195.0, 297.0, 42.695, 23.406), "LBPD": (366.4, 399.3, 42.068, 24.851),
       "LTFM": (836.9, 517.9, 41.275, 28.752)}
T = pyproj.Transformer.from_crs("EPSG:4326", "+proj=lcc +lat_1=40 +lat_2=46 +lat_0=43 +lon_0=25", always_xy=True)
xy = np.array([T.transform(v[3], v[2]) for v in PTS.values()])
P = np.c_[xy, np.ones(len(xy))]
CX, *_ = np.linalg.lstsq(P, np.array([v[0] for v in PTS.values()]), rcond=None)
CY, *_ = np.linalg.lstsq(P, np.array([v[1] for v in PTS.values()]), rcond=None)
RES = np.hypot(P @ CX - [v[0] for v in PTS.values()], P @ CY - [v[1] for v in PTS.values()])

def to_px(lat, lon):
    x, y = T.transform(np.asarray(lon), np.asarray(lat))
    return CX[0]*x + CX[1]*y + CX[2], CY[0]*x + CY[1]*y + CY[2]

SEGS = [  # manual polylines in image px (close gaps under overlays)
    [(297,139),(338,272),(343,285),(394,404),(436,520)],                    # SA|SB, SA/SC|SD
    [(125,250),(267,324),(309,350),(369,379),(385,378)],                    # SA|SC
    [(338,272),(451,282),(617,298)],                                        # SB south
    [(480,286),(610,405),(655,447)],                                        # SD|SE
    [(520,290),(573,310),(660,392),(700,430)],                              # SE|SF
    [(427,94),(537,220),(617,298),(733,407),(745,418)],                     # SB|VA, SF|VC
    [(553,235),(600,247),(663,243)],                                        # VA|VC
    [(663,243),(737,342),(800,400)],                                        # VC|VD
    [(663,243),(669,198),(687,177),(722,151),(752,126)],                    # VA|VB/VD
    [(722,151),(800,192),(984,305)],                                        # VB|VD
    [(851,131),(895,120),(1025,120),(1059,259),(984,305)],                  # VB north/east
    [(800,400),(861,380),(984,305)],                                        # VD south
    [(297,138),(316,134)], [(412,95),(427,94)],                             # Danube gaps
    [(598,66),(615,65),(752,126),(781,138),(792,124),(851,131)],            # Dobrudja border
    [(86,85),(110,67),(110,56),(128,56)],                                   # NW corner (Timok)
    [(128,56),(144,67),(155,70),(158,80),(147,86),(139,96),(136,110),(144,115),(160,118)],  # Danube NW
    [(551,81),(588,72),(598,66)],                                           # Danube NE gap
    [(147,452),(138,465),(139,503),(136,513),(133,514),(160,516)],          # SW corner
]
SOUTH = [(41.33,22.92),(41.34,23.20),(41.40,23.62),(41.37,24.05),(41.52,24.53),(41.43,25.10),
         (41.32,25.55),(41.36,25.95),(41.36,26.13),(41.72,26.36),(41.97,26.55),(42.01,26.95),
         (41.97,27.40),(41.97,27.80),(41.98,28.03),(41.98,28.40)]
SEEDS = {"SA": (230,230), "SB": (420,190), "SC": (250,450), "SD": (420,440), "SE": (600,360),
         "SF": (655,360), "VA": (560,110), "VC": (722,365), "VB": (880,215), "VD": (850,300)}

def build():
    a = np.array(Image.open(IMG).convert("RGB")).astype(int)
    blue = (a[..., 2] > 200) & (a[..., 0] < 60) & (a[..., 1] < 60)
    bar = Image.fromarray(np.zeros(blue.shape, np.uint8)); d = ImageDraw.Draw(bar)
    for s in SEGS:
        d.line(s, fill=1, width=3)
    sx, sy = to_px([p[0] for p in SOUTH], [p[1] for p in SOUTH])
    south = list(zip(sx, sy))
    d.line([(136, 514)] + south + [(745, 418), (800, 400)], fill=1, width=3)   # W border end .. Rezovo .. sea FIR
    barrier = ndimage.binary_dilation(blue, iterations=2) | (np.array(bar) > 0)
    lab, _ = ndimage.label(~barrier)
    regions = {}
    for name, (x, y) in SEEDS.items():
        regions[name] = lab == lab[y, x]
        if regions[name][0, :].any() or regions[name][-1, :].any() or regions[name][:, 0].any() or regions[name][:, -1].any():
            print(f"WARNING {name} leaks to image edge", file=sys.stderr)
    return a, barrier, regions

if __name__ == "__main__":
    print("georef residuals px:", np.round(RES, 1))
    a, barrier, regions = build()
    cols = {"SA":(255,0,0),"SB":(0,160,0),"SC":(0,0,255),"SD":(255,160,0),"SE":(160,0,160),"SF":(0,160,160),
            "VA":(128,64,0),"VC":(255,0,255),"VB":(0,90,200),"VD":(120,120,0)}
    out = a.copy().astype(float)
    for n, m in regions.items():
        out[m] = 0.55*out[m] + 0.45*np.array(cols[n])
        print(n, int(m.sum()))
    out[barrier] = (0, 0, 0)
    Image.fromarray(out.astype(np.uint8)).save("/home/claude/sectors/regions_check.png")
    np.savez_compressed("/home/claude/sectors/regions.npz", **regions)
