"""Renders docs/banner.png (1280x640, also the size GitHub wants for a social preview) and docs/screenshot.png.

Both are drawn from Ovo's own window code with sample numbers, so they never show anyone's real name or usage.
Needs Microsoft Edge (it renders the pages) and Pillow: python tools/make_media.py"""
import importlib.machinery
import importlib.util
import json
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
EDGE = next((p for p in (r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
                         r'C:\Program Files\Microsoft\Edge\Application\msedge.exe') if Path(p).exists()), None)

BANNER = """<!doctype html><meta charset=utf-8>
<style>
  html, body { margin: 0; width: 1280px; height: 640px; overflow: hidden; }
  body { position: relative; background: #151514; color: #ecebe8;
         font-family: 'Segoe UI Variable Text', 'Segoe UI', sans-serif; }
  .glow { position: absolute; border-radius: 50%; filter: blur(120px); }
  .g1 { width: 560px; height: 560px; background: #d97757; opacity: .34; left: -170px; bottom: -250px; }
  .g2 { width: 620px; height: 620px; background: #7a95ff; opacity: .30; right: -170px; top: -260px; }
  .grid { position: absolute; inset: 0; background-size: 44px 44px;
          background-image: linear-gradient(rgba(255,255,255,.035) 1px, transparent 1px),
                            linear-gradient(90deg, rgba(255,255,255,.035) 1px, transparent 1px);
          -webkit-mask-image: radial-gradient(ellipse at 50% 50%, #000 30%, transparent 78%); }
  .left { position: absolute; left: 80px; top: 0; bottom: 0; width: 560px; display: flex; flex-direction: column;
          justify-content: center; gap: 26px; }
  .brand { display: flex; align-items: center; gap: 28px; }
  .brand img { width: 116px; height: 116px; }
  h1 { font: 700 124px/1 Georgia, 'Times New Roman', serif; margin: 0; letter-spacing: -3px; }
  .tag { font-size: 36px; line-height: 1.28; color: #d2d0cb; margin: 0; }
  .pills { display: flex; gap: 10px; margin-top: 4px; }
  .pill { padding: 8px 17px; border-radius: 999px; font-size: 19px; color: #d6d4cf; white-space: nowrap;
          background: rgba(255,255,255,.07); border: 1px solid rgba(255,255,255,.13); }
  .right { position: absolute; right: 60px; top: 0; bottom: 0; display: flex; align-items: center; }
  .shot { zoom: 1.7; width: 316px; height: 152px; box-shadow: 0 24px 60px rgba(0,0,0,.6), 0 0 0 1px rgba(255,255,255,.05); }
  .shot iframe { width: 316px; height: 152px; border: 0; display: block; }
</style>
<div class="glow g1"></div><div class="glow g2"></div><div class="grid"></div>
<div class="left">
  <div class="brand"><img src="MARK"><h1>Ovo</h1></div>
  <p class="tag">Claude and Codex usage,<br>at a glance.</p>
  <div class="pills"><span class="pill">Windows 10 / 11</span><span class="pill">Always on top</span><span class="pill">Open source</span></div>
</div>
<div class="right"><div class="shot"><iframe src="widget.html"></iframe></div></div>"""

SHOT = """<!doctype html><meta charset=utf-8>
<style>
  html, body { margin: 0; width: 1100px; height: 560px; overflow: hidden; }
  body { display: flex; align-items: center; justify-content: center; background: linear-gradient(180deg, #1c1c1b, #121211); }
  .shot { zoom: 3; width: 316px; height: 152px; box-shadow: 0 18px 50px rgba(0,0,0,.55); }
  .shot iframe { width: 316px; height: 152px; border: 0; display: block; }
</style>
<div class="shot"><iframe src="widget.html"></iframe></div>"""


def load_ovo():
    spec = importlib.util.spec_from_loader('ovo', importlib.machinery.SourceFileLoader('ovo', str(ROOT / 'ovo.pyw')))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def widget_page(ovo):
    """Ovo's own window, filled with sample numbers and a made-up name."""
    now = datetime.now(timezone.utc)

    def at(**delta):
        return (now + timedelta(**delta)).isoformat()
    sample = {'claude': [(58, at(hours=2, minutes=10)), (36, at(days=4))],  # (percent used, when it resets)
              'codex': [(26, at(hours=3, minutes=20)), (48, at(days=3, hours=6))]}
    groups = {key: {'rows': [ovo.row_text({'utilization': used, 'resets_at': reset}, ovo.PROVIDERS[key]['remaining'])
                             for used, reset in rows]} for key, rows in sample.items()}
    config = {'ovo': ovo.image('ovo.png'), 'name': 'Alex',
              'providers': [dict(id=k, labels=list(p['labels']), accent=p['accent'], remaining=p['remaining'],
                                 windows=list(p['windows']), logo=ovo.image(p['logo'])) for k, p in ovo.PROVIDERS.items()]}
    # The greeting depends on the time of day; pin it so the picture is the same whenever it is made.
    return (ovo.page(ovo.HTML, config) +
            f'<script>greeting = () => "Good afternoon, Alex"; render({json.dumps({"groups": groups})});</script>')


def capture(page, out, width, height):
    """Render an HTML file with headless Edge to a PNG of exactly width x height."""
    subprocess.run([EDGE, '--headless=new', '--disable-gpu', '--hide-scrollbars', '--force-device-scale-factor=1',
                    '--virtual-time-budget=4000', f'--window-size={width},{height + 200}',
                    f'--screenshot={out}', page.as_uri()], check=True, timeout=90,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with Image.open(out) as shot:  # the window comes out taller than asked; keep the top
        shot.crop((0, 0, width, height)).save(out)


def main():
    if not EDGE:
        raise SystemExit('Microsoft Edge was not found, so the pages cannot be rendered.')
    ovo = load_ovo()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / 'widget.html').write_text(widget_page(ovo), encoding='utf-8')
        (tmp / 'banner.html').write_text(BANNER.replace('MARK', ovo.image('ovo.png')), encoding='utf-8')
        (tmp / 'shot.html').write_text(SHOT, encoding='utf-8')
        (ROOT / 'docs').mkdir(exist_ok=True)
        capture(tmp / 'banner.html', ROOT / 'docs' / 'banner.png', 1280, 640)
        capture(tmp / 'shot.html', ROOT / 'docs' / 'screenshot.png', 1100, 560)
    print('wrote docs/banner.png and docs/screenshot.png')


if __name__ == '__main__':
    main()
