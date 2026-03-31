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
import struct
import array
import fcntl
import glob as globmod
import threading

PORT = 5555
SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'spectrum-ctl.py')

# ---------------------------------------------------------------------------
# Inline HID helpers for fast preview (no subprocess spawn)
# ---------------------------------------------------------------------------
HIDIOCSFEATURE = lambda size: 0xC0004806 | (size << 16)
REPORT_SIZE = 960
OP_EFFECT_CHANGE = 0xCB
OP_PROFILE = 0xCA

_hid_lock = threading.Lock()
_hid_path = None

def _find_spectrum_hid():
    global _hid_path
    if _hid_path:
        return _hid_path
    for hidraw in sorted(globmod.glob('/sys/class/hidraw/hidraw*')):
        name = os.path.basename(hidraw)
        try:
            with open(f'{hidraw}/device/uevent') as f:
                uevent = f.read()
            if '048D' not in uevent.upper() or 'C197' not in uevent.upper():
                continue
            with open(f'{hidraw}/device/report_descriptor', 'rb') as f:
                desc = f.read()
            if b'\x06\x89\xff' in desc:
                _hid_path = f'/dev/{name}'
                return _hid_path
        except (IOError, OSError):
            continue
    return None

def _hid_set_feature(fd, data):
    buf = array.array('B', data[:REPORT_SIZE].ljust(REPORT_SIZE, b'\x00'))
    fcntl.ioctl(fd, HIDIOCSFEATURE(REPORT_SIZE), buf)

def _hid_get_feature(fd, report_id=0x07):
    buf = array.array('B', [report_id] + [0] * (REPORT_SIZE - 1))
    fcntl.ioctl(fd, 0xC0004807 | (REPORT_SIZE << 16), buf)
    return bytes(buf)

OP_GET_BRIGHTNESS = 0xCD
OP_BRIGHTNESS = 0xCE

def _send_keys_fast(key_color_map):
    """Send per-key static colors directly to HID — no subprocess.
    Opens and closes the device each time (same as CLI) for reliability."""
    with _hid_lock:
        path = _find_spectrum_hid()
        if not path:
            return False
        dev = open(path, 'rb+', buffering=0)
        try:
            # Get profile
            _hid_set_feature(dev, bytes([0x07, OP_PROFILE, 0xC0, 0x03]).ljust(REPORT_SIZE, b'\x00'))
            profile = _hid_get_feature(dev)[4]

            # Check brightness — bump to 3 if off (same as CLI)
            _hid_set_feature(dev, bytes([0x07, OP_GET_BRIGHTNESS, 0xC0, 0x03]).ljust(REPORT_SIZE, b'\x00'))
            brightness = _hid_get_feature(dev)[4]
            if brightness == 0:
                _hid_set_feature(dev, bytes([0x07, OP_BRIGHTNESS, 0xC0, 0x03, 3]).ljust(REPORT_SIZE, b'\x00'))

            # Group by color
            color_groups = {}
            for code, (r, g, b) in key_color_map.items():
                color_groups.setdefault((r, g, b), []).append(code)

            # Build effects
            effects = b''
            eno = 1
            for (r, g, b), codes in color_groups.items():
                color_mode = 0x02
                ehdr = bytes([eno, 0x06, 0x01, 11, 0x02, 0, 0x03, 0, 0x04, 0, 0x05, color_mode, 0x06, 0x00])
                ehdr += bytes([1, r, g, b])
                ehdr += bytes([len(codes)])
                for c in codes:
                    ehdr += struct.pack('<H', c)
                effects += ehdr
                eno += 1

            payload = bytes([profile, 0x01, 0x01]) + effects
            data = bytes([0x07, OP_EFFECT_CHANGE, 0xC0, 0x03]) + payload
            _hid_set_feature(dev, data)
            return True
        finally:
            dev.close()

# Effect types for per-key effects
EFFECT_TYPES = {
    'static': 11, 'type': 12, 'rain': 7, 'ripple': 8,
    'color-pulse': 4, 'color-wave': 5, 'rainbow-wave': 2,
    'smooth': 6, 'screw-rainbow': 1, 'color-change': 3,
}

def _send_effect_groups(groups):
    """Send multiple effect groups to HID. Each group: (effect_name, speed, colors, keycodes)."""
    with _hid_lock:
        path = _find_spectrum_hid()
        if not path:
            return False
        dev = open(path, 'rb+', buffering=0)
        try:
            _hid_set_feature(dev, bytes([0x07, OP_PROFILE, 0xC0, 0x03]).ljust(REPORT_SIZE, b'\x00'))
            profile = _hid_get_feature(dev)[4]
            _hid_set_feature(dev, bytes([0x07, OP_GET_BRIGHTNESS, 0xC0, 0x03]).ljust(REPORT_SIZE, b'\x00'))
            if _hid_get_feature(dev)[4] == 0:
                _hid_set_feature(dev, bytes([0x07, OP_BRIGHTNESS, 0xC0, 0x03, 3]).ljust(REPORT_SIZE, b'\x00'))

            effects = b''
            eno = 1
            for etype_name, speed, colors, codes in groups:
                etype = EFFECT_TYPES.get(etype_name, 11)
                color_mode = 0x02 if colors else 0x01
                ehdr = bytes([eno, 0x06, 0x01, etype, 0x02, speed, 0x03, 0, 0x04, 0, 0x05, color_mode, 0x06, 0x00])
                ehdr += bytes([len(colors)])
                for r, g, b in colors:
                    ehdr += bytes([r, g, b])
                ehdr += bytes([len(codes)])
                for c in codes:
                    ehdr += struct.pack('<H', c)
                effects += ehdr
                eno += 1

            payload = bytes([profile, 0x01, 0x01]) + effects
            data = bytes([0x07, OP_EFFECT_CHANGE, 0xC0, 0x03]) + payload
            _hid_set_feature(dev, data)
            return True
        finally:
            dev.close()

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
.color-row label { min-width: 80px; color: var(--dim); font-size: 0.9rem; display: flex; align-items: center; gap: 0.3rem; }
.color-row label input[type=checkbox] { accent-color: var(--accent); }
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
.kb-key:hover { filter: brightness(1.3); border-color: var(--accent) !important; z-index: 2; }
#keyboard { padding: 8px; background: #111; border-radius: 10px; border: 1px solid #222; }
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

    <div id="color-controls">
        <div class="color-row" id="color1-row">
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
        <div class="color-row extra-color" id="color2-row" style="display:none;">
            <label><input type="checkbox" id="color2-on" onchange="onColorToggle()"> Color 2</label>
            <input type="color" id="color2" value="#0088ff" disabled>
            <div class="color-swatches">
                <div class="swatch" style="background:#ff0000" onclick="setColor('color2','#ff0000')"></div>
                <div class="swatch" style="background:#0088ff" onclick="setColor('color2','#0088ff')"></div>
                <div class="swatch" style="background:#ff8800" onclick="setColor('color2','#ff8800')"></div>
                <div class="swatch" style="background:#ff00ff" onclick="setColor('color2','#ff00ff')"></div>
                <div class="swatch" style="background:#00ffff" onclick="setColor('color2','#00ffff')"></div>
            </div>
        </div>
        <div class="color-row extra-color" id="color3-row" style="display:none;">
            <label><input type="checkbox" id="color3-on" onchange="onColorToggle()"> Color 3</label>
            <input type="color" id="color3" value="#ff00ff" disabled>
            <div class="color-swatches">
                <div class="swatch" style="background:#ff0000" onclick="setColor('color3','#ff0000')"></div>
                <div class="swatch" style="background:#00ff00" onclick="setColor('color3','#00ff00')"></div>
                <div class="swatch" style="background:#0088ff" onclick="setColor('color3','#0088ff')"></div>
                <div class="swatch" style="background:#ff8800" onclick="setColor('color3','#ff8800')"></div>
                <div class="swatch" style="background:#00ffff" onclick="setColor('color3','#00ffff')"></div>
            </div>
        </div>
        <div class="color-row extra-color" id="color4-row" style="display:none;">
            <label><input type="checkbox" id="color4-on" onchange="onColorToggle()"> Color 4</label>
            <input type="color" id="color4" value="#00ffff" disabled>
            <div class="color-swatches">
                <div class="swatch" style="background:#ff0000" onclick="setColor('color4','#ff0000')"></div>
                <div class="swatch" style="background:#00ff00" onclick="setColor('color4','#00ff00')"></div>
                <div class="swatch" style="background:#ff8800" onclick="setColor('color4','#ff8800')"></div>
                <div class="swatch" style="background:#ff00ff" onclick="setColor('color4','#ff00ff')"></div>
                <div class="swatch" style="background:#8800ff" onclick="setColor('color4','#8800ff')"></div>
            </div>
        </div>
        <p id="color-hint" style="color:var(--dim);font-size:0.75rem;margin-top:0.3rem;"></p>
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

