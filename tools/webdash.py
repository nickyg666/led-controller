#!/usr/bin/env python3
"""LED Studio — full animation editor SPA for RP2040 WS2811 controller."""
import http.server
import json
import os
import select
import subprocess
import termios
import time
import glob
import threading
import base64

PORT = 8080
DEV = None
SEQ_FILE = "/home/sh/pico/tools/sequences.json"
ANIM_FILE = "/home/sh/pico/tools/animations.json"
EFFECTS = ["static","breath","rainbow","strobe","candle","wave","police","random",
           "storm","temp","chase","fire","sparkle","comet","theater","running",
           "meteor","bounce","confetti","sinelon","juggle","plasma","ripple",
           "wipe","fade","fireworks","snake","pulse","glitter","pride","ocean",
           "aurora","lava","matrix","k2000","heartbeat","colorcycle","twinkle",
           "sparklewave","stroberainbow","gradient","demo"]
NUM_LEDS = 81


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
        time.sleep(0.05)
        resp = b""
        while True:
            r, _, _ = select.select([fd], [], [], 0.2)
            if not r:
                break
            n = os.read(fd, 4096)
            if len(n) <= 0:
                break
            resp += n
        return resp.decode(errors="replace").strip()
    finally:
        os.close(fd)


def send_frame(colors):
    """Send an Adalight frame directly."""
    global DEV
    if DEV is None:
        DEV = find_device()
    if not DEV:
        return
    fd = os.open(DEV, os.O_RDWR | os.O_NOCTTY)
    try:
        attrs = termios.tcgetattr(fd)
        attrs[1] = termios.OPOST | termios.ONLCR
        attrs[3] = termios.CREAD | termios.CLOCAL
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 1
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        n = len(colors)
        # Adalight header
        buf = bytes([0x41, 0x64, 0x61, (n >> 8) & 0xFF, n & 0xFF,
                     ((n >> 8) & 0xFF) ^ (n & 0xFF) ^ 0x55])
        for c in colors:
            buf += bytes([c[1], c[0], c[2]])  # GRB order for WS2811
        os.write(fd, buf)
        time.sleep(0.02)
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


def load_anims():
    if os.path.exists(ANIM_FILE):
        try:
            return json.load(open(ANIM_FILE))
        except Exception:
            pass
    return {}


def save_anims(anims):
    json.dump(anims, open(ANIM_FILE, "w"), indent=2)


def sync_to_ha(seq_names=None):
    effects = EFFECTS
    seqs = load_seqs()
    anims = load_anims()
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
    for name in anims:
        anim = anims[name]
        frames = anim.get("frames", [])
        if frames:
            first = frames[0]
            # get dominant color
            if first:
                r = sum(c[0] for c in first) // len(first)
                g = sum(c[1] for c in first) // len(first)
                b = sum(c[2] for c in first) // len(first)
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
    try:
        import urllib.request
        token_data = json.load(open("/tmp/opencode/ha_token.json"))
        req = urllib.request.Request(
            "http://192.168.0.168:8123/api/services/google_assistant/request_sync",
            data=b"{}", headers={"Authorization": "Bearer " + token_data["access_token"],
                                 "Content-Type": "application/json"})
        urllib.request.urlopen(req)
    except Exception:
        pass
    return f"Synced {len(names)} sequences + {len(anims)} animations + {len(effects)} effects to HA & Google Home"


HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LED Studio</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#06060a;--bg2:#0c0c14;--card:#12121c;--card2:#181824;--border:#1e1e2e;--accent:#6366f1;--accent2:#a855f7;--accent3:#22d3ee;--text:#e2e2f0;--muted:#555;--success:#10b981;--danger:#ef4444;--warn:#f59e0b}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;overflow-x:hidden}
body::before{content:'';position:fixed;top:0;left:0;right:0;bottom:0;background:radial-gradient(ellipse at 15% 15%,rgba(99,102,241,.12) 0%,transparent 45%),radial-gradient(ellipse at 85% 85%,rgba(168,85,247,.08) 0%,transparent 45%),radial-gradient(ellipse at 50% 50%,rgba(34,211,238,.04) 0%,transparent 60%);pointer-events:none;z-index:0}
.container{max-width:1600px;margin:0 auto;padding:20px;position:relative;z-index:1}
header{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;padding-bottom:14px;border-bottom:1px solid var(--border)}
.logo{font-size:26px;font-weight:700;background:linear-gradient(135deg,var(--accent),var(--accent2),var(--accent3));-webkit-background-clip:text;-webkit-text-fill-color:transparent;letter-spacing:-.5px}
.subtitle{font-size:12px;color:var(--muted);margin-top:2px}
.status-dot{width:8px;height:8px;border-radius:50%;background:var(--success);display:inline-block;margin-right:6px;box-shadow:0 0 10px var(--success);animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
.tabs{display:flex;gap:2px;margin-bottom:18px;background:var(--card);padding:4px;border-radius:12px;border:1px solid var(--border)}
.tab{flex:1;padding:10px 12px;text-align:center;cursor:pointer;border-radius:9px;font-size:13px;font-weight:500;color:var(--muted);transition:all .2s;border:none;background:none}
.tab:hover{color:var(--text);background:rgba(255,255,255,.04)}
.tab.active{color:#fff;background:linear-gradient(135deg,var(--accent),var(--accent2));box-shadow:0 4px 16px rgba(99,102,241,.3)}
.card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:18px;margin:10px 0;backdrop-filter:blur(12px)}
.card h2{font-size:15px;font-weight:600;margin-bottom:12px;display:flex;align-items:center;gap:8px}
.card h2::before{content:'';width:3px;height:14px;background:linear-gradient(180deg,var(--accent),var(--accent2));border-radius:2px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:8px 0}
.btn{padding:9px 18px;border:none;border-radius:8px;background:linear-gradient(135deg,var(--accent),#4f46e5);color:#fff;cursor:pointer;font-weight:600;font-size:13px;transition:all .15s}
.btn:hover{transform:translateY(-1px);box-shadow:0 6px 18px rgba(99,102,241,.35)}
.btn:active{transform:translateY(0)}
.btn-sm{padding:5px 12px;font-size:11px}
.btn-danger{background:linear-gradient(135deg,var(--danger),#dc2626)}
.btn-danger:hover{box-shadow:0 6px 18px rgba(239,68,68,.35)}
.btn-success{background:linear-gradient(135deg,var(--success),#059669)}
.btn-success:hover{box-shadow:0 6px 18px rgba(16,185,129,.35)}
.btn-ghost{background:transparent;border:1px solid var(--border);color:var(--muted)}
.btn-ghost:hover{border-color:var(--accent);color:var(--text);box-shadow:none}
.btn-purple{background:linear-gradient(135deg,var(--accent2),#7c3aed)}
.btn-cyan{background:linear-gradient(135deg,var(--accent3),#0891b2)}
input[type=color]{width:44px;height:36px;border:2px solid var(--border);border-radius:8px;cursor:pointer;background:none;padding:2px}
input[type=range]{width:140px;accent-color:var(--accent);cursor:pointer}
input[type=text],input[type=number],select{padding:7px 10px;border-radius:8px;background:var(--bg2);color:var(--text);border:1px solid var(--border);font-size:13px}
select{cursor:pointer;min-width:120px}
.label{font-size:11px;color:var(--muted);margin-right:4px;text-transform:uppercase;letter-spacing:.5px}
.preview-canvas{width:100%;height:70px;border-radius:10px;background:#000;margin:10px 0;border:1px solid var(--border)}
.seq-builder{display:flex;gap:4px;flex-wrap:wrap;margin:10px 0;min-height:50px;padding:12px;background:var(--bg2);border-radius:10px;border:1px dashed var(--border);align-items:center}
.seq-item{width:36px;height:36px;border-radius:6px;cursor:pointer;position:relative;border:2px solid transparent;transition:transform .15s;box-shadow:0 2px 6px rgba(0,0,0,.3)}
.seq-item:hover{transform:scale(1.15);border-color:var(--accent)}
.seq-item .del{position:absolute;top:-6px;right:-6px;background:var(--danger);color:#fff;border-radius:50%;width:16px;height:16px;font-size:9px;display:none;align-items:center;justify-content:center;cursor:pointer;font-weight:700}
.seq-item:hover .del{display:flex}
.seq-empty{color:var(--muted);font-size:12px;font-style:italic}
.seqlist{display:flex;flex-direction:column;gap:6px;max-height:320px;overflow-y:auto;overflow-x:hidden;padding-right:4px;scrollbar-width:thin;scrollbar-color:var(--accent) var(--bg2)}
.seqlist::-webkit-scrollbar{width:6px}
.seqlist::-webkit-scrollbar-track{background:var(--bg2);border-radius:3px}
.seqlist::-webkit-scrollbar-thumb{background:var(--accent);border-radius:3px}
.seq-card{background:var(--bg2);border:1px solid var(--border);border-radius:10px;padding:10px 14px;display:flex;align-items:center;gap:10px;transition:border-color .2s;flex-wrap:wrap}
.seq-card:hover{border-color:var(--accent)}
.seq-dots{display:flex;gap:2px;flex-shrink:0}
.seq-dot{width:10px;height:10px;border-radius:2px}
.seq-info{flex:1;min-width:0}
.seq-name{font-weight:600;font-size:13px}
.seq-meta{font-size:10px;color:var(--muted);margin-top:1px}
.seq-actions{display:flex;gap:4px;flex-shrink:0}
.led-grid{display:grid;grid-template-columns:repeat(15,1fr);gap:2px;margin:10px 0}
.led-cell{aspect-ratio:1;border-radius:2px;background:#1a1a28;cursor:pointer;border:1px solid #222;transition:transform .1s}
.led-cell:hover{transform:scale(1.3);border-color:var(--accent)}
.led-cell.active{border-color:var(--accent2)}
.log{background:var(--bg2);padding:10px;border-radius:8px;font-family:'JetBrains Mono',monospace;font-size:11px;height:120px;overflow:auto;margin-top:8px;border:1px solid var(--border);color:#8f8}
.toast{position:fixed;bottom:20px;right:20px;background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;padding:12px 20px;border-radius:10px;font-weight:600;font-size:13px;opacity:0;transform:translateY(20px);transition:all .3s;pointer-events:none;z-index:100;box-shadow:0 8px 32px rgba(99,102,241,.3)}
.toast.show{opacity:1;transform:translateY(0)}
.status-bar{display:flex;align-items:center;gap:10px;padding:8px 14px;background:var(--bg2);border-radius:8px;font-size:12px;color:var(--muted);margin-top:8px}
.status-bar .dot{width:6px;height:6px;border-radius:50%;background:var(--success)}
.anim-timeline{display:flex;gap:4px;overflow-x:auto;padding:10px;background:var(--bg2);border-radius:10px;border:1px solid var(--border);margin:10px 0;min-height:80px}
.anim-frame{min-width:60px;height:60px;border-radius:8px;border:2px solid var(--border);cursor:pointer;position:relative;transition:all .15s;overflow:hidden;flex-shrink:0}
.anim-frame:hover{border-color:var(--accent);transform:scale(1.05)}
.anim-frame.active{border-color:var(--accent2);box-shadow:0 0 12px rgba(168,85,247,.3)}
.anim-frame .frame-num{position:absolute;bottom:2px;left:4px;font-size:9px;color:#fff;text-shadow:0 0 4px #000;font-weight:600}
.anim-frame .frame-del{position:absolute;top:2px;right:2px;background:var(--danger);color:#fff;border-radius:50%;width:14px;height:14px;font-size:8px;display:none;align-items:center;justify-content:center;cursor:pointer;font-weight:700}
.anim-frame:hover .frame-del{display:flex}
.anim-controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:10px 0}
.anim-preview{width:100%;height:80px;border-radius:10px;background:#000;margin:10px 0;border:1px solid var(--border);position:relative;overflow:hidden}
.anim-preview .led-row{display:flex;height:100%;gap:1px;padding:4px}
.anim-preview .led-px{flex:1;border-radius:2px;transition:background .05s}
@media(max-width:768px){.grid{grid-template-columns:1fr}.led-grid{grid-template-columns:repeat(9,1fr)}.tabs{flex-wrap:wrap}.tab{flex:1 1 40%;font-size:12px;padding:8px 6px}.row{gap:6px}.btn{padding:8px 14px;font-size:12px}input[type=range]{width:120px}select{min-width:100px;font-size:12px}.seq-card{flex-direction:column;align-items:flex-start;gap:6px}.seq-actions{width:100%;justify-content:flex-end}.seq-dots{order:-1}.anim-timeline{gap:3px}.anim-frame{min-width:50px;height:50px}.led-grid{grid-template-columns:repeat(9,1fr);gap:2px}.seq-builder{min-height:40px;padding:8px}.seq-item{width:32px;height:32px}.preview-canvas{height:50px}.log{height:80px;font-size:10px}.card{padding:14px;margin:8px 0}.container{padding:12px}header{flex-direction:column;gap:8px;align-items:flex-start}}
@media(max-width:480px){.led-grid{grid-template-columns:repeat(6,1fr)}.tabs{gap:2px}.tab{flex:1 1 100%;font-size:11px;padding:6px}.row{flex-direction:column;align-items:stretch}.btn{width:100%}input[type=range]{width:100%}input[type=color]{width:100%;height:44px}select{width:100%}input[type=text],input[type=number]{width:100%}.seq-actions{flex-direction:column}.seq-actions .btn{width:100%}.anim-controls{flex-direction:column;align-items:stretch}.anim-controls .btn{width:100%}}
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
  <button class="tab" onclick="showTab('animation',this)">Animation Editor</button>
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
  <p style="color:var(--muted);font-size:12px;margin-bottom:10px">Build a color chase. Click colors to remove. Run to animate.</p>
  <div class="row">
    <input type="color" id="seqcolor" value="#ff0000">
    <button class="btn btn-sm" onclick="addSeqColor()">Add</button>
    <button class="btn btn-sm btn-danger" onclick="clearSeq()">Clear</button>
    <button class="btn btn-sm btn-success" onclick="runSeq()">Run</button>
    <button class="btn btn-sm btn-ghost" onclick="stopSeq()">Stop</button>
  </div>
  <div class="seq-builder" id="seqbuilder"></div>
  <div class="row" style="margin-top:10px">
    <span class="label">Delay (ms)</span>
    <input type="number" id="seqdelay" value="300" min="50" max="2000" style="width:70px">
    <span class="label">Name</span>
    <input type="text" id="seqname" placeholder="my_sequence" style="width:140px">
    <button class="btn btn-sm btn-purple" onclick="saveSeq()">Save</button>
    <button class="btn btn-sm btn-cyan" onclick="syncHA()">Sync All to HA+GH</button>
  </div>
</div>
<div class="card">
  <h2>Saved Sequences</h2>
  <div class="seqlist" id="seqlist"></div>
</div>
</div>
</div>

<!-- Animation Editor -->
<div id="tab-animation" style="display:none">
<div class="card">
  <h2>Animation Editor</h2>
  <p style="color:var(--muted);font-size:12px;margin-bottom:10px">Frame-by-frame animation. Click LEDs to paint. Use the timeline to manage frames.</p>
  <div class="row">
    <span class="label">Paint color</span>
    <input type="color" id="animcolor" value="#ff0000">
    <span class="label">Brush</span>
    <select id="brushsize"><option value="1">1 LED</option><option value="2">2 LEDs</option><option value="3">3 LEDs</option><option value="5">5 LEDs</option></select>
    <button class="btn btn-sm" onclick="fillFrame()">Fill Frame</button>
    <button class="btn btn-sm" onclick="clearFrame()">Clear Frame</button>
  </div>
  <div class="row" style="margin-top:6px">
    <button class="btn btn-sm btn-success" onclick="addFrame()">+ Add Frame</button>
    <button class="btn btn-sm btn-ghost" onclick="dupFrame()">Duplicate</button>
    <button class="btn btn-sm btn-danger" onclick="delFrame()">Delete Frame</button>
    <button class="btn btn-sm btn-ghost" onclick="reverseFrames()">Reverse</button>
    <span class="label" style="margin-left:8px">Frame <span id="frameinfo">0/0</span></span>
  </div>
  <div class="anim-preview" id="animpreview"><div class="led-row" id="previewrow"></div></div>
  <div class="anim-timeline" id="timeline" ondragover="event.preventDefault()" ondrop="handleDrop(event)"></div>
  <div class="anim-controls">
    <button class="btn btn-sm btn-success" onclick="playAnim()">Play</button>
    <button class="btn btn-sm btn-danger" onclick="stopAnim()">Stop</button>
    <span class="label">FPS</span>
    <input type="range" id="animfps" min="1" max="30" value="10" oninput="document.getElementById('fpsv').textContent=this.value">
    <span id="fpsv">10</span>
    <span class="label">Frame delay (ms)</span>
    <input type="number" id="framedelay" value="100" min="30" max="2000" style="width:70px">
    <button class="btn btn-sm" onclick="updateFrameDelay()">Set</button>
    <button class="btn btn-sm btn-purple" onclick="saveAnim()">Save Animation</button>
  </div>
  <div class="row" style="margin-top:8px">
    <span class="label">Name</span>
    <input type="text" id="animname" placeholder="my_animation" style="width:160px">
    <button class="btn btn-sm btn-ghost" onclick="loadAnimList()">Load</button>
    <select id="animlist" style="min-width:160px"><option value="">-- saved --</option></select>
    <button class="btn btn-sm" onclick="loadAnim()">Load Selected</button>
    <button class="btn btn-sm btn-danger" onclick="deleteAnim()">Delete</button>
  </div>
  <div class="led-grid" id="animgrid"></div>
</div>
</div>

<!-- Per-LED -->
<div id="tab-leds" style="display:none">
<div class="card">
  <h2>Per-LED Control</h2>
  <div class="row">
    <span class="label">Index</span>
    <input type="number" id="pixi" value="0" min="0" max="1023" style="width:70px">
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
  <p style="color:var(--muted);font-size:12px;margin-top:8px">Set a base color first (Control tab). Color-based effects use the current color.</p>
</div>
</div>

<div class="log" id="log"></div>
<div class="toast" id="toast"></div>
<script>
let seqColors=[];
let animFrames=[];
let currentFrame=0;
let animPlaying=false;
let animInterval=null;
let ledColors=new Array(81).fill('#000000');
let paintColor='#ff0000';
let isPainting=false;

function showTab(t,el){document.querySelectorAll('[id^=tab-]').forEach(e=>e.style.display='none');document.getElementById('tab-'+t).style.display='block';document.querySelectorAll('.tab').forEach(e=>e.classList.remove('active'));el.classList.add('active');if(t==='animation'){renderTimeline();renderAnimGrid();renderPreview();}}
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

// Animation Editor

function renderAnimGrid(){
  const grid=document.getElementById('animgrid');
  grid.innerHTML='';
  for(let i=0;i<81;i++){
    const d=document.createElement('div');
    d.className='led-cell';
    d.style.background=ledColors[i];
    d.title='LED '+i;
    d.onmousedown=()=>{isPainting=true;paintLed(i);};
    d.onmouseenter=()=>{if(isPainting)paintLed(i);};
    d.onmouseup=()=>{isPainting=false;};
    grid.appendChild(d);
  }
  document.onmouseup=()=>{isPainting=false;};
}
function paintLed(i){
  if(animPlaying){stopAnim();toast('Stopped animation');}
  const bs=parseInt(document.getElementById('brushsize').value);
  for(let d=0;d<bs;d++){
    if(i+d<81){ledColors[i+d]=paintColor;document.querySelectorAll('#animgrid .led-cell')[i+d].style.background=paintColor;}
  }
  if(animFrames.length>0 && currentFrame>=0 && currentFrame<animFrames.length){
    animFrames[currentFrame]=[...ledColors];
  }
}
function fillFrame(){
  if(animPlaying){stopAnim();toast('Stopped animation first');}
  if(animFrames.length===0){toast('Add a frame first');return;}
  for(let i=0;i<81;i++){ledColors[i]=paintColor;}
  renderAnimGrid();
  animFrames[currentFrame]=[...ledColors];
  toast('Frame '+ (currentFrame+1) +' filled');
}
function clearFrame(){
  if(animPlaying){stopAnim();toast('Stopped animation first');}
  if(animFrames.length===0){toast('Add a frame first');return;}
  for(let i=0;i<81;i++){ledColors[i]='#000000';}
  renderAnimGrid();
  animFrames[currentFrame]=[...ledColors];
  toast('Frame '+ (currentFrame+1) +' cleared');
}
function updateFrameInfo(){
  const el=document.getElementById('frameinfo');
  if(el) el.textContent=(animFrames.length?currentFrame+1:0)+'/'+animFrames.length;
}
document.addEventListener('DOMContentLoaded',()=>{
  const pc=document.getElementById('animcolor');
  if(pc) pc.addEventListener('input',e=>{paintColor=e.target.value;});
});

function renderTimeline(){
  const tl=document.getElementById('timeline');
  tl.innerHTML='';
  if(!animFrames.length){tl.innerHTML='<div style="color:var(--muted);font-size:12px;padding:20px">No frames. Click "+ Add Frame" to start.</div>';return;}
  animFrames.forEach((f,i)=>{
    const div=document.createElement('div');
    div.className='anim-frame'+(i===currentFrame?' active':'');
    div.draggable=true;
    div.dataset.index=i;
    // render mini preview
    const canvas=document.createElement('canvas');
    canvas.width=60;canvas.height=60;
    const ctx=canvas.getContext('2d');
    const w=60/f.length;
    f.forEach((c,j)=>{ctx.fillStyle=c;ctx.fillRect(j*w,0,w,60);});
    div.appendChild(canvas);
    const num=document.createElement('div');num.className='frame-num';num.textContent=i+1;div.appendChild(num);
    const del=document.createElement('div');del.className='frame-del';del.textContent='×';del.onclick=(e)=>{e.stopPropagation();delFrame(i);};div.appendChild(del);
    div.onclick=()=>{loadFrame(i);};
    div.ondragstart=(e)=>{e.dataTransfer.setData('text/plain',i);div.style.opacity='0.4';};
    div.ondragend=(e)=>{div.style.opacity='1';};
    div.ondragover=(e)=>{e.preventDefault();div.style.border='2px solid var(--accent2)';};
    div.ondragleave=(e)=>{div.style.border='';};
    div.ondrop=(e)=>{e.preventDefault();e.stopPropagation();div.style.border='';const from=parseInt(e.dataTransfer.getData('text/plain'));if(from!==i){const item=animFrames.splice(from,1)[0];animFrames.splice(i,0,item);if(currentFrame===from)currentFrame=i;else if(from<currentFrame && i>=currentFrame)currentFrame--;else if(from>currentFrame && i<=currentFrame)currentFrame++;loadFrame(currentFrame);renderTimeline();renderPreview();toast('Frame moved');}};
    tl.appendChild(div);
  });
}
function renderPreview(){
  const row=document.getElementById('previewrow');
  if(!row) return;
  row.innerHTML='';
  const f=animFrames[currentFrame];
  if(!f) return;
  f.forEach(c=>{const d=document.createElement('div');d.className='led-px';d.style.background=c;row.appendChild(d);});
}
function loadFrame(i){
  if(i<0||i>=animFrames.length) return;
  if(animFrames.length>0 && currentFrame>=0 && currentFrame<animFrames.length){
    animFrames[currentFrame]=[...ledColors];
  }
  currentFrame=i;
  ledColors=[...animFrames[i]];
  renderAnimGrid();
  renderPreview();
  renderTimeline();
  updateFrameInfo();
}
function addFrame(){
  const frame=[...ledColors];
  animFrames.push(frame);
  currentFrame=animFrames.length-1;
  renderTimeline();
  renderPreview();
  updateFrameInfo();
  toast('Frame '+animFrames.length+' added');
}
function dupFrame(){
  if(!animFrames.length) return;
  animFrames.splice(currentFrame+1,0,[...animFrames[currentFrame]]);
  currentFrame++;
  loadFrame(currentFrame);
  renderTimeline();
  updateFrameInfo();
  toast('Frame duplicated');
}
function delFrame(idx){
  if(idx===undefined) idx=currentFrame;
  if(animFrames.length<=1){toast('Need at least 1 frame');return;}
  animFrames.splice(idx,1);
  if(currentFrame>=animFrames.length) currentFrame=animFrames.length-1;
  loadFrame(currentFrame);
  renderTimeline();
  renderPreview();
  updateFrameInfo();
  toast('Frame deleted');
}
function reverseFrames(){
  if(animFrames.length<2){toast('Need at least 2 frames');return;}
  // Save current frame first
  if(animFrames.length>0 && currentFrame>=0 && currentFrame<animFrames.length){
    animFrames[currentFrame]=[...ledColors];
  }
  animFrames.reverse();
  currentFrame=animFrames.length-1-currentFrame;
  loadFrame(currentFrame);
  renderTimeline();
  renderPreview();
  updateFrameInfo();
  toast('Frames reversed');
}
function updateFrameDelay(){
  // store per-frame delay
  if(animFrames[currentFrame]) animFrames[currentFrame]._delay=parseInt(document.getElementById('framedelay').value)||100;
}
function playAnim(){
  if(animPlaying) return;
  if(!animFrames.length){toast('No frames');return;}
  animPlaying=true;
  const fps=parseInt(document.getElementById('animfps').value)||10;
  const delay=1000/fps;
  let i=currentFrame;
  animInterval=setInterval(()=>{
    i=(i+1)%animFrames.length;
    currentFrame=i;
    loadFrame(i);
    renderTimeline();
    renderPreview();
    // stream to device
    const f=animFrames[i];
    const cmd='FRAME '+f.map(c=>c.replace('#','')).join(',');
    fetch('/api/cmd',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:cmd})});
  },delay);
  toast('Playing');
}
function stopAnim(){
  if(animInterval){clearInterval(animInterval);animInterval=null;}
  animPlaying=false;
  toast('Stopped');
}
async function saveAnim(){
  const name=document.getElementById('animname').value.trim();
  if(!name||!animFrames.length){toast('Name and frames required');return;}
  const delay=parseInt(document.getElementById('framedelay').value)||100;
  const frames=animFrames.map(f=>f.map(c=>c));
  const res=await fetch('/api/anim/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name,frames:frames,delay:delay/1000.0})});
  const t=await res.text();
  toast(t);
  loadAnimList();
}
function loadAnimList(){
  fetch('/api/anim/list').then(r=>r.json()).then(data=>{
    const sel=document.getElementById('animlist');
    sel.innerHTML='<option value="">-- saved --</option>';
    Object.keys(data).forEach(n=>{const o=document.createElement('option');o.value=n;o.textContent=n+' ('+data[n].frames.length+' frames)';sel.appendChild(o);});
  });
}
function loadAnim(){
  const name=document.getElementById('animlist').value;
  if(!name) return;
  fetch('/api/anim/get?name='+encodeURIComponent(name)).then(r=>r.json()).then(data=>{
    animFrames=data.frames.map(f=>[...f]);
    currentFrame=0;
    loadFrame(0);
    renderTimeline();
    renderPreview();
    document.getElementById('animname').value=name;
    document.getElementById('framedelay').value=Math.round((data.delay||0.1)*1000);
    toast('Loaded '+name);
  });
}
function deleteAnim(){
  const name=document.getElementById('animlist').value;
  if(!name) return;
  fetch('/api/anim/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name})}).then(r=>r.text()).then(t=>{toast(t);loadAnimList();});
}
function syncOneSeq(name){fetch('/api/sync',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name})}).then(r=>r.text()).then(t=>toast(t));}
function syncHA(){fetch('/api/sync',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({all:true})}).then(r=>r.text()).then(t=>toast(t));}
function setPix(){const i=document.getElementById('pixi').value;const hex=document.getElementById('pixcolor').value;const r=parseInt(hex.slice(1,3),16);const g=parseInt(hex.slice(3,5),16);const b=parseInt(hex.slice(5,7),16);cmd('PIX '+i+' '+r+' '+g+' '+b);}
function fillAll(){const hex=document.getElementById('fillcolor').value;const r=parseInt(hex.slice(1,3),16);const g=parseInt(hex.slice(3,5),16);const b=parseInt(hex.slice(5,7),16);cmd('FILL '+r+' '+g+' '+b);}
function refreshState(){fetch('/api/cmd',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd:'STATE'})}).then(r=>r.text()).then(t=>document.getElementById('status').textContent=t);}
// LED grid for per-LED
const grid=document.getElementById('ledgrid');
for(let i=0;i<81;i++){const d=document.createElement('div');d.className='led-cell';d.title='LED '+i;d.onclick=()=>{document.getElementById('pixi').value=i;};grid.appendChild(d);}
// Anim grid
renderAnimGrid();
loadSeqs(); loadAnimList(); refreshState(); updateFrameInfo();
// Keyboard shortcuts
document.addEventListener('keydown',e=>{
  if(e.target.tagName==='INPUT'||e.target.tagName==='TEXTAREA'||e.target.tagName==='SELECT') return;
  if(e.code==='Space'){e.preventDefault();animPlaying?stopAnim():playAnim();}
  if(e.code==='ArrowRight'){e.preventDefault();if(currentFrame<animFrames.length-1)loadFrame(currentFrame+1);}
  if(e.code==='ArrowLeft'){e.preventDefault();if(currentFrame>0)loadFrame(currentFrame-1);}
  if(e.code==='KeyN'){e.preventDefault();addFrame();}
  if(e.code==='KeyD'){e.preventDefault();dupFrame();}
  if(e.code==='Delete'){e.preventDefault();delFrame();}
});
</script></body></html>"""

anim_thread = None
anim_stop = threading.Event()


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
        elif self.path.startswith("/api/anim/list"):
            anims = load_anims()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({k: {"frames": len(v.get("frames", [])), "delay": v.get("delay", 0.1)} for k, v in anims.items()}).encode())
        elif self.path.startswith("/api/anim/get"):
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            name = qs.get("name", [""])[0]
            anims = load_anims()
            anim = anims.get(name, {})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(anim).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
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
            def runner():
                seq = seqs.get(name, {})
                colors = seq.get("colors", [])
                delay = seq.get("delay", 0.3)
                while True:
                    for hexc in colors:
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
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Stopped")
        elif self.path == "/api/anim/save":
            name = data.get("name", "").strip()
            if not name:
                self.send_response(400); self.end_headers(); self.wfile.write(b"Name required"); return
            anims = load_anims()
            anims[name] = {"frames": data.get("frames", []), "delay": data.get("delay", 0.1)}
            save_anims(anims)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"Saved animation '{name}' ({len(data.get('frames',[]))} frames)".encode())
        elif self.path == "/api/anim/delete":
            name = data.get("name", "")
            anims = load_anims()
            if name in anims:
                del anims[name]
                save_anims(anims)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"Deleted '{name}'".encode())
        elif self.path == "/api/anim/play":
            name = data.get("name", "")
            anims = load_anims()
            anim = anims.get(name, {})
            frames = anim.get("frames", [])
            delay = anim.get("delay", 0.1)
            def runner():
                while True:
                    for frame in frames:
                        colors = [(c[0], c[1], c[2]) for c in frame]
                        send_frame(colors)
                        time.sleep(delay)
            t = threading.Thread(target=runner, daemon=True)
            t.start()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(f"Playing '{name}'".encode())
        elif self.path == "/api/anim/stop":
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
