#!/usr/bin/env python3
"""
Navegador con aspecto de Safari para KDE/Qt.
Barra de título y barra de herramientas en un solo panel (ventana sin marco).

Dependencias (Arch):  sudo pacman -S python pyside6 qt6-webengine qt6-svg
Ejecutar:             python safari_like.py [url]

Los botones de la ventana (cerrar / minimizar / maximizar) se toman del tema de
decoración de ventanas Aurorae que tengas activo en KDE. Si no hay uno compatible,
se dibujan círculos de colores.
"""
import configparser
import datetime
import html
import json
import os
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, quote, quote_plus, urlparse

from PySide6.QtCore import Qt, QTimer, QUrl, QRectF
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QKeySequence, QPainter, QPainterPath, QRegion
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QFileDialog, QFrame, QHBoxLayout, QLineEdit,
    QListWidget, QMenu, QMenuBar, QMessageBox, QTabWidget, QToolButton,
    QVBoxLayout, QWidget,
)
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

try:
    from PySide6.QtSvg import QSvgRenderer
except ImportError:           # sin QtSvg se dibujan círculos simples
    QSvgRenderer = None

HOME = "about:home"   # marcador interno: abre la página de inicio
SEARCH_URL = "https://www.google.com/search?q="

CONFIG_DIR = Path.home() / ".config" / "navegador"
CACHE_DIR = Path.home() / ".cache" / "navegador"
THUMBS_DIR = CACHE_DIR / "thumbs"
START_FILE = CACHE_DIR / "inicio.html"
FAV_FILE = CONFIG_DIR / "favoritos.json"      # edítalo a mano si quieres
HIST_FILE = CONFIG_DIR / "historial.json"

DEFAULT_FAVORITES = [
    {"name": "Google", "url": "https://www.google.com/"},
    {"name": "YouTube", "url": "https://www.youtube.com/"},
    {"name": "Gmail", "url": "https://mail.google.com/"},
    {"name": "Wikipedia", "url": "https://es.wikipedia.org/"},
    {"name": "GitHub", "url": "https://github.com/"},
    {"name": "Reddit", "url": "https://www.reddit.com/"},
    {"name": "X", "url": "https://x.com/"},
    {"name": "WhatsApp", "url": "https://web.whatsapp.com/"},
    {"name": "Twitch", "url": "https://www.twitch.tv/"},
    {"name": "Spotify", "url": "https://open.spotify.com/"},
    {"name": "Netflix", "url": "https://www.netflix.com/"},
    {"name": "Claude", "url": "https://claude.ai/"},
]


# ---------------------------------------------------------------- página de inicio
def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path, data):
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def favicon(host):
    return f"https://www.google.com/s2/favicons?domain={host}&sz=128"


ENGINES = {
    "Google": "https://www.google.com/search?q=",
    "DuckDuckGo": "https://duckduckgo.com/?q=",
    "Bing": "https://www.bing.com/search?q=",
    "Brave": "https://search.brave.com/search?q=",
}
SETTINGS_FILE = CONFIG_DIR / "ajustes.json"
BG_COLORS = ["#1d1d20", "#2b3a55", "#33503f", "#5a3d5c", "#7a2f2f", "#e9e4da", "#cfd8e3", "#f1d3ad"]
DEFAULT_SETTINGS = {
    "show_favorites": True,
    "show_frequent": True,
    "engine": "Google",
    "background": {"mode": "default", "color": BG_COLORS[1], "image": ""},
}


def load_settings():
    data = _read_json(SETTINGS_FILE, {})
    s = json.loads(json.dumps(DEFAULT_SETTINGS))
    if isinstance(data, dict):
        for k, v in data.items():
            if k == "background" and isinstance(v, dict):
                s["background"].update(v)
            elif k in s and k != "background":
                s[k] = v
    if s["engine"] not in ENGINES:
        s["engine"] = "Google"
    return s


def save_settings(s):
    _write_json(SETTINGS_FILE, s)


def _luminance(color):
    """Brillo (0-255) de un color '#rrggbb', o None si no es válido."""
    if not (isinstance(color, str) and len(color) == 7 and color[0] == "#"):
        return None
    try:
        r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    except ValueError:
        return None
    return 0.299 * r + 0.587 * g + 0.114 * b


def background_css(bg):
    mode = bg.get("mode")
    if mode == "color":
        c = bg.get("color", "")
        lum = _luminance(c)
        if lum is not None:
            css = f".bg{{background:{c}}}.bg::after{{display:none}}"
            if lum > 150:   # fondo claro: texto oscuro
                css += ":root{--fg:#26262a;--shadow:none}"
            return css
    elif mode == "image":
        p = Path(str(bg.get("image", "")))
        if p.is_file():
            return (f'.bg{{background:#111 url("{p.as_uri()}") center/cover no-repeat}}'
                    ".bg::after{background:linear-gradient(180deg,rgba(0,0,0,.10),rgba(0,0,0,.30))}")
    return ""


START_TEMPLATE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Inicio</title>
<style>
:root{
  --base:#e8e3da; --a:#f2a26b; --d:#c4c1bc; --b:#dca843; --c:#8fb2cc;
  --tile:rgba(255,255,255,.9); --ink:#4a4a4f;
  --fg:#fff; --shadow:0 1px 3px rgba(0,0,0,.6);
}
@media (prefers-color-scheme: dark){
  :root{ --base:#1b1b1d; --a:#7d4627; --d:#2b2b2e; --b:#6e5420; --c:#2b4458;
         --tile:rgba(66,66,71,.92); --ink:#e6e6ea; }
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{min-height:100%}
body{font-family:system-ui,-apple-system,"SF Pro Text","Inter",sans-serif;color:var(--fg);
     background:var(--base);overflow-x:hidden}
.bg{position:fixed;inset:0;z-index:-1;
    background:linear-gradient(135deg,var(--a) 0 24%,var(--d) 24% 46%,var(--b) 46% 72%,var(--c) 72% 100%)}
.bg::after{content:"";position:absolute;inset:0;
    background:linear-gradient(180deg,rgba(255,255,255,.16),rgba(255,255,255,0) 45%)}
main{max-width:880px;margin:0 auto;padding:11vh 28px 90px}
h2{font-size:19px;font-weight:700;margin:36px 0 15px;color:var(--fg);text-shadow:var(--shadow)}
h2:first-child{margin-top:0}
.empty{font-size:13px;color:var(--fg);text-shadow:var(--shadow);opacity:.85}
a{-webkit-user-drag:none}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(84px,1fr));gap:20px 12px}
.tile{position:relative;display:flex;justify-content:center}
.open{display:flex;flex-direction:column;align-items:center;gap:8px;text-decoration:none;color:var(--fg)}
.icon{position:relative;width:64px;height:64px;border-radius:15px;background:var(--tile);
      display:grid;place-items:center;overflow:hidden;
      box-shadow:0 1px 3px rgba(0,0,0,.22),0 5px 14px rgba(0,0,0,.14);transition:transform .12s}