<!-- Keyboard Visualizer — full width below the grid -->
<div class="card" style="margin-top:1rem;" id="keyboard-card">
    <h2>Per-Key RGB</h2>

    <div style="display:flex; gap:25px; align-items:flex-start;">

        <!-- Keyboard (natural size, left-justified) -->
        <div style="flex:0 0 auto; display:flex; overflow-x:auto;">
            <div id="keyboard"></div>
        </div>

        <!-- Controls sidebar -->
        <div style="flex:1; flex-shrink:0; min-width:200px;" id="kb-sidebar">
            <label style="color:var(--dim);font-size:0.85rem;display:block;margin-bottom:0.4rem;">Paint Color</label>
            <div style="display:flex;align-items:center;gap:0.4rem;margin-bottom:0.6rem;">
                <input type="color" id="paint-color" value="#ff0000">
                <button class="btn" onclick="selectAll()" style="font-size:0.75rem;padding:0.4rem 0.6rem;">Select All</button>
                <button class="btn" onclick="clearSelection()" style="font-size:0.75rem;padding:0.4rem 0.6rem;border-color:var(--accent);color:var(--accent);">Clear Sel</button>
                <button class="btn" onclick="kbClear()" style="font-size:0.75rem;padding:0.4rem 0.6rem;">Reset All</button>
                <button class="btn" onclick="kbEraser()" id="eraser-btn" style="font-size:0.75rem;padding:0.4rem 0.6rem;">Eraser</button>
            </div>
            <div class="color-swatches" style="margin-bottom:0.4rem;">
                <div class="swatch" style="background:#E63946" onclick="onPaintColorChange('#E63946')" title="Crimson"></div>
                <div class="swatch" style="background:#F77F00" onclick="onPaintColorChange('#F77F00')" title="Tangerine"></div>
                <div class="swatch" style="background:#FCBF49" onclick="onPaintColorChange('#FCBF49')" title="Saffron"></div>
                <div class="swatch" style="background:#2DC653" onclick="onPaintColorChange('#2DC653')" title="Emerald"></div>
                <div class="swatch" style="background:#118AB2" onclick="onPaintColorChange('#118AB2')" title="Cerulean"></div>
                <div class="swatch" style="background:#073B4C" onclick="onPaintColorChange('#073B4C')" title="Midnight"></div>
                <div class="swatch" style="background:#7209B7" onclick="onPaintColorChange('#7209B7')" title="Violet"></div>
                <div class="swatch" style="background:#F72585" onclick="onPaintColorChange('#F72585')" title="Magenta"></div>
                <div class="swatch" style="background:#4CC9F0" onclick="onPaintColorChange('#4CC9F0')" title="Sky"></div>
            </div>
            <div class="color-swatches" style="margin-bottom:1rem;">
                <div class="swatch" style="background:#FFFFFF" onclick="onPaintColorChange('#FFFFFF')" title="White"></div>
                <div class="swatch" style="background:#CED4DA" onclick="onPaintColorChange('#CED4DA')" title="Silver"></div>
                <div class="swatch" style="background:#6C757D" onclick="onPaintColorChange('#6C757D')" title="Slate"></div>
                <div class="swatch" style="background:#EDF6F9" onclick="onPaintColorChange('#EDF6F9')" title="Ice"></div>
                <div class="swatch" style="background:#FFB5A7" onclick="onPaintColorChange('#FFB5A7')" title="Blush"></div>
                <div class="swatch" style="background:#B8F2E6" onclick="onPaintColorChange('#B8F2E6')" title="Mint"></div>
                <div class="swatch" style="background:#FDE2E4" onclick="onPaintColorChange('#FDE2E4')" title="Rose"></div>
                <div class="swatch" style="background:#CAF0F8" onclick="onPaintColorChange('#CAF0F8')" title="Frost"></div>
                <div class="swatch" style="background:#000000;border-color:#444;" onclick="onPaintColorChange('#000000')" title="Off"></div>
            </div>

            <label style="color:var(--dim);font-size:0.85rem;display:block;margin-bottom:0.4rem;">Gaming</label>
            <div style="display:flex;gap:0.3rem;flex-wrap:wrap;margin-bottom:0.6rem;">
                <button class="btn" onclick="gamerPreset('fps')" style="border-color:#c62828;font-size:0.72rem;padding:0.3rem 0.45rem;">FPS</button>
                <button class="btn" onclick="gamerPreset('moba')" style="border-color:#6a1b9a;font-size:0.72rem;padding:0.3rem 0.45rem;">MOBA</button>
                <button class="btn" onclick="gamerPreset('mmo')" style="border-color:#f57f17;font-size:0.72rem;padding:0.3rem 0.45rem;">MMO</button>
                <button class="btn" onclick="gamerPreset('racing')" style="border-color:#2e7d32;font-size:0.72rem;padding:0.3rem 0.45rem;">Racing</button>
                <button class="btn" onclick="gamerPreset('vaporwave')" style="border-color:#e040fb;font-size:0.72rem;padding:0.3rem 0.45rem;">Vapor</button>
                <button class="btn" onclick="gamerPreset('fire')" style="border-color:#ff6d00;font-size:0.72rem;padding:0.3rem 0.45rem;">Fire</button>
                <button class="btn" onclick="gamerPreset('ice')" style="border-color:#00b0ff;font-size:0.72rem;padding:0.3rem 0.45rem;">Ice</button>
                <button class="btn" onclick="gamerPreset('matrix')" style="border-color:#00c853;font-size:0.72rem;padding:0.3rem 0.45rem;">Matrix</button>
            </div>

            <label style="color:var(--dim);font-size:0.85rem;display:block;margin-bottom:0.4rem;">Creative Apps</label>
            <div style="display:flex;gap:0.3rem;flex-wrap:wrap;margin-bottom:0.6rem;">
                <button class="btn" onclick="appPreset('photoshop')" style="border-color:#31a8ff;font-size:0.72rem;padding:0.3rem 0.45rem;">Photoshop</button>
                <button class="btn" onclick="appPreset('premiere')" style="border-color:#9999ff;font-size:0.72rem;padding:0.3rem 0.45rem;">Premiere</button>
                <button class="btn" onclick="appPreset('gimp')" style="border-color:#8c6b3e;font-size:0.72rem;padding:0.3rem 0.45rem;">GIMP</button>
                <button class="btn" onclick="appPreset('blender')" style="border-color:#ea7600;font-size:0.72rem;padding:0.3rem 0.45rem;">Blender</button>
            </div>

            <label style="color:var(--dim);font-size:0.85rem;display:block;margin-bottom:0.4rem;">Effects</label>
            <div style="display:flex;gap:0.3rem;flex-wrap:wrap;margin-bottom:0.3rem;">
                <button class="btn" onclick="selectEffect('type-glow')" style="border-color:#00bcd4;font-size:0.72rem;padding:0.3rem 0.45rem;" id="eb-type-glow">Type Glow</button>
                <button class="btn" onclick="selectEffect('breathe')" style="border-color:#e040fb;font-size:0.72rem;padding:0.3rem 0.45rem;" id="eb-breathe">Breathe</button>
                <button class="btn" onclick="selectEffect('wave')" style="border-color:#ff9800;font-size:0.72rem;padding:0.3rem 0.45rem;" id="eb-wave">Wave</button>
                <button class="btn" onclick="selectEffect('rain')" style="border-color:#00bcd4;font-size:0.72rem;padding:0.3rem 0.45rem;" id="eb-rain">Rain</button>
            </div>
            <div id="effect-controls" style="display:none;background:#111;border:1px solid #333;border-radius:6px;padding:0.5rem;margin-bottom:0.4rem;">
                <div id="ec-1color" style="display:none;margin-bottom:0.4rem;">
                    <label style="color:var(--dim);font-size:0.7rem;">Color</label>
                    <input type="color" id="fx-color1" value="#00ffff" style="margin-left:0.3rem;">
                </div>
                <div id="ec-2color" style="display:none;margin-bottom:0.4rem;">
                    <div style="display:flex;align-items:center;gap:0.3rem;margin-bottom:0.3rem;">
                        <label style="color:var(--dim);font-size:0.7rem;">Color 1</label>
                        <input type="color" id="fx-color2a" value="#ff0000">
                    </div>
                    <div style="display:flex;align-items:center;gap:0.3rem;">
                        <label style="color:var(--dim);font-size:0.7rem;">Color 2</label>
                        <input type="color" id="fx-color2b" value="#000000">
                    </div>
                </div>
                <div id="ec-speed" style="display:flex;align-items:center;gap:0.4rem;margin-bottom:0.4rem;">
                    <label style="color:var(--dim);font-size:0.7rem;">Speed</label>
                    <input type="range" id="fx-speed" min="1" max="3" value="2" style="flex:1;accent-color:var(--accent);">
                    <span id="fx-speed-val" style="color:var(--dim);font-size:0.7rem;">2</span>
                </div>
                <button class="btn" onclick="applySelectedEffect()" style="width:100%;font-size:0.72rem;padding:0.35rem;border-color:var(--accent);color:var(--accent);">Apply to Painted Keys</button>
            </div>
            <div style="display:flex;gap:0.3rem;margin-bottom:0.6rem;">
                <button class="btn" onclick="clearEffectGroups()" style="font-size:0.65rem;padding:0.25rem 0.4rem;border-color:#555;flex:1;">Reset Groups</button>
            </div>

            <div id="modifier-hint" style="display:none;background:#111;border:1px solid var(--accent);border-radius:6px;padding:0.5rem;margin-bottom:0.6rem;">
                <label style="color:var(--accent);font-size:0.75rem;display:block;margin-bottom:0.2rem;">Modifier Layers Active</label>
                <span style="color:var(--dim);font-size:0.7rem;">Hold Shift / Ctrl / Alt to preview context keys on hardware</span>
            </div>

            <button class="btn" onclick="applyColorToSelection()" style="width:100%;margin-bottom:0.4rem;padding:0.6rem;border-color:#4caf50;color:#4caf50;font-weight:600;">Apply Color to Selection</button>
            <button class="apply-btn" onclick="applyKeyboard()">Send All to Hardware</button>
            <button class="btn" style="width:100%;margin-top:0.5rem;border-color:#ff8800;font-size:0.72rem;" onclick="startCalibration()">Calibrate Keys</button>
            <div id="cal-info" style="display:none;margin-top:0.5rem;font-size:0.7rem;color:var(--dim);">
                <span id="cal-idx">-</span>/101 — Code: <span id="cal-code">-</span><br>
                <button class="btn" onclick="calPrev()" style="font-size:0.65rem;padding:0.2rem 0.4rem;">Prev</button>
                <button class="btn" onclick="calNext()" style="font-size:0.65rem;padding:0.2rem 0.4rem;">Next</button>
                <button class="btn" onclick="calStop()" style="font-size:0.65rem;padding:0.2rem 0.4rem;">Stop</button>
            </div>
        </div>

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
    const cb = document.getElementById(id + '-on');
    if (cb && !cb.checked) { cb.checked = true; onColorToggle(); }
}

