"""Ovo: Claude and Codex usage, at a glance. One small always-on-top window.

`ovo.pyw` starts it (the first time it asks your name, what you use and a few options),
`ovo.pyw install` adds a Start Menu shortcut, `ovo.pyw --test` runs the self-check.

Shows the same numbers as claude.ai Settings > Usage and the Codex usage menu. Claude: a hidden WebView2
window keeps your login (claude.ai is behind Cloudflare, so only a real browser can call its API); on
first run a sign-in window opens, after that it stays hidden. Codex: reads the login the Codex app
already keeps in ~/.codex/auth.json, so there is no sign-in at all.
Drag to move (position is remembered). Right-click for the menu, including Settings.
"""
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

VERSION = '1.0.0'
FROZEN = getattr(sys, 'frozen', False)  # True in the packaged Ovo.exe
HERE = Path(sys.executable).parent if FROZEN else Path(__file__).parent
ASSETS = Path(getattr(sys, '_MEIPASS', HERE)) / 'assets'
# DATA holds your settings, the window position and the Claude login. The packaged exe keeps it in
# %APPDATA%\Ovo (the exe may sit in a read-only folder); running the script keeps it next to the script.
DATA = Path(os.environ.get('APPDATA', HERE)) / 'Ovo' if FROZEN else HERE / 'data'
SETTINGS_FILE, POS_FILE, PROFILE = DATA / 'settings.json', DATA / 'position.json', DATA / 'webview-profile'
UPDATE_FILE = DATA / 'update.json'  # which version you chose "Later" for, and until when
REPO = '1iiron/ovo'  # where releases are published
RELEASES_API = f'https://api.github.com/repos/{REPO}/releases/latest'
UPDATE_HOSTS = ('api.github.com', 'github.com', 'objects.githubusercontent.com', 'release-assets.githubusercontent.com')
CHECK_EVERY = 6 * 3600  # seconds between update checks
MAX_ZIP = 80 * 1024 * 1024  # the biggest download Ovo will accept
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'  # Windows starts what is listed here at sign-in
EVERY = 3  # seconds between refreshes
W, H_BASE, H_GROUP = 316, 52, 50  # window width; height is H_BASE + H_GROUP for each provider shown
CHOICES = {'claude': ['claude'], 'codex': ['codex'], 'both': ['claude', 'codex']}  # what the setup screen offers
OPTIONS = {'startup': False, 'alerts': True, 'hide_fullscreen': True, 'updates': True}  # on/off settings and defaults

# Both providers produce {session, week: {utilization, resets_at (ISO)}}, or an error dict:
# {status: <http error>} from a fetch script, {error: <text>} from read_codex.
# The Claude fetch script runs inside the signed-in site; same endpoint the Settings > Usage page calls.
FETCH_CLAUDE = """
(async () => {
  const m = document.cookie.match(/(?:^|; )lastActiveOrg=([^;]+)/);
  let org = m && m[1];
  if (!org) {
    const r = await fetch('/api/organizations');
    if (!r.ok) return {status: r.status};
    org = (await r.json())[0].uuid;
  }
  const r = await fetch(`/api/organizations/${org}/usage`);
  if (!r.ok) return {status: r.status};
  const u = await r.json();
  return {session: u.five_hour, week: u.seven_day};
})()
"""


