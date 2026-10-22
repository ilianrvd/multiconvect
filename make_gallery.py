import glob
import os
from datetime import datetime, timezone
from pathlib import Path


def make_gallery(maps_dir="docs/maps", out_html="docs/index.html"):
    maps = sorted(glob.glob(f"{maps_dir}/*.png"))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    files = [os.path.basename(m) for m in maps]
    labels = [f.replace("convection_", "").replace(".png", "") for f in files]

    files_js = "[" + ",".join(f'"maps/{f}"' for f in files) + "]"
    labels_js = "[" + ",".join(f'"{l}"' for l in labels) + "]"

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MultiConvect - Convective Forecast Bulgaria</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif;
          background: #0f1419; color: #e0e0e0; margin: 0; padding: 16px; }}
  h1 {{ font-size: 20px; font-weight: 600; margin: 0 0 4px 0; }}
  .meta {{ color: #7a8899; font-size: 13px; margin-bottom: 16px; }}
  .legend {{ background: #1a2332; padding: 10px 14px; border-radius: 8px;
             margin-bottom: 16px; font-size: 13px; display: flex;
             gap: 18px; flex-wrap: wrap; align-items: center; }}
  .dot {{ display: inline-block; width: 13px; height: 13px; border-radius: 3px;
          margin-right: 6px; vertical-align: middle; }}
  .viewer {{ background: #1a2332; border-radius: 12px; padding: 16px;
             max-width: 1100px; margin: 0 auto; }}
  .imgwrap {{ position: relative; width: 100%; background: #0f1419;
              border-radius: 8px; overflow: hidden; }}
  .imgwrap img {{ width: 100%; display: block; }}
  .controls {{ display: flex; align-items: center; gap: 12px;
               margin-top: 14px; }}
  .controls button {{ background: #2a3a52; color: #e0e0e0; border: none;
                      width: 44px; height: 44px; border-radius: 8px;
                      font-size: 18px; cursor: pointer; transition: 0.15s; }}
  .controls button:hover {{ background: #3a4a62; }}
  .controls button.play {{ background: #2e6da4; width: 60px; }}
  .slider {{ flex: 1; }}
  input[type=range] {{ width: 100%; height: 6px; border-radius: 3px;
                       background: #2a3a52; outline: none; -webkit-appearance: none; }}
  input[type=range]::-webkit-slider-thumb {{ -webkit-appearance: none;
       width: 20px; height: 20px; border-radius: 50%; background: #2e6da4;
       cursor: pointer; }}
  .timelabel {{ font-size: 15px; font-weight: 600; min-width: 180px;
                text-align: center; color: #8ab4d8; }}
  .frameinfo {{ text-align: center; color: #7a8899; font-size: 12px;
                margin-top: 8px; }}
</style>
</head>
<body>
  <h1>MultiConvect — Convective Forecast Bulgaria</h1>
  <div class="meta">ICON-EU (lead) + GFS + ECMWF-IFS &middot; Hourly to 48h &middot; Updated: {now}</div>
  <div class="legend">
    <span><span class="dot" style="background:#FF8C00"></span>HIGH (3 models)</span>
    <span><span class="dot" style="background:#4A7C2E"></span>MED (2 models)</span>
    <span><span class="dot" style="background:#A8C77A"></span>LOW (ICON only)</span>
    <span><span class="dot" style="background:#CC0000"></span>OCNL (dense cells)</span>
  </div>

  <div class="viewer">
    <div class="imgwrap">
      <img id="frame" src="" alt="forecast">
    </div>
    <div class="controls">
      <button onclick="step(-1)">&#9664;</button>
      <button class="play" id="playBtn" onclick="togglePlay()">&#9654;</button>
      <button onclick="step(1)">&#9654;</button>
      <div class="slider">
        <input type="range" id="slider" min="0" max="0" value="0"
               oninput="show(this.value)">
      </div>
      <div class="timelabel" id="timelabel"></div>
    </div>
    <div class="frameinfo" id="frameinfo"></div>
  </div>

<script>
  const files = {files_js};
  const labels = {labels_js};
  let idx = 0;
  let playing = false;
  let timer = null;

  const frame = document.getElementById('frame');
  const slider = document.getElementById('slider');
  const timelabel = document.getElementById('timelabel');
  const frameinfo = document.getElementById('frameinfo');

  slider.max = files.length - 1;

  function show(i) {{
    idx = parseInt(i);
    frame.src = files[idx];
    slider.value = idx;
    timelabel.textContent = labels[idx];
    frameinfo.textContent = (idx+1) + ' / ' + files.length;
  }}

  function step(d) {{
    let n = idx + d;
    if (n < 0) n = files.length - 1;
    if (n >= files.length) n = 0;
    show(n);
  }}

  function togglePlay() {{
    playing = !playing;
    const btn = document.getElementById('playBtn');
    if (playing) {{
      btn.innerHTML = '&#10074;&#10074;';
      timer = setInterval(() => step(1), 500);
    }} else {{
      btn.innerHTML = '&#9654;';
      clearInterval(timer);
    }}
  }}

  document.addEventListener('keydown', (e) => {{
    if (e.key === 'ArrowLeft') step(-1);
    if (e.key === 'ArrowRight') step(1);
    if (e.key === ' ') {{ e.preventDefault(); togglePlay(); }}
  }});

  if (files.length > 0) show(0);
</script>
</body>
</html>'''

    Path(out_html).parent.mkdir(parents=True, exist_ok=True)
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Gallery: {out_html} ({len(maps)} frames)")


if __name__ == "__main__":
    make_gallery()