function toggleZone(el) {
    el.classList.toggle('selected');
}

function getSelectedZones() {
    return [...document.querySelectorAll('.zone-chip.selected')].map(e => e.dataset.zone);
}

// Effect categories
const EFFECTS_NO_COLOR = ['rainbow-wave', 'screw-rainbow', 'smooth'];
const EFFECTS_MULTI_COLOR = ['color-change', 'color-pulse', 'color-wave'];

function onEffectChange() {
    const effect = document.getElementById('effect-select').value;
    const noColor = EFFECTS_NO_COLOR.includes(effect);
    const multiColor = EFFECTS_MULTI_COLOR.includes(effect);
    const hint = document.getElementById('color-hint');

    // Color 1: always visible unless no-color effect
    document.getElementById('color1-row').style.display = noColor ? 'none' : '';

    // Extra colors: only show rows for multi-color effects
    document.querySelectorAll('.extra-color').forEach(el => {
        el.style.display = multiColor ? '' : 'none';
    });

    if (noColor) {
        hint.textContent = 'This effect uses built-in colors (no color selection needed).';
    } else if (multiColor) {
        hint.textContent = 'Enable extra colors to cycle/pulse/wave between them.';
    } else {
        hint.textContent = '';
    }
}

function onColorToggle() {
    for (let i = 2; i <= 4; i++) {
        const cb = document.getElementById('color' + i + '-on');
        const picker = document.getElementById('color' + i);
        if (cb && picker) picker.disabled = !cb.checked;
    }
}

document.getElementById('effect-select').addEventListener('change', onEffectChange);
onEffectChange();