.icon b{display:none;font-size:27px;font-weight:600;color:var(--ink)}
.icon.noimg b{display:block}
.icon img{position:absolute;left:12px;top:12px;width:40px;height:40px;object-fit:contain}
.tile:hover .icon{transform:scale(1.07)}
.tile .open:active .icon{filter:brightness(.88)}
.label{font-size:11px;max-width:84px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
       text-shadow:var(--shadow)}
.x{position:absolute;top:-7px;left:calc(50% - 40px);width:20px;height:20px;border-radius:50%;
   background:rgba(40,40,44,.88);color:#fff;font-size:14px;line-height:20px;text-align:center;
   text-decoration:none;opacity:0;transition:opacity .12s;z-index:2}
.tile:hover .x,.card:hover .x{opacity:1}
.x:hover{background:#d93a3a}
.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}
.card{position:relative}
.card .open{align-items:stretch;gap:8px}
.card .x{top:8px;left:auto;right:8px}
.shot{display:block;aspect-ratio:16/10;border-radius:11px;overflow:hidden;background:var(--tile);
      box-shadow:0 1px 3px rgba(0,0,0,.22),0 6px 16px rgba(0,0,0,.16);transition:transform .12s}
.card:hover .shot{transform:scale(1.025)}
.thumb{display:block;width:100%;height:100%;object-fit:cover;object-position:top}
.nothumb{display:grid;place-items:center;width:100%;height:100%}
.nothumb img{width:44px;height:44px}
.host{font-size:11px;text-shadow:var(--shadow)}
@media (max-width:640px){.cards{grid-template-columns:1fr 1fr}}

#gear{position:fixed;right:18px;bottom:16px;width:36px;height:36px;border-radius:50%;border:0;
      background:var(--tile);color:var(--ink);display:grid;place-items:center;cursor:pointer;
      box-shadow:0 1px 3px rgba(0,0,0,.25),0 4px 12px rgba(0,0,0,.18);opacity:.85}
#gear:hover{opacity:1}
#panel{position:fixed;right:18px;bottom:62px;width:310px;max-height:calc(100vh - 90px);overflow:auto;
       background:var(--tile);color:var(--ink);-webkit-backdrop-filter:blur(18px);backdrop-filter:blur(18px);
       border-radius:14px;padding:16px;font-size:13px;box-shadow:0 10px 40px rgba(0,0,0,.35)}
