# RP2040 RGB PWM Controller

Non-addressable RGB LED strip firmware for RP2040 / RP2040-zero.
Hardware PWM, 16-bit resolution, USB CDC serial control, built-in animations.

## Features

- **Hardware PWM** on 3 GPIO pins — 16-bit, 100 Hz – 50 kHz
- **Linux integration** — virtual COM port (`/dev/ttyACM0`), udev rule included
- **10 animations**: static, breath, rainbow, strobe, candle, wave, police, random, storm, temp
- **12 commands**: `RGB`, `#RRGGBB`, `HSV`, `ANIM`, `SPEED`, `PWM`, `INVERT`, `TEMP`, `RANDOM`, `STATE`, `OFF`, `BOOT`, `PING`, `HELP`
- **Common anode / cathode** support (runtime toggle)
- **BOOTSEL reboot** — no physical button needed for flashing

## Wiring (RP2040-zero)

| Strip pin | RP2040-zero GPIO | PWM slice |
|-----------|-----------------|-----------|
| Red       | GPIO 10         | PWM5A     |
| Green     | GPIO 11         | PWM5B     |
| Blue      | GPIO 9          | PWM4B     |
| GND / VCC | GND / VSYS     | —         |

Default firmware assumes **common anode** (`INVERT_LOGIC=1`). Toggle at runtime with `INVERT 0`.

## Build

```bash
cd /home/sh/pico
cmake -B build
cmake --build build -j$(nproc)
```

Output: `build/rp2040_rgb_controller.uf2`

## Flash

1. Hold **BOOT** on the RP2040-zero, plug USB in, release.
2. A `RPI-RP2` drive appears.
3. Copy `build/rp2040_rgb_controller.uf2` to the drive.
4. The board resets and appears as `/dev/ttyACM0`.

## Linux setup

```bash
# Install udev rule (run once, as root)
sudo cp udev/99-rp2040-rgb.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

After this, the device symlinks to `/dev/rp2040-rgb`.

## Temperature integration

The firmware accepts a Celsius reading via `TEMP <c>` and maps it to a color:
- 30 °C → blue (cool)
- 50 °C → green (normal)
- 70 °C → yellow (warm)
- 90 °C → red (hot)

### Auto-temp script (Linux)

```bash
# One-liner: send CPU temp every 2 s
watch -n 2 "echo TEMP \$(($(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo 0)/1000)) > /dev/ttyACM0"
```

Or use the included daemon:
```bash
tools/rgbctl-temp -i 2
```

### Custom thermal zone

```bash
tools/rgbctl-temp -z /sys/class/thermal/thermal_zone1/temp -i 5
```

## CLI

```bash
chmod +x tools/rgbctl
./tools/rgbctl PING
./tools/rgbctl RGB 255 0 0
./tools/rgbctl "#00FF00"
./tools/rgbctl HSV 120 255 255
./tools/rgbctl ANIM rainbow
./tools/rgbctl SPEED 10
./tools/rgbctl STATE
./tools/rgbctl BOOT
```

## Serial protocol

| Command | Example | Description |
|---------|---------|-------------|
| `RGB <r> <g> <b>` | `RGB 255 0 0` | Set color 0-255 each |
| `#RRGGBB` | `#00FF00` | Hex color |
| `HSV <h> <s> <v>` | `HSV 120 255 255` | HSV (h 0-360, s/v 0-255) |
| `ANIM static\|breath\|rainbow\|strobe\|candle\|wave\|police\|random\|storm\|temp` | `ANIM breath` | Animation mode |
| `SPEED <1-255>` | `SPEED 10` | Speed; 1=~400 ms/tick (slow), 255=~1.6 ms/tick (fast) |
| `PWM <hz>` | `PWM 4000` | PWM frequency 100-50000 Hz |
| `INVERT <0\|1>` | `INVERT 0` | 0=cathode, 1=anode |
| `TEMP <celsius>` | `TEMP 55` | Set temperature; auto-switches to temp mode |
| `RANDOM` | — | Generate random RGB color |
| `STATE` | — | Print current values |
| `OFF` | — | Turn off |
| `PING` | — | Heartbeat |
| `BOOT` | — | Reboot to BOOTSEL mode |
| `HELP` | — | List commands |

## Animation descriptions

| Mode | Description |
|------|-------------|
| `static` | Hold the last set color |
| `breath` | Smooth fade in/out of current color |
| `rainbow` | Continuous hue cycle through full spectrum |
| `strobe` | Rapid flash of current color |
| `candle` | Warm-white base with pseudo-random flicker |
| `wave` | Three overlapping integer-sine waves on R/G/B |
| `police` | Alternating red/blue flashes |
| `random` | Hardware-PRNG random colors |
| `storm` | Mostly dark with occasional lightning flashes |
| `temp` | Color mapped from last `TEMP` reading (blue=cold → red=hot) |

## Hardware notes

- Strip VCC should come from a supply able to deliver the full strip current (e.g., 5 V / 10 A for 5 m at 60 LED/m).
- Do **not** power long strips from the RP2040-zero’s USB 5 V pin.
- Add a level shifter or MOSFET gate driver if your strip is 12 V.

## License

0BSD — do whatever you want.
