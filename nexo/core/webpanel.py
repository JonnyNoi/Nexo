"""Painel no telemóvel: uma página web servida na rede local com os sensores ao vivo e o jogo a correr.

Desligado por omissão (Definições → Painel no telemóvel). Quando ligado:
  • escuta na rede local (porta 8765 por omissão) — a página e os dados só respondem a quem tiver o código
    da ligação (`?k=…`, gerado ao acaso e mostrado no Nexo com um código QR); sem ele devolve 403;
  • só leitura: não há nenhuma ação que mude o PC;
  • a página não carrega nada da internet (HTML, CSS e JS próprios, tudo embutido).
A interface chama `update()` 1×/s com os valores; o servidor corre numa thread própria."""
from __future__ import annotations

import hmac
import json
import logging
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .util import APP_NAME, get_setting, set_setting

log = logging.getLogger("nexo.web")
TOKEN_LEN = 8


def token() -> str:
    t = str(get_setting("web_token") or "")
    if len(t) < 6:
        t = new_token()
    return t


def new_token() -> str:
    alphabet = "abcdefghijkmnpqrstuvwxyz23456789"      # sem letras/números parecidos (l/1, o/0)
    t = "".join(secrets.choice(alphabet) for _ in range(TOKEN_LEN))
    set_setting("web_token", t)
    return t


