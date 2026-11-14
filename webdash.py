#!/usr/bin/env python3
"""Web dashboard (SPA) for RP2040 WS2811 LED controller."""
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
SEQ_FILE = "/home/sh/pico/tools/sequences.json"


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


def load_seqs():
    if os.path.exists(SEQ_FILE):
        try:
            return json.load(open(SEQ_FILE))
        except Exception:
            pass
    return {}


def save_seqs(seqs):
    json.dump(seqs, open(SEQ_FILE, "w"), indent=2)


def run_sequence(name, seqs):
    seq = seqs.get(name)
    if not seq:
        return
    colors = seq.get("colors", [])
    delay = seq.get("delay", 0.3)
    if not colors:
        return
    while True:
        for hexc in colors:
            r = int(hexc[1:3], 16); g = int(hexc[3:5], 16); b = int(hexc[5:7], 16)
            send_cmd(f"RGB {r} {g} {b}")
            time.sleep(delay)


HTML = r"""<!DOCTYPE html>
<html><head><title>LED Studio</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0a0a0f;--card:#15151f;--accent:#4af;--text:#e0e0e0;--border:#2a2a3a}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}
.container{max-width:1200px;margin:0 auto;padding:20px}
h1{font-size:28px;background:linear-gradient(90deg,#4af,#a4f);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:20px}
h2{font-size:18px;color:#8af;margin:16px 0 8px}
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px;margin:12px 0;box-shadow:0 4px 20px rgba(0,0,0,.3)}
.row{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:8px 0}
.btn{padding:10px 20px;border:none;border-radius:6px;background:linear-gradient(135deg,#4af,#38d);color:#fff;cursor:pointer;font-weight:600;transition:transform .1s,box-shadow .2s}
.btn:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(74,175,255,.3)}
.btn:active{transform:translateY(0)}
.btn-sm{padding:6px 12px;font-size:13px}
.btn-danger{background:linear-gradient(135deg,#f44,#d33)}
.btn-success{background:linear-gradient(135deg,#4f4,#3d3)}
.btn-ghost{background:transparent;border:1px solid #555;color:#aaa}
input[type=color]{width:50px;height:40px;border:none;border-radius:6px;cursor:pointer;background:none}
input[type=range]{width:180px;accent-color:#4af}
select{padding:8px 12px;border-radius:6px;background:#222;color:#eee;border:1px solid #444;cursor:pointer}
input[type=text],input[type=number]{padding:8px 12px;border-radius:6px;background:#222;color:#eee;border:1px solid #444}
.label{font-size:13px;color:#888;margin-right:8px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}
.seq-builder{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0;min-height:50px;padding:12px;background:#0a0a0f;border-radius:8px;border:1px dashed #333}
.seq-item{width:40px;height:40px;border-radius:6px;cursor:pointer;position:relative;border:2px solid #444;transition:transform .1s}
.seq-item:hover{transform:scale(1.1);border-color:#4af}
.seq-item .del{position:absolute;top:-6px;right:-6px;background:#f44;color:#fff;border-radius:50%;width:16px;height:16px;font-size:10px;display:flex;align-items:center;justify-content:center;cursor:pointer}
.picker-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.status{font-size:12px;color:#666;margin-top:8px;font-family:monospace}
.log{background:#0a0a0f;padding:12px;border-radius:8px;font-family:monospace;font-size:12px;height:120px;overflow:auto;margin-top:8px;border:1px solid #222}
.tab{display:inline-block;padding:8px 16px;cursor:pointer;border-bottom:2px solid transparent;color:#888}
.tab.active{color:#4af;border-bottom-color:#4af}
.tabs{border-bottom:1px solid #222;margin-bottom:16px}
.toast{position:fixed;bottom:20px;right:20px;background:#4af;color:#000;padding:12px 24px;border-radius:8px;font-weight:600;opacity:0;transition:opacity .3s;pointer-events:none}
.toast.show{opacity:1}
</style></head><body>
<div class="container">
<h1>LED Studio</h1>
<div class="tabs">
  <span class="tab active" onclick="showTab('control')">Control</span>
  <span class="tab" onclick="showTab('sequence')">Sequences</span>
  <span class="tab" onclick="showTab('leds')">Per-LED</span>
  <span class="tab" onclick="showTab('effects')">Effects</span>
</div>

<!-- Control Tab -->
<div id="tab-control">
<div class="grid">
<div class="card">
  <h2>Power & Color</h2>
  <div class="row">
    <button class="btn btn-danger" onclick="cmd('OFF')">Power Off</button>
    <button class="btn btn-success" onclick="cmd('RGB 255 255 255')">All White</button>
  </div>
  <div class="row">
    <input type="color" id="color" value="#ff0000">
    <button class="btn" onclick="applyColor()">Apply Color</button>
    <button class="btn btn-ghost" onclick="cmd('CLEAR')">Clear</button>
  </div>
  <div class="row">
    <span class="label">Brightness</span>
    <input type="range" id="bright" min="0" max="255" value="255" oninput="document.getElementById('bv').textContent=this.value">
    <span id="bv">255</span>
    <button class="btn btn-sm" onclick="cmd('BRIGHTNESS '+document.getElementById('bright').value)">Set</button>
  </div>
  <div class="row">
    <span class="label">Speed</span>
    <input type="range" id="speed" min="1" max="255" value="10" oninput="document.getElementById('sv').textContent=this.value">
    <span id="sv">10</span>
    <button class="btn btn-sm" onclick="cmd('SPEED '+document.getElementById('speed').value)">Set</button>
  </div>
  <div class="row">
    <span class="label">White LED</span>
    <input type="range" id="white" min="0" max="255" value="0" oninput="document.getElementById('wv').textContent=this.value">
    <span id="wv">0</span>
    <button class="btn btn-sm" onclick="cmd('WHITE '+document.getElementById('white').value)">Set</button>
  </div>
</div>
<div class="card">
  <h2>Status</h2>
  <div id="status">Loading...</div>
  <button class="btn btn-sm btn-ghost" onclick="refreshState()">Refresh</button>
</div>
</div>
</div>

<!-- Sequence Tab -->
<div id="tab-sequence" style="display:none">
<div class="card">
  <h2>Sequence Builder</h2>
  <p style="color:#888;font-size:13px;margin-bottom:12px">Build a color sequence. Click colors to remove. Run to animate on the strip.</p>
  <div class="picker-row">
    <input type="color" id="seqcolor" value="#ff0000">
    <button class="btn btn-sm" onclick="addSeqColor()">Add Color</button>
    <button class="btn btn-sm btn-danger" onclick="clearSeq()">Clear</button>
    <button class="btn btn-sm btn-success" onclick="runSeq()">Run Sequence</button>
    <button class="btn btn-sm btn-ghost" onclick="stopSeq()">Stop</button>
  </div>
  <div class="seq-builder" id="seqbuilder"></div>
  <div class="row">
    <span class="label">Delay (ms)</span>
    <input type="number" id="seqdelay" value="300" min="50" max="2000" style="width:80px">
    <span class="label">Name</span>
    <input type="text" id="seqname" placeholder="my_sequence" style="width:160px">
    <button class="btn btn-sm" onclick="saveSeq()">Save</button>
  </div>
</div>
<div class="card">
  <h2>Saved Sequences</h2>
  <div id="seqlist"></div>
  <div class="row" style="margin-top:12px">
    <button class="btn btn-sm" onclick="syncHA()">Sync to Home Assistant</button>
  </div>
</div>
</div>

<!-- Per-LED Tab -->
<div id="tab-leds" style="display:none">
<div class="card">
  <h2>Per-LED Control</h2>
  <div class="row">
    <span class="label">Index</span>
    <input type="number" id="pixi" value="0" min="0" max="1023" style="width:80px">
    <input type="color" id="pixcolor" value="#00ff00">
    <button class="btn btn-sm" onclick="setPix()">Set LED</button>
    <button class="btn btn-sm btn-ghost" onclick="cmd('SHOW')">Show</button>
    <button class="btn btn-sm btn-danger" onclick="cmd('CLEAR')">Clear All</button>
  </div>
  <div class="row" style="margin-top:8px">
    <span class="label">Fill all:</span>
    <input type="color" id="fillcolor" value="#ff0000">
    <button class="btn btn-sm" onclick="fillAll()">Fill</button>
  </div>
</div>
</div>

<!-- Effects Tab -->
<div id="tab-effects" style="display:none">
<div class="card">
  <h2>Effects</h2>
  <div class="row">
    <select id="effect" style="min-width:200px">
      <option value="rainbow">Rainbow</option><option value="chase">Chase</option><option value="fire">Fire</option>
      <option value="sparkle">Sparkle</option><option value="comet">Comet</option><option value="theater">Theater</option>
      <option value="running">Running</option><option value="meteor">Meteor</option><option value="bounce">Bounce</option>
      <option value="confetti">Confetti</option><option value="sinelon">Sinelon</option><option value="juggle">Juggle</option>
      <option value="plasma">Plasma</option><option value="ripple">Ripple</option><option value="wipe">Wipe</option>
      <option value="fade">Fade</option><option value="fireworks">Fireworks</option><option value="snake">Snake</option>
      <option value="pulse">Pulse</option><option value="glitter">Glitter</option><option value="pride">Pride</option>
      <option value="ocean">Ocean</option><option value="aurora">Aurora</option><option value="lava">Lava</option>
      <option value="matrix">Matrix</option><option value="k2000">K2000</option><option value="heartbeat">Heartbeat</option>
      <option value="colorcycle">Colorcycle</option><option value="twinkle">Twinkle</option><option value="sparklewave">Sparklewave</option>
      <option value="stroberainbow">Strobe Rainbow</option><option value="gradient">Gradient</option><option value="demo">Demo</option>
      <option value="breath">Breath</option><option value="strobe">Strobe</option><option value="candle">Candle</option>
      <option value="wave">Wave</option><option value="police">Police</option><option value="random">Random</option>
      <option value="storm">Storm</option><option value="static">Static</option>
    </select>
    <button class="btn" onclick="cmd('ANIM '+document.getElementById('effect').value)">Start</button>
    <button class="btn btn-danger" onclick="cmd('OFF')">Stop</button>
  </div>
  <p style="color:#888;font-size:13px;margin-top:8px">Tip: Set a base color with "Apply Color" first, then start an effect. Color-based effects (theater, running, pulse, etc.) use the current color.</p>
</div>
</div>

<div class="log" id="log"></div>
<div class="toast" id="toast"></div>
<script>
let seqColors=[];
function showTab(t){document.querySelectorAll('[id^=tab-]').forEach(e=>e.style.display='none');document.getElementById('tab-'+t).style.display='block';document.querySelectorAll('.tab').forEach(e=>e.classList.remove('active'));event.target.classList.add('active');}
function log(msg){const l=document.getElementById('log');l.innerHTML+=msg+'<br>';l.scrollTop=l.scrollHeight;}
function toast(msg){const t=document.getElementById('toast');t.textContent=msg;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),2000);}
function cmd(c){fetch('/api/cmd',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:c})}).then(r=>r.text()).then(t=>log('> '+c+' => '+t.trim()));}
function applyColor(){const hex=document.getElementById('color').value;const r=parseInt(hex.slice(1,3),16);const g=parseInt(hex.slice(3,5),16);const b=parseInt(hex.slice(5,7),16);cmd('RGB '+r+' '+g+' '+b);}
function addSeqColor(){seqColors.push(document.getElementById('seqcolor').value);renderSeq();}
function clearSeq(){seqColors=[];renderSeq();}
function renderSeq(){const el=document.getElementById('seqbuilder');el.innerHTML='';seqColors.forEach((c,i)=>{const d=document.createElement('div');d.className='seq-item';d.style.background=c;d.title=c+' (click to remove)';d.onclick=()=>{seqColors.splice(i,1);renderSeq();};const x=document.createElement('div');x.className='del';x.textContent='x';d.appendChild(x);el.appendChild(d);});}
async function runSeq(){if(!seqColors.length){toast('Add colors first');return;}for(let i=0;i<seqColors.length;i++){const hex=seqColors[i];const r=parseInt(hex.slice(1,3),16);const g=parseInt(hex.slice(3,5),16);const b=parseInt(hex.slice(5,7),16);await fetch('/api/cmd',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:'RGB '+r+' '+g+' '+b})});await new Promise(res=>setTimeout(res,parseInt(document.getElementById('seqdelay').value)||300));}toast('Sequence done');}
function stopSeq(){cmd('OFF');}
function saveSeq(){const name=document.getElementById('seqname').value.trim();if(!name||!seqColors.length){toast('Name and colors required');return;}fetch('/api/seq/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name,colors:seqColors,delay:parseInt(document.getElementById('seqdelay').value)||300})}).then(r=>r.text()).then(t=>{toast(t);loadSeqs();});}
function loadSeqs(){fetch('/api/seq/list').then(r=>r.json()).then(data=>{const el=document.getElementById('seqlist');el.innerHTML='';Object.keys(data).forEach(name=>{const d=document.createElement('div');d.className='row';d.style.marginBottom='8px';d.innerHTML='<b>'+name+'</b> ('+data[name].colors.length+' colors) <button class="btn btn-sm" onclick="runSaved(\''+name+'\')">Run</button> <button class="btn btn-sm btn-danger" onclick="delSeq(\''+name+'\')">Delete</button> <button class="btn btn-sm btn-ghost" onclick="syncOne(\''+name+'\')">Sync HA</button>';el.appendChild(d);});});}
function runSaved(name){fetch('/api/seq/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name})}).then(r=>r.text()).then(t=>toast(t));}
function delSeq(name){fetch('/api/seq/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name})}).then(r=>r.text()).then(t=>{toast(t);loadSeqs();});}
function syncOne(name){fetch('/api/sync',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name})}).then(r=>r.text()).then(t=>toast(t));}
function syncHA(){fetch('/api/sync',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({all:true})}).then(r=>r.text()).then(t=>toast(t));}
function setPix(){const i=document.getElementById('pixi').value;const hex=document.getElementById('pixcolor').value;const r=parseInt(hex.slice(1,3),16);const g=parseInt(hex.slice(3,5),16);const b=parseInt(hex.slice(5,7),16);cmd('PIX '+i+' '+r+' '+g+' '+b);}
function fillAll(){const hex=document.getElementById('fillcolor').value;const r=parseInt(hex.slice(1,3),16);const g=parseInt(hex.slice(3,5),16);const b=parseInt(hex.slice(5,7),16);cmd('FILL '+r+' '+g+' '+b);}
function refreshState(){fetch('/api/cmd',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:'STATE'})}).then(r=>r.text()).then(t=>document.getElementById('status').textContent=t);}
loadSeqs(); refreshState();
</script></body></html>"""

