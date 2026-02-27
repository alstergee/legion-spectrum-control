#!/usr/bin/env python3
"""
Lenovo Legion Gen 10 Spectrum Keyboard/Accent Lighting Controller
Based on LenovoLegionToolkit's SpectrumKeyboardBacklightController protocol.

Protocol: HID Feature Reports (960 bytes) via 048d:c197 (ITE 8258).
Header format: [0x07, operation_type, size_lo, 0x03]

Zones:
  keyboard  - 101 per-key LEDs on the keyboard
  perimeter - 28 accent LEDs around the chassis edges (front, sides, rear)
  logo      - 1 LED behind the "LEGION" text on the lid
  all       - everything (key 0x0065)
"""

import sys
import os
import fcntl
import array
import struct
import glob
import json

# ---------------------------------------------------------------------------
# HID constants
# ---------------------------------------------------------------------------
HIDIOCSFEATURE = lambda size: 0xC0004806 | (size << 16)
HIDIOCGFEATURE = lambda size: 0xC0004807 | (size << 16)
REPORT_SIZE = 960

# ---------------------------------------------------------------------------
# Spectrum protocol operation types
# ---------------------------------------------------------------------------
OP_COMPATIBILITY    = 0xD1
OP_KEY_COUNT        = 0xC4
OP_KEY_PAGE         = 0xC5
OP_PROFILE_CHANGE   = 0xC8
OP_PROFILE_DEFAULT  = 0xC9
OP_PROFILE          = 0xCA
OP_EFFECT_CHANGE    = 0xCB
OP_EFFECT           = 0xCC
OP_GET_BRIGHTNESS   = 0xCD
OP_BRIGHTNESS       = 0xCE
OP_AURORA_START_STOP = 0xD0
OP_AURORA_SEND_BITMAP = 0xA1
OP_GET_LOGO_STATUS  = 0xA5
OP_LOGO_STATUS      = 0xA6

# ---------------------------------------------------------------------------
# Effect types
# ---------------------------------------------------------------------------
EFFECTS = {
    'screw-rainbow': 1,
    'rainbow-wave':  2,
    'color-change':  3,
    'color-pulse':   4,
    'color-wave':    5,
    'smooth':        6,
    'rain':          7,
    'ripple':        8,
    'audio-bounce':  9,
    'audio-ripple':  10,
    'static':        11,
    'type':          12,
}

# Effects that need a speed parameter
EFFECTS_WITH_SPEED = {
    'screw-rainbow', 'rainbow-wave', 'color-change', 'color-pulse',
    'color-wave', 'smooth', 'rain', 'ripple', 'type',
}

# Effects that use direction
EFFECTS_WITH_DIRECTION = {'color-wave', 'rainbow-wave'}

# Effects that use clockwise
EFFECTS_WITH_CLOCKWISE = {'screw-rainbow'}

# Directions
DIRECTIONS = {
    'up':    1,
    'down':  2,
    'right': 3,
    'left':  4,
}

# ---------------------------------------------------------------------------
# Zone definitions — Legion Pro 7 16IAX10H (22x9 Full Spectrum layout)
# ---------------------------------------------------------------------------
KEYBOARD_KEYS = [
    0x0001, 0x0002, 0x0003, 0x0004, 0x0005, 0x0006, 0x0007, 0x0008,
    0x0009, 0x000a, 0x000b, 0x000c, 0x000d, 0x000e, 0x000f, 0x0010,
    0x0011, 0x0012, 0x0013, 0x0014, 0x0016, 0x0017, 0x0018, 0x0019,
    0x001a, 0x001b, 0x001c, 0x001d, 0x001e, 0x001f, 0x0020, 0x0021,
    0x0022, 0x0026, 0x0027, 0x0028, 0x0029, 0x0038, 0x0040, 0x0042,
    0x0043, 0x0044, 0x0045, 0x0046, 0x0047, 0x0048, 0x0049, 0x004a,
    0x004b, 0x004c, 0x004d, 0x004e, 0x004f, 0x0050, 0x0051, 0x0055,
    0x0058, 0x0059, 0x005a, 0x005b, 0x005c, 0x005d, 0x005f, 0x0068,
    0x006a, 0x006d, 0x006e, 0x006f, 0x0070, 0x0071, 0x0072, 0x0073,
    0x0074, 0x0075, 0x0076, 0x0077, 0x0079, 0x007b, 0x007c, 0x007f,
    0x0080, 0x0082, 0x0083, 0x0087, 0x0088, 0x008d, 0x008e, 0x0090,
    0x0092, 0x0096, 0x0097, 0x0098, 0x009a, 0x009b, 0x009c, 0x009d,
    0x009f, 0x00a1, 0x00a3, 0x00a5, 0x00a7,
]