async function applyCustom() {
    const effect = document.getElementById('effect-select').value;
    const zones = getSelectedZones();
    const speed = document.getElementById('speed-slider').value;

    if (!zones.length) { toast('Select at least one zone', false); return; }

    // Collect enabled colors
    const noColor = EFFECTS_NO_COLOR.includes(effect);
    let colorList = [];
    if (!noColor) {
        colorList.push(document.getElementById('color1').value);
        for (let i = 2; i <= 4; i++) {
            const cb = document.getElementById('color' + i + '-on');
            if (cb && cb.checked) {
                colorList.push(document.getElementById('color' + i).value);
            }
        }
    }
    const colorStr = colorList.join(',');

    const allZones = ['keyboard', 'perimeter', 'logo'];
    const parts = [];
    for (const z of allZones) {
        if (zones.includes(z)) {
            if (colorStr) {
                parts.push(z + ':' + effect + ':' + colorStr + ':' + speed);
            } else {
                parts.push(z + ':' + effect + '::' + speed);
            }
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

// =========================================================================
// Per-Key Keyboard Visualizer
// =========================================================================

// Perimeter and logo keycodes (needed to send everything in one shot)
const PERIM_CODES = [
    0x03e9,0x03ea,0x03eb,0x03ec,0x03ed,0x03ee,0x03ef,
    0x03f0,0x03f1,0x03f2,0x03f3,0x03f4,0x03f5,0x03f6,
    0x03f7,0x03f8,0x03f9,0x03fa,
    0x01f5,0x01f6,0x01f7,0x01f8,0x01f9,0x01fa,
    0x01fb,0x01fc,0x01fd,0x01fe,
];
const LOGO_CODE = 0x05DD;

// CSS Grid keyboard layout for Legion Pro 7 16IAX10H.
// Each 1u key = 4 sub-columns. Numpad keys ~0.75u = 3 sub-cols.
// Gap between main block and numpad = ~0.7u = 3 sub-cols.
const K = 53;  // 1u key width in px
const G = 3;   // inter-key gap px
const GG = 12; // group gap px (F-row clusters)
const KH = 48; // key height px
const NK = 34; // numpad key width px (~0.75u)

// Sub-column width: K/4 = 11.5px. We use fractional fr units in CSS grid.
// Main area: widest row is row 1 (15u total key width) = 60 sub-cols
// Group gaps in F-row: 4 gaps of ~GG each ≈ 0.87u each ≈ 3.5 sub-cols, we round
// Total main sub-cols = 60 (keys) + some gap cols
// Numpad: 4 keys * 3 sub-cols = 12, plus gap cols between = 15 sub-cols
// Gap between main and numpad: 3 sub-cols
// We define the grid precisely per-key using grid-column start/span.

// Keyboard data: each entry is [label, code, gridCol, gridColSpan, gridRow, gridRowSpan]
// gridCol and gridColSpan are in sub-column units (1 sub-col ≈ 11.5px)
// gridRow is 1-indexed row in the CSS grid
// Right-side column alignment:
// Col 57-60: Del end | Bksp end | \ end | Enter end | Shift end | (blank) | → end
// Col 62-64: Home | NumLk | 7 | 4 | 1 | 0
// Col 65-67: End | / | 8 | 5 | 2 | 0-cont
// Col 68-70: PgUp | * | 9 | 6 | 3 | .
// Col 71-73: PgDn | - | +(tall) | +cont | Ent(tall) | Ent-cont
const KB_KEYS = [
  // --- Row 0: F-key row ---
  ['Esc',    0x0001, 1, 4, 1, 1],
  ['F1',     0x0002, 6, 3, 1, 1],
  ['F2',     0x0003, 9, 4, 1, 1],
  ['F3',     0x0004, 13, 3, 1, 1],
  ['F4',     0x0005, 16, 4, 1, 1],
  ['F5',     0x0006, 21, 3, 1, 1],
  ['F6',     0x0007, 24, 4, 1, 1],
  ['F7',     0x0008, 28, 3, 1, 1],
  ['F8',     0x0009, 31, 4, 1, 1],
  ['F9',     0x000a, 36, 3, 1, 1],
  ['F10',    0x000b, 39, 4, 1, 1],
  ['F11',    0x000c, 43, 3, 1, 1],
  ['F12',    0x000d, 46, 4, 1, 1],
  ['Ins',    0x000e, 51, 3, 1, 1],
  ['PrtSc',  0x000f, 54, 3, 1, 1],
  ['Del',    0x0010, 57, 4, 1, 1],
  // F-row numpad area: Home End PgUp PgDn
  ['Home',   0x0011, 62, 3, 1, 1],
  ['End',    0x0012, 65, 3, 1, 1],
  ['PgUp',   0x0013, 68, 3, 1, 1],
  ['PgDn',   0x0014, 71, 3, 1, 1],

  // --- Row 1: Number row ---
  ['~',      0x0016, 1, 4, 2, 1],
  ['1',      0x0017, 5, 4, 2, 1],
  ['2',      0x0018, 9, 4, 2, 1],
  ['3',      0x0019, 13, 4, 2, 1],
  ['4',      0x001a, 17, 4, 2, 1],
  ['5',      0x001b, 21, 4, 2, 1],
  ['6',      0x001c, 25, 4, 2, 1],
  ['7',      0x001d, 29, 4, 2, 1],
  ['8',      0x001e, 33, 4, 2, 1],
  ['9',      0x001f, 37, 4, 2, 1],
  ['0',      0x0020, 41, 4, 2, 1],
  ['-',      0x0021, 45, 4, 2, 1],
  ['=',      0x0022, 49, 4, 2, 1],
  ['Bksp',   0x0038, 53, 8, 2, 1],   // ends at col 60
  // Numpad: Num / * -
  ['Num',    0x0026, 62, 3, 2, 1],
  ['/',      0x0027, 65, 3, 2, 1],
  ['*',      0x0028, 68, 3, 2, 1],
  ['\u2212', 0x0029, 71, 3, 2, 1],

  // --- Row 2: QWERTY ---
  ['Tab',    0x0040, 1, 6, 3, 1],
  ['Q',      0x0042, 7, 4, 3, 1],
  ['W',      0x0043, 11, 4, 3, 1],
  ['E',      0x0044, 15, 4, 3, 1],
  ['R',      0x0045, 19, 4, 3, 1],
  ['T',      0x0046, 23, 4, 3, 1],
  ['Y',      0x0047, 27, 4, 3, 1],
  ['U',      0x0048, 31, 4, 3, 1],
  ['I',      0x0049, 35, 4, 3, 1],
  ['O',      0x004a, 39, 4, 3, 1],
  ['P',      0x004b, 43, 4, 3, 1],
  ['[',      0x004c, 47, 4, 3, 1],
  [']',      0x004d, 51, 4, 3, 1],
  ['\\',     0x004e, 55, 6, 3, 1],   // ends at col 60
  // Numpad: 7 8 9 +(tall spans 2 rows)
  ['7',      0x004f, 62, 3, 3, 1],
  ['8',      0x0050, 65, 3, 3, 1],
  ['9',      0x0051, 68, 3, 3, 1],
  ['+',      0x0068, 71, 3, 3, 2],

  // --- Row 3: Home row ---
  ['Caps',   0x0055, 1, 7, 4, 1],
  ['A',      0x006d, 8, 4, 4, 1],
  ['S',      0x006e, 12, 4, 4, 1],
  ['D',      0x0058, 16, 4, 4, 1],
  ['F',      0x0059, 20, 4, 4, 1],
  ['G',      0x005a, 24, 4, 4, 1],
  ['H',      0x0071, 28, 4, 4, 1],
  ['J',      0x0072, 32, 4, 4, 1],
  ['K',      0x005b, 36, 4, 4, 1],
  ['L',      0x005c, 40, 4, 4, 1],
  [';',      0x005d, 44, 4, 4, 1],
  ["'",      0x005f, 48, 4, 4, 1],
  ['Enter',  0x0077, 52, 9, 4, 1],   // ends at col 60
  // Numpad: 4 5 6 (+ spans from above)
  ['4',      0x0079, 62, 3, 4, 1],
  ['5',      0x007b, 65, 3, 4, 1],
  ['6',      0x007c, 68, 3, 4, 1],

  // --- Row 4: Shift row (keycodes shifted 1 position right vs KEY_NAMES) ---
  ['Shift',  0x006a, 1, 9, 5, 1],
  ['Z',      0x0082, 10, 4, 5, 1],
  ['X',      0x0083, 14, 4, 5, 1],
  ['C',      0x006f, 18, 4, 5, 1],
  ['V',      0x0070, 22, 4, 5, 1],
  ['B',      0x0087, 26, 4, 5, 1],
  ['N',      0x0088, 30, 4, 5, 1],
  ['M',      0x0073, 34, 4, 5, 1],
  [',',      0x0074, 38, 4, 5, 1],
  ['.',      0x0075, 42, 4, 5, 1],
  ['/',      0x0076, 46, 4, 5, 1],
  ['Shift',  0x008d, 50, 11, 5, 1],  // ends at col 60
  // Numpad: 1 2 3 Enter(tall spans 2 rows)
  ['1',      0x008e, 62, 3, 5, 1],
  ['2',      0x0090, 65, 3, 5, 1],
  ['3',      0x0092, 68, 3, 5, 1],
  ['Ent',    0x00a7, 71, 3, 5, 2],

  // --- Row 5: Bottom row (left side shifted 1 right vs KEY_NAMES) ---
  ['Ctrl',   0x007f, 1, 6, 6, 1],
  ['Fn',     0x0080, 7, 4, 6, 1],
  ['\u2756', 0x0096, 11, 5, 6, 1],
  ['Alt',    0x0097, 16, 5, 6, 1],
  ['',       0x0098, 21, 22, 6, 1],
  ['Alt',    0x009a, 43, 5, 6, 1],
  ['\u2B22', 0x009b, 48, 5, 6, 1],
  // Arrow up: same row as bottom
  ['\u2191', 0x009d, 55, 3, 6, 1],
  // Numpad: 0(wide) .  (Enter spans from above)
  ['0',      0x00a3, 62, 6, 6, 1],
  ['.',      0x00a5, 68, 3, 6, 1],

  // --- Row 7: Arrow left/down/right ---
  ['\u2190', 0x009c, 52, 3, 7, 1],
  ['\u2193', 0x009f, 55, 3, 7, 1],
  ['\u2192', 0x00a1, 58, 3, 7, 1],
];

// Total grid: 74 sub-columns, 7 rows (6 main + 1 arrow row)
const GRID_COLS = 74;
const GRID_ROWS = 7;

// Backward-compatible KB row structure for preset gradient code.
// Groups KB_KEYS by grid row into {main:[], num:[]} where main cols < 64, num cols >= 64.
// Each entry is [label, code, size] to match old format expected by preset applicator.
const KB = [];
for (const [label, code, col, colSpan, row, rowSpan] of KB_KEYS) {
    const ri = row - 1;
    if (!KB[ri]) KB[ri] = { main: [], num: [] };
    const entry = [label, code, colSpan / 4];
    if (col >= 62) KB[ri].num.push(entry);
    else KB[ri].main.push(entry);
}
// Ensure all rows exist
for (let i = 0; i < GRID_ROWS; i++) {
    if (!KB[i]) KB[i] = { main: [], num: [] };
}

// Perimeter LEDs: rear exhaust (top 1-10, bottom 18-11) + front edge (F1-F10)
const PERIM_REAR_TOP = [0x03e9,0x03ea,0x03eb,0x03ec,0x03ed,0x03ee,0x03ef,0x03f0,0x03f1,0x03f2];
const PERIM_REAR_BOT = [0x03fa,0x03f9,0x03f8,0x03f7,0x03f6,0x03f5,0x03f4,0x03f3];
const PERIM_FRONT = [0x01f5,0x01f6,0x01f7,0x01f8,0x01f9,0x01fa,0x01fb,0x01fc,0x01fd,0x01fe];

const KEY_U = K;
const KEY_GAP = G;
const KEY_H = KH;
let selectedKeys = new Set();   // currently selected keycodes (pending assignment)
let appliedGroups = [];         // [{effect, speed, colors, keys:[codes]}] — applied to hardware
let keyColors = {};             // keycode -> hex color (for visual state tracking)
let eraserMode = false;
let livePreview = true;

// Throttled preview — max one HID write per 150ms
let _previewTimer = null;
let _previewQueue = null;
let _previewInFlight = false;

function previewHW(keysObj) {
    _previewQueue = keysObj;
    if (_previewInFlight || _previewTimer) return;
    _previewTimer = setTimeout(() => {
        _previewTimer = null;
        if (!_previewQueue) return;
        const payload = _previewQueue;
        _previewQueue = null;
        _previewInFlight = true;
        fetch('/preview', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({keys: payload})
        }).catch(() => {}).finally(() => {
            _previewInFlight = false;
            // If more queued while we were in-flight, fire again
            if (_previewQueue) previewHW(_previewQueue);
        });
    }, 150);
}

function buildFullHWState(extraCode, extraColor) {
    // Merge locked keyColors + the hovered key into one state for HID
    const state = {};
    for (const [code, color] of Object.entries(keyColors)) {
        state['0x' + parseInt(code).toString(16).padStart(4,'0')] = color;
    }
    if (extraCode && extraColor) {
        state['0x' + extraCode.toString(16).padStart(4,'0')] = extraColor;
    }
    return state;
}

function makeKeyEl(label, code, w) {
    const key = document.createElement('div');
    const pw = Math.round(w * KEY_U);
    key.style.cssText = `
        width:${pw}px; height:${KEY_H}px;
        border:1px solid #333; border-radius:4px;
        display:flex; align-items:center; justify-content:center;
        font-size:${label.length > 4 ? '0.65rem' : label.length > 2 ? '0.72rem' : '0.8rem'};
        color:#999; cursor:pointer;
        background:#181818;
        transition: background 0.08s, border-color 0.12s, box-shadow 0.12s;
        flex-shrink:0;
    `;
    key.textContent = label;
    key.dataset.code = code;
    key.classList.add('kb-key');
    if (keyColors[code]) applyKeyColor(key, keyColors[code]);

    key.addEventListener('mousedown', (e) => { e.preventDefault(); toggleSelect(key); });
    key.addEventListener('mouseenter', (e) => {
        if (e.buttons === 1) { toggleSelect(key); }
        else if (livePreview) {
            const c = eraserMode ? '#000000' : document.getElementById('paint-color').value;
            previewHW(buildFullHWState(parseInt(key.dataset.code), c));
        }
    });
    key.addEventListener('mouseleave', (e) => {
        if (e.buttons !== 1 && livePreview && !keyColors[parseInt(key.dataset.code)])
            previewHW(buildFullHWState(null, null));
    });
    return key;
}


function makePerimLED(code, w, h) {
    const el = document.createElement('div');
    el.style.cssText = `
        width:${w}px; height:${h}px;
        border-radius:2px; cursor:pointer;
        background:#111; border:1px solid #222;
        transition: background 0.08s, box-shadow 0.12s;
    `;
    el.dataset.code = code;
    el.classList.add('kb-key');
    if (keyColors[code]) applyKeyColor(el, keyColors[code]);
    el.addEventListener('mousedown', (e) => { e.preventDefault(); paintKey(el); });
    el.addEventListener('mouseenter', (e) => {
        if (e.buttons === 1) paintKey(el);
    });
    return el;
}

function buildKeyboard() {
    const kb = document.getElementById('keyboard');
    kb.innerHTML = '';
    kb.style.cssText = 'display:inline-flex;flex-direction:column;user-select:none;';

    // --- Rear exhaust arc (2 rows: top 1-10, bottom 18-11) ---
    const rearWrap = document.createElement('div');
    rearWrap.style.cssText = 'display:flex;flex-direction:column;align-items:center;gap:2px;margin-bottom:6px;';
    let rearIdx = 1;
    for (const rowCodes of [PERIM_REAR_TOP, PERIM_REAR_BOT]) {
        const row = document.createElement('div');
        row.style.cssText = 'display:flex;gap:3px;justify-content:center;';
        for (const code of rowCodes) {
            const led = makePerimLED(code, 54, 18);
            led.style.cssText += 'font-size:0.6rem;display:flex;align-items:center;justify-content:center;color:#555;';
            led.textContent = rearIdx++;
            row.appendChild(led);
        }
        rearWrap.appendChild(row);
    }
    kb.appendChild(rearWrap);

    // --- CSS Grid keyboard ---
    const SUB = (K + G) / 4;  // sub-column width including gap share
    const grid = document.createElement('div');
    grid.style.cssText = `
        display: grid;
        grid-template-columns: repeat(${GRID_COLS}, ${SUB}px);
        grid-template-rows: repeat(7, ${KH}px);
        gap: ${G}px;
        user-select: none;
    `;

    for (const keyDef of KB_KEYS) {
        const [label, code, col, colSpan, row, rowSpan] = keyDef;
        const el = makeKeyEl(label, code, 1); // width param is placeholder; overridden by grid
        // Remove the fixed width from makeKeyEl — let CSS grid control sizing
        el.style.width = '';
        el.style.flexShrink = '';
        el.style.gridColumn = `${col} / span ${colSpan}`;
        el.style.gridRow = `${row} / span ${rowSpan}`;
        el.style.height = '100%'; // fill the grid cell (tall keys span 2 rows)
        grid.appendChild(el);
    }

    kb.appendChild(grid);

    // --- Front edge LEDs (F1-F10) ---
    const frontStrip = document.createElement('div');
    frontStrip.style.cssText = 'display:flex;gap:3px;justify-content:center;margin-top:6px;';
    let frontIdx = 1;
    for (const code of PERIM_FRONT) {
        const led = makePerimLED(code, 50, 18);
        led.style.cssText += 'font-size:0.6rem;display:flex;align-items:center;justify-content:center;color:#555;';
        led.textContent = 'F' + frontIdx++;
        frontStrip.appendChild(led);
    }
    kb.appendChild(frontStrip);
}

function toggleSelect(keyEl) {
    const code = parseInt(keyEl.dataset.code);
    if (eraserMode) {
        // Eraser: remove from applied groups and clear visual
        selectedKeys.delete(code);
        appliedGroups = appliedGroups.map(g => ({...g, keys: g.keys.filter(k => k !== code)})).filter(g => g.keys.length > 0);
        delete keyColors[code];
        keyEl.style.background = '#181818';
        keyEl.style.borderColor = '#333';
        keyEl.style.boxShadow = 'none';
        keyEl.style.color = '#999';
        keyEl.style.outline = '';
        sendAllGroups();
        return;
    }
    if (selectedKeys.has(code)) {
        selectedKeys.delete(code);
        keyEl.style.outline = '';
    } else {
        selectedKeys.add(code);
        keyEl.style.outline = '2px solid var(--accent)';
    }
}

function applyKeyColor(keyEl, hex) {
    keyEl.style.background = hex;
    keyEl.style.borderColor = hex;
    // Glow effect
    keyEl.style.boxShadow = `0 0 8px ${hex}88, inset 0 0 12px ${hex}44`;
    // Readable text: dark text on bright keys
    const r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16);
    const lum = (0.299*r + 0.587*g + 0.114*b);
    keyEl.style.color = lum > 140 ? '#111' : '#fff';
    if (r === 0 && g === 0 && b === 0) {
        keyEl.style.background = '#0a0a0a';
        keyEl.style.borderColor = '#333';
        keyEl.style.boxShadow = 'none';
        keyEl.style.color = '#555';
    }
}

function selectAll() {
    document.querySelectorAll('.kb-key').forEach(k => {
        const code = parseInt(k.dataset.code);
        selectedKeys.add(code);
        k.style.outline = '2px solid var(--accent)';
    });
}

function clearSelection() {
    selectedKeys.clear();
    document.querySelectorAll('.kb-key').forEach(k => { k.style.outline = ''; });
}

function onPaintColorChange(newColor) {
    if (newColor) document.getElementById('paint-color').value = newColor;
}

function kbClear() {
    // Clear everything: selection, applied groups, visuals, hardware
    selectedKeys.clear();
    appliedGroups = [];
    keyColors = {};
    document.querySelectorAll('.kb-key').forEach(k => {
        k.style.background = '#181818';
        k.style.borderColor = '#333';
        k.style.boxShadow = 'none';
        k.style.color = '#999';
        k.style.outline = '';
    });
    if (livePreview) previewHW({});
}

function kbEraser() {
    eraserMode = !eraserMode;
    const btn = document.getElementById('eraser-btn');
    btn.classList.toggle('active', eraserMode);
}

// Apply color to selected keys as a static group
function applyColorToSelection() {
    if (selectedKeys.size === 0) { toast('Select some keys first', false); return; }
    const color = document.getElementById('paint-color').value;
    const codes = [...selectedKeys];

    // Add as a static color group
    appliedGroups.push({ effect: 'static', speed: 0, colors: [color], keys: codes });

    // Visual feedback
    codes.forEach(code => {
        keyColors[code] = color;
        const el = document.querySelector(`.kb-key[data-code="${code}"]`);
        if (el) { applyKeyColor(el, color); el.style.outline = ''; }
    });

    // Clear selection
    selectedKeys.clear();
    sendAllGroups();
    toast(`Applied color to ${codes.length} keys`);
}

// Send all applied groups to hardware
async function sendAllGroups() {
    if (appliedGroups.length === 0) return;
    const groups = appliedGroups.map(g => ({
        effect: g.effect, speed: g.speed, colors: g.colors,
        keys: g.keys.map(c => '0x' + c.toString(16).padStart(4, '0')),
    }));
    try {
        await fetch('/effect-keys', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({groups})
        });
    } catch(e) {}
}

