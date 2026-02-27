#!/usr/bin/env python3
"""
Web UI for Lenovo Legion Gen 10 Spectrum Lighting Controller.
Run with: sudo python3 spectrum-web.py
Then open http://localhost:5555
"""

import http.server
import json
import subprocess
import html
import sys
import os

PORT = 5555
SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'spectrum-ctl.py')

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Legion Spectrum Control</title>
<style>
:root {
    --bg: #0d0d0d;
    --card: #1a1a1a;
    --border: #333;
    --text: #e0e0e0;
    --accent: #4fc3f7;
    --accent2: #e040fb;
    --dim: #888;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    padding: 1.5rem;
}
h1 {
    font-size: 1.4rem;
    font-weight: 600;
    margin-bottom: 1.5rem;
    color: var(--accent);
    display: flex;
    align-items: center;
    gap: 0.5rem;
}
h1 .dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: #4caf50;
    animation: pulse 2s infinite;
}
@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
}
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 1rem; }
.card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1.2rem;
}
.card h2 {
    font-size: 0.85rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--dim);
    margin-bottom: 1rem;
}
.status-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.5rem 0;
    border-bottom: 1px solid var(--border);
}
.status-row:last-child { border-bottom: none; }
.status-label { color: var(--dim); font-size: 0.9rem; }
.status-value { font-weight: 600; font-size: 0.95rem; }
.slider-row {
    display: flex;
    align-items: center;
    gap: 1rem;
    margin: 0.8rem 0;
}
.slider-row label { min-width: 80px; color: var(--dim); font-size: 0.9rem; }
.slider-row input[type=range] { flex: 1; accent-color: var(--accent); }
.slider-row .val { min-width: 24px; text-align: center; font-weight: 600; }
.btn-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
    gap: 0.5rem;
}
.btn {
    padding: 0.65rem 0.8rem;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--bg);
    color: var(--text);
    cursor: pointer;
    font-size: 0.85rem;
    transition: all 0.15s;
    text-align: center;
}
.btn:hover { border-color: var(--accent); color: var(--accent); }
.btn:active { transform: scale(0.97); }
.btn.active { border-color: var(--accent); background: rgba(79, 195, 247, 0.12); color: var(--accent); }
.color-row {
    display: flex;
    align-items: center;
    gap: 0.8rem;
    margin: 0.6rem 0;
}
.color-row label { min-width: 80px; color: var(--dim); font-size: 0.9rem; }
input[type=color] {
    width: 48px; height: 32px;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--bg);
    cursor: pointer;
    padding: 2px;
}
.color-swatches {
    display: flex;
    gap: 0.4rem;
    flex-wrap: wrap;
}
.swatch {
    width: 28px; height: 28px;
    border-radius: 4px;
    border: 2px solid var(--border);
    cursor: pointer;
    transition: all 0.15s;
}
.swatch:hover { border-color: #fff; transform: scale(1.15); }
select {
    padding: 0.5rem;
    background: var(--bg);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 4px;
    font-size: 0.9rem;
}
.toggle {
    display: flex;
    align-items: center;
    gap: 0.8rem;
    cursor: pointer;
    padding: 0.5rem 0;
}
.toggle-switch {
    width: 44px; height: 24px;
    border-radius: 12px;
    background: #444;
    position: relative;
    transition: background 0.2s;
}
.toggle-switch.on { background: var(--accent); }
.toggle-switch::after {
    content: '';
    position: absolute;
    top: 3px; left: 3px;
    width: 18px; height: 18px;
    border-radius: 50%;
    background: white;
    transition: transform 0.2s;
}
.toggle-switch.on::after { transform: translateX(20px); }
.zone-select { display: flex; gap: 0.4rem; flex-wrap: wrap; margin: 0.6rem 0; }
.zone-chip {
    padding: 0.35rem 0.7rem;
    border: 1px solid var(--border);
    border-radius: 20px;
    font-size: 0.8rem;
    cursor: pointer;
    transition: all 0.15s;
}
.zone-chip:hover { border-color: var(--accent); }
.zone-chip.selected { background: rgba(79, 195, 247, 0.15); border-color: var(--accent); color: var(--accent); }
.toast {
    position: fixed;
    bottom: 1.5rem;
    right: 1.5rem;
    padding: 0.7rem 1.2rem;
    border-radius: 6px;
    font-size: 0.85rem;
    opacity: 0;
    transform: translateY(10px);
    transition: all 0.3s;
    pointer-events: none;
    z-index: 100;
}
.toast.show { opacity: 1; transform: translateY(0); }
.toast.ok { background: #1b5e20; color: #a5d6a7; }
.toast.err { background: #b71c1c; color: #ef9a9a; }
.apply-btn {
    width: 100%;
    padding: 0.8rem;
    margin-top: 1rem;
    border: none;
    border-radius: 6px;
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    color: white;
    font-size: 0.95rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
}
.apply-btn:hover { filter: brightness(1.15); }
.apply-btn:active { transform: scale(0.98); }
.quick-presets { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.5rem; }
</style>
</head>
<body>

<h1><span class="dot"></span> Legion Spectrum Control</h1>

<div class="grid">

<!-- Status Card -->
<div class="card" id="status-card">
    <h2>Status</h2>
    <div class="status-row">
        <span class="status-label">Brightness</span>
        <span class="status-value" id="st-brightness">-</span>
    </div>
    <div class="status-row">
        <span class="status-label">Profile</span>
        <span class="status-value" id="st-profile">-</span>
    </div>
    <div class="status-row">
        <span class="status-label">Logo</span>
        <span class="status-value" id="st-logo">-</span>
    </div>
    <div class="slider-row">
        <label>Brightness</label>
        <input type="range" id="brightness-slider" min="0" max="9" value="3">
        <span class="val" id="brightness-val">3</span>
    </div>
    <div class="toggle" onclick="toggleLogo()">
        <div class="toggle-switch" id="logo-toggle"></div>
        <span style="color: var(--dim); font-size: 0.9rem;">LEGION logo</span>
    </div>
</div>

<!-- Quick Presets -->
<div class="card">
    <h2>Quick Presets</h2>
    <div class="btn-grid">
        <button class="btn" onclick="run('on')">Lights On</button>
        <button class="btn" onclick="run('stealth')">All Off</button>
        <button class="btn" onclick="run('white')">White Keys</button>
        <button class="btn" onclick="run('rgb')">Rainbow</button>
        <button class="btn" onclick="run('multi keyboard:static:white perimeter:static:blue')">White + Blue Edge</button>
        <button class="btn" onclick="run('multi keyboard:static:white perimeter:static:red')">White + Red Edge</button>
        <button class="btn" onclick="run('multi keyboard:rain:cyan perimeter:static:off')">Cyan Rain</button>
        <button class="btn" onclick="run('multi keyboard:color-wave:red,orange perimeter:static:off')">Lava Keys</button>
        <button class="btn" onclick="run('multi keyboard:static:off perimeter:rainbow-wave')">Edge Rainbow</button>
        <button class="btn" onclick="run('multi keyboard:type:cyan perimeter:static:off')">Type Glow</button>
        <button class="btn" onclick="run('multi keyboard:color-pulse:purple,blue perimeter:color-pulse:purple,blue')">Purple Pulse</button>
    </div>
</div>

<!-- Custom Effect -->
<div class="card">
    <h2>Custom Effect</h2>

    <div style="margin-bottom: 0.8rem;">
        <label style="color: var(--dim); font-size: 0.9rem; display: block; margin-bottom: 0.3rem;">Effect</label>
        <select id="effect-select" style="width: 100%;">
            <option value="static">Static</option>
            <option value="rainbow-wave">Rainbow Wave</option>
            <option value="screw-rainbow">Screw Rainbow</option>
            <option value="color-change">Color Change</option>
            <option value="color-pulse">Color Pulse</option>
            <option value="color-wave">Color Wave</option>
            <option value="smooth">Smooth</option>
            <option value="rain">Rain</option>
            <option value="ripple">Ripple</option>
            <option value="type">Type Lighting</option>
        </select>
    </div>

    <label style="color: var(--dim); font-size: 0.9rem;">Zones</label>
    <div class="zone-select" id="zone-select">
        <span class="zone-chip selected" data-zone="keyboard" onclick="toggleZone(this)">Keyboard</span>
        <span class="zone-chip" data-zone="perimeter" onclick="toggleZone(this)">Perimeter</span>
        <span class="zone-chip" data-zone="logo" onclick="toggleZone(this)">Logo</span>
    </div>

    <div class="color-row">
        <label>Color 1</label>
        <input type="color" id="color1" value="#ffffff">
        <div class="color-swatches">
            <div class="swatch" style="background:#fff" onclick="setColor('color1','#ffffff')"></div>
            <div class="swatch" style="background:#ff0000" onclick="setColor('color1','#ff0000')"></div>
            <div class="swatch" style="background:#00ff00" onclick="setColor('color1','#00ff00')"></div>
            <div class="swatch" style="background:#0088ff" onclick="setColor('color1','#0088ff')"></div>
            <div class="swatch" style="background:#ff8800" onclick="setColor('color1','#ff8800')"></div>
            <div class="swatch" style="background:#ff00ff" onclick="setColor('color1','#ff00ff')"></div>
            <div class="swatch" style="background:#00ffff" onclick="setColor('color1','#00ffff')"></div>
            <div class="swatch" style="background:#8800ff" onclick="setColor('color1','#8800ff')"></div>
        </div>
    </div>
    <div class="color-row">
        <label>Color 2</label>
        <input type="color" id="color2" value="#000000">
        <div class="color-swatches">
            <div class="swatch" style="background:#000;border-color:#555" onclick="setColor('color2','#000000')"></div>
            <div class="swatch" style="background:#ff0000" onclick="setColor('color2','#ff0000')"></div>
            <div class="swatch" style="background:#0088ff" onclick="setColor('color2','#0088ff')"></div>
            <div class="swatch" style="background:#ff8800" onclick="setColor('color2','#ff8800')"></div>
            <div class="swatch" style="background:#ff00ff" onclick="setColor('color2','#ff00ff')"></div>
            <div class="swatch" style="background:#00ffff" onclick="setColor('color2','#00ffff')"></div>
        </div>
    </div>

    <div class="slider-row">
        <label>Speed</label>
        <input type="range" id="speed-slider" min="1" max="3" value="2">
        <span class="val" id="speed-val">2</span>
    </div>

    <button class="apply-btn" onclick="applyCustom()">Apply Effect</button>
</div>

<!-- Hardware Monitor -->
<div class="card">
    <h2>Hardware Monitor</h2>
    <div>
        <div class="status-row">
            <span class="status-label">Platform Profile</span>
            <span class="status-value" id="sys-profile">-</span>
        </div>
        <div class="status-row">
            <span class="status-label">Fan 1 (CPU)</span>
            <span class="status-value" id="sys-fan1">-</span>
        </div>
        <div class="status-row">
            <span class="status-label">Fan 2 (GPU)</span>
            <span class="status-value" id="sys-fan2">-</span>
        </div>
        <div class="status-row">
            <span class="status-label">Fan 3 (GPU2)</span>
            <span class="status-value" id="sys-fan3">-</span>
        </div>
        <div class="status-row">
            <span class="status-label">CPU Temp</span>
            <span class="status-value" id="sys-cputemp">-</span>
        </div>
        <div class="status-row">
            <span class="status-label">GPU Temp</span>
            <span class="status-value" id="sys-gputemp">-</span>
        </div>
    </div>
    <button class="btn" style="width:100%;margin-top:0.8rem;" onclick="refreshSysStatus()">Refresh</button>
</div>

<!-- Multi-Zone -->
<div class="card">
    <h2>Multi-Zone Builder</h2>
    <p style="color: var(--dim); font-size: 0.8rem; margin-bottom: 0.8rem;">Set different effects for keyboard, perimeter, and logo independently.</p>

    <div style="margin-bottom: 0.8rem;">
        <label style="color: var(--dim); font-size: 0.85rem;">Keyboard</label>
        <div style="display:flex; gap:0.5rem; margin-top:0.3rem;">
            <select id="mz-kb-effect" style="flex:1;"><option value="static">Static</option><option value="rainbow-wave">Rainbow Wave</option><option value="color-change">Color Change</option><option value="color-pulse">Color Pulse</option><option value="color-wave">Color Wave</option><option value="smooth">Smooth</option><option value="rain">Rain</option><option value="ripple">Ripple</option><option value="type">Type Lighting</option></select>
            <input type="color" id="mz-kb-color" value="#ffffff">
        </div>
    </div>
    <div style="margin-bottom: 0.8rem;">
        <label style="color: var(--dim); font-size: 0.85rem;">Perimeter</label>
        <div style="display:flex; gap:0.5rem; margin-top:0.3rem;">
            <select id="mz-pr-effect" style="flex:1;"><option value="static">Static</option><option value="static" data-off>Off</option><option value="rainbow-wave">Rainbow Wave</option><option value="color-change">Color Change</option><option value="color-pulse">Color Pulse</option><option value="color-wave">Color Wave</option><option value="smooth">Smooth</option></select>
            <input type="color" id="mz-pr-color" value="#000000">
        </div>
    </div>
    <div style="margin-bottom: 0.8rem;">
        <label style="color: var(--dim); font-size: 0.85rem;">Logo</label>
        <div style="display:flex; gap:0.5rem; margin-top:0.3rem;">
            <select id="mz-lo-effect" style="flex:1;"><option value="static">Static</option><option value="color-pulse">Pulse</option></select>
            <input type="color" id="mz-lo-color" value="#000000">
        </div>
    </div>

    <button class="apply-btn" onclick="applyMultiZone()">Apply Multi-Zone</button>
</div>

</div>

<div class="toast" id="toast"></div>

<script>
const API = '/api';

function toast(msg, ok=true) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.className = 'toast show ' + (ok ? 'ok' : 'err');
    setTimeout(() => t.className = 'toast', 2000);
}

async function api(cmd) {
    try {
        const r = await fetch(API, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({cmd})
        });
        const d = await r.json();
        if (d.ok) { toast(d.output || 'OK'); }
        else { toast(d.output || 'Error', false); }
        return d;
    } catch(e) {
        toast('Connection error', false);
    }
}

async function run(cmdStr) {
    await api(cmdStr);
    refreshStatus();
}

async function refreshStatus() {
    const d = await api('status');
    if (!d || !d.ok) return;
    const lines = d.output.split('\n');
    for (const line of lines) {
        const [k, v] = line.split(':').map(s => s.trim());
        if (k === 'Brightness') {
            document.getElementById('st-brightness').textContent = v;
            const n = parseInt(v);
            document.getElementById('brightness-slider').value = n;
            document.getElementById('brightness-val').textContent = n;
        }
        if (k === 'Profile') document.getElementById('st-profile').textContent = v;
        if (k === 'Logo') {
            document.getElementById('st-logo').textContent = v;
            const tog = document.getElementById('logo-toggle');
            tog.className = 'toggle-switch' + (v === 'on' ? ' on' : '');
        }
    }
}

// Brightness slider
const bslider = document.getElementById('brightness-slider');
let bTimeout;
bslider.addEventListener('input', () => {
    document.getElementById('brightness-val').textContent = bslider.value;
    clearTimeout(bTimeout);
    bTimeout = setTimeout(() => run('brightness ' + bslider.value), 200);
});

// Speed slider
const sspeed = document.getElementById('speed-slider');
sspeed.addEventListener('input', () => {
    document.getElementById('speed-val').textContent = sspeed.value;
});

function toggleLogo() {
    const tog = document.getElementById('logo-toggle');
    const isOn = tog.classList.contains('on');
    run('logo ' + (isOn ? 'off' : 'on'));
}

function setColor(id, hex) {
    document.getElementById(id).value = hex;
}

function toggleZone(el) {
    el.classList.toggle('selected');
}

function getSelectedZones() {
    return [...document.querySelectorAll('.zone-chip.selected')].map(e => e.dataset.zone);
}

async function applyCustom() {
    const effect = document.getElementById('effect-select').value;
    const zones = getSelectedZones();
    const c1 = document.getElementById('color1').value;
    const c2 = document.getElementById('color2').value;
    const speed = document.getElementById('speed-slider').value;

    if (!zones.length) { toast('Select at least one zone', false); return; }

    // Build multi command for selected zones with effect, unselected zones get off
    const allZones = ['keyboard', 'perimeter', 'logo'];
    const parts = [];
    for (const z of allZones) {
        if (zones.includes(z)) {
            let colors = c1;
            if (c2 !== '#000000') colors += ',' + c2;
            parts.push(z + ':' + effect + ':' + colors + ':' + speed);
        } else {
            parts.push(z + ':static:off');
        }
    }
    await run('multi ' + parts.join(' '));
}

async function applyMultiZone() {
    const kbEffect = document.getElementById('mz-kb-effect').value;
    const kbColor = document.getElementById('mz-kb-color').value;
    const prEffect = document.getElementById('mz-pr-effect').value;
    const prColor = document.getElementById('mz-pr-color').value;
    const loEffect = document.getElementById('mz-lo-effect').value;
    const loColor = document.getElementById('mz-lo-color').value;

    const cmd = `multi keyboard:${kbEffect}:${kbColor} perimeter:${prEffect}:${prColor} logo:${loEffect}:${loColor}`;
    await run(cmd);
}

// Hardware Monitor
async function refreshSysStatus() {
    try {
        const r = await fetch('/sys', {method: 'GET'});
        const d = await r.json();
        if (!d) return;
        document.getElementById('sys-profile').textContent = d.profile || '-';
        document.getElementById('sys-fan1').textContent = d.fan1 ? d.fan1 + ' RPM' : '-';
        document.getElementById('sys-fan2').textContent = d.fan2 ? d.fan2 + ' RPM' : '-';
        document.getElementById('sys-fan3').textContent = d.fan3 ? d.fan3 + ' RPM' : '-';
        document.getElementById('sys-cputemp').textContent = d.cpu_temp ? d.cpu_temp + '\u00b0C' : '-';
        document.getElementById('sys-gputemp').textContent = d.gpu_temp ? d.gpu_temp + '\u00b0C' : '-';
    } catch(e) {}
}

// Init
refreshStatus();
refreshSysStatus();
setInterval(refreshSysStatus, 5000);
</script>
</body>
</html>"""


SYSFS_LEDS = {
    'ylogo': '/sys/class/leds/platform::ylogo/brightness',
    'ioport': '/sys/class/leds/platform::ioport/brightness',
    'kbd_backlight': '/sys/class/leds/platform::kbd_backlight/brightness',
}

def read_sysfs(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return None

def write_sysfs(path, value):
    try:
        with open(path, 'w') as f:
            f.write(str(value))
        return True
    except Exception:
        return False

def find_legion_hwmon():
    import glob
    for d in glob.glob('/sys/class/hwmon/hwmon*/'):
        name = read_sysfs(d + 'name')
        if name == 'legion_hwmon':
            return d
    return None


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # quiet

    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(HTML.encode())
        elif self.path == '/sys':
            data = {}
            for name, path in SYSFS_LEDS.items():
                v = read_sysfs(path)
                data[name] = int(v) if v and v.isdigit() else 0
            data['profile'] = read_sysfs('/sys/firmware/acpi/platform_profile') or ''
            hwmon = find_legion_hwmon()
            if hwmon:
                for i, key in [(1, 'fan1'), (2, 'fan2'), (3, 'fan3')]:
                    v = read_sysfs(hwmon + f'fan{i}_input')
                    data[key] = int(v) if v and v.isdigit() else None
                for i, key in [(1, 'cpu_temp'), (2, 'gpu_temp')]:
                    v = read_sysfs(hwmon + f'temp{i}_input')
                    data[key] = round(int(v) / 1000, 1) if v and v.isdigit() else None
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        elif self.path == '/favicon.ico':
            self.send_response(204)
            self.end_headers()
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == '/sys':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            led = body.get('led', '')
            value = body.get('value', 0)
            ok = False
            if led in SYSFS_LEDS:
                ok = write_sysfs(SYSFS_LEDS[led], int(value))
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'ok': ok}).encode())
            return
        if self.path == '/api':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            cmd = body.get('cmd', '')

            try:
                result = subprocess.run(
                    ['python3', SCRIPT] + cmd.split(),
                    capture_output=True, text=True, timeout=10,
                )
                output = (result.stdout + result.stderr).strip()
                # Strip the "Using device:" line
                lines = [l for l in output.split('\n') if not l.startswith('Using device:')]
                output = '\n'.join(lines)
                ok = result.returncode == 0

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'ok': ok, 'output': output}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'output': str(e)}).encode())
        else:
            self.send_error(404)


def main():
    if os.geteuid() != 0:
        print("This needs root for hidraw access. Run with: sudo python3 spectrum-web.py")
        sys.exit(1)

    server = http.server.HTTPServer(('0.0.0.0', PORT), Handler)
    print(f"Legion Spectrum Control running at http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == '__main__':
    main()