PERIMETER_KEYS = [
    # Rear accent (row 0)
    0x03e9, 0x03ea, 0x03eb, 0x03ec, 0x03ed, 0x03ee, 0x03ef,
    0x03f0, 0x03f1, 0x03f2, 0x03f3, 0x03f4, 0x03f5, 0x03f6,
    0x03f7, 0x03f8, 0x03f9, 0x03fa,
    # Side + front accent
    0x01f5, 0x01f6, 0x01f7, 0x01f8, 0x01f9, 0x01fa,
    0x01fb, 0x01fc, 0x01fd, 0x01fe,
]

LOGO_KEY = 0x05DD
ALL_KEY  = 0x0065  # special "all lights" code

ZONES = {
    'keyboard':  KEYBOARD_KEYS,
    'perimeter': PERIMETER_KEYS,
    'logo':      [LOGO_KEY],
    'all':       [ALL_KEY],
}

# ---------------------------------------------------------------------------
# Low-level HID helpers
# ---------------------------------------------------------------------------
def find_spectrum_device():
    """Find hidraw for 048d:c197 (ITE 8258) — the Spectrum protocol responder."""
    for hidraw in sorted(glob.glob('/sys/class/hidraw/hidraw*')):
        name = os.path.basename(hidraw)
        try:
            with open(f'{hidraw}/device/uevent') as f:
                uevent = f.read()
            if '048D' not in uevent.upper() or 'C197' not in uevent.upper():
                continue
            with open(f'{hidraw}/device/report_descriptor', 'rb') as f:
                desc = f.read()
            if b'\x06\x89\xff' in desc:
                return f'/dev/{name}'
        except (IOError, OSError):
            continue
    return None


def set_feature(dev, data):
    buf = array.array('B', data[:REPORT_SIZE].ljust(REPORT_SIZE, b'\x00'))
    fcntl.ioctl(dev, HIDIOCSFEATURE(REPORT_SIZE), buf)


def get_feature(dev, report_id=0x07):
    buf = array.array('B', [report_id] + [0] * (REPORT_SIZE - 1))
    fcntl.ioctl(dev, HIDIOCGFEATURE(REPORT_SIZE), buf)
    return bytes(buf)


def make_header(op_type, size=0xC0):
    return bytes([0x07, op_type, size & 0xFF, 0x03])


def make_request(op_type, payload=b'', size=0xC0):
    return (make_header(op_type, size) + payload).ljust(REPORT_SIZE, b'\x00')

# ---------------------------------------------------------------------------
# Protocol operations
# ---------------------------------------------------------------------------
def get_brightness(dev):
    set_feature(dev, make_request(OP_GET_BRIGHTNESS))
    return get_feature(dev)[4]


def set_brightness(dev, level):
    set_feature(dev, make_request(OP_BRIGHTNESS, bytes([max(0, min(9, level))])))


def get_profile(dev):
    set_feature(dev, make_request(OP_PROFILE))
    return get_feature(dev)[4]


def set_profile(dev, profile):
    set_feature(dev, make_request(OP_PROFILE_CHANGE, bytes([max(0, min(6, profile))])))


def set_profile_default(dev, profile):
    set_feature(dev, make_request(OP_PROFILE_DEFAULT, bytes([max(0, min(6, profile))])))