// Gamer Presets
const GAMER_PRESETS = {
    fps: {
        // WASD bright red, surrounding keys dim red, number row for weapons, shift/ctrl/space utility
        base: '#000000',
        keys: {
            0x0043:'#ff0000', 0x006d:'#ff0000', 0x006e:'#ff0000', 0x0058:'#ff0000', // WASD
            0x0042:'#880000', 0x0044:'#880000', 0x0045:'#880000',  // Q E R
            0x0059:'#880000', 0x005a:'#880000',  // F G
            0x006a:'#cc3300', // LShift (sprint)
            0x0096:'#cc3300', // LCtrl (crouch)
            0x0098:'#cc3300', // Space (jump)
            0x0040:'#550000', // Tab (scoreboard)
            0x0017:'#ff4400', 0x0018:'#ff4400', 0x0019:'#ff4400', 0x001a:'#ff4400', 0x001b:'#ff4400', // 1-5 weapons
            0x0082:'#660000', 0x0083:'#660000', 0x006f:'#660000', 0x0070:'#660000', // Z X C V (utility)
            0x0045:'#880000', 0x0046:'#660000', // R T (reload, chat)
            0x0001:'#ff0000', // Esc
        },
        perim: '#ff0000', logo: '#ff0000',
    },
    moba: {
        // QWER abilities bright, DF summoners, 1-6 items, space/tab utility
        base: '#000000',
        keys: {
            0x0042:'#aa00ff', 0x0043:'#aa00ff', 0x0044:'#aa00ff', 0x0045:'#aa00ff', // QWER
            0x0058:'#ff8800', 0x0059:'#ff8800', // D F (summoner spells)
            0x0017:'#6600cc', 0x0018:'#6600cc', 0x0019:'#6600cc', 0x001a:'#6600cc', 0x001b:'#6600cc', 0x001c:'#6600cc', // 1-6 items
            0x0098:'#440088', // Space
            0x0040:'#440088', // Tab
            0x006d:'#330066', // A (attack move)
            0x006e:'#330066', // S (stop)
            0x0070:'#550088', // B (recall)
            0x005a:'#440066', // G (ping)
            0x0047:'#440066', // Y
            0x0046:'#440066', // T
            0x0001:'#aa00ff', // Esc
        },
        perim: '#7700ff', logo: '#aa00ff',
    },
    mmo: {
        // Number row rainbow gradient, WASD, F1-F12 action bars, modifiers
        base: '#000000',
        keys: {
            // WASD - gold
            0x0043:'#ffaa00', 0x006d:'#ffaa00', 0x006e:'#ffaa00', 0x0058:'#ffaa00',
            // Number row - rainbow
            0x0017:'#ff0000', 0x0018:'#ff4400', 0x0019:'#ff8800', 0x001a:'#ffcc00',
            0x001b:'#88ff00', 0x001c:'#00ff44', 0x001d:'#00ffaa', 0x001e:'#00ccff',
            0x001f:'#0066ff', 0x0020:'#4400ff',
            // F-keys - dim cyan bar
            0x0002:'#006688', 0x0003:'#006688', 0x0004:'#006688', 0x0005:'#006688',
            0x0006:'#008888', 0x0007:'#008888', 0x0008:'#008888', 0x0009:'#008888',
            0x000a:'#008866', 0x000b:'#008866', 0x000c:'#008866', 0x000d:'#008866',
            // Modifiers
            0x006a:'#884400', 0x0096:'#884400', 0x0098:'#884400',
            0x0040:'#664400', // Tab (target)
            0x0001:'#ffaa00',
        },
        perim: '#ff8800', logo: '#ffaa00',
    },
    racing: {
        base: '#000000',
        keys: {
            // WASD / Arrow keys - green
            0x0043:'#00ff00', 0x006d:'#00ff00', 0x006e:'#00ff00', 0x0058:'#00ff00',
            0x008e:'#00ff00', 0x009c:'#00ff00', 0x009d:'#00ff00', 0x009f:'#00ff00',
            // Shift (nitro/boost) - orange flash
            0x006a:'#ff6600', 0x008d:'#ff6600',
            // Space (handbrake)
            0x0098:'#ffcc00',
            // Ctrl (brake)
            0x0096:'#ff0000',
            // Number keys for camera/gear
            0x0017:'#004400', 0x0018:'#004400', 0x0019:'#004400', 0x001a:'#004400',
            0x0001:'#00ff00',
        },
        perim: '#00ff00', logo: '#00ff00',
    },
    stealth: {
        // Very dim, only essentials lit with deep blue
        base: '#000000',
        keys: {
            0x0043:'#001122', 0x006d:'#001122', 0x006e:'#001122', 0x0058:'#001122', // WASD
            0x0098:'#001122', // Space
            0x006a:'#001122', 0x0096:'#001122', // Shift Ctrl
            0x0001:'#002244', // Esc
            0x0040:'#000d1a', // Tab
        },
        perim: '#000000', logo: '#000000',
    },
    vaporwave: {
        // Pink and cyan gradient across the keyboard
        base: '#110022',
        gradient: true,
        gradColors: ['#ff00ff','#ff00aa','#ff0088','#cc0088','#aa00aa','#8800cc','#6600ee','#4400ff','#2200ff','#0044ff','#0088ff','#00bbff','#00ffff'],
        perim: '#ff00ff', logo: '#00ffff',
    },
    fire: {
        base: '#110000',
        gradient: true,
        // Bottom rows bright (close to fire), top rows cooler
        gradRows: [
            '#330000', // F-row (smoke)
            '#551100', // Number row
            '#883300', // QWERTY
            '#cc5500', // Home row
            '#ff6600', // Shift row (flames)
            '#ff9900', // Bottom row (hottest)
        ],
        perim: '#ff4400', logo: '#ff6600',
    },
    ice: {
        base: '#000811',
        gradient: true,
        gradColors: ['#001133','#002255','#003377','#004499','#0055bb','#0077dd','#0099ee','#00aaff','#00ccff','#44ddff','#88eeff','#bbf4ff','#ffffff'],
        perim: '#00ccff', logo: '#88eeff',
    },
    matrix: {
        // Random green intensities, code rain feel
        base: '#000000',
        random: true,
        randomColors: ['#003300','#004400','#005500','#006600','#008800','#00aa00','#00cc00','#00ff00','#00ff00','#44ff44'],
        perim: '#003300', logo: '#00ff00',
    },
    'team-red': {
        base: '#1a0000',
        fill: '#cc0000',
        accent: '#ff0000',
        accentKeys: [0x0043,0x006d,0x006e,0x0058,0x0098,0x0001], // WASD Space Esc
        perim: '#ff0000', logo: '#ff0000',
    },
    'team-blue': {
        base: '#00001a',
        fill: '#0000cc',
        accent: '#0066ff',
        accentKeys: [0x0043,0x006d,0x006e,0x0058,0x0098,0x0001],
        perim: '#0066ff', logo: '#0066ff',
    },
};

