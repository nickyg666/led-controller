#!/usr/bin/env python3
"""LED Studio — modern SPA dashboard for RP2040 WS2811 controller."""
import http.server
import json
import os
import select
import subprocess
import termios
import time
import glob
import threading

PORT = 8080
DEV = None
SEQ_FILE = "/home/sh/pico/tools/sequences.json"
EFFECTS = ["static","breath","rainbow","strobe","candle","wave","police","random",
           "storm","temp","chase","fire","sparkle","comet","theater","running",
           "meteor","bounce","confetti","sinelon","juggle","plasma","ripple",
           "wipe","fade","fireworks","snake","pulse","glitter","pride","ocean",
           "aurora","lava","matrix","k2000","heartbeat","colorcycle","twinkle",
           "sparklewave","stroberainbow","gradient","demo"]


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
        time.sleep(0.08)
        resp = b""
        while True:
            r, _, _ = select.select([fd], [], [], 0.25)
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


def sync_to_ha(seq_names=None):
    effects = EFFECTS
    seqs = load_seqs()
    names = seq_names if seq_names else list(seqs.keys())
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
    with open("/tmp/scenes.yaml", "w") as f:
        f.write(content)
    subprocess.run(["scp", "-o", "StrictHostKeyChecking=no", "/tmp/scenes.yaml",
                    "host@192.168.0.168:/tmp/scenes.yaml"], capture_output=True)
    subprocess.run(["sshpass", "-p", "1", "ssh", "-o", "StrictHostKeyChecking=no",
                    "host@192.168.0.168",
                    "echo '1' | sudo -S docker cp /tmp/scenes.yaml homeassistant:/config/scenes.yaml"],
                   capture_output=True)
    subprocess.run(["sshpass", "-p", "1", "ssh", "-o", "StrictHostKeyChecking=no",
                    "host@192.168.0.168",
                    "echo '1' | sudo -S docker restart homeassistant"], capture_output=True)
    # request sync to google
    import urllib.request
    try:
        token_data = json.load(open("/tmp/opencode/ha_token.json"))
        req = urllib.request.Request(
            "http://192.168.0.168:8123/api/services/google_assistant/request_sync",
            data=b"{}", headers={"Authorization": "Bearer " + token_data["access_token"],
                                 "Content-Type": "application/json"})
        urllib.request.urlopen(req)
    except Exception:
        pass
    return f"Synced {len(names)} custom + {len(effects)} effects to HA & Google Home"


HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LED Studio</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#08080d;--bg2:#0f0f18;--card:#14141f;--card2:#1a1a28;--border:#252535;--accent:#5b8def;--accent2:#a855f7;--text:#e8e8f0;--muted:#666;--success:#22c55e;--danger:#ef4444;--warn:#f59e0b}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;overflow-x:hidden}
body::before{content:'';position:fixed;top:0;left:0;right:0;bottom:0;background:radial-gradient(ellipse at 20% 20%,rgba(91,141,239,.08) 0%,transparent 50%),radial-gradient(ellipse at 80% 80%,rgba(168,85,247,.06) 0%,transparent 50%);pointer-events:none;z-index:0}
.container{max-width:1400px;margin:0 auto;padding:24px;position:relative;z-index:1}
header{display:flex;align-items:center;justify-content:space-between;margin-bottom:24px;padding-bottom:16px;border-bottom:1px solid var(--border)}
.logo{font-size:24px;font-weight:700;background:linear-gradient(135deg,var(--accent),var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.subtitle{font-size:13px;color:var(--muted);margin-top:2px}
.status-dot{width:8px;height:8px;border-radius:50%;background:var(--success);display:inline-block;margin-right:6px;box-shadow:0 0 8px var(--success)}
.tabs{display:flex;gap:4px;margin-bottom:20px;background:var(--card);padding:4px;border-radius:10px;border:1px solid var(--border)}
.tab{flex:1;padding:10px 16px;text-align:center;cursor:pointer;border-radius:8px;font-size:14px;font-weight:500;color:var(--muted);transition:all .2s;border:none;background:none}
.tab:hover{color:var(--text);background:rgba(255,255,255,.03)}
.tab.active{color:#fff;background:linear-gradient(135deg,var(--accent),var(--accent2));box-shadow:0 2px 12px rgba(91,141,239,.25)}
.card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:20px;margin:12px 0;backdrop-filter:blur(10px)}
.card h2{font-size:16px;font-weight:600;margin-bottom:14px;display:flex;align-items:center;gap:8px}
.card h2::before{content:'';width:3px;height:16px;background:linear-gradient(180deg,var(--accent),var(--accent2));border-radius:2px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin:10px 0}
.btn{padding:10px 20px;border:none;border-radius:8px;background:linear-gradient(135deg,var(--accent),#3a7de0);color:#fff;cursor:pointer;font-weight:600;font-size:14px;transition:all .15s;position:relative;overflow:hidden}
.btn:hover{transform:translateY(-1px);box-shadow:0 6px 20px rgba(91,141,239,.35)}
.btn:active{transform:translateY(0)}
.btn-sm{padding:6px 14px;font-size:12px}
.btn-danger{background:linear-gradient(135deg,var(--danger),#c33)}
.btn-danger:hover{box-shadow:0 6px 20px rgba(239,68,68,.35)}
.btn-success{background:linear-gradient(135deg,var(--success),#16a34a)}
.btn-success:hover{box-shadow:0 6px 20px rgba(34,197,94,.35)}
.btn-ghost{background:transparent;border:1px solid var(--border);color:var(--muted)}
.btn-ghost:hover{border-color:var(--accent);color:var(--text);box-shadow:none}
.btn-purple{background:linear-gradient(135deg,var(--accent2),#7c3aed)}
input[type=color]{width:48px;height:40px;border:2px solid var(--border);border-radius:8px;cursor:pointer;background:none;padding:2px}
input[type=range]{width:160px;accent-color:var(--accent);cursor:pointer}
input[type=text],input[type=number],select{padding:8px 12px;border-radius:8px;background:var(--bg2);color:var(--text);border:1px solid var(--border);font-size:14px}
select{cursor:pointer;min-width:140px}
.label{font-size:12px;color:var(--muted);margin-right:6px;text-transform:uppercase;letter-spacing:.5px}
.preview-canvas{width:100%;height:60px;border-radius:8px;background:#000;margin:12px 0;border:1px solid var(--border)}
.seq-builder{display:flex;gap:6px;flex-wrap:wrap;margin:12px 0;min-height:60px;padding:16px;background:var(--bg2);border-radius:10px;border:1px dashed var(--border);align-items:center}
.seq-item{width:44px;height:44px;border-radius:8px;cursor:pointer;position:relative;border:2px solid transparent;transition:transform .15s,box-shadow .15s;box-shadow:0 2px 8px rgba(0,0,0,.3)}
.seq-item:hover{transform:scale(1.15);border-color:var(--accent)}
.seq-item .del{position:absolute;top:-8px;right:-8px;background:var(--danger);color:#fff;border-radius:50%;width:18px;height:18px;font-size:10px;display:none;align-items:center;justify-content:center;cursor:pointer;font-weight:700}
.seq-item:hover .del{display:flex}
.seq-empty{color:var(--muted);font-size:13px;font-style:italic}
.seqlist{display:flex;flex-direction:column;gap:8px}
.seq-card{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:12px 16px;display:flex;align-items:center;gap:12px;transition:border-color .2s}
.seq-card:hover{border-color:var(--accent)}
.seq-dots{display:flex;gap:3px;flex-shrink:0}
.seq-dot{width:12px;height:12px;border-radius:3px}
.seq-info{flex:1;min-width:0}
.seq-name{font-weight:600;font-size:14px}
.seq-meta{font-size:11px;color:var(--muted);margin-top:2px}
.seq-actions{display:flex;gap:6px;flex-shrink:0}
.led-grid{display:grid;grid-template-columns:repeat(20,1fr);gap:2px;margin:12px 0}
.led-cell{aspect-ratio:1;border-radius:3px;background:#1a1a28;cursor:pointer;border:1px solid #222;transition:transform .1s}
.led-cell:hover{transform:scale(1.2);border-color:var(--accent)}
.log{background:var(--bg2);padding:12px;border-radius:8px;font-family:'SF Mono',monospace;font-size:11px;height:140px;overflow:auto;margin-top:8px;border:1px solid var(--border);color:#8f8}
.toast{position:fixed;bottom:24px;right:24px;background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;padding:14px 24px;border-radius:10px;font-weight:600;font-size:14px;opacity:0;transform:translateY(20px);transition:all .3s;pointer-events:none;z-index:100;box-shadow:0 8px 32px rgba(91,141,239,.3)}
.toast.show{opacity:1;transform:translateY(0)}
.status-bar{display:flex;align-items:center;gap:12px;padding:10px 16px;background:var(--bg2);border-radius:8px;font-size:13px;color:var(--muted);margin-top:8px}
.status-bar .dot{width:6px;height:6px;border-radius:50%;background:var(--success)}
@media(max-width:768px){.grid{grid-template-columns:1fr}.led-grid{grid-template-columns:repeat(10,1fr)}}
</style></head><body>
<div class="container">
<header>
  <div><div class="logo">LED Studio</div><div class="subtitle">RP2040 WS2811 Controller &middot; <span class="status-dot"></span>Connected</div></div>
  <div style="display:flex;gap:8px">
    <button class="btn btn-sm btn-ghost" onclick="refreshState()">Refresh</button>
  </div>
</header>
<div class="tabs">
  <button class="tab active" onclick="showTab('control',this)">Control</button>
  <button class="tab" onclick="showTab('sequence',this)">Sequences</button>
  <button class="tab" onclick="showTab('leds',this)">Per-LED</button>
  <button class="tab" onclick="showTab('effects',this)">Effects</button>
</div>

<!-- Control -->
<div id="tab-control">
<div class="grid">
<div class="card">
  <h2>Power & Color</h2>
  <div class="row">
    <button class="btn btn-danger" onclick="cmd('OFF')">Power Off</button>
    <button class="btn btn-success" onclick="cmd('RGB 255 255 255')">All White</button>
    <button class="btn btn-ghost" onclick="cmd('CLEAR')">Clear</button>
  </div>
  <div class="row">
    <input type="color" id="color" value="#ff0000">
    <button class="btn" onclick="applyColor()">Apply Color</button>
  </div>
  <canvas id="preview" class="preview-canvas"></canvas>
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
  <div class="status-bar" id="status">Loading...</div>
  <button class="btn btn-sm btn-ghost" onclick="refreshState()" style="margin-top:8px">Refresh</button>
</div>
</div>
</div>

<!-- Sequences -->
<div id="tab-sequence" style="display:none">
<div class="grid">
<div class="card">
  <h2>Sequence Builder</h2>
  <p style="color:var(--muted);font-size:13px;margin-bottom:12px">Build a color chase sequence. Click colors to remove. Run to animate on the strip.</p>
  <div class="picker-row" style="margin-bottom:12px">
    <input type="color" id="seqcolor" value="#ff0000">
    <button class="btn btn-sm" onclick="addSeqColor()">Add Color</button>
    <button class="btn btn-sm btn-danger" onclick="clearSeq()">Clear</button>
    <button class="btn btn-sm btn-success" onclick="runSeq()">Run</button>
    <button class="btn btn-sm btn-ghost" onclick="stopSeq()">Stop</button>
  </div>
  <div class="seq-builder" id="seqbuilder"></div>
  <div class="row" style="margin-top:12px">
    <span class="label">Delay (ms)</span>
    <input type="number" id="seqdelay" value="300" min="50" max="2000" style="width:80px">
    <span class="label">Name</span>
    <input type="text" id="seqname" placeholder="my_sequence" style="width:160px">
    <button class="btn btn-sm btn-purple" onclick="saveSeq()">Save</button>
    <button class="btn btn-sm" onclick="syncHA()">Sync All to HA+GH</button>
  </div>
</div>
<div class="card">
  <h2>Saved Sequences</h2>
  <div class="seqlist" id="seqlist"></div>
</div>
</div>
</div>

<!-- Per-LED -->
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
  <div class="led-grid" id="ledgrid"></div>
</div>
</div>

<!-- Effects -->
<div id="tab-effects" style="display:none">
<div class="card">
  <h2>Effects</h2>
  <div class="row">
    <select id="effect" style="min-width:220px">
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
    <button class="btn" onclick="cmd('ANIM '+document.getElementById('effect').value)">Start Effect</button>
    <button class="btn btn-danger" onclick="cmd('OFF')">Stop</button>
  </div>
  <p style="color:var(--muted);font-size:13px;margin-top:8px">Set a base color first (Control tab), then start an effect. Color-based effects use the current color.</p>
</div>
</div>

<div class="log" id="log"></div>
<div class="toast" id="toast"></div>
<script>
let seqColors=[];
function showTab(t,el){document.querySelectorAll('[id^=tab-]').forEach(e=>e.style.display='none');document.getElementById('tab-'+t).style.display='block';document.querySelectorAll('.tab').forEach(e=>e.classList.remove('active'));el.classList.add('active');}
function log(msg){const l=document.getElementById('log');l.innerHTML+=msg+'<br>';l.scrollTop=l.scrollHeight;}
function toast(msg){const t=document.getElementById('toast');t.textContent=msg;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),2500);}
function cmd(c){fetch('/api/cmd',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:c})}).then(r=>r.text()).then(t=>log('> '+c+' => '+t.trim()));}
function applyColor(){const hex=document.getElementById('color').value;const r=parseInt(hex.slice(1,3),16);const g=parseInt(hex.slice(3,5),16);const b=parseInt(hex.slice(5,7),16);cmd('RGB '+r+' '+g+' '+b);}
function addSeqColor(){seqColors.push(document.getElementById('seqcolor').value);renderSeq();}
function clearSeq(){seqColors=[];renderSeq();}
function renderSeq(){const el=document.getElementById('seqbuilder');el.innerHTML='';if(!seqColors.length){el.innerHTML='<span class="seq-empty">Click "Add Color" to build a sequence</span>';return;}seqColors.forEach((c,i)=>{const d=document.createElement('div');d.className='seq-item';d.style.background=c;d.title=c+' (click to remove)';d.onclick=()=>{seqColors.splice(i,1);renderSeq();};const x=document.createElement('div');x.className='del';x.textContent='×';d.appendChild(x);el.appendChild(d);});}
async function runSeq(){if(!seqColors.length){toast('Add colors first');return;}for(let i=0;i<seqColors.length;i++){const hex=seqColors[i];const r=parseInt(hex.slice(1,3),16);const g=parseInt(hex.slice(3,5),16);const b=parseInt(hex.slice(5,7),16);await fetch('/api/cmd',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:'RGB '+r+' '+g+' '+b})});await new Promise(res=>setTimeout(res,parseInt(document.getElementById('seqdelay').value)||300));}toast('Sequence done');}
function stopSeq(){cmd('OFF');}
function saveSeq(){const name=document.getElementById('seqname').value.trim();if(!name||!seqColors.length){toast('Name and colors required');return;}fetch('/api/seq/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name,colors:seqColors,delay:parseInt(document.getElementById('seqdelay').value)||300})}).then(r=>r.text()).then(t=>{toast(t);loadSeqs();});}
function loadSeqs(){fetch('/api/seq/list').then(r=>r.json()).then(data=>{const el=document.getElementById('seqlist');el.innerHTML='';const keys=Object.keys(data);if(!keys.length){el.innerHTML='<div style="color:var(--muted);font-size:13px">No saved sequences</div>';return;}keys.forEach(name=>{const d=document.createElement('div');d.className='seq-card';const dots=data[name].colors.map(c=>'<div class="seq-dot" style="background:'+c+'"></div>').join('');d.innerHTML='<div class="seq-dots">'+dots+'</div><div class="seq-info"><div class="seq-name">'+name+'</div><div class="seq-meta">'+data[name].colors.length+' colors &middot; '+(data[name].delay*1000).toFixed(0)+'ms delay</div></div><div class="seq-actions"><button class="btn btn-sm btn-success" onclick="runSaved(\''+name+'\')">Run</button><button class="btn btn-sm btn-ghost" onclick="syncOne(\''+name+'\')">Sync HA</button><button class="btn btn-sm btn-danger" onclick="delSeq(\''+name+'\')">Delete</button></div>';el.appendChild(d);});});}
function runSaved(name){fetch('/api/seq/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name})}).then(r=>r.text()).then(t=>toast(t));}
function delSeq(name){fetch('/api/seq/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name})}).then(r=>r.text()).then(t=>{toast(t);loadSeqs();});}
function syncOne(name){fetch('/api/sync',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name})}).then(r=>r.text()).then(t=>toast(t));}
function syncHA(){fetch('/api/sync',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({all:true})}).then(r=>r.text()).then(t=>toast(t));}
function setPix(){const i=document.getElementById('pixi').value;const hex=document.getElementById('pixcolor').value;const r=parseInt(hex.slice(1,3),16);const g=parseInt(hex.slice(3,5),16);const b=parseInt(hex.slice(5,7),16);cmd('PIX '+i+' '+r+' '+g+' '+b);}
function fillAll(){const hex=document.getElementById('fillcolor').value;const r=parseInt(hex.slice(1,3),16);const g=parseInt(hex.slice(3,5),16);const b=parseInt(hex.slice(5,7),16);cmd('FILL '+r+' '+g+' '+b);}
function refreshState(){fetch('/api/cmd',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:'STATE'})}).then(r=>r.text()).then(t=>document.getElementById('status').textContent=t);}
// LED grid
const grid=document.getElementById('ledgrid');
for(let i=0;i<81;i++){const d=document.createElement('div');d.className='led-cell';d.title='LED '+i;d.onclick=()=>{document.getElementById('pixi').value=i;};grid.appendChild(d);}
renderSeq(); loadSeqs(); refreshState();
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
            names = [data.get("name")] if data.get("name") else list(load_seqs().keys()) if data.get("all") else []
            result = sync_to_ha(names if names else None)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(result.encode())
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