def get_logo_status(dev):
    set_feature(dev, make_request(OP_GET_LOGO_STATUS))
    return get_feature(dev)[4] == 1


def set_logo_status(dev, on):
    set_feature(dev, make_request(OP_LOGO_STATUS, bytes([1 if on else 0])))


def check_compatibility(dev):
    set_feature(dev, make_request(OP_COMPATIBILITY))
    return get_feature(dev)[4] == 0


def get_key_count(dev):
    set_feature(dev, make_request(OP_KEY_COUNT, bytes([0x07])))
    resp = get_feature(dev)
    return resp[5], resp[6]  # rows, cols


def get_current_state(dev):
    """Read per-key RGB state from the device."""
    resp = get_feature(dev)
    # Response is packed LENOVO_SPECTRUM_KEY_STATE entries: u16 keycode, u8 r, g, b
    keys = {}
    offset = 4  # skip header
    while offset + 4 < REPORT_SIZE:
        kc = resp[offset] | (resp[offset+1] << 8)
        if kc == 0:
            break
        r, g, b = resp[offset+2], resp[offset+3], resp[offset+4]
        keys[kc] = (r, g, b)
        offset += 5
    return keys

# ---------------------------------------------------------------------------
# Effect builder
# ---------------------------------------------------------------------------
def build_effect_header(effect_type, speed=0, direction=0, clockwise=0, color_mode=2):
    return bytes([
        0x06, 0x01, effect_type,
        0x02, speed,
        0x03, clockwise,
        0x04, direction,
        0x05, color_mode,
        0x06, 0x00,
    ])


def build_effect(effect_no, effect_type, colors, keycodes,
                 speed=0, direction=0, clockwise=0):
    """Build a single effect binary blob."""
    color_mode = 0x02 if colors else (0x01 if effect_type != 11 else 0x00)
    header = build_effect_header(effect_type, speed, direction, clockwise, color_mode)

    data = bytes([effect_no])
    data += header
    data += bytes([len(colors)])
    for r, g, b in colors:
        data += bytes([r, g, b])
    data += bytes([len(keycodes)])
    for kc in keycodes:
        data += struct.pack('<H', kc)
    return data


def send_effects(dev, profile, effects_data):
    """Send a full effect description to the device.
    effects_data is a list of bytes blobs from build_effect().
    """
    payload = bytes([profile, 0x01, 0x01])
    for e in effects_data:
        payload += e
    data = make_header(OP_EFFECT_CHANGE) + payload
    set_feature(dev, data)

# ---------------------------------------------------------------------------
# High-level commands
# ---------------------------------------------------------------------------
def resolve_zone_keys(zone_name):
    """Resolve a zone name to a list of keycodes."""
    if zone_name in ZONES:
        return ZONES[zone_name]
    # Allow comma-separated zone names: "keyboard,logo"
    keys = []
    for z in zone_name.split(','):
        z = z.strip()
        if z in ZONES:
            keys.extend(ZONES[z])
        else:
            raise ValueError(f"Unknown zone: {z}. Valid: {', '.join(ZONES.keys())}")
    return keys


def parse_color(s):
    """Parse a color string: 'R,G,B' or '#RRGGBB' or a named color."""
    named = {
        'white':   (255, 255, 255),
        'red':     (255, 0, 0),
        'green':   (0, 255, 0),
        'blue':    (0, 0, 255),
        'cyan':    (0, 255, 255),
        'magenta': (255, 0, 255),
        'yellow':  (255, 255, 0),
        'orange':  (255, 128, 0),
        'purple':  (128, 0, 255),
        'pink':    (255, 64, 128),
        'off':     (0, 0, 0),
        'black':   (0, 0, 0),
    }
    s = s.strip().lower()
    if s in named:
        return named[s]
    if s.startswith('#') and len(s) == 7:
        return (int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16))
    # Bare 6-char hex without # prefix
    if len(s) == 6 and all(c in '0123456789abcdef' for c in s):
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    parts = s.split(',')
    if len(parts) == 3:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    raise ValueError(f"Invalid color: {s}. Use name, R,G,B, or #RRGGBB")