seq_thread = None
seq_stop = threading.Event()


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(HTML.encode())
        elif self.path == "/api/seq/list":
            seqs = load_seqs()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(seqs).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        global seq_thread, seq_stop
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        try:
            data = json.loads(body) if body else {}
        except Exception:
            data = {}
        if self.path == "/api/cmd":
            resp = send_cmd(data.get("cmd", ""))
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(resp.encode())
        elif self.path == "/api/seq/save":
            seqs = load_seqs()
            name = data.get("name", "").strip()
            if not name:
                self.send_response(400); self.end_headers(); self.wfile.write(b"Name required"); return
            seqs[name] = {"colors": data.get("colors", []), "delay": data.get("delay", 300) / 1000.0}
            save_seqs(seqs)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"Saved '{name}'".encode())
        elif self.path == "/api/seq/run":
            name = data.get("name", "")
            seqs = load_seqs()
            seq_stop.clear()
            def runner():
                seq = seqs.get(name, {})
                colors = seq.get("colors", [])
                delay = seq.get("delay", 0.3)
                while not seq_stop.is_set():
                    for hexc in colors:
                        if seq_stop.is_set():
                            break
                        r = int(hexc[1:3], 16); g = int(hexc[3:5], 16); b = int(hexc[5:7], 16)
                        send_cmd(f"RGB {r} {g} {b}")
                        time.sleep(delay)
            t = threading.Thread(target=runner, daemon=True)
            t.start()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"Running '{name}'".encode())
        elif self.path == "/api/seq/delete":
            name = data.get("name", "")
            seqs = load_seqs()
            if name in seqs:
                del seqs[name]
                save_seqs(seqs)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"Deleted '{name}'".encode())
        elif self.path == "/api/seq/stop":
            seq_stop.set()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Stopped")
        elif self.path == "/api/sync":
            # Sync saved sequences to HA as scenes
            seqs = load_seqs()
            names = [data.get("name")] if data.get("name") else list(seqs.keys()) if data.get("all") else []
            # Generate scenes.yaml with original effects + custom sequences
            effects = ["static","breath","rainbow","strobe","candle","wave","police","random","storm","temp","chase","fire","sparkle","comet","theater","running","meteor","bounce","confetti","sinelon","juggle","plasma","ripple","wipe","fade","fireworks","snake","pulse","glitter","pride","ocean","aurora","lava","matrix","k2000","heartbeat","colorcycle","twinkle","sparklewave","stroberainbow","gradient","demo"]
            lines = []
            for e in effects:
                lines.append(f'- name: "{e.capitalize()} Effect"')
                lines.append('  entities:')
                lines.append('    light.pc_lights:')
                lines.append('      state: "on"')
                lines.append(f'      effect: {e}')
                lines.append('')
            for name in names:
                seq = seqs.get(name, {})
                colors = seq.get("colors", [])
                if colors:
                    hexc = colors[0]
                    r = int(hexc[1:3], 16); g = int(hexc[3:5], 16); b = int(hexc[5:7], 16)
                    lines.append(f'- name: "{name}"')
                    lines.append('  entities:')
                    lines.append('    light.pc_lights:')
                    lines.append('      state: "on"')
                    lines.append(f'      rgb_color: [{r},{g},{b}]')
                    lines.append('')
            content = "\n".join(lines)
            # Write to remote HA
            import subprocess
            subprocess.run(["scp", "-o", "StrictHostKeyChecking=no", "/dev/stdin", "host@192.168.0.168:/tmp/scenes.yaml"], input=content.encode(), capture_output=True)
            subprocess.run(["sshpass", "-p", "1", "ssh", "-o", "StrictHostKeyChecking=no", "host@192.168.0.168", "echo '1' | sudo -S docker cp /tmp/scenes.yaml homeassistant:/config/scenes.yaml"], capture_output=True)
            subprocess.run(["sshpass", "-p", "1", "ssh", "-o", "StrictHostKeyChecking=no", "host@192.168.0.168", "echo '1' | sudo -S docker restart homeassistant"], capture_output=True)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"Synced {len(names)} custom scenes + {len(effects)} effects to HA".encode())
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
