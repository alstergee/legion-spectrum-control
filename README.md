# Legion Spectrum Control

**The only open-source per-key RGB controller for Lenovo Legion Gen 10 laptops on Linux.**

CLI + Web UI for full per-key lighting control via the ITE 8258 Spectrum controller (USB HID `048d:c197`). Zero dependencies. Pure Python. Works right now.

Built and tested on the **Lenovo Legion Pro 7 16IAX10H** (83F5, Intel Arrow Lake / RTX 5090). Should work on any Gen 10 Legion with Spectrum RGB (22x9 full-spectrum layout).

## Why This Exists

Every other Linux RGB tool for Legion laptops tops out at 4-zone control. The Gen 10 Spectrum hardware supports **individual key addressing** — 101 keys, 28 perimeter accent LEDs, and the lid logo, all independently controllable. This project is the first and only open-source implementation of that protocol on Linux.

- **Per-key RGB** — set every key to a different color
- **28 perimeter accent LEDs** — rear, side, and front chassis edges
- **Lid LEGION logo** — independent on/off and color
- **12 built-in effects** — static, rainbow-wave, color-pulse, rain, ripple, type-reactive, and more
- **Multi-zone** — different effects on keyboard, perimeter, and logo simultaneously
- **Key groups** — WASD, arrows, numpad, F-keys as named groups
- **Named colors + hex + RGB** — `red`, `#FF8800`, `255,128,0`
- **Web UI** with hardware monitoring (fan speeds, temps, platform profile)
- **No dependencies** — stdlib only (Python 3.6+, `fcntl`, `struct`, `http.server`)

## Quick Demo

```bash
# Per-key: WASD green, arrows cyan, Esc red
sudo spectrum-ctl.py keys wasd:green arrows:cyan esc:red

# Multi-zone: rainbow keyboard, purple pulsing perimeter, logo off
sudo spectrum-ctl.py multi keyboard:rainbow-wave: perimeter:color-pulse:purple,cyan logo:static:off

# Full rainbow everything
sudo spectrum-ctl.py rgb

# Stealth mode
sudo spectrum-ctl.py stealth
```

## Screenshots

The web UI runs on `http://localhost:5555` and provides:

- **Status**: brightness slider, logo toggle, profile info
- **Quick Presets**: one-click lighting modes (Lights On, All Off, Rainbow, White Keys, etc.)
- **Custom Effect**: pick effect, zones, colors, and speed
- **Hardware Monitor**: live fan speeds, temps, and platform profile from the `legion-laptop` kernel module
- **Multi-Zone Builder**: independent effect/color per zone

## Requirements