def cmd_preset(dev, name, zones, colors, speed=2, direction=0, clockwise=0):
    """Apply a named effect preset to the given zones."""
    profile = get_profile(dev)

    if name not in EFFECTS:
        raise ValueError(f"Unknown effect: {name}. Valid: {', '.join(EFFECTS.keys())}")
    etype = EFFECTS[name]

    effects = []
    effect_no = 1

    for zone_name in zones:
        keys = resolve_zone_keys(zone_name)
        zone_colors = colors if colors else []
        # For static with no color specified, default white
        if name == 'static' and not zone_colors:
            zone_colors = [(255, 255, 255)]
        effects.append(build_effect(
            effect_no, etype, zone_colors, keys,
            speed=speed, direction=direction, clockwise=clockwise,
        ))
        effect_no += 1

    send_effects(dev, profile, effects)


def cmd_multi(dev, zone_specs):
    """Apply different effects/colors to different zones at once.
    zone_specs is a list of (zone, effect_name, colors, speed, direction, clockwise).
    """
    profile = get_profile(dev)
    effects = []
    effect_no = 1

    for zone_name, ename, colors, speed, direction, clockwise in zone_specs:
        etype = EFFECTS[ename]
        keys = resolve_zone_keys(zone_name)
        effects.append(build_effect(
            effect_no, etype, colors, keys,
            speed=speed, direction=direction, clockwise=clockwise,
        ))
        effect_no += 1

    send_effects(dev, profile, effects)


def cmd_keys(dev, key_colors):
    """Set individual keys to specific colors (everything else off).
    key_colors: dict of keycode -> (r, g, b)
    """
    profile = get_profile(dev)
    effects = []
    effect_no = 1

    # Group by color for efficiency
    color_groups = {}
    for kc, color in key_colors.items():
        color_groups.setdefault(color, []).append(kc)

    for color, keycodes in color_groups.items():
        effects.append(build_effect(
            effect_no, EFFECTS['static'], [color], keycodes,
        ))
        effect_no += 1

    send_effects(dev, profile, effects)

# ---------------------------------------------------------------------------
# Main CLI
# ---------------------------------------------------------------------------
def print_usage():
    print("""Lenovo Legion Gen 10 Spectrum Lighting Controller

BASIC CONTROLS:
  status                          Show brightness, profile, logo
  off                             All lights off (brightness 0)
  on                              Restore brightness to 3
  brightness N                    Set brightness 0-9
  profile N                       Switch profile 0-6
  default N                       Reset profile N to factory default
  logo on|off                     Toggle LEGION lid logo
  info                            Device info + key layout

PRESETS (apply to zones):
  preset EFFECT [ZONES] [COLORS] [--speed 1-3] [--dir up|down|left|right]

  Effects: static, rainbow-wave, screw-rainbow, color-change, color-pulse,
           color-wave, smooth, rain, ripple, type
  Zones:   keyboard, perimeter, logo, all (default: all)
  Colors:  white, red, green, blue, cyan, magenta, yellow, orange, purple,
           pink, off, #RRGGBB, or R,G,B

  Examples:
    preset static keyboard white                  White keyboard only
    preset static keyboard white perimeter off    White keys, no edge lights
    preset rainbow-wave all --speed 2             Rainbow wave everything
    preset color-pulse keyboard red,blue          Pulse between red and blue
    preset static keyboard #FF8800               Orange keyboard

MULTI-ZONE (different effects per zone in one command):
  multi zone1:effect:color zone2:effect:color ...

  Examples:
    multi keyboard:static:white perimeter:static:off
    multi keyboard:static:white perimeter:color-wave:red,blue logo:static:off
    multi keyboard:rain:cyan perimeter:rainbow-wave

PER-KEY CONTROL:
  keys KEYCODE:COLOR [KEYCODE:COLOR ...]

  Keycodes are hex (0x0001) or the key names from 'keymap'.
  Examples:
    keys 0x0001:red 0x0002:blue 0x0003:green
    keys esc:red wasd:green

  keymap                          Print all keycodes and their names

QUICK PRESETS:
  white                           White keyboard, no perimeter
  rgb                             Rainbow wave on everything
  stealth                         All lights completely off
""")