function gamerPreset(name) {
    const p = GAMER_PRESETS[name];
    if (!p) return;
    // Reset everything
    selectedKeys.clear();
    appliedGroups = [];
    keyColors = {};

    // Collect all key elements
    const allKeys = document.querySelectorAll('.kb-key');
    const keyEls = {};
    allKeys.forEach(k => { keyEls[parseInt(k.dataset.code)] = k; });

    if (p.fill) {
        // Team color: fill all with base, accent specific keys
        allKeys.forEach(k => {
            const code = parseInt(k.dataset.code);
            keyColors[code] = p.fill;
            applyKeyColor(k, p.fill);
        });
        if (p.accentKeys) {
            p.accentKeys.forEach(code => {
                if (keyEls[code]) {
                    keyColors[code] = p.accent;
                    applyKeyColor(keyEls[code], p.accent);
                }
            });
        }
    } else if (p.random) {
        // Random colors from palette
        allKeys.forEach(k => {
            const code = parseInt(k.dataset.code);
            const c = p.randomColors[Math.floor(Math.random() * p.randomColors.length)];
            keyColors[code] = c;
            applyKeyColor(k, c);
        });
    } else if (p.gradient && p.gradRows) {
        for (let ri = 0; ri < KB.length; ri++) {
            const color = p.gradRows[Math.min(ri, p.gradRows.length-1)];
            [...KB[ri].main,...KB[ri].num].forEach(k => {
                if (!Array.isArray(k) || k[1] === null) return;
                if (keyEls[k[1]]) { keyColors[k[1]] = color; applyKeyColor(keyEls[k[1]], color); }
            });
        }
    } else if (p.gradient && p.gradColors) {
        for (let ri = 0; ri < KB.length; ri++) {
            const rowKeys = [...KB[ri].main,...KB[ri].num].filter(k => Array.isArray(k) && k[1] !== null);
            rowKeys.forEach((k, ki) => {
                const idx = Math.floor((ki / Math.max(rowKeys.length-1,1)) * (p.gradColors.length-1));
                if (keyEls[k[1]]) { keyColors[k[1]] = p.gradColors[idx]; applyKeyColor(keyEls[k[1]], p.gradColors[idx]); }
            });
        }
    } else {
        // Specific key mapping
        // First set base color on all
        allKeys.forEach(k => {
            const code = parseInt(k.dataset.code);
            keyColors[code] = p.base;
            applyKeyColor(k, p.base);
        });
        // Then override specifics
        for (const [codeStr, color] of Object.entries(p.keys)) {
            const code = parseInt(codeStr);
            if (keyEls[code]) {
                keyColors[code] = color;
                applyKeyColor(keyEls[code], color);
            }
        }
    }

    // Set perimeter and logo
    // Color perimeter LEDs
    if (p.perim) {
        const allPerim = [...PERIM_REAR_TOP,...PERIM_REAR_BOT,...PERIM_FRONT];
        allPerim.forEach(code => {
            keyColors[code] = p.perim;
            if (keyEls[code]) applyKeyColor(keyEls[code], p.perim);
        });
    }
    // Color logo
    if (p.logo) {
        keyColors[LOGO_CODE] = p.logo;
        if (keyEls[LOGO_CODE]) applyKeyColor(keyEls[LOGO_CODE], p.logo);
    }

    // Build applied groups from keyColors (group by color for efficiency)
    const colorGroups = {};
    for (const [code, color] of Object.entries(keyColors)) {
        if (color === '#000000') continue;
        if (!colorGroups[color]) colorGroups[color] = [];
        colorGroups[color].push(parseInt(code));
    }
    for (const [color, codes] of Object.entries(colorGroups)) {
        appliedGroups.push({ effect: 'static', speed: 0, colors: [color], keys: codes });
    }
    sendAllGroups();
    // Clear selection outlines
    document.querySelectorAll('.kb-key').forEach(k => { k.style.outline = ''; });
}

async function applyKeyboard() {
    // If there's an active selection, apply color to it first
    if (selectedKeys.size > 0) {
        applyColorToSelection();
    }
    // Send all applied groups to hardware
    if (appliedGroups.length === 0) {
        toast('Nothing to apply — select keys and assign colors/effects first', false);
        return;
    }
    await sendAllGroups();
    toast(`Applied ${appliedGroups.length} group(s) to hardware`);
    refreshStatus();
}

// =========================================================================
// Creative App Presets — shortcut key highlighting with modifier layers
// =========================================================================
// Key name -> code lookup (subset for readability)
// Keycodes corrected to match KB_KEYS grid (shift row offset, bottom row offset)
const KC = {
    esc:0x0001, '1':0x0017,'2':0x0018,'3':0x0019,'4':0x001a,'5':0x001b,
    '6':0x001c,'7':0x001d,'8':0x001e,'9':0x001f,'0':0x0020,
    q:0x0042,w:0x0043,e:0x0044,r:0x0045,t:0x0046,y:0x0047,u:0x0048,
    i:0x0049,o:0x004a,p:0x004b,a:0x006d,s:0x006e,d:0x0058,f:0x0059,
    g:0x005a,h:0x0071,j:0x0072,k:0x005b,l:0x005c,
    z:0x0082,x:0x0083,c:0x006f,v:0x0070,b:0x0087,n:0x0088,m:0x0073,
    tab:0x0040,caps:0x0055,shift:0x006a,ctrl:0x007f,alt:0x0097,
    space:0x0098,enter:0x0077,bksp:0x0038,del:0x0010,
    f1:0x0002,f2:0x0003,f3:0x0004,f4:0x0005,f5:0x0006,f6:0x0007,
    f7:0x0008,f8:0x0009,f9:0x000a,f10:0x000b,f11:0x000c,f12:0x000d,
    minus:0x0021,equals:0x0022,lbr:0x004c,rbr:0x004d,
    comma:0x0074,period:0x0075,slash:0x0076,semi:0x005d,quote:0x005f,
};