- Linux with USB HID access (root or udev rules)
- Python 3.6+
- No external dependencies
- The `legion-laptop` kernel module from [LenovoLegionLinux](https://github.com/johnfanv2/LenovoLegionLinux) (optional — for hardware monitor panel in web UI)

## Install

```bash
# Clone
sudo git clone https://github.com/alstergee/legion-spectrum-control.git /opt/legion-spectrum-control
sudo ln -s /opt/legion-spectrum-control/spectrum-ctl.py /usr/local/bin/spectrum-ctl

# Test
sudo spectrum-ctl status

# Install web UI as a service
sudo cp /opt/legion-spectrum-control/spectrum-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now spectrum-web.service

# Open http://localhost:5555
```

## Linux Driver Setup (Gen 10)

Gen 10 Legions (Arrow Lake / 2025 models) have a messy driver situation on Linux 6.17+. Three modules fight over `platform_profile`: the in-tree `lenovo_wmi_gamezone`, `ideapad_laptop`, and the out-of-tree `legion_laptop` (DKMS). Here's the tested config for Gen 10:

```bash
# /etc/modprobe.d/legion-laptop.conf
# Blacklist redundant WMI drivers — legion_laptop handles fan/hwmon/profiles better
blacklist lenovo_wmi_gamezone
blacklist lenovo_wmi_other
blacklist lenovo_wmi_helpers
blacklist lenovo_wmi_events
blacklist lenovo_wmi_capdata01
blacklist lenovo_wmi_hotkey_utilities

# Keep ideapad_laptop for conservation_mode, fn_lock, usb_charging
# (its platform_profile and DYTC are non-functional on Gen 10)
```

```bash
# Lock performance profile across reboots
echo 'w /sys/firmware/acpi/platform_profile - - - - performance' | \
  sudo tee /etc/tmpfiles.d/legion-performance.conf

sudo update-initramfs -u
```

This gives you:
- `legion_laptop` (DKMS): sole authority for fan curves, hwmon (3 fans + 3 temp sensors), platform profiles
- `ideapad_laptop`: conservation_mode, fn_lock, usb_charging
- No more KDE power widget conflicts from `lenovo_wmi_gamezone`

## CLI Reference

```
BASIC CONTROLS:
  status                          Show brightness, profile, logo
  off                             All lights off (brightness 0)
  on                              All LEDs white, full brightness, logo on
  brightness N                    Set brightness 0-9
  logo on|off                     Toggle LEGION lid logo

QUICK PRESETS:
  white                           White keyboard, perimeter off
  rgb                             Rainbow wave on all zones
  stealth                         All lights completely off

PRESETS (apply to zones):
  preset EFFECT [ZONES] [COLORS] [--speed 1-3] [--dir up|down|left|right]

  Effects: static, rainbow-wave, screw-rainbow, color-change, color-pulse,
           color-wave, smooth, rain, ripple, type
  Zones:   keyboard, perimeter, logo, all
  Colors:  white, red, green, blue, cyan, magenta, yellow, orange, purple,
           pink, off, #RRGGBB, or R,G,B

MULTI-ZONE:
  multi zone1:effect:color zone2:effect:color ...

  Examples:
    multi keyboard:static:white perimeter:static:blue
    multi keyboard:rain:cyan perimeter:rainbow-wave logo:color-pulse:purple,blue

PER-KEY:
  keys KEYCODE:COLOR [KEYCODE:COLOR ...]
  keys wasd:red arrows:blue esc:orange

KEY GROUPS:
  wasd, arrows, numpad, fkeys
```

## Protocol

Communication is via 960-byte HID Feature Reports to the ITE 8258 controller, based on the Spectrum protocol reverse-engineered by [LenovoLegionToolkit](https://github.com/BartoszCichworklern/LenovoLegionToolkit).

Header format: `[0x07, operation_type, size_lo, 0x03]`

| Op Code | Name | Description |
|---------|------|-------------|
| 0xCE | BRIGHTNESS | Set LED brightness 0-9 |
| 0xCD | GET_BRIGHTNESS | Read current brightness |
| 0xCB | EFFECT_CHANGE | Apply effect to zones |
| 0xCC | EFFECT | Read current effect |
| 0xA6 | LOGO_STATUS | Toggle lid logo on/off |
| 0xA5 | GET_LOGO_STATUS | Read logo state |
| 0xC8 | PROFILE_CHANGE | Switch lighting profile (0-6) |
| 0xCA | PROFILE | Read current profile |
| 0xC4 | KEY_COUNT | Query layout dimensions |
| 0xD1 | COMPATIBILITY | Check device compatibility |
| 0xA1 | AURORA_SEND_BITMAP | Raw per-key bitmap mode |

## Hardware

| Component | Details |
|-----------|---------|
| Controller | ITE 8258 (USB HID `048d:c197`) |
| Keyboard | 101 per-key LEDs, 22x9 matrix |
| Perimeter | 28 accent LEDs (18 rear + 10 side/front) |
| Logo | 1 LED behind lid "LEGION" text |
| Zones | keyboard, perimeter, logo, all |

## Tested On

| Model | BIOS | CPU | GPU | Status |
|-------|------|-----|-----|--------|
| Legion Pro 7 16IAX10H (83F5) | Q7CN | Intel Arrow Lake | RTX 5090 | Full per-key + perimeter + logo working |

If you test on another model, open an issue with your results.

## Related Projects

- [LenovoLegionLinux](https://github.com/johnfanv2/LenovoLegionLinux) — Kernel module for fan control and hardware monitoring
- [LenovoLegionToolkit](https://github.com/BartoszCichworklern/LenovoLegionToolkit) — Windows utility (Spectrum protocol reference)
- [L5P-Keyboard-RGB](https://github.com/4JX/L5P-Keyboard-RGB) — 4-zone keyboard RGB for older Legions (Rust)
- [Issue #385](https://github.com/johnfanv2/LenovoLegionLinux/issues/385) — Gen 10 16IAX10H Linux support tracking
- [PR #402](https://github.com/johnfanv2/LenovoLegionLinux/pull/402) — Y-Logo LED fix for Gen 10

## License

MIT