# Key name mapping (common keys)
KEY_NAMES = {
    'esc': 0x0001, 'f1': 0x0002, 'f2': 0x0003, 'f3': 0x0004,
    'f4': 0x0005, 'f5': 0x0006, 'f6': 0x0007, 'f7': 0x0008,
    'f8': 0x0009, 'f9': 0x000a, 'f10': 0x000b, 'f11': 0x000c,
    'f12': 0x000d, 'prtsc': 0x000e, 'insert': 0x000f, 'delete': 0x0010,
    'home': 0x0011, 'end': 0x0012, 'pgup': 0x0013, 'pgdn': 0x0014,
    'tilde': 0x0016, '1': 0x0017, '2': 0x0018, '3': 0x0019,
    '4': 0x001a, '5': 0x001b, '6': 0x001c, '7': 0x001d,
    '8': 0x001e, '9': 0x001f, '0': 0x0020, 'minus': 0x0021,
    'equals': 0x0022, 'backspace': 0x0038,
    'numlock': 0x0026, 'numdiv': 0x0027, 'nummul': 0x0028, 'numsub': 0x0029,
    'tab': 0x0040, 'q': 0x0042, 'w': 0x0043, 'e': 0x0044,
    'r': 0x0045, 't': 0x0046, 'y': 0x0047, 'u': 0x0048,
    'i': 0x0049, 'o': 0x004a, 'p': 0x004b, 'lbracket': 0x004c,
    'rbracket': 0x004d, 'backslash': 0x004e,
    'num7': 0x004f, 'num8': 0x0050, 'num9': 0x0051, 'numadd': 0x0068,
    'caps': 0x0055, 'a': 0x006d, 's': 0x006e, 'd': 0x0058,
    'f': 0x0059, 'g': 0x005a, 'h': 0x0071, 'j': 0x0072,
    'k': 0x005b, 'l': 0x005c, 'semicolon': 0x005d, 'quote': 0x005f,
    'num4': 0x0079, 'num5': 0x007b, 'num6': 0x007c,
    'lshift': 0x01f5, 'z': 0x006a, 'x': 0x0082, 'c': 0x0083,
    'v': 0x006f, 'b': 0x0070, 'n': 0x0087, 'm': 0x0088,
    'comma': 0x0073, 'period': 0x0074, 'slash': 0x0075,
    'rshift': 0x008d, 'up': 0x008e, 'num1': 0x0090, 'num2': 0x0092,
    'num3': 0x00a7,
    'lctrl': 0x01f5, 'fn': 0x007f, 'win': 0x0080, 'lalt': 0x0096,
    'space': 0x0098, 'ralt': 0x009a, 'rctrl': 0x009b,
    'left': 0x009c, 'down': 0x009d, 'right': 0x009f,
    'num0': 0x00a3, 'numdot': 0x00a5, 'numenter': 0x00a7,
    'enter': 0x0077,
}

# WASD group
KEY_GROUPS = {
    'wasd': ['w', 'a', 's', 'd'],
    'arrows': ['up', 'down', 'left', 'right'],
    'numpad': ['numlock', 'numdiv', 'nummul', 'numsub', 'num7', 'num8', 'num9',
               'numadd', 'num4', 'num5', 'num6', 'num1', 'num2', 'num3',
               'num0', 'numdot', 'numenter'],
    'fkeys': ['f1', 'f2', 'f3', 'f4', 'f5', 'f6', 'f7', 'f8', 'f9', 'f10', 'f11', 'f12'],
}


def resolve_key(name):
    """Resolve a key name/hex/group to a list of keycodes."""
    name = name.lower().strip()
    if name in KEY_GROUPS:
        return [KEY_NAMES[k] for k in KEY_GROUPS[name]]
    if name in KEY_NAMES:
        return [KEY_NAMES[name]]
    if name.startswith('0x'):
        return [int(name, 16)]
    raise ValueError(f"Unknown key: {name}. Use 'keymap' to see available names.")