CODEX_URL = 'https://chatgpt.com/backend-api/wham/usage'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: the request carries your Codex token, which must only ever go to chatgpt.com."""
    def redirect_request(self, *args, **kwargs):
        return None


CODEX_OPENER = urllib.request.build_opener(NoRedirect)  # HTTPS with certificate checks, the default


def read_codex():
    """Codex usage via the login the Codex app/CLI keeps in ~/.codex/auth.json. The app refreshes that
    token whenever it is used, so only a login left unused for days expires. The token is read from that
    file, sent only to CODEX_URL, and never printed, logged or stored anywhere else."""
    try:
        tokens = json.loads((Path.home() / '.codex' / 'auth.json').read_text())['tokens']
        headers = {'Authorization': 'Bearer ' + tokens['access_token'], 'User-Agent': f'Ovo/{VERSION}'}
    except (OSError, ValueError, KeyError, TypeError):
        return {'error': 'Codex login not found: sign in to Codex first'}
    if tokens.get('account_id'):
        headers['ChatGPT-Account-Id'] = tokens['account_id']
    try:
        req = urllib.request.Request(CODEX_URL, headers=headers)
        with CODEX_OPENER.open(req, timeout=15) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        return {'error': 'Codex login expired: open Codex once to refresh it' if e.code in (401, 403)
                else f'chatgpt.com error {e.code}'}
    except OSError as e:  # no network, timeout
        return {'error': str(e)}
    except ValueError:  # an unreadable reply or login; such a message could echo the token, so it says nothing of it
        return {'error': 'Codex sent something Ovo could not read'}
    limits = data.get('rate_limit') if isinstance(data, dict) else None  # primary = 5 hours, secondary = weekly
    limits = limits if isinstance(limits, dict) else {}

    def block(w):  # reset_at is unix seconds
        if not isinstance(w, dict):
            return None
        try:
            return {'utilization': w['used_percent'],
                    'resets_at': datetime.fromtimestamp(w['reset_at'], timezone.utc).isoformat()}
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            return None
    return {'session': block(limits.get('primary_window')), 'week': block(limits.get('secondary_window'))}


PROVIDERS = {
    'claude': dict(name='Claude', site='claude.ai', login='https://claude.ai/login',
                   idle='https://claude.ai/robots.txt',  # tiny same-origin page, so the hidden window stays light
                   fetch=FETCH_CLAUDE, logo='claude.png', accent='#d97757',
                   remaining=False, labels=('Session', 'Week'), windows=(5 * 3600, 7 * 86400)),
    'codex': dict(name='Codex', site='chatgpt.com', read=read_codex, logo='codex.png', accent='#7a95ff',
                  # Codex's own usage menu shows what is left ("Usage remaining"), not what is used.
                  remaining=True, labels=('5h', 'Weekly'), windows=(5 * 3600, 7 * 86400)),
}

# Both pages are Ovo's own and need nothing from the network, so this policy lets them load nothing:
# no requests, no frames, no outside images or scripts. Even if something odd got into a page, it could not send data out.
CSP = ("<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; img-src data:; "
       "style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\">")

HTML = """<!doctype html><meta charset=utf-8>__CSP__
<style>
  html, body { margin: 0; height: 100%; overflow: hidden; user-select: none; cursor: default; }
  body { box-sizing: border-box; padding: 8px 12px 8px 10px; display: flex; flex-direction: column;
         justify-content: center; gap: 6px;
         background: linear-gradient(180deg, #252523, #1b1b1a); color: #ecebe8;
         border: 1px solid transparent; border-image: linear-gradient(120deg, #d97757, #7a95ff) 1;
         font: 12px 'Segoe UI Variable Text', 'Segoe UI', sans-serif; }
  .head { display: flex; align-items: center; gap: 8px; min-height: 26px; }
  .head img { width: 22px; height: 22px; flex: none; }
  #hello { font: 13.5px Georgia, 'Times New Roman', serif; white-space: nowrap; overflow: hidden;
           text-overflow: ellipsis; }
  body[data-alert] { --alert: #f0a03c; animation: pulse 1.3s ease-in-out 3; }
  body[data-alert="90"] { --alert: #e5484d; }
  body[data-alert="reset"] { --alert: #3fb27f; }
  body[data-alert] #hello { color: var(--alert); font: 600 12.5px 'Segoe UI Variable Text', 'Segoe UI', sans-serif; }
  #upd { display: none; flex: 1; min-width: 0; align-items: center; gap: 6px; }
  body.updating:not([data-alert]) #hello { display: none; }
  body.updating:not([data-alert]) #upd { display: flex; }
  #updtext { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
             font: 600 12px 'Segoe UI Variable Text', 'Segoe UI', sans-serif; }
  #upd button { font: 600 11px 'Segoe UI', sans-serif; padding: 3px 9px; border-radius: 6px; cursor: pointer;
                color: #ecebe8; background: rgba(255, 255, 255, .08); border: 1px solid rgba(255, 255, 255, .18); }
  #upd button:hover { background: rgba(255, 255, 255, .16); }
  #upd #updgo { color: #1b1b1a; background: #ecebe8; border-color: #ecebe8; }
  #upd #updgo:hover { background: #fff; }
  @keyframes pulse { 50% { box-shadow: inset 0 0 0 2px var(--alert); } }
  #groups { display: contents; }
  .group { display: grid; grid-template-columns: 22px 1fr; gap: 10px; align-items: center; padding-top: 6px;
           border-top: 1px solid rgba(255, 255, 255, .07); }
  .glogo { position: relative; width: 22px; height: 22px; }
  .glogo img { width: 22px; height: 22px; }
  .group.stale .glogo::after { content: ''; position: absolute; right: -2px; top: -2px; width: 7px; height: 7px;
                               border-radius: 50%; background: #f0a03c; }
  .rows { display: grid; gap: 4px; min-height: 38px; align-content: center; }
  .row { display: grid; grid-template-columns: 48px 1fr 34px 76px; align-items: center; gap: 8px; }
  .label { color: #a3a19c; font-size: 11px; letter-spacing: .02em; }
  .bar { position: relative; height: 6px; background: rgba(255, 255, 255, .08); border-radius: 3px; overflow: hidden; }
  .bar b { display: block; height: 100%; width: 0; border-radius: 3px; background: var(--c);
           transition: width .6s cubic-bezier(.2, .8, .2, 1), background .3s; }
  .tick { position: absolute; top: 0; bottom: 0; width: 2px; margin-left: -1px; background: #ecebe8; opacity: .8; }
  .pct { text-align: right; font-weight: 600; font-size: 13px; font-variant-numeric: tabular-nums; }
  .reset { color: #7d7b77; font-size: 10.5px; text-align: right; white-space: nowrap; }
  .reset .clock, body:hover .reset .left { display: none; }
  body:hover .reset .clock { display: inline; }
  .msg { display: none; color: #a3a19c; font-size: 11px; line-height: 1.35; }
  .group.showmsg .row { display: none; }
  .group.showmsg .msg { display: block; }
  .group.stale .row { opacity: .45; filter: grayscale(1); }
  #menu { display: none; position: fixed; z-index: 1; padding: 3px; min-width: 116px; border-radius: 6px;
          background: #2d2d2b; border: 1px solid rgba(255, 255, 255, .1); box-shadow: 0 4px 12px rgba(0, 0, 0, .4); }
  #menu button { display: block; width: 100%; padding: 2px 8px; border: 0; border-radius: 4px; text-align: left;
                 background: none; color: #ecebe8; font: 11.5px 'Segoe UI', sans-serif; cursor: default; }
  #menu button:hover, #menu button:focus-visible { background: rgba(255, 255, 255, .1); outline: none; }
</style>
<div class=head><img id=ovo alt="Ovo"><div id=hello></div>
  <div id=upd><span id=updtext></span><button id=updgo></button><button id=updlater></button></div></div>
<div id=groups></div>
<div id=menu role=menu>
  <button role=menuitem data-a=refresh>Refresh now</button>
  <button role=menuitem data-a=reset_position>Reset position</button>
  <button role=menuitem data-a=settings>Settings…</button>
  <button role=menuitem data-a=quit>Quit</button>
</div>
<script>
  const CFG = __CONFIG__;
  document.getElementById('ovo').src = CFG.ovo;
  const rowHtml = label => `<div class=row><span class=label>${label}</span><div class=bar><b></b><i class=tick></i></div>` +
                           `<span class=pct>—</span><span class=reset></span></div>`;
  CFG.providers.forEach(p => document.getElementById('groups').insertAdjacentHTML('beforeend',
    `<div class=group id="g-${p.id}"><div class=glogo><img src="${p.logo}" alt="${p.id}"></div>` +
    `<div class=rows>${rowHtml(p.labels[0])}${rowHtml(p.labels[1])}<div class=msg></div></div></div>`));

  const menu = document.getElementById('menu');
  document.oncontextmenu = e => {
    e.preventDefault();
    menu.style.display = 'block';
    menu.style.left = Math.min(e.clientX, innerWidth - menu.offsetWidth - 4) + 'px';
    menu.style.top = Math.max(4, Math.min(e.clientY, innerHeight - menu.offsetHeight - 4)) + 'px';
    menu.querySelector('button').focus();
  };
  const closeMenu = () => { menu.style.display = 'none'; };
  menu.onclick = e => { const a = e.target.dataset.a; if (a) { closeMenu(); pywebview.api[a](); } };
  document.addEventListener('mousedown', e => { if (!menu.contains(e.target)) closeMenu(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeMenu(); });
  window.addEventListener('blur', closeMenu);

  function updateUI(text, go, later) {  // the update prompt in the header; null for text hides it
    document.body.classList.toggle('updating', text !== null);
    if (text === null) return;
    document.getElementById('updtext').textContent = text;
    [['updgo', go], ['updlater', later]].forEach(([id, label]) => {
      const b = document.getElementById(id);
      b.textContent = label || '';
      b.style.display = label ? '' : 'none';
    });
  }
  document.getElementById('updgo').onclick = () => pywebview.api.update_action('go');
  document.getElementById('updlater').onclick = () => pywebview.api.update_action('later');

  // Warning colors follow how much is used, so for a "remaining" provider a low number is the red one.
  const color = (p, pct) => {
    const used = p.remaining ? 100 - pct : pct;
    return used >= 90 ? '#e5484d' : used >= 70 ? '#f0a03c' : p.accent;
  };
  let last = null;
  function greeting() {  // uses this PC's clock, like claude.ai's home page
    const h = new Date().getHours();
    const part = h < 12 ? 'morning' : h < 17 ? 'afternoon' : 'evening';
    return `Good ${part}, ${CFG.name}`;
  }
  function countdown(iso) {
    const m = Math.ceil((new Date(iso) - Date.now()) / 60000);
    if (m <= 0) return 'resetting…';
    return 'in ' + (m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m`);
  }
  function ago(ms) {
    const m = Math.floor((Date.now() - ms) / 60000);
    return m < 1 ? 'less than a minute ago' : m < 60 ? `${m}m ago` : `${Math.floor(m / 60)}h ${m % 60}m ago`;
  }
  function renderGroup(p, g) {
    const el = document.getElementById('g-' + p.id);
    el.classList.toggle('stale', !!g.stale_since);
    el.classList.toggle('showmsg', !!g.status);
    el.title = g.stale_since ? `${p.id} is offline · last updated ${ago(g.stale_since)}` : '';
    el.querySelector('.msg').textContent = g.status || '';
    if (!g.rows) return;
    el.querySelectorAll('.row').forEach((row, i) => {
      const [pct, text, clock, iso] = g.rows[i];
      const bar = row.querySelector('b');
      bar.style.width = Math.min(pct, 100) + '%';
      bar.style.setProperty('--c', color(p, pct));
      row.querySelector('.pct').textContent = text;
      // The first row counts down (clock time on hover); the second keeps the day + time.
      const left = i === 0 && iso ? countdown(iso) : clock;
      row.querySelector('.reset').innerHTML = clock ? '↻ <span class=left></span><span class=clock></span>' : '';
      if (clock) {
        row.querySelector('.left').textContent = left;
        row.querySelector('.clock').textContent = clock;
      }
      // The pace marker: how far through its window we are. A bar that is past it (before it, for a
      // "remaining" bar) is being used faster than the window resets.
      const tick = row.querySelector('.tick');
      const timeLeft = iso ? Math.min(1, Math.max(0, (new Date(iso) - Date.now()) / (p.windows[i] * 1000))) : null;
      tick.style.display = timeLeft === null ? 'none' : 'block';
      row.title = '';
      if (timeLeft !== null) {
        tick.style.left = (p.remaining ? timeLeft : 1 - timeLeft) * 100 + '%';
        const used = p.remaining ? 100 - pct : pct, gone = (1 - timeLeft) * 100;
        row.title = `${used.toFixed(0)}% used, ${gone.toFixed(0)}% of the time gone: ` +
          (used > gone + 5 ? 'using it faster than it resets' : used < gone - 5 ? 'under pace, plenty of room' : 'on pace');
      }
    });
  }
  let flashing = false, flashTimer = null;
  function flash(text, kind) {  // an alert: shown in place of the greeting for a while, with a pulsing outline
    flashing = true;
    document.body.dataset.alert = kind;
    document.getElementById('hello').textContent = text;
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => { flashing = false; delete document.body.dataset.alert; render(last || {}); }, 15000);
  }
  function render(v) {
    last = v;
    if (!flashing) document.getElementById('hello').textContent = greeting();
    CFG.providers.forEach(p => renderGroup(p, (v.groups || {})[p.id] || {status: 'Connecting…'}));
  }
  setInterval(() => last && render(last), 15000);  // keeps countdowns, greeting and "ago" current between polls
  render({});
</script>"""

SETUP_HTML = """<!doctype html><meta charset=utf-8>__CSP__
<style>
  html, body { margin: 0; height: 100%; }
  body { box-sizing: border-box; padding: 26px 36px 22px; background: linear-gradient(180deg, #252523, #1b1b1a);
         color: #ecebe8; font: 13px 'Segoe UI Variable Text', 'Segoe UI', sans-serif; display: flex;
         flex-direction: column; }
  header { text-align: center; margin-bottom: 14px; }
  header img { width: 56px; height: 56px; }
  h1 { font: 26px Georgia, 'Times New Roman', serif; margin: 8px 0 4px; }
  header p { margin: 0; color: #a3a19c; }
  .label { display: block; margin: 14px 0 7px; color: #a3a19c; font-size: 12px; letter-spacing: .02em; }
  #name, .card, #go { font-family: 'Segoe UI Variable Text', 'Segoe UI', sans-serif; }
  #name { width: 100%; box-sizing: border-box; padding: 11px 13px; border-radius: 9px; font-size: 14px;
          color: #ecebe8; background: #2d2d2b; border: 1px solid rgba(255, 255, 255, .12); outline: none; }
  #name:focus { border-color: #7a95ff; }
  .cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
  .card { height: 88px; border-radius: 11px; border: 1px solid rgba(255, 255, 255, .1); background: #2d2d2b;
          color: #ecebe8; font-size: 13px; cursor: pointer; display: flex; flex-direction: column;
          align-items: center; justify-content: center; gap: 9px; }
  .card:hover { background: #343432; }
  .card.on { outline: 2px solid var(--c); outline-offset: -1px; background: #343432; }
  .logos { display: flex; gap: 6px; } .logos img { width: 28px; height: 28px; }
  #hint { min-height: 34px; margin: 10px 2px 0; color: #a3a19c; font-size: 12px; line-height: 1.45; }
  .opts { margin-top: 6px; border-top: 1px solid rgba(255, 255, 255, .07); padding-top: 6px; }
  .opts label { display: flex; align-items: center; gap: 10px; margin: 8px 0; color: #d6d4cf; font-size: 12.5px;
                cursor: pointer; }
  .opts input { width: 16px; height: 16px; margin: 0; accent-color: #7a95ff; }
  #err { min-height: 16px; margin: 4px 2px 0; color: #e5484d; font-size: 12px; }
  #go { margin-top: auto; padding: 12px; border: 0; border-radius: 9px; font-size: 14px; font-weight: 600;
        cursor: pointer; color: #1b1b1a; background: #ecebe8; }
  #go:disabled { opacity: .35; cursor: default; }
  #go:not(:disabled):hover { background: #fff; }
  footer { margin-top: 10px; text-align: center; color: #6f6d69; font-size: 11px; }
  footer a { color: #a3a19c; } footer a:hover { color: #ecebe8; } #chkres { color: #a3a19c; }
</style>
<header><img id=logo alt="Ovo"><h1 id=title></h1><p>Claude and Codex usage, at a glance.</p></header>
<label class=label for=name>What should we call you?</label>
<input id=name maxlength=24 placeholder="Your first name" autocomplete=off spellcheck=false>
<span class=label>What do you use?</span>
<div class=cards id=cards></div>
<div id=hint></div>
<div class=opts>
  <label><input type=checkbox id=startup> Start Ovo when Windows starts</label>
  <label><input type=checkbox id=alerts> Notify me at 80% and 90%, and when a limit resets</label>
  <label><input type=checkbox id=hide_fullscreen> Hide while a full-screen app is running</label>
  <label><input type=checkbox id=updates> Check for updates (always asks before installing)</label>
</div>
<div id=err></div>
<button id=go></button>
<footer><span id=ver></span> · <a href="#" id=chk>Check for updates</a> <span id=chkres></span></footer>
<script>
  const CFG = __CONFIG__;
  const $ = id => document.getElementById(id);
  $('logo').src = CFG.ovo;
  $('title').textContent = CFG.editing ? 'Settings' : 'Welcome to Ovo';
  $('go').textContent = CFG.editing ? 'Save and restart' : 'Start Ovo';
  $('ver').textContent = 'Ovo ' + CFG.version;
  $('chk').onclick = async e => {
    e.preventDefault();
    $('chkres').textContent = 'Checking…';
    $('chkres').textContent = await pywebview.api.check_updates();
  };
  const CHOICES = [
    {id: 'claude', label: 'Claude', logos: [CFG.claude], color: '#d97757',
     hint: "You'll sign in to claude.ai once, in a small window. Ovo then keeps you signed in."},
    {id: 'codex', label: 'Codex', logos: [CFG.codex], color: '#7a95ff',
     hint: 'No sign-in needed: Ovo uses the login the Codex app already has on this PC.'},
    {id: 'both', label: 'Both', logos: [CFG.claude, CFG.codex], color: '#ecebe8',
     hint: "Claude needs a one-time sign-in in a small window. Codex needs nothing: Ovo uses the login the Codex app already has."},
  ];
  let choice = CFG.choice;
  CHOICES.forEach(c => {
    const b = document.createElement('button');
    b.className = 'card'; b.style.setProperty('--c', c.color); b.dataset.id = c.id;
    b.innerHTML = `<span class=logos>${c.logos.map(s => `<img src="${s}" alt="">`).join('')}</span>${c.label}`;
    b.onclick = () => { choice = c.id; refresh(); };
    $('cards').appendChild(b);
  });
  Object.keys(CFG.options).forEach(k => { $(k).checked = CFG.options[k]; });
  const valid = () => $('name').value.trim().length > 0 && choice;
  function refresh() {
    document.querySelectorAll('.card').forEach(b => b.classList.toggle('on', b.dataset.id === choice));
    const c = CHOICES.find(c => c.id === choice);
    $('hint').textContent = c ? c.hint : 'Pick the one you use, or both.';
    $('go').disabled = !valid();
  }
  async function submit() {
    if (!valid()) return;
    $('go').disabled = true; $('err').textContent = '';
    const options = {};
    Object.keys(CFG.options).forEach(k => { options[k] = $(k).checked; });
    const err = await pywebview.api.save($('name').value, choice, options);
    if (err) { $('err').textContent = err; refresh(); }
  }
  $('name').value = CFG.name;
  $('name').addEventListener('input', refresh);
  $('name').addEventListener('keydown', e => { if (e.key === 'Enter') submit(); });
  $('go').onclick = submit;
  $('name').focus(); refresh();
</script>"""


def format_reset(iso, now=None):
    """'2:10 PM' when the reset is today, else 'Sun 7:00 PM' (same wording as the usage page)."""
    # resets_at is e.g. 10:09:59.70; the page rounds it to the nearest minute (10:10).
    when = datetime.fromisoformat(iso).astimezone(now.tzinfo if now else None) + timedelta(seconds=30)
    now = now or datetime.now().astimezone()
    clock = when.strftime('%I:%M %p').lstrip('0')
    return clock if when.date() == now.date() else f"{when.strftime('%a')} {clock}"


def number(value):
    """A percentage from a service's reply, or None if it isn't a plain number. Replies come over the network,
    so their shape is never trusted. Kept within 0 to 100."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:  # NaN is not a percentage
        return None
    return max(0.0, min(100.0, float(value)))


def parse_time(text):
    """A reset time from a service's reply as a timezone-aware datetime, or None if it isn't one."""
    try:
        when = datetime.fromisoformat(text) if isinstance(text, str) else None
    except ValueError:
        return None
    return when if when and when.tzinfo else None


def embed(data):
    """JSON that is safe to put inside a <script> tag: no '<' means it can never close the tag early."""
    return json.dumps(data).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')


def row_text(block, remaining=False):
    """(percent, percent label, reset clock text, reset ISO time for the countdown)."""
    used = number(block.get('utilization')) if isinstance(block, dict) else None
    if used is None:
        return 0, '—', '', None
    iso = block.get('resets_at')
    if not parse_time(iso):
        iso = None
    pct = 100 - used if remaining else used
    return pct, f'{pct:.0f}%', format_reset(iso) if iso else '', iso


def alert_step(prev, used, resets_at):
    """Decide whether a row needs an alert. `prev` is (resets_at, level) from the last check, or None on the
    first one. Returns (new state, kind): kind is 80 or 90 (just crossed it), 'reset' (a new window began
    after you had reached 80%), or None. Levels only go up within a window."""
    level = 90 if used >= 90 else 80 if used >= 80 else 0
    if prev is None:
        return (resets_at, level), None  # the first look at a row never alerts
    old_reset, old_level = prev
    gap = abs((datetime.fromisoformat(resets_at) - datetime.fromisoformat(old_reset)).total_seconds())
    if gap > 120:  # a different reset time: a new window began (the same one is reported with tiny jitter)
        return (resets_at, level), 'reset' if old_level else None
    if level > old_level:
        return (old_reset, level), level
    return (old_reset, old_level), None


def alert_text(p, row, kind, used, resets_at):
    name, label = p['name'], p['labels'][row]
    if kind == 'reset':
        return f'{name} · {label} has reset. You have a fresh window.'
    amount = f'{100 - used:g}% left' if p['remaining'] else f'{used:g}% used'
    return f"{name} · {label}: {amount}. Resets {format_reset(resets_at)}."


def alert_short(p, row, kind, used):
    """The same alert, short enough for Ovo's own window."""
    name, label = p['name'], p['labels'][row]
    if kind == 'reset':
        return f'{name} {label} has reset'
    return f'{name} {label}: {100 - used:g}% left' if p['remaining'] else f'{name} {label}: {used:g}% used'


def clean_name(text):
    """The name as typed, tidied (None if empty or longer than 24 characters)."""
    name = re.sub(r'\s+', ' ', str(text)).strip()
    return name if 0 < len(name) <= 24 else None


def parse_settings(raw):
    """The saved settings (name, providers and the OPTIONS), or None when the file is missing or unusable."""
    try:
        name, providers = clean_name(raw['name']), [k for k in PROVIDERS if k in raw['providers']]
        options = {k: bool(raw.get(k, default)) for k, default in OPTIONS.items()}
    except (KeyError, TypeError, AttributeError):
        return None
    return dict(options, name=name, providers=providers) if name and providers else None


def load_settings():
    try:
        return parse_settings(json.loads(SETTINGS_FILE.read_text()))
    except (OSError, ValueError):
        return None


def parse_version(text):
    """(1, 2, 3) from '1.2.3' or 'v1.2.3'; None for anything else (a pre-release tag, a typo, junk)."""
    match = re.fullmatch(r'v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})', text) if isinstance(text, str) else None
    return tuple(int(part) for part in match.groups()) if match else None


def allowed_url(url):
    """True for an https address on GitHub's own hosts (and nothing else)."""
    try:
        parts = urllib.parse.urlsplit(url)
        return parts.scheme == 'https' and parts.hostname in UPDATE_HOSTS and not parts.username and parts.port in (None, 443)
    except ValueError:
        return False


class GitHubRedirects(urllib.request.HTTPRedirectHandler):
    """GitHub sends downloads on to its own storage hosts. Follow that, but only to hosts on the list."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, newurl) if allowed_url(newurl) else None


UPDATE_OPENER = urllib.request.build_opener(GitHubRedirects)  # HTTPS with certificate checks, the default


def fetch(url, limit):
    """The bytes at an https GitHub address, at most `limit` of them. Sends no login or personal data."""
    if not allowed_url(url):
        raise ValueError('address not allowed')
    request = urllib.request.Request(url, headers={'User-Agent': f'Ovo/{VERSION}', 'Accept': 'application/vnd.github+json'})
    with UPDATE_OPENER.open(request, timeout=30) as reply:
        data = reply.read(limit + 1)
    if len(data) > limit:
        raise ValueError('reply too large')
    return data


def find_update(data, current):
    """The update to offer from GitHub's "latest release" reply, or None when nothing newer is there or the reply
    isn't one Ovo trusts. The reply only says which version and files exist; the download addresses are built here
    from the version, never taken from the reply."""
    if not isinstance(data, dict) or data.get('draft') or data.get('prerelease'):
        return None
    tag = data.get('tag_name')
    version = parse_version(tag)
    if not version or version <= current or tag != 'v' + '.'.join(map(str, version)):
        return None
    text = '.'.join(map(str, version))
    zip_name = f'Ovo-{text}-windows.zip'
    names = {a.get('name') for a in data.get('assets') or [] if isinstance(a, dict)}
    if not {zip_name, zip_name + '.sha256'} <= names:
        return None  # the release isn't complete yet
    base = f'https://github.com/{REPO}/releases/'
    return {'version': text, 'zip_name': zip_name, 'page': f'{base}tag/{tag}',
            'zip_url': f'{base}download/{tag}/{zip_name}', 'sha_url': f'{base}download/{tag}/{zip_name}.sha256'}


def latest_update(fetcher=fetch):
    """The update on offer, or None if you're up to date. Raises OSError or ValueError if GitHub can't be asked."""
    return find_update(json.loads(fetcher(RELEASES_API, 1_000_000)), parse_version(VERSION))


def expected_hash(text, zip_name):
    """The SHA-256 from a checksum file ('<64 hex digits>  <file name>'), or ValueError if it isn't one for this zip."""
    parts = text.split()
    if not parts or not re.fullmatch(r'[0-9a-fA-F]{64}', parts[0]) or (len(parts) > 1 and parts[1].lstrip('*') != zip_name):
        raise ValueError('unreadable checksum')
    return parts[0].lower()


def download_update(offer, dest, fetcher=fetch):
    """Download the new Ovo.exe to `dest`, only after its checksum matches. Raises ValueError when anything is off."""
    archive = fetcher(offer['zip_url'], MAX_ZIP)
    want = expected_hash(fetcher(offer['sha_url'], 4096).decode('ascii'), offer['zip_name'])
    if hashlib.sha256(archive).hexdigest() != want:
        raise ValueError('checksum mismatch')
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        if z.getinfo('Ovo.exe').file_size > MAX_ZIP:  # also guards against a zip that unpacks to something huge
            raise ValueError('file too large')
        exe = z.read('Ovo.exe')  # only this one name is ever read, so no path in the zip is used
    if not exe.startswith(b'MZ'):
        raise ValueError('not a Windows program')
    dest.write_bytes(exe)
    return dest


def apply_update(new_exe, current_exe):
    """Swap the running Ovo.exe for the new one. Windows lets a running program be renamed, so the old one is kept
    as Ovo.exe.old until the next start, and put back if the swap fails."""
    old = current_exe.with_name(current_exe.name + '.old')
    old.unlink(missing_ok=True)
    current_exe.rename(old)
    try:
        new_exe.replace(current_exe)
    except OSError:
        old.rename(current_exe)
        raise


def clean_update_leftovers():
    if FROZEN:
        for suffix in ('.old', '.new'):
            Path(sys.executable).with_name(Path(sys.executable).name + suffix).unlink(missing_ok=True)


def can_self_update():
    """True for the packaged exe when its folder can be written to. (From source, Ovo just opens the release page.)"""
    if not FROZEN:
        return False
    try:
        probe = Path(sys.executable).with_name('.ovo-write-test')
        probe.write_bytes(b'')
        probe.unlink()
        return True
    except OSError:
        return False


def snoozed(version, now=None, file=None):
    """True if you chose "Later" for this version less than a day ago."""
    try:
        saved = json.loads((file or UPDATE_FILE).read_text())
        return saved.get('version') == version and saved.get('until', 0) > (now or time.time())
    except (OSError, ValueError, AttributeError):
        return False


def snooze(version, file=None):
    file = file or UPDATE_FILE
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps({'version': version, 'until': time.time() + 24 * 3600}))


def eval_async(window, script, site, timeout=15):
    """evaluate_js only hands back a resolved Promise through its callback."""
    done, out = threading.Event(), {}
    window.evaluate_js(script, lambda r: (out.update(r=r), done.set()))
    if not done.wait(timeout):
        raise TimeoutError(f'{site} did not answer')
    return out['r']


wakes = {key: threading.Event() for key in PROVIDERS}  # set by "Refresh now" to skip the wait
quitting = threading.Event()  # set when shutting down, so closing the hidden sign-in window is allowed then
signing_in = threading.Event()  # the sign-in window is up and we are waiting for a login
state, state_lock = {}, threading.Lock()  # each provider's latest group, shown together in one window
ui = {}  # the running windows ('widget', and 'setup' while the settings window is open) and the 'settings'


def push(widget, key, group):
    """Show this provider's latest state; the other provider's part stays as it was."""
    with state_lock:
        state[key] = group
        try:
            widget.evaluate_js(f'render({json.dumps({"groups": state})})')
        except Exception:
            pass  # widget page not ready yet


def notify(text):
    """A Windows notification: a balloon from a tray icon with Ovo's logo, which goes away afterwards."""
    def show():
        from System import Action
        from System.Drawing import Icon
        from System.Windows.Forms import NotifyIcon, ToolTipIcon
        form, box = ui['widget'].native, []

        def create():
            icon = NotifyIcon()
            icon.Icon = Icon(str(ASSETS / 'ovo.ico'))
            icon.Visible = True
            icon.ShowBalloonTip(8000, 'Ovo', text, getattr(ToolTipIcon, 'None'))  # `None` is a Python keyword
            box.append(icon)
        form.Invoke(Action(create))
        time.sleep(10)  # long enough for the balloon to show, then the icon leaves the tray
        form.Invoke(Action(lambda: box[0].Dispose()))
    threading.Thread(target=show, daemon=True).start()


def alert(widget, p, row, kind, used, resets_at):
    """Tell you a limit needs attention: a banner in Ovo's own window, which is always in view, and also a
    Windows notification (which Windows may hold back, for example in Do Not Disturb)."""
    try:
        widget.evaluate_js(f'flash({json.dumps(alert_short(p, row, kind, used))}, {json.dumps(str(kind))})')
    except Exception:
        pass  # widget page not ready yet
    notify(alert_text(p, row, kind, used, resets_at))


def poll(key, feed, widget):
    """Check one provider every few seconds and push what it found. `feed` is Claude's hidden browser window."""
    p = PROVIDERS[key]
    last = None  # last good group, kept on screen (dimmed) when the site stops answering
    alerts = {}  # row -> alert_step state
    while True:
        try:
            res = (p['read']() if 'read' in p else eval_async(feed, p['fetch'], p['site'])) or {}
        except Exception as e:  # page still loading, timeout, or a script error
            res = {'error': str(e)}
            if feed and not signing_in.is_set():
                feed.load_url(p['idle'])  # a check lost mid-navigation can wedge the page; a fresh page answers again
        if not isinstance(res, dict):  # replies come over the network: never trust their shape
            res = {'error': f"{p['site']} sent an unexpected reply"}
        try:
            if 'session' in res:
                if signing_in.is_set():
                    signing_in.clear()
                    feed.hide()
                    feed.load_url(p['idle'])
                blocks = (res.get('session'), res.get('week'))
                group = {'rows': [row_text(block, p['remaining']) for block in blocks]}
                last = dict(group, at=time.time() * 1000)
                if ui['settings']['alerts']:
                    for row, block in enumerate(blocks):
                        used = number(block.get('utilization')) if isinstance(block, dict) else None
                        resets = block.get('resets_at') if isinstance(block, dict) else None
                        if used is not None and parse_time(resets):
                            alerts[row], kind = alert_step(alerts.get(row), used, resets)
                            if kind:
                                alert(widget, p, row, kind, used, resets)
            elif feed and (res.get('status') in (401, 403) or signing_in.is_set()):  # while signing in, the login pages answer 404 or not at all
                if not signing_in.is_set():  # logged out, or Cloudflare wants a check: both are solved in a real page
                    signing_in.set()
                    feed.load_url(p['login'])
                    feed.show()
                group = {'status': f"Sign in to {p['site']} in the window that opened"}
            elif last:  # offline, timeout or server error: keep the last numbers, marked as old
                group = dict(last, stale_since=last['at'])
            else:
                group = {'status': str(res.get('error') or f"{p['site']} is not answering")[:120]}
        except Exception:  # whatever the reply held, one odd answer must not stop the checks
            group = dict(last, stale_since=last['at']) if last else {'status': f"{p['site']} sent an unexpected reply"}
        push(widget, key, group)
        wakes[key].wait(EVERY)
        wakes[key].clear()


def is_fullscreen(notification_state):
    """From SHQueryUserNotificationState: 2 = a full-screen app, 3 = a full-screen game (Direct3D),
    4 = presentation mode. (5 is normal use.)"""
    return notification_state in (2, 3, 4)


def covers(window, monitor):
    """True when the window rectangle (left, top, right, bottom) covers the whole monitor rectangle."""
    return window[0] <= monitor[0] and window[1] <= monitor[1] and window[2] >= monitor[2] and window[3] >= monitor[3]


def foreground_is_fullscreen():
    """True when the window you are using covers its whole screen, taskbar included (a borderless game, F11 in a
    browser). Windows' own check misses some of these. The desktop and the taskbar don't count."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    name = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, name, 64)
    if name.value in ('Progman', 'WorkerW', 'Shell_TrayWnd'):
        return False

    class MonitorInfo(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT), ('work', wintypes.RECT), ('flags', wintypes.DWORD)]
    rect, info = wintypes.RECT(), MonitorInfo()
    info.size = ctypes.sizeof(info)
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(info))  # 2 = the nearest monitor
    m = info.monitor
    return covers((rect.left, rect.top, rect.right, rect.bottom), (m.left, m.top, m.right, m.bottom))


def watch_fullscreen(widget):
    """Hide Ovo while a full-screen app (game, video, presentation) is running; bring it back afterwards."""
    import ctypes
    state_value, hidden = ctypes.c_int(), False
    while not quitting.is_set():
        ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state_value))
        busy = is_fullscreen(state_value.value) or foreground_is_fullscreen()
        if busy != hidden:
            (widget.hide if busy else widget.show)()
            hidden = busy
        time.sleep(2)


def update_ui(text, go=None, later=None):
    """Show the update prompt in Ovo's header (or hide it, with text None)."""
    try:
        ui['widget'].evaluate_js(f'updateUI({json.dumps(text)}, {json.dumps(go)}, {json.dumps(later)})')
    except Exception:
        pass  # the window isn't ready, or is closing


def show_offer(offer):
    ui['update'] = {'offer': offer, 'stage': 'offer'}
    update_ui(f"Ovo {offer['version']} is available", 'Update', 'Later')


def update_loop():
    """Look for a new release now and then. It only ever asks: nothing is installed unless you press Update."""
    if quitting.wait(30):  # let the window settle first
        return
    while True:
        if ui['settings']['updates']:
            try:
                offer = latest_update()
            except (OSError, ValueError):
                offer = None  # offline, rate-limited, or no release visible: try again later
            if offer and not snoozed(offer['version']) and not ui.get('update'):
                show_offer(offer)
        if quitting.wait(CHECK_EVERY):
            return


def open_release_page(offer):
    import webbrowser
    webbrowser.open(offer['page'])  # the address was built from the checked version, not taken from the reply


def install_update():
    """You pressed Update. The packaged exe downloads, checks and swaps itself, then restarts; a script run from
    source opens the release page instead."""
    offer = ui['update']['offer']
    try:
        if can_self_update():
            exe = Path(sys.executable)
            update_ui('Downloading…')
            new = download_update(offer, exe.with_name(exe.name + '.new'))
            update_ui('Installing…')
            apply_update(new, exe)
            update_ui('Restarting…')
            restart()
            shut_down()
        else:
            open_release_page(offer)
            snooze(offer['version'])
            ui.pop('update', None)
            update_ui(None)
    except Exception:  # whatever went wrong, the running copy still works: say so and offer the page
        ui['update']['stage'] = 'failed'
        update_ui("Couldn't update", 'Open page', 'Close')


def run(feed, widget, active):
    for key in active:
        threading.Thread(target=poll, args=(key, feed if key == 'claude' else None, widget), daemon=True).start()
    threading.Thread(target=update_loop, daemon=True).start()
    if ui['settings']['hide_fullscreen']:
        threading.Thread(target=watch_fullscreen, args=(widget,), daemon=True).start()


def brand(*pairs):
    """Give windows their icons, so the taskbar shows Ovo's logo, not Python's."""
    from System import Action
    from System.Drawing import Icon
    for window, ico in pairs:
        if window:
            icon, form = Icon(str(ASSETS / ico)), window.native
            form.Invoke(Action(lambda form=form, icon=icon: setattr(form, 'Icon', icon)))


def single_instance(wait=0):
    """False when Ovo is already running (a second launch just exits). `wait`: seconds to wait for a
    running Ovo to finish first, used when Ovo restarts itself."""
    import ctypes
    kernel = ctypes.windll.kernel32
    deadline = time.time() + wait
    while True:
        handle = kernel.CreateMutexW(None, False, 'Ovo')  # kept open until the process ends
        if kernel.GetLastError() != 183:  # ERROR_ALREADY_EXISTS
            return True
        kernel.CloseHandle(handle)
        if time.time() >= deadline:
            return False
        time.sleep(0.3)


def launch_command(*extra):
    """The command that starts Ovo: the packaged exe, or pythonw (no console window) running this script."""
    if FROZEN:
        return [sys.executable, *extra]
    return [str(Path(sys.executable).with_name('pythonw.exe')), str(Path(__file__).resolve()), *extra]


def restart():
    """Start a fresh Ovo that waits for this one to finish (after the settings changed)."""
    # The packaged exe unpacks itself into a temp folder that goes away when it exits, so the new copy must
    # unpack afresh and not reuse this one's folder (that is what the variable asks PyInstaller to do).
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1')
    subprocess.Popen(launch_command('--restart'), env=env,
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW)


def set_startup(enabled):
    """Add or remove Ovo in the list of programs Windows starts at sign-in (only your own account)."""
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, 'Ovo', 0, winreg.REG_SZ, subprocess.list2cmdline(launch_command()))
        else:
            try:
                winreg.DeleteValue(key, 'Ovo')
            except FileNotFoundError:
                pass


def shut_down():
    import webview
    quitting.set()
    for w in list(webview.windows):
        w.destroy()


def image(name):
    # The pages have no base URL to load files from, so images are inlined.
    return 'data:image/png;base64,' + base64.b64encode((ASSETS / name).read_bytes()).decode()


def page(template, config):
    """An Ovo page ready to show: the security policy in, and the settings filled in (escaped for a <script> tag,
    so a name like "</script>" is just text)."""
    return template.replace('__CSP__', CSP).replace('__CONFIG__', embed(config))


def open_setup(settings):
    """The setup window: your name, what you use and the options. `settings` is the current ones (None on first run)."""
    import webview
    if ui.get('setup'):
        ui['setup'].show()  # already open: bring it forward
        return
    choice = next((k for k, v in CHOICES.items() if settings and v == settings['providers']), '')
    options = {k: settings[k] if settings else True for k in OPTIONS}  # new users start with everything on
    config = {'ovo': image('ovo.png'), 'claude': image('claude.png'), 'codex': image('codex.png'),
              'name': settings['name'] if settings else '', 'choice': choice, 'options': options,
              'editing': bool(settings), 'version': VERSION}
    window = webview.create_window('Ovo settings' if settings else 'Welcome to Ovo',
                                   html=page(SETUP_HTML, config), js_api=SetupApi(),
                                   width=440, height=760, resizable=False, background_color='#1f1f1e')
    ui['setup'] = window
    window.events.shown += lambda: brand((window, 'ovo.ico'))
    window.events.closed += lambda: ui.pop('setup', None)


class SetupApi:
    def check_updates(self):
        """The "Check for updates" link in Settings. Returns the sentence to show next to it."""
        try:
            offer = latest_update()
        except (OSError, ValueError):
            return "Couldn't check right now."
        if not offer:
            return f'Ovo {VERSION} is up to date.'
        if ui.get('widget'):
            if not ui.get('update'):
                show_offer(offer)
            return f"Ovo {offer['version']} is available. See the Ovo window."
        return f"Ovo {offer['version']} is available."

    def save(self, name, choice, options):
        """Called by the setup page. Returns a message if something is wrong, otherwise restarts Ovo."""
        name = clean_name(name)
        if not name:
            return 'Type your name (up to 24 characters).'
        if choice not in CHOICES or not isinstance(options, dict):
            return 'Pick what you use.'
        DATA.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(dict({k: bool(options.get(k)) for k in OPTIONS},
                                                 name=name, providers=CHOICES[choice])))
        restart()
        shut_down()


def default_pos(height):
    import webview
    s = webview.screens[0]  # bottom-right corner, just above the taskbar
    return s.width - W - 12, s.height - height - 60


class Api:
    def quit(self):
        shut_down()

    def refresh(self):
        for event in wakes.values():
            event.set()

    def reset_position(self):
        widget = ui['widget']
        widget.move(*default_pos(widget.height))  # the moved event saves the new spot

    def settings(self):
        open_setup(load_settings())

    def update_action(self, which):
        """The two buttons of the update prompt: 'go' (Update, or Open page after a failure) and 'later'."""
        current = ui.get('update')
        if not current:
            return
        if which == 'go' and current['stage'] == 'offer':
            threading.Thread(target=install_update, daemon=True).start()
        elif which == 'go':
            open_release_page(current['offer'])
        elif which == 'later':
            snooze(current['offer']['version'])
            ui.pop('update', None)
            update_ui(None)


def main():
    import ctypes
    import webview
    if not single_instance(wait=15 if '--restart' in sys.argv else 0):
        return
    clean_update_leftovers()  # the copy of Ovo.exe that an update replaced
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Ovo')  # the taskbar groups it as Ovo, not Python
    # Keep the embedded browser as closed as it can be. Set explicitly, so a different default in a future
    # pywebview cannot loosen it: no local debugging port, no file:// pages, no downloads, certificate errors
    # are errors. QUIC is switched off so the browser opens no UDP socket: plain HTTPS to the two sites only.
    webview.settings.update(REMOTE_DEBUGGING_PORT=None, ALLOW_FILE_URLS=False, ALLOW_DOWNLOADS=False,
                            IGNORE_SSL_ERRORS=False)
    os.environ['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = '--disable-quic'
    DATA.mkdir(parents=True, exist_ok=True)
    settings = load_settings()
    if not settings:  # first run: ask before showing anything else
        open_setup(None)
        webview.start(private_mode=False, storage_path=str(PROFILE), debug=False)
        return
    ui['settings'] = settings
    set_startup(settings['startup'])  # also refreshes the saved path if Ovo was moved

    active, height = settings['providers'], H_BASE + H_GROUP * len(settings['providers'])
    try:
        x, y = json.loads(POS_FILE.read_text())
    except (OSError, ValueError):
        x, y = default_pos(height)

    feed = None  # Claude's hidden browser window, only when Claude is used
    if 'claude' in active:
        claude = PROVIDERS['claude']
        feed = webview.create_window(f"Ovo · sign in to {claude['site']}", claude['idle'], hidden=True,
                                     width=480, height=720)

        def keep_feed():
            # A closed sign-in window leaves the widget nothing to read from, so hide it instead. If the
            # login was not finished, the next check finds you signed out and opens it again.
            if not quitting.is_set():
                feed.hide()
                feed.load_url(claude['idle'])
                signing_in.clear()
                return False
        feed.events.closing += keep_feed

    config = {'ovo': image('ovo.png'), 'name': settings['name'],
              'providers': [dict(id=key, labels=list(PROVIDERS[key]['labels']), accent=PROVIDERS[key]['accent'],
                                 remaining=PROVIDERS[key]['remaining'], windows=list(PROVIDERS[key]['windows']),
                                 logo=image(PROVIDERS[key]['logo'])) for key in active]}
    widget = webview.create_window('Ovo', html=page(HTML, config), js_api=Api(),
                                   width=W, height=height, x=x, y=y, min_size=(W, height), frameless=True,
                                   easy_drag=True, shadow=False, on_top=True, resizable=False,
                                   background_color='#1f1f1e')
    # Square corners on purpose: Windows 11 only rounds a window together with a drop shadow,
    # and WebView2 ignores window regions/transparency keys, so a shadow-free window stays square.
    ui['widget'] = widget
    widget.events.shown += lambda: brand((widget, 'ovo.ico'), (feed, 'claude.ico'))
    widget.events.moved += lambda *xy: POS_FILE.write_text(json.dumps([widget.x, widget.y]))
    webview.start(run, (feed, widget, active), private_mode=False, storage_path=str(PROFILE), debug=False)


def install_shortcut():
    """Add an 'Ovo' shortcut to the Start Menu."""
    lnk = Path(os.environ['APPDATA']) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / 'Ovo.lnk'
    target, *args = launch_command()
    quote = lambda s: s.replace("'", "''")  # for a PowerShell single-quoted string
    script = (f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{quote(str(lnk))}');"
              f"$s.TargetPath = '{quote(target)}'; $s.Arguments = '{quote(subprocess.list2cmdline(args))}';"
              f"$s.WorkingDirectory = '{quote(str(HERE))}'; $s.IconLocation = '{quote(str(ASSETS / 'ovo.ico'))}';"
              "$s.Description = 'Claude and Codex usage, at a glance'; $s.Save()")
    subprocess.run(['powershell', '-NoProfile', '-Command', script], check=True)
    print('Start Menu shortcut created:', lnk)


def self_test():
    utc = timezone.utc
    now = datetime(2026, 11, 2, 8, 0, tzinfo=utc)
    assert format_reset('2026-11-02T10:09:59.703916+00:00', now) == '10:10 AM'
    assert format_reset('2026-11-08T14:59:59.703940+00:00', now) == 'Sun 3:00 PM'
    assert format_reset('2026-11-02T10:09:10+00:00', now) == '10:09 AM'
    assert format_reset('2026-11-02T10:09:59.703Z', now) == '10:10 AM'
    assert row_text(None) == (0, '—', '', None)
    assert row_text({'utilization': 15, 'resets_at': None}) == (15, '15%', '', None)  # used
    assert row_text({'utilization': 15, 'resets_at': None}, remaining=True) == (85, '85%', '', None)  # left
    # Replies come from the network. Odd ones must never crash a check or reach a page unchecked.
    for odd in ('x', 5, [1], {'utilization': 'high'}, {'utilization': True}, {'utilization': float('nan')},
                {'utilization': {}}, {'utilization': None}):
        assert row_text(odd) == (0, '—', '', None), odd
    assert row_text({'utilization': 250, 'resets_at': '2026-11-02T10:00:00+00:00'})[0] == 100  # clamped
    assert row_text({'utilization': -5})[0] == 0
    assert row_text({'utilization': 10, 'resets_at': 'not a time'}) == (10, '10%', '', None)
    assert row_text({'utilization': 10, 'resets_at': '2026-11-02T10:00:00'}) == (10, '10%', '', None)  # no timezone
    assert parse_time('2026-11-02T10:00:00+00:00') and not parse_time(None) and not parse_time(12345)
    # A name cannot close the <script> tag it is placed in.
    assert '</script>' not in embed({'name': '</script><script>alert(1)</script>'})
    assert '<' not in page(SETUP_HTML, {'name': '<b>'}).split('const CFG = ')[1].split(';\n')[0]
    # The Codex request never follows a redirect (the token must only go to chatgpt.com).
    assert NoRedirect().redirect_request(None, None, 302, 'Found', {}, 'https://evil.example/') is None
    assert CODEX_URL.startswith('https://chatgpt.com/')
    assert clean_name('  Alex   M ') == 'Alex M' and clean_name('   ') is None and clean_name('x' * 25) is None
    assert parse_settings({'name': 'Alex', 'providers': ['codex', 'nope']}) == \
        {'name': 'Alex', 'providers': ['codex'], 'startup': False, 'alerts': True, 'hide_fullscreen': True,
         'updates': True}
    assert parse_settings({'name': 'K', 'providers': ['claude'], 'alerts': False})['alerts'] is False
    assert parse_settings({'name': 'Alex', 'providers': []}) is None and parse_settings({'name': ''}) is None
    assert parse_settings('junk') is None and parse_settings(None) is None
    assert all(c in PROVIDERS for v in CHOICES.values() for c in v)
    # Alerts: quiet at first sight, then 80, 90 once each, then 'reset' when a new window starts.
    t0, t1 = '2026-11-02T10:00:00+00:00', '2026-11-02T15:00:00+00:00'
    s, kind = alert_step(None, 85, t0)
    assert (s, kind) == ((t0, 80), None)
    assert alert_step(s, 86, t0 + '') == ((t0, 80), None)
    s, kind = alert_step(s, 91, '2026-11-02T10:00:00.700+00:00')  # same window, tiny jitter in the reset time
    assert kind == 90 and s[1] == 90
    assert alert_step(s, 95, t0)[1] is None
    s, kind = alert_step(s, 3, t1)
    assert kind == 'reset' and s == (t1, 0)
    assert alert_step(s, 10, t1)[1] is None and alert_step((t0, 0), 5, t1)[1] is None  # reset after a quiet window: silent
    assert alert_text(PROVIDERS['codex'], 0, 90, 92, t0).startswith('Codex · 5h: 8% left')
    assert alert_text(PROVIDERS['claude'], 1, 80, 81, t0).startswith('Claude · Week: 81% used')
    assert 'reset' in alert_text(PROVIDERS['claude'], 0, 'reset', 3, t1)
    assert alert_short(PROVIDERS['codex'], 0, 90, 92) == 'Codex 5h: 8% left'
    assert alert_short(PROVIDERS['claude'], 1, 80, 81) == 'Claude Week: 81% used'
    assert alert_short(PROVIDERS['claude'], 0, 'reset', 3) == 'Claude Session has reset'
    assert [is_fullscreen(v) for v in (1, 2, 3, 4, 5)] == [False, True, True, True, False]
    screen = (0, 0, 1920, 1080)
    assert covers((0, 0, 1920, 1080), screen) and covers((-8, -8, 1928, 1088), screen)
    assert not covers((0, 0, 1920, 1040), screen) and not covers((100, 100, 900, 700), screen)  # maximized keeps the taskbar
    cmd = launch_command('--restart')
    assert cmd[-1] == '--restart' and cmd[0].lower().endswith(('.exe',))
    assert '__CONFIG__' in HTML and '__CONFIG__' in SETUP_HTML and '__CSP__' in HTML and '__CSP__' in SETUP_HTML
    assert "default-src 'none'" in CSP and 'connect-src' not in CSP  # nothing is allowed to connect anywhere
    assert all((ASSETS / f).exists() for f in ('ovo.png', 'ovo.ico', 'claude.ico')) \
        and all((ASSETS / p['logo']).exists() for p in PROVIDERS.values())
    self_test_updates()
    print('ok')


def self_test_updates():
    import tempfile
    # Which release counts as newer: compared as numbers, and only a plain vX.Y.Z tag.
    assert parse_version('v1.2.3') == (1, 2, 3) and parse_version('1.10.0') > parse_version('1.9.9')
    for junk in ('1.2', 'v1.2.3-beta', 'latest', '1.2.3.4', '', None, 5, 'v1.2.3 '):
        assert parse_version(junk) is None, junk

    def release(tag, names=None, **extra):
        name = f"Ovo-{tag.lstrip('v')}-windows.zip"
        return dict({'tag_name': tag, 'assets': [{'name': n} for n in (names or [name, name + '.sha256'])]}, **extra)
    current = (1, 0, 0)
    offer = find_update(release('v1.1.0'), current)
    assert offer and offer['version'] == '1.1.0' and offer['page'] == f'https://github.com/{REPO}/releases/tag/v1.1.0'
    assert offer['zip_url'] == f'https://github.com/{REPO}/releases/download/v1.1.0/Ovo-1.1.0-windows.zip'
    assert offer['sha_url'] == offer['zip_url'] + '.sha256'
    # Nothing to offer: same or older version, drafts, pre-releases, an incomplete or odd release.
    for none in (release('v1.0.0'), release('v0.9.0'), release('v1.1.0', draft=True), release('v1.1.0', prerelease=True),
                 release('v1.1.0', names=['Ovo-1.1.0-windows.zip']), release('v1.1.0', names=['evil.zip', 'evil.zip.sha256']),
                 release('1.1.0'), None, 'x', [], {'tag_name': 5}, {'tag_name': 'v2.0.0', 'assets': 'nope'},
                 {'tag_name': 'v2.0.0', 'assets': [None, 3]}):
        assert find_update(none, current) is None, none
    # The download addresses are built from the checked version, so a hostile reply cannot point Ovo elsewhere.
    hostile = release('v1.1.0')
    hostile['assets'][0]['browser_download_url'] = 'https://evil.example/x.zip'
    assert find_update(hostile, current)['zip_url'].startswith('https://github.com/')
    # Only GitHub's own https hosts are ever contacted, and a redirect cannot leave that list.
    assert allowed_url(RELEASES_API) and allowed_url(offer['zip_url']) and allowed_url('https://objects.githubusercontent.com/x')
    for bad in ('http://github.com/x', 'https://evil.example/x', 'https://github.com.evil.example/x', 'https://u@github.com/x',
                'https://github.com:8443/x', 'file:///c:/x', 'ftp://github.com/x', '', 'github.com'):
        assert not allowed_url(bad), bad
    assert GitHubRedirects().redirect_request(urllib.request.Request('https://github.com/a'), None, 302, 'Found', {},
                                              'https://evil.example/') is None
    try:
        fetch('http://github.com/x', 10)
        raise AssertionError('fetched an address that is not allowed')
    except ValueError:
        pass
    assert FROZEN or not can_self_update()  # a script run from source never replaces itself

    # Installing: the checksum is checked first, and only a plain Ovo.exe is taken from the zip.
    exe_bytes = b'MZ' + b'\0' * 100

    def make_zip(members):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as z:
            for member, data in members.items():
                z.writestr(member, data)
        return buffer.getvalue()

    def serve(archive, checksum):
        return lambda url, limit: archive if url == offer['zip_url'] else checksum.encode()
    name = offer['zip_name']
    good = make_zip({'Ovo.exe': exe_bytes, 'README.md': b'hi'})
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        done = download_update(offer, tmp / 'Ovo.exe.new', serve(good, f'{hashlib.sha256(good).hexdigest()}  {name}'))
        assert done.read_bytes() == exe_bytes
        wrong_member, not_exe = make_zip({'Other.exe': exe_bytes}), make_zip({'Ovo.exe': b'not a program'})
        for archive, checksum in ((good, '0' * 64 + f'  {name}'), (good, 'garbage'), (good, ''),
                                  (good, f'{hashlib.sha256(good).hexdigest()}  other.zip'),
                                  (wrong_member, f'{hashlib.sha256(wrong_member).hexdigest()}  {name}'),
                                  (not_exe, f'{hashlib.sha256(not_exe).hexdigest()}  {name}'),
                                  (b'not a zip', f'{hashlib.sha256(b"not a zip").hexdigest()}  {name}')):
            try:
                download_update(offer, tmp / 'bad.new', serve(archive, checksum))
                raise AssertionError('accepted a bad update')
            except (ValueError, KeyError, zipfile.BadZipFile):
                pass
        assert not (tmp / 'bad.new').exists()  # nothing is written until every check has passed
        # Swapping the files in place, and putting the working copy back if the swap fails.
        current_exe, new_exe = tmp / 'Ovo.exe', tmp / 'swap.new'
        current_exe.write_bytes(b'old')
        new_exe.write_bytes(b'new')
        apply_update(new_exe, current_exe)
        assert current_exe.read_bytes() == b'new' and (tmp / 'Ovo.exe.old').read_bytes() == b'old' and not new_exe.exists()
        try:
            apply_update(tmp / 'missing.new', current_exe)
            raise AssertionError('the swap should have failed')
        except OSError:
            pass
        assert current_exe.read_bytes() == b'new'
        # "Later" is remembered for a day, for that version only.
        remembered = tmp / 'update.json'
        assert not snoozed('1.1.0', file=remembered)
        snooze('1.1.0', file=remembered)
        assert snoozed('1.1.0', file=remembered) and not snoozed('1.2.0', file=remembered)
        assert not snoozed('1.1.0', now=time.time() + 25 * 3600, file=remembered)
        remembered.write_text('junk')
        assert not snoozed('1.1.0', file=remembered)


if __name__ == '__main__':
    if '--test' in sys.argv:
        self_test()
    elif 'install' in sys.argv:
        install_shortcut()
    else:
        main()