#panel[hidden]{display:none}
#panel h3{font-size:15px;margin-bottom:6px}
#panel h4{font-size:11px;text-transform:uppercase;letter-spacing:.06em;opacity:.6;margin:16px 0 8px}
.row{display:flex;justify-content:space-between;align-items:center;padding:7px 0;color:var(--ink);text-decoration:none}
.switch{width:38px;height:22px;border-radius:11px;background:#9a9aa0;position:relative;transition:background .15s}
.switch::after{content:"";position:absolute;top:2px;left:2px;width:18px;height:18px;border-radius:50%;
               background:#fff;transition:transform .15s}
.switch.on{background:#34c759}
.switch.on::after{transform:translateX(16px)}
.swatches{display:flex;flex-wrap:wrap;gap:10px}
.sw{display:block;width:28px;height:28px;border-radius:50%;box-shadow:inset 0 0 0 1px rgba(0,0,0,.25)}
.sw.def{background:linear-gradient(135deg,#f2a26b 0 25%,#c4c1bc 25% 50%,#dca843 50% 75%,#8fb2cc 75%)}
.sw.sel,.btn.sel{outline:2px solid #0a84ff;outline-offset:2px}
.btn{display:inline-block;margin:8px 8px 0 0;padding:6px 11px;border-radius:8px;
     background:rgba(128,128,128,.22);color:var(--ink);text-decoration:none}
.btn:hover{background:rgba(128,128,128,.34)}
.btn.danger{color:#d93a3a}
@@BGCSS@@
</style></head>
<body><div class="bg"></div>
<main>
  @@FAVS@@
  @@FREQ@@
</main>
@@PANEL@@
<script>
const panel = document.getElementById('panel'), gear = document.getElementById('gear');
function setOpen(o){ panel.hidden = !o; try{ sessionStorage.setItem('panel', o ? '1' : '0'); }catch(e){} }
gear.addEventListener('click', e => { e.stopPropagation(); setOpen(panel.hidden); });
document.addEventListener('click', e => { if(!panel.hidden && !panel.contains(e.target)) setOpen(false); });
try{ if(sessionStorage.getItem('panel') === '1') setOpen(true); }catch(e){}
</script>
</body></html>
"""

GEAR_SVG = (
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round"><path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/>'
    '<circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/></svg>'
)


def build_start_html():
    esc = lambda s: html.escape(str(s), quote=True)
    st = load_settings()

    favs = _read_json(FAV_FILE, None)
    if not isinstance(favs, list):          # [] es válido: el usuario quitó todos
        favs = list(DEFAULT_FAVORITES)
        _write_json(FAV_FILE, favs)

    tiles = []
    for f in favs:
        url = f.get("url", "")
        host = QUrl(url).host()
        name = f.get("name") or host
        remove = "navegador://remove-fav?url=" + quote(url, safe="")
        tiles.append(
            '<div class="tile">'
            f'<a class="open" href="{esc(url)}">'
            f'<span class="icon"><b>{esc(name[:1].upper())}</b>'
            f'<img src="{favicon(host)}" alt="" '
            f"onerror=\"this.parentNode.classList.add('noimg');this.remove()\" "
            f'onload="if(this.naturalWidth<2)this.parentNode.classList.add(\'noimg\')">'
            f'</span><span class="label">{esc(name)}</span></a>'
            f'<a class="x" href="{esc(remove)}" title="Quitar de favoritos">×</a></div>'
        )

    hist = _read_json(HIST_FILE, {})
    top = sorted(hist.items(), key=lambda kv: kv[1].get("count", 0), reverse=True)[:3]
    cards = []
    for host, e in top:
        link = e.get("url") or f"https://{host}/"
        thumb = THUMBS_DIR / f"{host}.jpg"
        if thumb.exists():
            inner = f'<img class="thumb" src="{thumb.as_uri()}" alt="">'
        else:
            inner = (f'<span class="nothumb"><img src="{favicon(host)}" alt="" '
                     f'onerror="this.remove()"></span>')
        remove = "navegador://remove-freq?host=" + quote(host, safe="")
        cards.append(
            '<div class="card">'
            f'<a class="open" href="{esc(link)}">'
            f'<span class="shot">{inner}</span><span class="host">{esc(host)}</span></a>'
            f'<a class="x" href="{esc(remove)}" title="Quitar de la lista">×</a></div>'
        )

    favs_html = ""
    if st["show_favorites"]:
        favs_html = "<h2>Favoritos</h2>" + (
            '<div class="grid">' + "".join(tiles) + "</div>" if tiles else
            '<p class="empty">No hay favoritos. Pulsa Ctrl+D en un sitio para añadirlo.</p>'
        )
    freq_html = ""
    if st["show_frequent"] and cards:
        freq_html = '<h2>Visitados con frecuencia</h2><div class="cards">' + "".join(cards) + "</div>"

    # ---- panel de personalización
    def switch(key, on, label):
        href = f"navegador://toggle?key={key}&value={0 if on else 1}"
        return (f'<a class="row" href="{href}"><span>{label}</span>'
                f'<span class="switch{" on" if on else ""}"></span></a>')

    bg = st["background"]
    swatches = ['<a class="sw def' + (" sel" if bg["mode"] == "default" else "") +
                '" href="navegador://bg?mode=default" title="Predeterminado"></a>']
    for c in BG_COLORS:
        sel = " sel" if bg["mode"] == "color" and bg.get("color") == c else ""
        swatches.append(f'<a class="sw{sel}" style="background:{c}" title="{c}" '
                        f'href="navegador://bg?mode=color&value={quote(c, safe="")}"></a>')
    image_sel = " sel" if bg["mode"] == "image" else ""
    engines = "".join(
        f'<a class="btn{" sel" if n == st["engine"] else ""}" href="navegador://engine?name={quote(n)}">{n}</a>'
        for n in ENGINES
    )
    panel = (
        f'<button id="gear" title="Personalizar">{GEAR_SVG}</button>'
        '<div id="panel" hidden><h3>Personalizar</h3>'
        + switch("show_favorites", st["show_favorites"], "Favoritos")
        + switch("show_frequent", st["show_frequent"], "Visitados con frecuencia")
        + '<h4>Fondo</h4><div class="swatches">' + "".join(swatches) + "</div>"
        + f'<a class="btn{image_sel}" href="navegador://bg?mode=pick">Elegir imagen…</a>'
        + "<h4>Buscador</h4>" + engines
        + "<h4>Datos</h4>"
        + '<a class="btn" href="navegador://reset-fav">Restaurar favoritos</a>'
        + '<a class="btn danger" href="navegador://clear-freq">Borrar sitios frecuentes</a>'
        + "</div>"
    )

    page = START_TEMPLATE
    for key, value in (("@@BGCSS@@", background_css(bg)), ("@@FAVS@@", favs_html),
                       ("@@FREQ@@", freq_html), ("@@PANEL@@", panel)):
        page = page.replace(key, value)
    return page


# ---------------------------------------------------------------- historial
HISTORY = "about:history"                       # marcador interno: abre el historial
VISITS_FILE = CONFIG_DIR / "visitas.json"       # una entrada por página visitada
HISTORY_PAGE = CACHE_DIR / "historial.html"
MAX_VISITS = 5000                               # las más antiguas se van descartando
SHOWN_VISITS = 2000

DAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MONTHS_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
             "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

WINDOWS = []        # ventanas abiertas (evita que Python las recoja)


def record_visit(url, title):
    visits = _read_json(VISITS_FILE, [])
    if not isinstance(visits, list):
        visits = []
    now = time.time()
    if visits and visits[-1].get("url") == url and now - visits[-1].get("t", 0) < 30:
        visits[-1].update(t=now, title=title or visits[-1].get("title", ""))   # recarga: no duplicar
    else:
        new_id = int(now * 1000)
        if visits:
            new_id = max(new_id, int(visits[-1].get("id", 0)) + 1)
        visits.append({"id": new_id, "url": url, "title": title or url, "t": now})
    del visits[:-MAX_VISITS]
    _write_json(VISITS_FILE, visits)


def day_label(ts):
    d = datetime.date.fromtimestamp(ts)
    today = datetime.date.today()
    if d == today:
        return "Hoy"
    if d == today - datetime.timedelta(days=1):
        return "Ayer"
    label = f"{DAYS_ES[d.weekday()].capitalize()}, {d.day} de {MONTHS_ES[d.month - 1]}"
    return label if d.year == today.year else f"{label} de {d.year}"


HISTORY_TEMPLATE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Historial</title>
<style>
:root{ --bg:#f5f5f7; --ink:#1d1d1f; --mute:#6e6e73; --hover:rgba(0,0,0,.05); --line:rgba(0,0,0,.09);
       --field:#e8e8ed; --accent:#0a84ff; }
@media (prefers-color-scheme: dark){
  :root{ --bg:#1c1c1e; --ink:#f2f2f7; --mute:#98989f; --hover:rgba(255,255,255,.07);
         --line:rgba(255,255,255,.1); --field:#2c2c2e; }
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,"SF Pro Text","Inter",sans-serif;background:var(--bg);color:var(--ink)}
header{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);
       padding:18px 28px 14px}
.bar{max-width:860px;margin:0 auto;display:flex;align-items:center;gap:14px}
h1{font-size:22px;font-weight:700;flex:0 0 auto}
#q{flex:1;height:32px;border:0;border-radius:8px;background:var(--field);color:var(--ink);
   padding:0 12px;font-size:14px;outline:none}
#q:focus{box-shadow:0 0 0 2px var(--accent)}
.clear{flex:0 0 auto;color:#d93a3a;text-decoration:none;font-size:13px;padding:6px 10px;border-radius:8px}
.clear:hover{background:var(--hover)}
main{max-width:860px;margin:0 auto;padding:8px 28px 60px}
.day[hidden],.item[hidden]{display:none}
.day h3{font-size:13px;font-weight:700;color:var(--mute);margin:24px 0 6px;padding:0 10px}
ul{list-style:none}
.item{display:grid;grid-template-columns:44px 18px minmax(0,1fr) auto 22px;align-items:center;gap:10px;
      padding:7px 10px;border-radius:8px}
.item:hover{background:var(--hover)}
.time{font-size:12px;color:var(--mute);font-variant-numeric:tabular-nums}
.fav{width:16px;height:16px;border-radius:3px}
.title{color:var(--ink);text-decoration:none;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.title:hover{text-decoration:underline}
.host{font-size:12px;color:var(--mute);max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.del{width:20px;height:20px;border-radius:50%;text-align:center;line-height:20px;color:var(--mute);
     text-decoration:none;opacity:0}
.item:hover .del{opacity:1}
.del:hover{background:#d93a3a;color:#fff}
.empty{margin-top:60px;text-align:center;color:var(--mute)}
</style></head>
<body>
<header><div class="bar">
  <h1>Historial</h1>
  <input id="q" type="search" placeholder="Buscar en el historial" autofocus>
  <a class="clear" href="navegador://clear-history" onclick="return confirm('¿Borrar todo el historial?')">Borrar historial</a>
</div></header>
<main>@@BODY@@</main>
<script>
const q = document.getElementById('q');
q.addEventListener('input', () => {
  const t = q.value.trim().toLowerCase();
  document.querySelectorAll('.day').forEach(day => {
    let any = false;
    day.querySelectorAll('.item').forEach(li => {
      const ok = !t || li.dataset.q.includes(t);
      li.hidden = !ok;
      if (ok) any = true;
    });
    day.hidden = !any;
  });
});
</script>
</body></html>
"""


def build_history_html():
    esc = lambda s: html.escape(str(s), quote=True)
    visits = _read_json(VISITS_FILE, [])
    if not isinstance(visits, list):
        visits = []
    visits = visits[-SHOWN_VISITS:][::-1]          # las más recientes primero

    groups, last = [], None
    for v in visits:
        ts = v.get("t", 0)
        label = day_label(ts)
        if label != last:
            groups.append((label, []))
            last = label
        url = v.get("url", "")
        host = QUrl(url).host()
        title = v.get("title") or url
        hhmm = datetime.datetime.fromtimestamp(ts).strftime("%H:%M")
        vid = int(v.get("id", 0))
        groups[-1][1].append(
            f'<li class="item" data-q="{esc((title + " " + url).lower())}">'
            f'<span class="time">{hhmm}</span>'
            f'<img class="fav" loading="lazy" src="{favicon(host)}" alt="" '
            f"onerror=\"this.style.visibility='hidden'\">"
            f'<a class="title" href="{esc(url)}">{esc(title)}</a>'
            f'<span class="host">{esc(host)}</span>'
            f'<a class="del" href="navegador://remove-visit?id={vid}" title="Quitar del historial">×</a></li>'
        )

    if groups:
        body = "".join(
            f'<section class="day"><h3>{esc(label)}</h3><ul>{"".join(rows)}</ul></section>'
            for label, rows in groups
        )
    else:
        body = '<p class="empty">Todavía no hay historial.</p>'
    return HISTORY_TEMPLATE.replace("@@BODY@@", body)


def global_menu_available():
    """¿Hay un widget de 'Menú global' (registro com.canonical.AppMenu) en esta sesión?"""
    try:
        from PySide6.QtDBus import QDBusConnection
        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            return False
        reply = bus.interface().isServiceRegistered("com.canonical.AppMenu.Registrar")
        return bool(reply.value() if hasattr(reply, "value") else reply)
    except Exception:
        return False


RADIUS = 10
BOTTOM_INSET = RADIUS   # franja bajo la página para poder redondear las esquinas de abajo
                        # (0 = página hasta el borde, pero con esquinas inferiores cuadradas)
MARGIN = 6          # borde invisible para poder redimensionar
SIDE_WIDTH = 190    # ancho de los grupos izquierdo/derecho (mantiene la URL centrada)

# Semáforos (proporciones de Safari). Ajusta estos valores a tu gusto.
LIGHT_SIZE = 12     # diámetro de cada círculo
LIGHT_GAP = 8       # espacio entre círculos
LIGHT_LEFT = 20     # distancia desde el borde izquierdo de la ventana al primer círculo
GROUP_HOVER = False  # False = solo el botón bajo el ratón muestra su símbolo (como KWin)
                     # True  = los tres a la vez al pasar sobre uno (como macOS)


# ---------------------------------------------------------------- tema de los botones
class WindowTheme:
    """Botones de ventana tomados del tema de decoración Aurorae activo en KDE.

    Lee ~/.config/kwinrc, localiza la carpeta del tema y carga sus
    close / minimize / maximize / restore (.svg o .svgz), con el tamaño y la
    separación que define su archivo <tema>rc. Si algo falla (tema de otro tipo,
    falta QtSvg...) available queda en False y se dibujan círculos de colores.
    """

    def __init__(self):
        self.available = False
        self.w = self.h = LIGHT_SIZE
        self.gap = LIGHT_GAP
        self.renderers = {}
        try:
            self._load()
        except Exception as exc:   # nunca debe impedir que el navegador abra
            print(f"[navegador] botones de ventana por defecto: {exc}", file=sys.stderr)
            self.available = False
            self.renderers = {}
            self.w = self.h = LIGHT_SIZE
            self.gap = LIGHT_GAP

    @staticmethod
    def _ini(path):
        cp = configparser.RawConfigParser(strict=False, delimiters=("=",), allow_no_value=True)
        cp.optionxform = str
        cp.read(path, encoding="utf-8")
        return cp

    @staticmethod
    def _roots():
        data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
        data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
        bases = [data_home] + [Path(d) for d in data_dirs.split(":") if d]
        return [b / "aurorae" / "themes" for b in bases]

    @classmethod
    def _find_folder(cls, name):
        roots = cls._roots()
        for root in roots:
            if (root / name).is_dir():
                return root / name
        # por si renombraste la carpeta pero el nombre interno del tema es otro
        for root in roots:
            if not root.is_dir():
                continue
            for sub in root.iterdir():
                for meta in ("metadata.desktop", "metadata.json"):
                    f = sub / meta
                    if f.is_file():
                        txt = f.read_text(encoding="utf-8", errors="ignore")
                        if f"X-KDE-PluginInfo-Name={name}" in txt or f'"Id": "{name}"' in txt:
                            return sub
        return None

    def _load(self):
        if QSvgRenderer is None:
            raise RuntimeError("falta QtSvg (instala qt6-svg)")
        cfg_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        kwin = self._ini(cfg_home / "kwinrc")
        theme = kwin.get("org.kde.kdecoration2", "theme", fallback="") or ""
        prefix = "__aurorae__svg__"
        if not theme.startswith(prefix):
            raise RuntimeError(f"el tema de ventanas activo ({theme or 'ninguno'}) no es Aurorae SVG")
        name = theme[len(prefix):]
        folder = self._find_folder(name)
        if folder is None:
            raise RuntimeError(f"no encuentro la carpeta del tema '{name}'")

        # medidas del tema
        w, h, gap = LIGHT_SIZE, LIGHT_SIZE, LIGHT_GAP
        for rc_file in [folder / f"{folder.name}rc"] + sorted(folder.glob("*rc")):
            if rc_file.is_file():
                rc = self._ini(rc_file)
                if rc.has_section("Layout"):
                    w = rc.getint("Layout", "ButtonWidth", fallback=w)
                    h = rc.getint("Layout", "ButtonHeight", fallback=h)
                    gap = rc.getint("Layout", "ButtonSpacing", fallback=gap)
                    break

        # imágenes de los botones
        for key in ("close", "minimize", "maximize", "restore"):
            for ext in ("svg", "svgz"):
                f = folder / f"{key}.{ext}"
                if f.is_file():
                    r = QSvgRenderer(str(f))
                    if r.isValid():
                        self.renderers[key] = r
                    break
        if not all(k in self.renderers for k in ("close", "minimize", "maximize")):
            raise RuntimeError(f"al tema '{name}' le faltan los SVG de los botones")

        self.w, self.h, self.gap = max(w, 8), max(h, 8), max(gap, 0)
        self.available = True

    def paint(self, p, key, state, rect):
        """state: active, inactive, hover, hover-inactive, pressed, pressed-inactive"""
        r = self.renderers.get(key) or self.renderers["maximize"]
        for element in (f"{state}-center", "active-center"):
            if r.elementExists(element):
                r.render(p, element, rect)
                return
        r.render(p, rect)


# ---------------------------------------------------------------- semáforos
class Light(QAbstractButton):
    def __init__(self, key, color, symbol, theme, parent=None):
        super().__init__(parent)
        self.key = key              # "close" | "minimize" | "maximize"
        self.color = QColor(color)
        self.symbol = symbol
        self.theme = theme
        self.group_hover = False
        self.self_hover = False
        self.setFixedSize(theme.w, theme.h)
        self.setCursor(Qt.ArrowCursor)

    def enterEvent(self, e):
        self.self_hover = True
        self.update()

    def leaveEvent(self, e):
        self.self_hover = False
        self.update()

    def hovered(self):
        return self.group_hover if GROUP_HOVER else self.self_hover

    def state(self):
        base = "pressed" if self.isDown() else ("hover" if self.hovered() else "active")
        if self.window().isActiveWindow():
            return base
        return "inactive" if base == "active" else base + "-inactive"

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        if self.theme.available:
            key = self.key
            if key == "maximize" and self.window().isMaximized():
                key = "restore"
            self.theme.paint(p, key, self.state(), QRectF(self.rect()))
            return
        # respaldo: círculos dibujados a mano
        hov = self.hovered()
        active = self.window().isActiveWindow() or hov
        fill = self.color if active else QColor(128, 128, 128, 110)
        p.setPen(fill.darker(125))
        p.setBrush(fill)
        p.drawEllipse(self.rect().adjusted(0, 0, -1, -1))
        if hov:
            p.setPen(QColor(0, 0, 0, 160))
            f = QFont(self.font())
            f.setBold(True)
            f.setPixelSize(max(self.theme.h - 3, 8))
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter, self.symbol)


class Lights(QWidget):
    def __init__(self, win):
        super().__init__()
        th = win.theme
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(th.gap)
        self.setFixedSize(th.w * 3 + th.gap * 2, th.h)
        close = Light("close", "#ff5f57", "×", th)
        mini = Light("minimize", "#febc2e", "−", th)
        maxi = Light("maximize", "#28c840", "+", th)
        close.clicked.connect(win.close)
        mini.clicked.connect(win.showMinimized)
        maxi.clicked.connect(win.toggle_max)
        for b in (close, mini, maxi):
            lay.addWidget(b)
        self.buttons = (close, mini, maxi)

    def _set(self, v):
        for b in self.buttons:
            b.group_hover = v
            b.update()

    def enterEvent(self, e):
        self._set(True)

    def leaveEvent(self, e):
        self._set(False)


# ---------------------------------------------------------------- barra superior
class TitleBar(QWidget):
    """Arrastrable: mover la ventana pulsando en cualquier zona vacía."""

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.window().windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.window().toggle_max()


def tool_button(icon_name, fallback, tip):
    b = QToolButton()
    b.setIcon(QIcon.fromTheme(icon_name))
    if b.icon().isNull():
        b.setText(fallback)
    b.setToolTip(tip)
    b.setAutoRaise(True)
    b.setCursor(Qt.ArrowCursor)
    return b


# ---------------------------------------------------------------- vista web
class Page(QWebEnginePage):
    """Página web que además atiende las órdenes navegador://... de la pantalla de inicio."""

    def __init__(self, browser, parent=None):
        super().__init__(parent)
        self.browser = browser

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if url.scheme() == "navegador":
            # solo las páginas internas (inicio e historial) pueden dar órdenes; cualquier otra web se ignora
            if is_main_frame and self.browser.is_internal(self.url()):
                self.browser.handle_action(url)
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)


class View(QWebEngineView):
    def __init__(self, browser):
        super().__init__()
        self.browser = browser
        self.setPage(Page(browser, self))
        # la página de inicio es un archivo local que carga iconos de internet
        self.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )

    def createWindow(self, _type):  # target=_blank / window.open
        return self.browser.new_tab(None)


# ---------------------------------------------------------------- ventana
class Browser(QWidget):
    def __init__(self, start_url=HOME):
        super().__init__()
        self.setWindowTitle("Navegador")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.resize(1200, 780)
        self.theme = WindowTheme()      # botones del tema de ventanas de KDE

        outer = QVBoxLayout(self)
        outer.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        self.outer = outer

        self.root = QFrame()
        self.root.setObjectName("root")
        # los hijos no deben heredar el cursor de redimensionar del borde
        self.root.setCursor(Qt.ArrowCursor)
        self.root.setStyleSheet(
            f"#root {{ background: palette(window); border-radius: {RADIUS}px; }}"
        )
        outer.addWidget(self.root)
        col = QVBoxLayout(self.root)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self.col = col

        # --- barra unificada: semáforos + controles + URL
        bar = TitleBar()
        bar.setFixedHeight(46)
        row = QHBoxLayout(bar)
        row.setContentsMargins(LIGHT_LEFT - MARGIN, 0, 14, 0)

        left = QWidget()
        left.setFixedWidth(SIDE_WIDTH)
        ll = QHBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(4)
        ll.addWidget(Lights(self), 0, Qt.AlignLeft | Qt.AlignVCenter)
        ll.addSpacing(16)
        self.btn_side = tool_button("view-sidebar", "☰", "Barra lateral")
        self.btn_back = tool_button("go-previous", "‹", "Atrás")
        self.btn_fwd = tool_button("go-next", "›", "Adelante")
        for b in (self.btn_side, self.btn_back, self.btn_fwd):
            ll.addWidget(b)
        ll.addStretch()

        self.url = QLineEdit()
        self.url.setPlaceholderText("Search or enter website name")
        self.url.setAlignment(Qt.AlignCenter)
        self.url.setClearButtonEnabled(True)
        self.url.setMaximumWidth(560)
        self.url.setFixedHeight(28)
        self.url.setStyleSheet(
            "QLineEdit { border: none; border-radius: 7px; padding: 0 10px;"
            " background: palette(base); }"
        )

        right = QWidget()
        right.setFixedWidth(SIDE_WIDTH)
        rl = QHBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)
        rl.addStretch()
        self.btn_reload = tool_button("view-refresh", "⟳", "Recargar")
        self.btn_new = tool_button("tab-new", "+", "Nueva pestaña")
        self.btn_menu = tool_button("application-menu", "⋯", "Menú")   # solo si no hay menú global
        self.btn_menu.setStyleSheet("QToolButton::menu-indicator{image:none}")
        rl.addWidget(self.btn_reload)
        rl.addWidget(self.btn_new)
        rl.addWidget(self.btn_menu)

        # Los "stretch" absorben el espacio sobrante: así los semáforos quedan
        # pegados a la esquina y la URL centrada, sea cual sea el ancho.
        row.addWidget(left)
        row.addStretch(1)
        row.addWidget(self.url, 100)
        row.addStretch(1)
        row.addWidget(right)
        col.addWidget(bar)

        # --- cuerpo: barra lateral + pestañas
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.side = QListWidget()
        self.side.setFixedWidth(200)
        self.side.setFrameShape(QFrame.NoFrame)
        self.side.hide()
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setTabBarAutoHide(True)   # como Safari: solo con 2+ pestañas
        self.tabs.tabBar().setExpanding(True)
        body.addWidget(self.side)
        body.addWidget(self.tabs, 1)
        col.addLayout(body, 1)

        # --- conexiones
        self.url.returnPressed.connect(self.go)
        self.btn_back.clicked.connect(lambda: self.view().back())
        self.btn_fwd.clicked.connect(lambda: self.view().forward())
        self.btn_reload.clicked.connect(self.reload)
        self.btn_new.clicked.connect(lambda: self.new_tab(HOME, focus_url=True))
        self.btn_side.clicked.connect(lambda: self.side.setVisible(not self.side.isVisible()))
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.side.currentRowChanged.connect(
            lambda i: self.tabs.setCurrentIndex(i) if i >= 0 else None
        )

        # --- acciones, atajos y menús
        self.make_actions()
        if global_menu_available():
            # Barra de menús real de Qt: Plasma la muestra en el widget "Menú global"
            self.menubar = QMenuBar(self)
            self.build_menus(self.menubar)
            self.menubar.hide()          # no ocupa sitio en la ventana
            self.btn_menu.hide()
        else:
            # Sin menú global: los mismos menús, en un botón de la barra
            menu = QMenu(self)
            self.build_menus(menu)
            self.btn_menu.setMenu(menu)
            self.btn_menu.setPopupMode(QToolButton.InstantPopup)

        self.new_tab(start_url)

    # ------------------------------------------------ pestañas
    def view(self):
        return self.tabs.currentWidget()

    def new_tab(self, url=HOME, focus_url=False):
        v = View(self)
        i = self.tabs.addTab(v, "Nueva pestaña")
        v.titleChanged.connect(lambda t, v=v: self.set_title(v, t))
        v.urlChanged.connect(lambda u, v=v: self.on_url(v, u))
        v.loadFinished.connect(self.update_nav)
        v.loadFinished.connect(lambda ok, v=v: self.on_loaded(v, ok))
        if url == HOME:
            self.show_home(v)
        elif url == HISTORY:
            self.show_history(v)
        elif url:
            v.setUrl(QUrl(url))
        self.tabs.setCurrentIndex(i)
        self.refresh_side()
        if focus_url:
            self.url.setFocus()
            self.url.selectAll()
        return v

    def close_tab(self, i):
        if self.tabs.count() <= 1:
            self.close()
            return
        w = self.tabs.widget(i)
        self.tabs.removeTab(i)
        w.deleteLater()
        self.refresh_side()

    def set_title(self, v, title):
        i = self.tabs.indexOf(v)
        if i >= 0:
            self.tabs.setTabText(i, (title or "Sin título")[:28])
            self.refresh_side()
        if v is self.view():
            self.setWindowTitle(title or "Navegador")

    def refresh_side(self):
        self.side.blockSignals(True)
        self.side.clear()
        for i in range(self.tabs.count()):
            self.side.addItem(self.tabs.tabText(i))
        self.side.setCurrentRow(self.tabs.currentIndex())
        self.side.blockSignals(False)

    # ------------------------------------------------ navegación
    def go(self):
        text = self.url.text().strip()
        if not text:
            return
        if "://" in text:
            target = text
        elif "." in text and " " not in text:
            target = "https://" + text
        else:
            target = ENGINES[load_settings()["engine"]] + quote_plus(text)
        self.view().setUrl(QUrl(target))
        self.view().setFocus()

    def on_url(self, v, u):
        if v is self.view():
            self.set_url_text(u)
        self.update_nav()

    def on_tab_changed(self, _i):
        v = self.view()
        if v:
            self.set_url_text(v.url())
            self.setWindowTitle(v.title() or "Navegador")
        self.update_nav()
        self.refresh_side()

    def update_nav(self, *_):
        v = self.view()
        if not v:
            return
        h = v.history()
        self.btn_back.setEnabled(h.canGoBack())
        self.btn_fwd.setEnabled(h.canGoForward())

    # ------------------------------------------------ inicio, historial, favoritos
    def is_start(self, u):
        return u.isLocalFile() and u.toLocalFile() == str(START_FILE)

    def is_history(self, u):
        return u.isLocalFile() and u.toLocalFile() == str(HISTORY_PAGE)

    def is_internal(self, u):
        return self.is_start(u) or self.is_history(u)

    def set_url_text(self, u):
        if self.is_start(u):
            text = ""
        elif self.is_history(u):
            text = "about:historial"
        else:
            text = u.toString()
        self.url.setText(text)
        self.url.setCursorPosition(0)

    def write_home(self):
        START_FILE.parent.mkdir(parents=True, exist_ok=True)
        START_FILE.write_text(build_start_html(), encoding="utf-8")

    def show_home(self, v):
        self.write_home()
        v.setUrl(QUrl.fromLocalFile(str(START_FILE)))

    def write_history(self):
        HISTORY_PAGE.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_PAGE.write_text(build_history_html(), encoding="utf-8")

    def show_history(self, v):
        self.write_history()
        v.setUrl(QUrl.fromLocalFile(str(HISTORY_PAGE)))

    def regenerate(self, u):
        """Vuelve a generar la página interna que se está viendo (inicio o historial)."""
        if self.is_start(u):
            self.write_home()
        elif self.is_history(u):
            self.write_history()

    def reload(self, *_):
        v = self.view()
        if v is None:
            return
        self.regenerate(v.url())   # refresca favoritos, frecuentes e historial
        v.reload()

    def on_loaded(self, v, ok):
        u = v.url()
        if not ok or self.is_internal(u) or u.scheme() not in ("http", "https") or not u.host():
            return
        record_visit(u.toString(), v.title())
        hist = _read_json(HIST_FILE, {})
        e = hist.get(u.host(), {})
        e.update(count=e.get("count", 0) + 1, url=f"{u.scheme()}://{u.host()}/", title=v.title())
        hist[u.host()] = e
        _write_json(HIST_FILE, hist)
        host = u.host()
        QTimer.singleShot(1500, lambda: self.snap(v, host))

    def snap(self, v, host):
        """Guarda una miniatura de la página para 'Visitados con frecuencia'."""
        try:
            if v.url().host() != host or not v.isVisible():
                return
            f = THUMBS_DIR / f"{host}.jpg"
            if f.exists() and time.time() - f.stat().st_mtime < 86400:
                return
            pix = v.grab()
            if pix.isNull():
                return
            pix = pix.scaled(480, 300, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            pix = pix.copy((pix.width() - 480) // 2, 0, 480, 300)
            THUMBS_DIR.mkdir(parents=True, exist_ok=True)
            pix.save(str(f), "JPG", 75)
        except (RuntimeError, OSError):
            pass

    def add_favorite(self, *_):
        """Ctrl+D: añade el sitio actual a los favoritos."""
        u = self.view().url()
        if self.is_internal(u) or not u.host():
            return
        favs = _read_json(FAV_FILE, None)
        if not isinstance(favs, list):
            favs = list(DEFAULT_FAVORITES)
        if any(QUrl(f.get("url", "")).host() == u.host() for f in favs):
            return
        name = u.host().removeprefix("www.").split(".")[0].capitalize()
        favs.append({"name": name, "url": f"{u.scheme()}://{u.host()}/"})
        _write_json(FAV_FILE, favs)

    # ------------------------------------------------ personalizar la pantalla de inicio
    def handle_action(self, url):
        """Órdenes del panel de la pantalla de inicio (enlaces navegador://acción?datos)."""
        parts = urlparse(url.toString(QUrl.FullyEncoded))
        action = parts.netloc
        q = {k: v[0] for k, v in parse_qs(parts.query).items()}
        st = load_settings()

        if action == "remove-fav":
            favs = _read_json(FAV_FILE, None)
            if not isinstance(favs, list):
                favs = list(DEFAULT_FAVORITES)
            _write_json(FAV_FILE, [f for f in favs if f.get("url") != q.get("url")])
        elif action == "reset-fav":
            _write_json(FAV_FILE, DEFAULT_FAVORITES)
        elif action == "remove-freq":
            hist = _read_json(HIST_FILE, {})
            host = q.get("host", "")
            if host in hist:            # solo claves que ya existen en el historial
                hist.pop(host)
                _write_json(HIST_FILE, hist)
                try:
                    (THUMBS_DIR / f"{host}.jpg").unlink(missing_ok=True)
                except OSError:
                    pass
        elif action == "clear-freq":
            _write_json(HIST_FILE, {})
            shutil.rmtree(THUMBS_DIR, ignore_errors=True)
        elif action == "toggle":
            if q.get("key") in ("show_favorites", "show_frequent"):
                st[q["key"]] = q.get("value") == "1"
        elif action == "engine":
            if q.get("name") in ENGINES:
                st["engine"] = q["name"]
        elif action == "bg":
            mode = q.get("mode")
            if mode == "default":
                st["background"]["mode"] = "default"
            elif mode == "color" and _luminance(q.get("value")) is not None:
                st["background"].update(mode="color", color=q["value"])
            elif mode == "pick":
                QTimer.singleShot(0, self.pick_background)   # diálogo fuera de la navegación
                return
        elif action == "remove-visit":
            visits = _read_json(VISITS_FILE, [])
            if isinstance(visits, list):
                _write_json(VISITS_FILE, [x for x in visits if str(x.get("id")) != q.get("id")])
        elif action == "clear-history":
            self._wipe_history()
        else:
            return

        save_settings(st)
        QTimer.singleShot(0, self.refresh_home)

    def refresh_home(self):
        v = self.view()
        if v is not None and self.is_internal(v.url()):
            self.regenerate(v.url())
            v.reload()

    @staticmethod
    def _wipe_history():
        _write_json(VISITS_FILE, [])
        _write_json(HIST_FILE, {})          # los "visitados con frecuencia" salen del historial
        shutil.rmtree(THUMBS_DIR, ignore_errors=True)

    def open_history(self):
        for i in range(self.tabs.count()):          # si ya está abierto, ir a esa pestaña
            if self.is_history(self.tabs.widget(i).url()):
                self.tabs.setCurrentIndex(i)
                self.reload()
                return
        self.new_tab(HISTORY)

    def clear_history(self):
        yes = QMessageBox.StandardButton.Yes
        if QMessageBox.question(self, "Borrar historial",
                                "¿Borrar todo el historial y los sitios frecuentes?") != yes:
            return
        self._wipe_history()
        self.refresh_home()

    # ------------------------------------------------ menús (también el "Menú global" de KDE)
    def make_actions(self):
        """Todas las acciones se crean una vez y se reutilizan en los menús y en los atajos."""
        self.acts = {}
        self._dyn = {}      # acciones dinámicas de cada menú (historial reciente, favoritos)

        def add(name, text, slot, *keys):
            a = QAction(text, self)
            if keys:
                a.setShortcuts([QKeySequence(k) for k in keys])
            a.triggered.connect(lambda checked=False, f=slot: f())
            self.addAction(a)       # los atajos funcionan aunque los menús no estén a la vista
            self.acts[name] = a

        def page(action):
            return lambda: self.view().triggerPageAction(getattr(QWebEnginePage.WebAction, action))

        add("new_tab", "Nueva pestaña", lambda: self.new_tab(HOME, focus_url=True), "Ctrl+T")
        add("new_window", "Nueva ventana", self.new_window, "Ctrl+N")
        add("open_loc", "Abrir ubicación…", self.focus_url, "Ctrl+L")
        add("close_tab", "Cerrar pestaña", lambda: self.close_tab(self.tabs.currentIndex()), "Ctrl+W")
        add("close_window", "Cerrar ventana", self.close, "Ctrl+Shift+W")
        add("quit", "Salir", QApplication.quit, "Ctrl+Q")

        # (sin atajo propio: la página ya atiende Ctrl+C, Ctrl+V... y no queremos pelearnos con ella)
        add("undo", "Deshacer", page("Undo"))
        add("redo", "Rehacer", page("Redo"))
        add("cut", "Cortar", page("Cut"))
        add("copy", "Copiar", page("Copy"))
        add("paste", "Pegar", page("Paste"))
        add("select_all", "Seleccionar todo", page("SelectAll"))

        add("reload", "Recargar página", self.reload, "Ctrl+R", "F5")
        add("stop", "Detener", lambda: self.view().stop(), "Ctrl+.")
        add("zoom_in", "Acercar", lambda: self.zoom(0.1), "Ctrl++", "Ctrl+=")
        add("zoom_out", "Alejar", lambda: self.zoom(-0.1), "Ctrl+-")
        add("zoom_reset", "Tamaño real", lambda: self.zoom(None), "Ctrl+0")
        add("sidebar", "Mostrar u ocultar la barra lateral", self.toggle_side, "Ctrl+Shift+L")
        add("fullscreen", "Pantalla completa", self.toggle_fullscreen, "F11")

        add("back", "Atrás", lambda: self.view().back(), "Alt+Left")
        add("forward", "Adelante", lambda: self.view().forward(), "Alt+Right")
        add("home", "Página de inicio", lambda: self.show_home(self.view()), "Ctrl+Shift+H")
        add("history", "Mostrar todo el historial", self.open_history, "Ctrl+H")
        add("clear_history", "Borrar historial…", self.clear_history)
        add("add_fav", "Añadir a favoritos", self.add_favorite, "Ctrl+D")

        add("minimize", "Minimizar", self.showMinimized, "Ctrl+M")
        add("maximize", "Maximizar o restaurar", self.toggle_max)
        add("about", "Acerca de Navegador", self.about)

    def build_menus(self, bar):
        """Crea los menús en 'bar' (una QMenuBar para el menú global, o un QMenu)."""
        a = self.acts

        def fill(menu, *names):
            for n in names:
                menu.addSeparator() if n is None else menu.addAction(a[n])

        m = bar.addMenu("&Archivo")
        fill(m, "new_tab", "new_window", "open_loc", None, "close_tab", "close_window", None, "quit")
        m = bar.addMenu("&Edición")
        fill(m, "undo", "redo", None, "cut", "copy", "paste", "select_all")
        m = bar.addMenu("&Ver")
        fill(m, "reload", "stop", None, "zoom_in", "zoom_out", "zoom_reset", None, "sidebar", "fullscreen")
        m = bar.addMenu("&Historial")
        fill(m, "back", "forward", "home", None, "history", "clear_history", None)
        m.aboutToShow.connect(lambda m=m: self.fill_dynamic(m, self.recent_pages()))
        m = bar.addMenu("&Favoritos")
        fill(m, "add_fav", None)
        m.aboutToShow.connect(lambda m=m: self.fill_dynamic(m, self.favorite_items()))
        m = bar.addMenu("Ven&tana")
        fill(m, "minimize", "maximize")
        m = bar.addMenu("A&yuda")
        fill(m, "about")

    def fill_dynamic(self, menu, items):
        """Rellena al abrirse el final de un menú con una lista de (texto, url)."""
        for old in self._dyn.pop(id(menu), []):
            menu.removeAction(old)
            old.deleteLater()
        new = []
        for text, url in items:
            label = (text[:48] + "…" if len(text) > 48 else text).replace("&", "&&")
            ac = QAction(label, menu)
            ac.triggered.connect(lambda checked=False, u=url: self.open_url(u))
            menu.addAction(ac)
            new.append(ac)
        self._dyn[id(menu)] = new

    @staticmethod
    def recent_pages(limit=12):
        visits = _read_json(VISITS_FILE, [])
        seen, items = set(), []
        for v in reversed(visits if isinstance(visits, list) else []):
            url = v.get("url", "")
            if not url or url in seen:
                continue
            seen.add(url)
            items.append((v.get("title") or url, url))
            if len(items) >= limit:
                break
        return items

    @staticmethod
    def favorite_items():
        favs = _read_json(FAV_FILE, None)
        if not isinstance(favs, list):
            favs = DEFAULT_FAVORITES
        return [(f.get("name") or f.get("url", ""), f.get("url", "")) for f in favs if f.get("url")]

    def open_url(self, url):
        self.view().setUrl(QUrl(url))

    def focus_url(self):
        self.url.setFocus()
        self.url.selectAll()

    def toggle_side(self):
        self.side.setVisible(not self.side.isVisible())

    def toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def zoom(self, delta):
        v = self.view()
        if v is None:
            return
        v.setZoomFactor(1.0 if delta is None else max(0.25, min(5.0, round(v.zoomFactor() + delta, 2))))

    def new_window(self):
        w = Browser(HOME)
        WINDOWS.append(w)
        w.show()

    def about(self):
        QMessageBox.about(
            self, "Acerca de Navegador",
            "Navegador con aspecto de Safari.\nHecho con Python, PySide6 y QtWebEngine.",
        )

    def pick_background(self):
        start = Path.home() / "Imágenes"
        path, _ = QFileDialog.getOpenFileName(
            self, "Elegir imagen de fondo",
            str(start if start.is_dir() else Path.home()),
            "Imágenes (*.png *.jpg *.jpeg *.webp *.bmp *.gif)",
        )
        if not path:
            return
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            for old in CONFIG_DIR.glob("fondo-*"):      # no acumular copias viejas
                old.unlink(missing_ok=True)
            dst = CONFIG_DIR / f"fondo-{int(time.time())}{Path(path).suffix.lower()}"
            shutil.copyfile(path, dst)                  # copia propia: sobrevive si borras el original
        except OSError:
            return
        st = load_settings()
        st["background"].update(mode="image", image=str(dst))
        save_settings(st)
        self.refresh_home()

    # ------------------------------------------------ ventana sin marco
    def toggle_max(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def update_shape(self):
        if self.isMaximized() or self.isFullScreen():
            self.outer.setContentsMargins(0, 0, 0, 0)
            self.col.setContentsMargins(0, 0, 0, 0)
            self.root.clearMask()
            self.root.setStyleSheet("#root { background: palette(window); }")
        else:
            self.outer.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
            # La vista web es una superficie de GPU y Qt no la recorta con la máscara
            # redondeada, así que sus esquinas inferiores se quedaban cuadradas.
            # Dejamos libre una franja del alto del radio: esa franja sí se redondea.
            self.col.setContentsMargins(0, 0, 0, BOTTOM_INSET)
            self.root.setStyleSheet(
                f"#root {{ background: palette(window); border-radius: {RADIUS}px; }}"
            )
            w = self.width() - 2 * MARGIN
            h = self.height() - 2 * MARGIN
            path = QPainterPath()
            path.addRoundedRect(QRectF(0, 0, w, h), RADIUS, RADIUS)
            self.root.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.update_shape()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == e.Type.WindowStateChange:
            self.update_shape()
            for b in self.findChildren(Light):   # maximizar <-> restaurar
                b.update()
        elif e.type() == e.Type.ActivationChange:
            for b in self.findChildren(Light):
                b.update()

    def _edges(self, pos):
        edges = Qt.Edges()
        if pos.x() <= MARGIN:
            edges |= Qt.LeftEdge
        if pos.x() >= self.width() - MARGIN:
            edges |= Qt.RightEdge
        if pos.y() <= MARGIN:
            edges |= Qt.TopEdge
        if pos.y() >= self.height() - MARGIN:
            edges |= Qt.BottomEdge
        return edges

    def mouseMoveEvent(self, e):
        ed = self._edges(e.position().toPoint())
        if ed in (Qt.LeftEdge | Qt.TopEdge, Qt.RightEdge | Qt.BottomEdge):
            self.setCursor(Qt.SizeFDiagCursor)
        elif ed in (Qt.RightEdge | Qt.TopEdge, Qt.LeftEdge | Qt.BottomEdge):
            self.setCursor(Qt.SizeBDiagCursor)
        elif ed & (Qt.LeftEdge | Qt.RightEdge):
            self.setCursor(Qt.SizeHorCursor)
        elif ed & (Qt.TopEdge | Qt.BottomEdge):
            self.setCursor(Qt.SizeVerCursor)
        else:
            self.unsetCursor()

    def leaveEvent(self, e):
        # al pasar del borde a un widget hijo, quitar el cursor de redimensionar
        self.unsetCursor()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        ed = self._edges(e.position().toPoint())
        if e.button() == Qt.LeftButton and ed:
            self.windowHandle().startSystemResize(ed)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("navegador")
    app.setApplicationDisplayName("Navegador")
    app.setDesktopFileName("navegador")
    win = Browser(sys.argv[1] if len(sys.argv) > 1 else HOME)
    WINDOWS.append(win)
    win.show()
    sys.exit(app.exec())
