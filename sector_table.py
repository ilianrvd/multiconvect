"""
sector_table.py
Per ACC sector and 6-hour block: TIME, TOP FL and coverage % with ISOL / OCNL / FRQ,
in the layout of the BULATSA FIR SIGWX sector form. ISOL counts HIGH ISOL only.
Sector polygons: config/sectors.geojson (digitised, approximate).
"""
import json
from datetime import timedelta
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import shape

ORDER = {"SOFIA": ["SA", "SC", "SB", "SD", "SE", "SF"], "VARNA": ["VA", "VC", "VB", "VD"],
         "IST_EAST": ["I-EAST"], "IST_WEST": ["I-WEST"]}
FS_TITLE = {"SOFIA": "ФС СОФИЯ", "VARNA": "ФС ВАРНА", "IST_EAST": "ISTANBUL EAST", "IST_WEST": "ISTANBUL WEST"}
MIN_SHARE = 0.03      # below 3 % of the sector -> "-"
MIN_CELLS = 3         # hour counts for TIME if at least this many signal cells inside
COLOURS = {"ISOL": "#5FA35C", "OCNL": "#F2E04A", "FRQ": "#F59E2E"}


def load_sectors(path):
    fc = json.load(open(path, encoding="utf-8"))
    return {f["properties"]["name"]: shape(f["geometry"]) for f in fc["features"]}


def _scaled(g, k):
    return shapely.transform(g, lambda c: c * np.array([k, 1.0]))   # lon * cos(lat0): equal-area enough


def _pct(share):
    if share < MIN_SHARE:
        return None
    return int(min(100, max(10, round(share * 10) * 10)))


def min_tops(sectors, cfg_tops=None):
    """Minimum TOP for a sector to enter the table: Istanbul sectors, the sectors bordering
    them, all others (sigwx.sector_min_top in config)."""
    t = {"istanbul": 180, "adjacent": 220, "other": 250, **(cfg_tops or {})}
    ist = {n: g for n, g in sectors.items() if n.startswith("I-")}
    out = {}
    for n, g in sectors.items():
        if n in ist:
            out[n] = t["istanbul"]
        elif any(g.distance(i) < 0.02 for i in ist.values()):
            out[n] = t["adjacent"]
        else:
            out[n] = t["other"]
    return out


def block_rows(frames, geoms, b0, sectors, hh, to_fl, min_fl=100, min_top=None):
    """geoms: {'HIGH': geom|None, 'OCNL': geom|None, 'FRQ': geom|None} of the drawn SIGWX block."""
    hours = [h for h in (b0 + timedelta(hours=i) for i in range(6)) if h in frames]
    rows = {}
    if not hours:
        return rows
    lat, lon = frames[hours[0]]["lat"], frames[hours[0]]["lon"]
    k = np.cos(np.radians(42.7))
    empty = shapely.Polygon()
    hi = geoms.get("HIGH") or empty
    oc = geoms.get("OCNL") or empty
    fr = geoms.get("FRQ") or empty
    parts = {"FRQ": fr, "OCNL": oc.difference(fr), "ISOL": hi.difference(oc).difference(fr)}
    for name, sec in sectors.items():
        a_sec = _scaled(sec, k).area
        cov = {c: _pct(_scaled(sec.intersection(g), k).area / a_sec) if not g.is_empty else None
               for c, g in parts.items()}
        row = {"TIME": None, "TOP": None, **cov}
        if any(cov.values()):
            inside = shapely.contains_xy(sec, lon, lat)
            present, tops = [], []
            for h in hours:
                sel = inside & (frames[h]["sig2"] | frames[h]["act"])
                if sel.sum() >= MIN_CELLS:
                    present.append(h)
                    v = frames[h]["htop"][sel]
                    tops.extend(v[v > 0].tolist())
            if present:
                row["TIME"] = f"{hh(present[0])}-{hh(present[-1] + timedelta(hours=1), True)}"
            if tops:
                fl = to_fl(float(np.percentile(tops, 90)))
                row["TOP"] = fl if fl and fl >= min_fl else None
        if min_top and (row["TOP"] is None or row["TOP"] < min_top.get(name, 0)):
            row = {"TIME": None, "TOP": None, "ISOL": None, "OCNL": None, "FRQ": None}
        rows[name] = row
    return rows


def html_table(rows):
    if not rows or not any(any(r.values()) for r in rows.values()):
        return '<div class="sect none">No CB in the sectors</div>'
    head = "<tr><th>Sector</th><th>TIME</th><th>TOP FL</th><th>ISOL %</th><th>OCNL %</th><th>FRQ %</th></tr>"
    body = ""
    for fs, names in ORDER.items():
        for n in names:
            r = rows.get(n)
            if not r or not any(r.values()):
                continue
            cells = "".join(
                f'<td style="background:{COLOURS[c]};color:#111">{r[c]}</td>' if r[c] else "<td>-</td>"
                for c in ("ISOL", "OCNL", "FRQ"))
            body += f"<tr><td>{n}</td><td>{r['TIME'] or '-'}</td><td>{r['TOP'] or '-'}</td>{cells}</tr>"
    return f'<table class="sect">{head}{body}</table>'


def write_xlsx(state, out_path):
    """state: {date_str: {'00-06': {'run': label, 'rows': rows}, ...}} -> one sheet per date,
    form layout; column H names the run each block comes from."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
    wb = Workbook()
    wb.remove(wb.active)
    thin = Side(style="thin", color="999999")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    fills = {c: PatternFill("solid", fgColor=v.lstrip("#")) for c, v in COLOURS.items()}
    for day, blocks in state.items():
        ws = wb.create_sheet(day.replace(".", "-"))
        ws.append(["СЕКТОР", "карта FIR-SIGWX", "период (хх-хх)", "TOP FL (xxx)",
                   "Процентно запълване с ISOL/OCNL/FRQ (xx)", None, None, "RUN"])
        ws.merge_cells(start_row=1, start_column=5, end_row=1, end_column=7)
        for fs, names in ORDER.items():
            ws.append([FS_TITLE[fs], None, "TIME", "TOP", "ISOL", "OCNL", "FRQ", None])
            ws.append([None, None, "UTC", "FL", "%", "%", "%", None])
            for n in names:
                first = ws.max_row + 1
                for blk in ("00-06", "06-12", "12-18", "18-24"):
                    b = blocks.get(blk) or {}
                    r = (b.get("rows") or {}).get(n, {})
                    vals = [r.get("TIME"), r.get("TOP"), r.get("ISOL"), r.get("OCNL"), r.get("FRQ")]
                    ws.append([n if blk == "00-06" else None, blk] + [v if v else "-" for v in vals]
                              + [b.get("run", "n/a")])
                    for j, c in enumerate(("ISOL", "OCNL", "FRQ")):
                        if r.get(c):
                            ws.cell(ws.max_row, 5 + j).fill = fills[c]
                ws.merge_cells(start_row=first, start_column=1, end_row=first + 3, end_column=1)
        for row in ws.iter_rows():
            for c in row:
                c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                c.border = box
                if c.value in list(FS_TITLE.values()) + ["СЕКТОР"]:
                    c.font = Font(bold=True)
        for col, w in zip("ABCDEFGH", (14, 12, 12, 10, 10, 10, 10, 11)):
            ws.column_dimensions[col].width = w
        ws.row_dimensions[1].height = 45
    wb.save(out_path)
