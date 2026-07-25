import glob
import os
from datetime import datetime, timezone
from pathlib import Path


def make_gallery(maps_dir="docs/maps", out_html="docs/index.html"):
    maps = sorted(glob.glob(f"{maps_dir}/*.png"))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    cards = ""
    for m in maps:
        name = os.path.basename(m)
        rel = f"maps/{name}"
        label = name.replace("convection_", "").replace(".png", "")
        cards += f'''
        <div class="card">
          <img src="{rel}" loading="lazy" onclick="openModal('{rel}')">
          <div class="label">{label}</div>
        </div>'''

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MultiConvect - Convective Forecast Bulgaria</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif;
          background: #1a1a2e; color: #e0e0e0; margin: 0; padding: 20px; }}
  h1 {{ font-size: 22px; font-weight: 600; }}
  .meta {{ color: #888; font-size: 13px; margin-bottom: 20px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
           gap: 16px; }}
  .card {{ background: #16213e; border-radius: 8px; overflow: hidden;
           cursor: pointer; transition: transform 0.15s; }}
  .card:hover {{ transform: scale(1.02); }}
  .card img {{ width: 100%; display: block; }}
  .label {{ padding: 8px 12px; font-size: 13px; color: #aaa; }}
  .modal {{ display: none; position: fixed; top: 0; left: 0; width: 100%;
            height: 100%; background: rgba(0,0,0,0.9); z-index: 100;
            justify-content: center; align-items: center; }}
  .modal img {{ max-width: 95%; max-height: 95%; }}
  .legend {{ background: #16213e; padding: 12px 16px; border-radius: 8px;
             margin-bottom: 20px; font-size: 13px; display: inline-block; }}
  .dot {{ display: inline-block; width: 12px; height: 12px; border-radius: 3px;
          margin-right: 6px; vertical-align: middle; }}
</style>
</head>
<body>
  <h1>MultiConvect — Convective Forecast Bulgaria</h1>
  <div class="meta">ICON-EU (lead) + GFS + ECMWF-IFS &middot; Updated: {now}</div>
  <div class="legend">
    <span class="dot" style="background:#FF8C00"></span>HIGH (3 models)&nbsp;&nbsp;
    <span class="dot" style="background:#FFD700"></span>MED (ICON + 1)&nbsp;&nbsp;
    <span class="dot" style="background:#00CC44"></span>LOW (ICON only)
  </div>
  <div class="grid">{cards}
  </div>
  <div class="modal" id="modal" onclick="this.style.display='none'">
    <img id="modalImg" src="">
  </div>
<script>
  function openModal(src) {{
    document.getElementById('modalImg').src = src;
    document.getElementById('modal').style.display = 'flex';
  }}
</script>
</body>
</html>'''

    Path(out_html).parent.mkdir(parents=True, exist_ok=True)
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Gallery: {out_html} ({len(maps)} maps)")


if __name__ == "__main__":
    make_gallery()