const APP_PRESETS = {
    photoshop: {
        name: 'Photoshop',
        base: '#000000',
        perim: '#31a8ff',
        // Tool shortcuts
        keys: {
            [KC.v]:'#31a8ff',  // Move
            [KC.m]:'#31a8ff',  // Marquee
            [KC.l]:'#31a8ff',  // Lasso
            [KC.w]:'#31a8ff',  // Magic Wand
            [KC.c]:'#31a8ff',  // Crop
            [KC.i]:'#31a8ff',  // Eyedropper
            [KC.j]:'#31a8ff',  // Healing
            [KC.b]:'#ff6600',  // Brush (highlight)
            [KC.s]:'#ff6600',  // Clone Stamp
            [KC.y]:'#31a8ff',  // History Brush
            [KC.e]:'#ff4444',  // Eraser (red)
            [KC.g]:'#31a8ff',  // Gradient
            [KC.o]:'#31a8ff',  // Dodge/Burn
            [KC.p]:'#31a8ff',  // Pen
            [KC.t]:'#31a8ff',  // Text
            [KC.u]:'#31a8ff',  // Shape
            [KC.h]:'#224488',  // Hand
            [KC.z]:'#224488',  // Zoom
            [KC.d]:'#444444',  // Default colors
            [KC.x]:'#444444',  // Swap colors
            [KC.q]:'#442244',  // Quick Mask
            [KC.space]:'#1a2a44', // Hand (hold)
            [KC.tab]:'#1a1a2a',   // Hide panels
            [KC.lbr]:'#333355',   // Brush smaller
            [KC.rbr]:'#333355',   // Brush bigger
            [KC.f5]:'#222244',    // Brushes panel
        },
        ctrl: {  // Ctrl+key shortcuts
            [KC.z]:'#ff4444',  // Undo
            [KC.s]:'#44ff44',  // Save
            [KC.n]:'#44aaff',  // New
            [KC.o]:'#44aaff',  // Open
            [KC.a]:'#ffaa00',  // Select All
            [KC.d]:'#ffaa00',  // Deselect
            [KC.c]:'#88ff88',  // Copy
            [KC.v]:'#88ff88',  // Paste
            [KC.x]:'#88ff88',  // Cut
            [KC.t]:'#ff8800',  // Free Transform
            [KC.j]:'#44aaff',  // Duplicate Layer
            [KC.e]:'#ffaa00',  // Merge Down
            [KC.g]:'#44aaff',  // Group
            [KC.equals]:'#666688', // Zoom In
            [KC.minus]:'#666688',  // Zoom Out
        },
        shift: {
            [KC.b]:'#ff8844',  // Pencil (shift+B cycles tools)
            [KC.m]:'#5588cc',  // Elliptical Marquee
            [KC.f5]:'#444466', // Fill
            [KC.f6]:'#444466', // Feather
        },
        alt: {
            [KC.bksp]:'#ff8844',  // Fill foreground
            [KC.del]:'#ff8844',   // Fill background
        },
    },
    premiere: {
        name: 'Premiere Pro',
        base: '#000000',
        perim: '#9999ff',
        keys: {
            [KC.space]:'#9999ff',  // Play/Pause
            [KC.j]:'#6666cc',     // Rewind
            [KC.k]:'#9999ff',     // Pause
            [KC.l]:'#6666cc',     // Forward
            [KC.i]:'#ff8800',     // Mark In
            [KC.o]:'#ff8800',     // Mark Out
            [KC.c]:'#ff4444',     // Razor tool
            [KC.v]:'#9999ff',     // Selection tool
            [KC.a]:'#6666aa',     // Track Select
            [KC.b]:'#6666aa',     // Rolling Edit
            [KC.n]:'#6666aa',     // Slip
            [KC.m]:'#44cc44',     // Add Marker
            [KC.semi]:'#ffaa00', // Lift
            [KC.quote]:'#ffaa00',    // Extract
            [KC.comma]:'#666688',    // Shuttle left
            [KC.period]:'#666688',   // Shuttle right
            [KC.q]:'#446688',     // Trim start to playhead
            [KC.w]:'#446688',     // Trim end to playhead
            [KC.d]:'#446688',     // Select clip at playhead
            [KC.e]:'#446688',     // Extend edit
            [KC.del]:'#ff4444',   // Delete/Ripple
            [KC.bksp]:'#ff4444',  // Delete
            [KC.equals]:'#444466', // Zoom in timeline
            [KC.minus]:'#444466',  // Zoom out timeline
            [KC.f1]:'#333344',    // Help
        },
        ctrl: {
            [KC.z]:'#ff4444',    // Undo
            [KC.s]:'#44ff44',    // Save
            [KC.k]:'#ff4444',    // Cut at playhead
            [KC.m]:'#44aaff',    // Export Media
            [KC.d]:'#ffaa00',    // Duration
            [KC.c]:'#88ff88',    // Copy
            [KC.v]:'#88ff88',    // Paste
            [KC.a]:'#ffaa00',    // Select All
        },
        shift: {
            [KC['1']]:'#444466', // Audio track 1
            [KC['2']]:'#444466', // Audio track 2
            [KC['3']]:'#444466', // Audio track 3
            [KC.del]:'#ff6644',  // Ripple delete
        },
        alt: {},
    },
    gimp: {
        name: 'GIMP',
        base: '#000000',
        perim: '#8c6b3e',
        keys: {
            [KC.b]:'#ff8800',  // Paintbrush
            [KC.p]:'#cc8844',  // Pencil
            [KC.e]:'#ff4444',  // Eraser
            [KC.a]:'#44aa44',  // Airbrush
            [KC.g]:'#44aa88',  // Gradient
            [KC.f]:'#44aa88',  // Flip
            [KC.t]:'#44aaff',  // Text
            [KC.z]:'#446688',  // Zoom
            [KC.m]:'#44aa44',  // Move
            [KC.o]:'#44aa44',  // Color Picker
            [KC.r]:'#44aa44',  // Rotate
            [KC.s]:'#44aa44',  // Scale
            [KC.u]:'#44aa44',  // Fuzzy Select
            [KC.i]:'#44aa44',  // Scissors
            [KC.n]:'#44aa44',  // Measure
            [KC.c]:'#44aa44',  // Clone
            [KC.h]:'#44aa44',  // Heal
            [KC.l]:'#44aa44',  // Free Select (Lasso)
            [KC.q]:'#44aa44',  // Align
            [KC.w]:'#44aa44',  // Warp
            [KC.x]:'#666644',  // Swap colors
            [KC.d]:'#666644',  // Default colors
            [KC.lbr]:'#444433',  // Brush smaller
            [KC.rbr]:'#444433',  // Brush bigger
            [KC.space]:'#223322',
        },
        ctrl: {
            [KC.z]:'#ff4444',  // Undo
            [KC.s]:'#44ff44',  // Save/Export
            [KC.a]:'#ffaa00',  // Select All
            [KC.c]:'#88ff88',  // Copy
            [KC.v]:'#88ff88',  // Paste
            [KC.x]:'#88ff88',  // Cut
            [KC.d]:'#ffaa00',  // Duplicate
            [KC.l]:'#44aaff',  // Levels
            [KC.u]:'#44aaff',  // Curves (Hue-Sat)
            [KC.b]:'#44aaff',  // Brightness-Contrast
            [KC.e]:'#44aaff',  // Fit image in window
            [KC.n]:'#44aaff',  // New
        },
        shift: {},
        alt: {},
    },
    blender: {
        name: 'Blender',
        base: '#000000',
        perim: '#ea7600',
        keys: {
            [KC.g]:'#ea7600',  // Grab/Move
            [KC.r]:'#ea7600',  // Rotate
            [KC.s]:'#ea7600',  // Scale
            [KC.e]:'#ff8844',  // Extrude
            [KC.x]:'#ff4444',  // Delete
            [KC.tab]:'#446688', // Edit/Object mode toggle
            [KC.z]:'#446688',  // Shading toggle
            [KC.a]:'#ffaa00',  // Select All
            [KC.b]:'#886644',  // Box Select
            [KC.c]:'#886644',  // Circle Select
            [KC.l]:'#886644',  // Select Linked
            [KC.h]:'#444444',  // Hide
            [KC.m]:'#444444',  // Merge/Collection
            [KC.n]:'#444444',  // Properties panel
            [KC.t]:'#444444',  // Toolbar
            [KC.i]:'#ff8844',  // Inset
            [KC.k]:'#ff8844',  // Knife
            [KC.f]:'#ff8844',  // Fill face
            [KC.p]:'#886644',  // Separate
            [KC.o]:'#886644',  // Proportional editing
            [KC.space]:'#335533', // Play animation
            [KC['1']]:'#224422', // Vertex mode
            [KC['2']]:'#224422', // Edge mode
            [KC['3']]:'#224422', // Face mode
            [KC.f1]:'#333333', [KC.f2]:'#333333', [KC.f3]:'#333333',
            [KC.f5]:'#333333', [KC.f12]:'#44aaff', // Render
        },
        ctrl: {
            [KC.z]:'#ff4444',  // Undo
            [KC.s]:'#44ff44',  // Save
            [KC.c]:'#88ff88',  // Copy
            [KC.v]:'#88ff88',  // Paste
            [KC.a]:'#ffaa00',  // Deselect All
            [KC.j]:'#886644',  // Join
            [KC.r]:'#ff8844',  // Loop Cut
            [KC.b]:'#886644',  // Bevel
            [KC.tab]:'#446688', // Pie menu
        },
        shift: {
            [KC.a]:'#ffaa00',  // Add menu
            [KC.d]:'#886644',  // Duplicate
            [KC.s]:'#44ff44',  // Save As
            [KC.z]:'#ff6644',  // Redo
            [KC.space]:'#335533', // Reverse playback
        },
        alt: {
            [KC.z]:'#446688',  // Shading pie
        },
    },
};

let activeAppPreset = null;
let activeModifiers = new Set();

function appPreset(name) {
    const p = APP_PRESETS[name];
    if (!p) return;
    selectedKeys.clear();
    appliedGroups = [];
    activeAppPreset = name;
    document.getElementById('modifier-hint').style.display = 'block';

    // Apply base layer
    applyAppLayer(p, 'base');

    // Build groups and send to hardware
    const colorGroups = {};
    for (const [code, color] of Object.entries(keyColors)) {
        if (color === '#000000') continue;
        if (!colorGroups[color]) colorGroups[color] = [];
        colorGroups[color].push(parseInt(code));
    }
    for (const [color, codes] of Object.entries(colorGroups)) {
        appliedGroups.push({ effect: 'static', speed: 0, colors: [color], keys: codes });
    }
    sendAllGroups();
    document.querySelectorAll('.kb-key').forEach(k => { k.style.outline = ''; });
}

