# Legion Spectrum Control

Web UI and CLI for controlling Lenovo Legion Gen 10 per-key RGB lighting via the ITE 8258 Spectrum controller (USB HID `048d:c197`).

Built for the **Lenovo Legion Pro 7 16IAX10H** (83F5) but should work on any Gen 10 Legion with Spectrum RGB (22x9 full-spectrum layout).

## What It Controls

- Per-key keyboard RGB (101 keys)
- Perimeter accent LEDs (28 LEDs around chassis edges)
- Lid LEGION logo LED
- Overall LED brightness (0-9)
- Multiple effect types: static, rainbow-wave, color-pulse, rain, ripple, type-lighting, and more
- Multi-zone: set different effects for keyboard, perimeter, and logo independently

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
- No external dependencies (uses only stdlib: `fcntl`, `struct`, `http.server`)
- The `legion-laptop` kernel module from [LenovoLegionLinux](https://github.com/johnfanv2/LenovoLegionLinux) (for hardware monitor data; not required for lighting control)

## Install

```bash
# Clone
sudo git clone https://github.com/alstergee/legion-spectrum-control.git /opt/legion-spectrum-control

# Test CLI
sudo python3 /opt/legion-spectrum-control/spectrum-ctl.py status

# Install systemd service for the web UI
sudo cp /opt/legion-spectrum-control/spectrum-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now spectrum-web.service

# Open http://localhost:5555
```

## CLI Usage

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
```

## Protocol

Based on the Spectrum protocol from [LenovoLegionToolkit](https://github.com/BartoszCichworklern/LenovoLegionToolkit). Communication is via 960-byte HID Feature Reports to the ITE 8258 controller.

Header format: `[0x07, operation_type, size_lo, 0x03]`

Key operations:
| Op Code | Name | Description |
|---------|------|-------------|
| 0xCE | BRIGHTNESS | Set LED brightness 0-9 |
| 0xCD | GET_BRIGHTNESS | Read current brightness |
| 0xCB | EFFECT_CHANGE | Apply effect to zones |
| 0xA6 | LOGO_STATUS | Toggle lid logo on/off |
| 0xC8 | PROFILE_CHANGE | Switch lighting profile |

## Hardware Info

| Component | Details |
|-----------|---------|
| Controller | ITE 8258 (USB HID `048d:c197`) |
| Keyboard | 101 per-key LEDs, 22x9 matrix |
| Perimeter | 28 accent LEDs (18 rear + 10 side/front) |
| Logo | 1 LED behind lid "LEGION" text |
| Zones | keyboard, perimeter, logo, all |

## Related

- [LenovoLegionLinux](https://github.com/johnfanv2/LenovoLegionLinux) - Kernel module for fan control, platform profiles, and hardware monitoring
- [LenovoLegionToolkit](https://github.com/BartoszCichworklern/LenovoLegionToolkit) - Windows utility (Spectrum protocol reference)
- [Issue #385](https://github.com/johnfanv2/LenovoLegionLinux/issues/385) - Gen 10 16IAX10H support tracking

## License

MIT