def open_device():
    devpath = find_spectrum_device()
    if not devpath:
        print("ERROR: Spectrum device not found (048d:c197)")
        sys.exit(1)
    return open(devpath, 'rb+', buffering=0)


def main():
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(0)

    cmd = sys.argv[1].lower()

    # Quick presets that don't need arg parsing
    if cmd == 'white':
        dev = open_device()
        cmd_multi(dev, [
            ('keyboard', 'static', [(255, 255, 255)], 0, 0, 0),
            ('perimeter', 'static', [(0, 0, 0)], 0, 0, 0),
            ('logo', 'static', [(0, 0, 0)], 0, 0, 0),
        ])
        # Make sure brightness is up
        if get_brightness(dev) == 0:
            set_brightness(dev, 3)
        print("White keyboard, perimeter off")
        dev.close()
        return

    if cmd == 'rgb':
        dev = open_device()
        cmd_multi(dev, [
            ('keyboard', 'rainbow-wave', [], 2, 4, 0),
            ('perimeter', 'rainbow-wave', [], 2, 4, 0),
            ('logo', 'color-pulse', [(128, 0, 255), (0, 128, 255)], 2, 0, 0),
        ])
        set_logo_status(dev, True)
        if get_brightness(dev) == 0:
            set_brightness(dev, 3)
        print("Rainbow wave on all zones")
        dev.close()
        return

    if cmd == 'stealth':
        dev = open_device()
        cmd_multi(dev, [
            ('keyboard', 'static', [(0, 0, 0)], 0, 0, 0),
            ('perimeter', 'static', [(0, 0, 0)], 0, 0, 0),
            ('logo', 'static', [(0, 0, 0)], 0, 0, 0),
        ])
        set_brightness(dev, 0)
        set_logo_status(dev, False)
        print("All lights off")
        dev.close()
        return

    dev = open_device()

    try:
        if cmd == 'status':
            b = get_brightness(dev)
            p = get_profile(dev)
            logo = get_logo_status(dev)
            print(f"Brightness: {b}/9")
            print(f"Profile:    {p}")
            print(f"Logo:       {'on' if logo else 'off'}")

        elif cmd == 'off':
            set_brightness(dev, 0)
            print("All lights off")

        elif cmd == 'on':
            cmd_multi(dev, [
                ('keyboard', 'static', [(255, 255, 255)], 0, 0, 0),
                ('perimeter', 'static', [(255, 255, 255)], 0, 0, 0),
                ('logo', 'static', [(255, 255, 255)], 0, 0, 0),
            ])
            set_brightness(dev, 9)
            set_logo_status(dev, True)
            print("All lights on: full white, max brightness")

        elif cmd == 'brightness':
            n = int(sys.argv[2])
            set_brightness(dev, n)
            print(f"Brightness: {n}")

        elif cmd == 'profile':
            n = int(sys.argv[2])
            set_profile(dev, n)
            print(f"Profile: {n}")

        elif cmd == 'default':
            n = int(sys.argv[2])
            set_profile_default(dev, n)
            print(f"Profile {n} reset to default")

        elif cmd == 'logo':
            on = sys.argv[2].lower() in ('on', '1', 'true', 'yes')
            set_logo_status(dev, on)
            print(f"Logo: {'on' if on else 'off'}")

        elif cmd == 'info':
            print(f"Compatible: {check_compatibility(dev)}")
            rows, cols = get_key_count(dev)
            print(f"Layout:     {cols}x{rows}")
            print(f"Brightness: {get_brightness(dev)}/9")
            print(f"Profile:    {get_profile(dev)}")
            print(f"Logo:       {'on' if get_logo_status(dev) else 'off'}")
            print(f"Keyboard:   {len(KEYBOARD_KEYS)} keys")
            print(f"Perimeter:  {len(PERIMETER_KEYS)} LEDs")

        elif cmd == 'preset':
            # preset EFFECT [zone1 zone2 ...] [color1 color2 ...] [--speed N] [--dir DIR]
            args = sys.argv[2:]
            if not args:
                print("Usage: preset EFFECT [ZONES] [COLORS] [--speed 1-3] [--dir up|down|left|right]")
                sys.exit(1)

            effect_name = args[0].lower()
            zones = []
            colors = []
            speed = 2
            direction = 0
            clockwise = 0
            i = 1
            while i < len(args):
                a = args[i].lower()
                if a == '--speed' and i + 1 < len(args):
                    speed = int(args[i+1])
                    i += 2
                    continue
                elif a == '--dir' and i + 1 < len(args):
                    d = args[i+1].lower()
                    direction = DIRECTIONS.get(d, 0)
                    i += 2
                    continue
                elif a == '--cw':
                    clockwise = 1
                    i += 1
                    continue
                elif a == '--ccw':
                    clockwise = 2
                    i += 1
                    continue
                elif a in ZONES or ',' in a and all(p.strip() in ZONES for p in a.split(',')):
                    zones.append(a)
                else:
                    try:
                        colors.append(parse_color(a))
                    except ValueError:
                        # Maybe it's a zone
                        if a in ZONES:
                            zones.append(a)
                        else:
                            print(f"Unknown argument: {a}")
                            sys.exit(1)
                i += 1

            if not zones:
                zones = ['all']

            cmd_preset(dev, effect_name, zones, colors, speed, direction, clockwise)
            if get_brightness(dev) == 0:
                set_brightness(dev, 3)
            print(f"{effect_name} on {', '.join(zones)}")

        elif cmd == 'multi':
            # multi zone1:effect:color1,color2 zone2:effect:color ...
            specs = []
            for arg in sys.argv[2:]:
                parts = arg.split(':')
                if len(parts) < 2:
                    print(f"Invalid spec: {arg}. Use zone:effect[:color1,color2]")
                    sys.exit(1)
                zone_name = parts[0].lower()
                ename = parts[1].lower()
                if ename not in EFFECTS:
                    print(f"Unknown effect: {ename}")
                    sys.exit(1)
                colors = []
                speed = 2
                if len(parts) >= 3 and parts[2]:
                    for cs in parts[2].split(','):
                        colors.append(parse_color(cs.strip()))
                if len(parts) >= 4:
                    speed = int(parts[3])
                specs.append((zone_name, ename, colors, speed, 0, 0))

            cmd_multi(dev, specs)
            if get_brightness(dev) == 0:
                set_brightness(dev, 3)
            zones_str = ', '.join(s[0] for s in specs)
            print(f"Applied effects to: {zones_str}")

        elif cmd == 'keys':
            # keys KEY:COLOR [KEY:COLOR ...]
            key_colors = {}
            for arg in sys.argv[2:]:
                parts = arg.split(':')
                if len(parts) != 2:
                    print(f"Invalid: {arg}. Use KEY:COLOR (e.g. wasd:red)")
                    sys.exit(1)
                keycodes = resolve_key(parts[0])
                color = parse_color(parts[1])
                for kc in keycodes:
                    key_colors[kc] = color

            cmd_keys(dev, key_colors)
            if get_brightness(dev) == 0:
                set_brightness(dev, 3)
            print(f"Set {len(key_colors)} individual keys")

        elif cmd == 'keymap':
            print("KEY NAMES:")
            for name, kc in sorted(KEY_NAMES.items(), key=lambda x: x[1]):
                print(f"  {name:15s} 0x{kc:04x}")
            print()
            print("KEY GROUPS:")
            for name, keys in KEY_GROUPS.items():
                print(f"  {name:15s} {', '.join(keys)}")
            print()
            print("ZONES:")
            for name, keys in ZONES.items():
                print(f"  {name:15s} {len(keys)} keys")

        else:
            print(f"Unknown command: {cmd}")
            print("Run with no arguments for help.")
            sys.exit(1)

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        dev.close()


if __name__ == '__main__':
    main()