function applyAppLayer(p, layer) {
    keyColors = {};
    const allKeys = document.querySelectorAll('.kb-key');
    const keyEls = {};
    allKeys.forEach(k => { keyEls[parseInt(k.dataset.code)] = k; });

    // Set base color on all
    allKeys.forEach(k => {
        const code = parseInt(k.dataset.code);
        keyColors[code] = p.base;
        applyKeyColor(k, p.base);
    });

    // Highlight the tool/shortcut keys for this layer
    let layerKeys = p.keys || {};
    if (layer === 'ctrl' && p.ctrl) layerKeys = p.ctrl;
    else if (layer === 'shift' && p.shift) layerKeys = p.shift;
    else if (layer === 'alt' && p.alt) layerKeys = p.alt;

    for (const [codeStr, color] of Object.entries(layerKeys)) {
        const code = parseInt(codeStr);
        if (keyEls[code]) {
            keyColors[code] = color;
            applyKeyColor(keyEls[code], color);
        }
    }

    // Highlight the active modifier key itself
    if (layer === 'ctrl' && keyEls[KC.ctrl]) {
        keyColors[KC.ctrl] = '#ffffff';
        applyKeyColor(keyEls[KC.ctrl], '#ffffff');
    }
    if (layer === 'shift' && keyEls[KC.shift]) {
        keyColors[KC.shift] = '#ffffff';
        applyKeyColor(keyEls[KC.shift], '#ffffff');
    }
    if (layer === 'alt' && keyEls[KC.alt]) {
        keyColors[KC.alt] = '#ffffff';
        applyKeyColor(keyEls[KC.alt], '#ffffff');
    }

    // Perimeter
    if (p.perim) {
        const allPerim = [...PERIM_REAR_TOP,...PERIM_REAR_BOT,...PERIM_FRONT];
        allPerim.forEach(code => {
            keyColors[code] = p.perim;
            if (keyEls[code]) applyKeyColor(keyEls[code], p.perim);
        });
    }
}

// Modifier key detection — swap lighting on Shift/Ctrl/Alt press
document.addEventListener('keydown', (e) => {
    if (!activeAppPreset) return;
    const p = APP_PRESETS[activeAppPreset];
    if (!p) return;
    let layer = null;
    if (e.key === 'Control') layer = 'ctrl';
    else if (e.key === 'Shift') layer = 'shift';
    else if (e.key === 'Alt') { layer = 'alt'; e.preventDefault(); }
    if (layer && !activeModifiers.has(layer)) {
        activeModifiers.add(layer);
        applyAppLayer(p, layer);
        if (livePreview) previewHW(buildFullHWState(null, null));
    }
});

document.addEventListener('keyup', (e) => {
    if (!activeAppPreset) return;
    const p = APP_PRESETS[activeAppPreset];
    if (!p) return;
    let layer = null;
    if (e.key === 'Control') layer = 'ctrl';
    else if (e.key === 'Shift') layer = 'shift';
    else if (e.key === 'Alt') layer = 'alt';
    if (layer && activeModifiers.has(layer)) {
        activeModifiers.delete(layer);
        // Restore base or whatever modifier is still held
        const remaining = [...activeModifiers];
        applyAppLayer(p, remaining.length > 0 ? remaining[0] : 'base');
        if (livePreview) previewHW(buildFullHWState(null, null));
    }
});

// =========================================================================
// Effect system — select keys → apply color or effect → clear selection → repeat
// =========================================================================
const EFFECT_MAP = {
    'type-glow': 'type',
    'breathe':   'color-pulse',
    'wave':      'color-wave',
    'rain':      'rain',
};
const EFFECT_CFG = {
    'type-glow': { colors: 1, speed: true },
    'breathe':   { colors: 2, speed: true },
    'wave':      { colors: 2, speed: true },
    'rain':      { colors: 1, speed: true },
};

let selectedEffect = null;

function selectEffect(mode) {
    selectedEffect = mode;
    const cfg = EFFECT_CFG[mode] || { colors: 1, speed: true };
    document.querySelectorAll('[id^="eb-"]').forEach(b => b.classList.remove('active'));
    const btn = document.getElementById('eb-' + mode);
    if (btn) btn.classList.add('active');
    const panel = document.getElementById('effect-controls');
    panel.style.display = 'block';
    document.getElementById('ec-1color').style.display = cfg.colors === 1 ? '' : 'none';
    document.getElementById('ec-2color').style.display = cfg.colors === 2 ? '' : 'none';
    document.getElementById('ec-speed').style.display = cfg.speed ? 'flex' : 'none';
}

document.getElementById('fx-speed').addEventListener('input', function() {
    document.getElementById('fx-speed-val').textContent = this.value;
});

// Apply effect to current selection
function applyEffectToSelection() {
    if (selectedKeys.size === 0) { toast('Select some keys first', false); return; }
    if (!selectedEffect) { toast('Pick an effect first', false); return; }
    const ename = EFFECT_MAP[selectedEffect] || 'static';
    const cfg = EFFECT_CFG[selectedEffect] || { colors: 1 };
    const speed = parseInt(document.getElementById('fx-speed').value) || 2;
    let colors;
    if (cfg.colors === 2) {
        colors = [document.getElementById('fx-color2a').value, document.getElementById('fx-color2b').value];
    } else {
        colors = [document.getElementById('fx-color1').value];
    }
    const codes = [...selectedKeys];

    appliedGroups.push({ effect: ename, speed, colors, keys: codes });

    // Visual: color the keys and clear selection outline
    codes.forEach(code => {
        keyColors[code] = colors[0];
        const el = document.querySelector(`.kb-key[data-code="${code}"]`);
        if (el) { applyKeyColor(el, colors[0]); el.style.outline = ''; }
    });
    selectedKeys.clear();
    sendAllGroups();
    toast(`${ename} on ${codes.length} keys`);
}

async function applySelectedEffect() { applyEffectToSelection(); }

// =========================================================================
// Key Calibration Tool — lights up one keycode at a time to identify mapping
// =========================================================================
const ALL_CODES = [0x0001,0x0002,0x0003,0x0004,0x0005,0x0006,0x0007,0x0008,
  0x0009,0x000a,0x000b,0x000c,0x000d,0x000e,0x000f,0x0010,
  0x0011,0x0012,0x0013,0x0014,0x0016,0x0017,0x0018,0x0019,
  0x001a,0x001b,0x001c,0x001d,0x001e,0x001f,0x0020,0x0021,
  0x0022,0x0026,0x0027,0x0028,0x0029,0x0038,0x0040,0x0042,
  0x0043,0x0044,0x0045,0x0046,0x0047,0x0048,0x0049,0x004a,
  0x004b,0x004c,0x004d,0x004e,0x004f,0x0050,0x0051,0x0055,
  0x0058,0x0059,0x005a,0x005b,0x005c,0x005d,0x005f,0x0068,
  0x006a,0x006d,0x006e,0x006f,0x0070,0x0071,0x0072,0x0073,
  0x0074,0x0075,0x0076,0x0077,0x0079,0x007b,0x007c,0x007f,
  0x0080,0x0082,0x0083,0x0087,0x0088,0x008d,0x008e,0x0090,
  0x0092,0x0096,0x0097,0x0098,0x009a,0x009b,0x009c,0x009d,
  0x009f,0x00a1,0x00a3,0x00a5,0x00a7];
let calIdx = 0;
let calActive = false;

function startCalibration() {
    calActive = true;
    calIdx = 0;
    document.getElementById('cal-info').style.display = 'block';
    calShow();
}
function calStop() {
    calActive = false;
    document.getElementById('cal-info').style.display = 'none';
}
function calNext() { if (calIdx < ALL_CODES.length - 1) { calIdx++; calShow(); } }
function calPrev() { if (calIdx > 0) { calIdx--; calShow(); } }
function calShow() {
    const code = ALL_CODES[calIdx];
    document.getElementById('cal-idx').textContent = calIdx + 1;
    document.getElementById('cal-code').textContent = '0x' + code.toString(16).padStart(4, '0');
    // Light ONLY this one key bright white on hardware
    const state = {};
    state['0x' + code.toString(16).padStart(4, '0')] = '#ffffff';
    fetch('/preview', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({keys: state})
    });
}

// Build keyboard on load
buildKeyboard();

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
        if self.path == '/effect-keys':
            # Per-key-group effects: {groups: [{effect, speed, colors:["#RRGGBB"], keys:["0xNNNN"]}]}
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            try:
                groups = []
                for g in body.get('groups', []):
                    ename = g.get('effect', 'static')
                    speed = g.get('speed', 2)
                    colors = []
                    for c in g.get('colors', []):
                        h = c.lstrip('#')
                        colors.append((int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)))
                    codes = []
                    for k in g.get('keys', []):
                        codes.append(int(k, 16) if isinstance(k, str) else int(k))
                    groups.append((ename, speed, colors, codes))
                ok = _send_effect_groups(groups)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'ok': ok}).encode())
            except Exception as e:
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'err': str(e)}).encode())
            return
        if self.path == '/preview':
            # Fast HID preview — no subprocess, direct ioctl
            # Body: {"keys": {"0x0042": "#ff0000", ...}}
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            keys = body.get('keys', {})
            try:
                key_map = {}
                for code_str, hex_color in keys.items():
                    code = int(code_str, 16) if code_str.startswith('0x') else int(code_str)
                    h = hex_color.lstrip('#')
                    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
                    key_map[code] = (r, g, b)
                ok = _send_keys_fast(key_map)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'ok': ok}).encode())
            except Exception as e:
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'err': str(e)}).encode())
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