def lan_ip() -> str:
    """IP deste PC na rede local (não envia nada: um socket UDP «ligado» só escolhe a interface)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))        # endereço de documentação (TEST-NET-1)
        ip = s.getsockname()[0]
    except OSError:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


class _Handler(BaseHTTPRequestHandler):
    server_version = APP_NAME
    sys_version = ""

    def log_message(self, fmt, *args):     # sem registo de cada pedido
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                         "connect-src 'self'; img-src data:")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 — nome da API do http.server
        panel: Panel = self.server.panel      # type: ignore[attr-defined]
        u = urlparse(self.path)
        k = (parse_qs(u.query).get("k") or [""])[0]
        if not hmac.compare_digest(k.encode(), panel.token.encode()):
            from .i18n import tr
            self._send(403, tr("Código errado — abra a ligação mostrada no Nexo.").encode(),
                       "text/plain; charset=utf-8")
            return
        if u.path == "/":
            self._send(200, page_html().encode(), "text/html; charset=utf-8")
        elif u.path == "/api":
            self._send(200, json.dumps(panel.snapshot()).encode(), "application/json")
        else:
            self._send(404, b"", "text/plain")


class Panel:
    def __init__(self):
        self._data: dict = {}
        self._server: ThreadingHTTPServer | None = None
        self.token = ""
        self.port = 0
        self.error = ""

    @property
    def running(self) -> bool:
        return self._server is not None

    def update(self, data: dict) -> None:
        self._data = {**data, "t": time.time()}      # troca o dicionário inteiro (seguro entre threads)

    def snapshot(self) -> dict:
        return self._data

    def url(self) -> str:
        return f"http://{lan_ip()}:{self.port}/?k={self.token}"

    def start(self, port: int | None = None) -> tuple[bool, str]:
        self.stop()
        self.port = int(port or get_setting("web_port") or 8765)
        self.token = token()
        try:
            srv = ThreadingHTTPServer(("0.0.0.0", self.port), _Handler)
        except OSError as e:
            self.error = f"Não foi possível usar a porta {self.port}: {e.strerror or e}"
            return False, self.error
        srv.daemon_threads = True
        srv.panel = self                                   # type: ignore[attr-defined]
        self._server = srv
        threading.Thread(target=srv.serve_forever, daemon=True, name="webpanel").start()
        self.error = ""
        return True, self.url()

    def stop(self) -> None:
        srv, self._server = self._server, None
        if srv is not None:
            threading.Thread(target=lambda: (srv.shutdown(), srv.server_close()), daemon=True).start()


_PAGE_EN = {'lang="pt"': 'lang="en"', ">A ligar…<": ">Connecting…<", ">A jogar<": ">Playing<",
            ">Consumo<": ">Power<", ">Placa gráfica<": ">Graphics card<",
            ">Temperaturas (últimos 2 min)<": ">Temperatures (last 2 min)<", "'Ao vivo · '": "'Live · '",
            "'Sem dados novos há '": "'No new data for '", "' ms por fotograma'": "' ms per frame'",
            "'carga '": "'load '", "'Sem ligação ao Nexo'": "'No connection to Nexo'"}


def page_html() -> str:
    from .i18n import lang
    if lang() != "en":
        return PAGE
    out = PAGE
    for a, b in _PAGE_EN.items():
        out = out.replace(a, b)
    return out


_panel: Panel | None = None


def panel() -> Panel:
    global _panel
    if _panel is None:
        _panel = Panel()
    return _panel


PAGE = r"""<!doctype html>
<html lang="pt"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0a0c11"><title>Nexo</title>
<style>
:root{--bg:#0a0c11;--card:#12151c;--line:#242a37;--text:#e9ecf3;--muted:#8a93a6;--acc:#7c8cff;--ok:#3ecf8e;
--warn:#f5b84a;--bad:#ff6b6b}
@media (prefers-color-scheme:light){:root{--bg:#f4f5fa;--card:#fff;--line:#e3e6ee;--text:#141824;--muted:#5d6577}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;padding:16px;padding-top:max(16px,env(safe-area-inset-top))}
h1{font-size:18px;margin:0 0 2px}.sub{color:var(--muted);font-size:13px;margin-bottom:14px}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 14px}
.lab{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.val{font-size:30px;font-weight:650;font-variant-numeric:tabular-nums}.small{color:var(--muted);font-size:13px}
.wide{grid-column:1/-1}.game{font-size:20px;font-weight:600}
canvas{width:100%;height:90px;display:block;margin-top:6px}
.bar{height:6px;border-radius:3px;background:var(--line);margin-top:8px;overflow:hidden}
.bar>i{display:block;height:100%;background:var(--acc);width:0}
.off{color:var(--bad)}
</style></head><body>
<h1 id="host">Nexo</h1><div class="sub" id="status">A ligar…</div>
<div class="grid">
<div class="card wide" id="gamecard" style="display:none"><div class="lab">A jogar</div><div class="game" id="game"></div>
<div class="small" id="gamesub"></div></div>
<div class="card"><div class="lab">FPS</div><div class="val" id="fps">—</div><div class="small" id="ft"></div></div>
<div class="card"><div class="lab">Consumo</div><div class="val" id="pw">—</div><div class="small" id="pwsub"></div></div>
<div class="card"><div class="lab">CPU</div><div class="val" id="ct">—</div><div class="small" id="cl"></div>
<div class="bar"><i id="clb"></i></div></div>
<div class="card"><div class="lab">Placa gráfica</div><div class="val" id="gt">—</div><div class="small" id="gl"></div>
<div class="bar"><i id="glb"></i></div></div>
<div class="card"><div class="lab">RAM</div><div class="val" id="ram">—</div><div class="bar"><i id="ramb"></i></div></div>
<div class="card"><div class="lab">VRAM</div><div class="val" id="vram">—</div><div class="bar"><i id="vramb"></i></div></div>
<div class="card wide"><div class="lab">Temperaturas (últimos 2 min)</div><canvas id="chart"></canvas>
<div class="small"><span style="color:var(--acc)">●</span> CPU &nbsp; <span style="color:var(--warn)">●</span> GPU</div></div>
</div>
<script>
const k=new URLSearchParams(location.search).get('k');const $=id=>document.getElementById(id);
const hist={c:[],g:[]};const N=120;
function f(v,u,d){return v==null?'—':v.toFixed(d||0)+(u||'')}
function bar(id,v){$(id).style.width=(v==null?0:Math.min(100,v))+'%'}
function hhmm(s){s=Math.floor(s);const h=Math.floor(s/3600),m=Math.floor(s%3600/60);return h?h+' h '+String(m).padStart(2,'0')+' min':m+' min'}
function draw(){const c=$('chart'),r=devicePixelRatio||1,w=c.clientWidth,h=c.clientHeight;c.width=w*r;c.height=h*r;
const x=c.getContext('2d');x.scale(r,r);const all=hist.c.concat(hist.g).filter(v=>v!=null);
const lo=Math.max(0,Math.min(...all,30)-5),hi=Math.max(...all,60)+5;const css=getComputedStyle(document.documentElement);
x.strokeStyle=css.getPropertyValue('--line');x.lineWidth=1;for(let i=0;i<=2;i++){const y=h*i/2;x.beginPath();x.moveTo(0,y);x.lineTo(w,y);x.stroke()}
[[hist.c,'--acc'],[hist.g,'--warn']].forEach(([s,col])=>{x.strokeStyle=css.getPropertyValue(col);x.lineWidth=2;x.beginPath();
let st=false;s.forEach((v,i)=>{if(v==null){st=false;return}const px=w*(i+N-s.length)/(N-1),py=h-(v-lo)/(hi-lo)*h;
st?x.lineTo(px,py):x.moveTo(px,py);st=true});x.stroke()});}
async function tick(){try{const r=await fetch('/api?k='+encodeURIComponent(k),{cache:'no-store'});
if(!r.ok)throw 0;const d=await r.json();const age=Date.now()/1000-d.t;
$('status').textContent=age<5?'Ao vivo · '+new Date().toLocaleTimeString():'Sem dados novos há '+Math.round(age)+' s';
$('status').className=age<5?'sub':'sub off';$('host').textContent=d.host||'Nexo';
$('fps').textContent=f(d.fps);$('ft').textContent=d.ft?d.ft.toFixed(1)+' ms por fotograma':'';
const pw=(d.cpu_p||0)+(d.gpu_p||0);$('pw').textContent=(d.cpu_p==null&&d.gpu_p==null)?'—':pw.toFixed(0)+' W';
$('pwsub').textContent='CPU '+f(d.cpu_p,' W')+' · GPU '+f(d.gpu_p,' W');
$('ct').textContent=f(d.cpu_t,' °C');$('cl').textContent='carga '+f(d.cpu_l,' %');bar('clb',d.cpu_l);
$('gt').textContent=f(d.gpu_t,' °C');$('gl').textContent='carga '+f(d.gpu_l,' %');bar('glb',d.gpu_l);
$('ram').textContent=f(d.ram,' %');bar('ramb',d.ram);$('vram').textContent=f(d.vram,' %');bar('vramb',d.vram);
if(d.game){$('gamecard').style.display='';$('game').textContent=d.game;$('gamesub').textContent=hhmm(d.elapsed||0)}
else $('gamecard').style.display='none';
hist.c.push(d.cpu_t);hist.g.push(d.gpu_t);if(hist.c.length>N){hist.c.shift();hist.g.shift()}draw();
}catch(e){$('status').textContent='Sem ligação ao Nexo';$('status').className='sub off'}}
tick();setInterval(tick,1000);addEventListener('resize',draw);
</script></body></html>"""
