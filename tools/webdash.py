#!/usr/bin/env python3
"""Web dashboard for RP2040 WS2811 LED controller."""
import http.server
import json
import os
import select
import termios
import time
import glob
import threading

PORT = 8080
DEV = None


def find_device():
    if os.path.exists("/dev/rp2040-rgb"):
        return "/dev/rp2040-rgb"
    ds = sorted(glob.glob("/dev/ttyACM*"))
    return ds[0] if ds else None


def send_cmd(cmd):
    global DEV
    if DEV is None:
        DEV = find_device()
    if not DEV:
        return "no device"
    fd = os.open(DEV, os.O_RDWR | os.O_NOCTTY)
    try:
        attrs = termios.tcgetattr(fd)
        attrs[1] = termios.OPOST | termios.ONLCR
        attrs[3] = termios.CREAD | termios.CLOCAL
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 1
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        os.write(fd, (cmd + "\r\n").encode())
        time.sleep(0.1)
        resp = b""
        while True:
            r, _, _ = select.select([fd], [], [], 0.3)
            if not r:
                break
            n = os.read(fd, 4096)
            if len(n) <= 0:
                break
            resp += n
        return resp.decode(errors="replace").strip()
    finally:
        os.close(fd)


HTML = r"""<!DOCTYPE html>
<html><head><title>LED Dashboard</title>
<style>
body{font-family:sans-serif;background:#111;color:#eee;margin:20px}
h1{color:#4af}
.card{background:#222;border-radius:8px;padding:16px;margin:12px 0}
.row{display:flex;gap:12px;flex-wrap:wrap;align-items:center}
button{padding:8px 16px;border:none;border-radius:4px;background:#444;color:#eee;cursor:pointer}
button:hover{background:#666}
button.active{background:#4af;color:#000}
input[type=color]{width:60px;height:40px;border:none;background:none;cursor:pointer}
input[type=range]{width:200px}
select{padding:8px;border-radius:4px;background:#333;color:#eee;border:1px solid #555}
#status{font-size:12px;color:#888;margin-top:8px}
.seq{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}
.seq-color{width:30px;height:30px;border-radius:4px;border:2px solid #555;cursor:pointer}
.log{background:#000;padding:8px;border-radius:4px;font-family:monospace;font-size:12px;height:100px;overflow:auto;margin-top:8px}
</style></head><body>
<h1>RP2040 LED Dashboard</h1>
<div class="card">
  <h3>Power & Color</h3>
  <div class="row">
    <button onclick="cmd('OFF')">Off</button>
    <button onclick="cmd('RGB 255 0 0')">Red</button>
    <button onclick="cmd('RGB 0 255 0')">Green</button>
    <button onclick="cmd('RGB 0 0 255')">Blue</button>
    <button onclick="cmd('RGB 255 255 255')">White</button>
    <input type="color" id="color" value="#ff0000">
    <button onclick="applyColor()">Apply Color</button>
  </div>
  <div class="row" style="margin-top:8px">
    <label>Brightness: </label><input type="range" id="bright" min="0" max="255" value="255" oninput="document.getElementById('brightval').textContent=this.value">
    <span id="brightval">255</span>
    <button onclick="cmd('BRIGHTNESS '+document.getElementById('bright').value)">Set</button>
  </div>
  <div class="row" style="margin-top:8px">
    <label>Speed: </label><input type="range" id="speed" min="1" max="255" value="10" oninput="document.getElementById('speedval').textContent=this.value">
    <span id="speedval">10</span>
    <button onclick="cmd('SPEED '+document.getElementById('speed').value)">Set</button>
  </div>
</div>
<div class="card">
  <h3>Effects</h3>
  <div class="row">
    <select id="effect">
      <option value="rainbow">Rainbow</option>
      <option value="chase">Chase</option>
      <option value="fire">Fire</option>
      <option value="sparkle">Sparkle</option>
      <option value="comet">Comet</option>
      <option value="theater">Theater</option>
      <option value="running">Running</option>
      <option value="meteor">Meteor</option>
      <option value="bounce">Bounce</option>
      <option value="confetti">Confetti</option>
      <option value="sinelon">Sinelon</option>
      <option value="juggle">Juggle</option>
      <option value="plasma">Plasma</option>
      <option value="ripple">Ripple</option>
      <option value="wipe">Wipe</option>
      <option value="fade">Fade</option>
      <option value="fireworks">Fireworks</option>
      <option value="snake">Snake</option>
      <option value="pulse">Pulse</option>
      <option value="glitter">Glitter</option>
      <option value="pride">Pride</option>
      <option value="ocean">Ocean</option>
      <option value="aurora">Aurora</option>
      <option value="lava">Lava</option>
      <option value="matrix">Matrix</option>
      <option value="k2000">K2000</option>
      <option value="heartbeat">Heartbeat</option>
      <option value="colorcycle">Colorcycle</option>
      <option value="twinkle">Twinkle</option>
      <option value="sparklewave">Sparklewave</option>
      <option value="stroberainbow">Strobe Rainbow</option>
      <option value="gradient">Gradient</option>
      <option value="demo">Demo</option>
      <option value="breath">Breath</option>
      <option value="strobe">Strobe</option>
      <option value="candle">Candle</option>
      <option value="wave">Wave</option>
      <option value="police">Police</option>
      <option value="random">Random</option>
      <option value="storm">Storm</option>
      <option value="static">Static</option>
    </select>
    <button onclick="cmd('ANIM '+document.getElementById('effect').value)">Start Effect</button>
    <button onclick="cmd('OFF')">Stop</button>
  </div>
</div>
<div class="card">
  <h3>Custom Sequence Builder</h3>
  <p>Add colors to build a chase/sequence. Click "Run Sequence" to animate.</p>
  <div class="row">
    <input type="color" id="seqcolor" value="#ff0000">
    <button onclick="addColor()">Add Color</button>
    <button onclick="clearSeq()">Clear</button>
    <button onclick="runSeq()">Run Sequence</button>
  </div>
  <div class="seq" id="seq"></div>
</div>
<div class="card">
  <h3>Per-LED (PIX)</h3>
  <div class="row">
    <label>Index:</label><input type="number" id="pixi" value="0" min="0" max="1023" style="width:80px">
    <input type="color" id="pixcolor" value="#00ff00">
    <button onclick="setPix()">Set LED</button>
    <button onclick="cmd('CLEAR')">Clear All</button>
    <button onclick="cmd('SHOW')">Show</button>
  </div>
</div>
<div class="log" id="log"></div>
<script>
let seqColors = [];
function log(msg){const l=document.getElementById('log'); l.innerHTML += msg+'<br>'; l.scrollTop=l.scrollHeight;}
function cmd(c){fetch('/api/cmd',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:c})}).then(r=>r.text()).then(t=>log('> '+c+' => '+t));}
function applyColor(){const hex=document.getElementById('color').value; const r=parseInt(hex.slice(1,3),16); const g=parseInt(hex.slice(3,5),16); const b=parseInt(hex.slice(5,7),16); cmd('RGB '+r+' '+g+' '+b);}
function addColor(){seqColors.push(document.getElementById('seqcolor').value); renderSeq();}
function clearSeq(){seqColors=[]; renderSeq();}
function renderSeq(){const el=document.getElementById('seq'); el.innerHTML=''; seqColors.forEach((c,i)=>{const d=document.createElement('div'); d.className='seq-color'; d.style.background=c; d.title=c; d.onclick=()=>{seqColors.splice(i,1); renderSeq();}; el.appendChild(d);});}
async function runSeq(){if(!seqColors.length) return; for(let i=0;i<seqColors.length;i++){const hex=seqColors[i]; const r=parseInt(hex.slice(1,3),16); const g=parseInt(hex.slice(3,5),16); const b=parseInt(hex.slice(5,7),16); await fetch('/api/cmd',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:'RGB '+r+' '+g+' '+b})}); await new Promise(res=>setTimeout(res,300));}}
function setPix(){const i=document.getElementById('pixi').value; const hex=document.getElementById('pixcolor').value; const r=parseInt(hex.slice(1,3),16); const g=parseInt(hex.slice(3,5),16); const b=parseInt(hex.slice(5,7),16); cmd('PIX '+i+' '+r+' '+g+' '+b);}
</script></body></html>"""

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(HTML.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/cmd":
            n = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(n)
            data = json.loads(body)
            resp = send_cmd(data.get("cmd", ""))
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(resp.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    DEV = find_device()
    print(f"Device: {DEV}")
    print(f"Dashboard: http://0.0.0.0:{PORT}")
    http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
