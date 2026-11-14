#!/usr/bin/env bash
# ASRock Polychrome V1 ARGB headers CANNOT be driven per-LED from the host
# (OpenRGB docs: "Per ARGB LED support is not possible with these devices").
# The 'ARGB Header Config' mode below only sets LED count + color order for
# the controller's built-in effects (Spring/Stack/Cram/Scan/Neon/Water/Rainbow).
#
# For TRUE per-LED addressability, move the WS2811 strip to the RP2040 bridge:
#   1. Flash build/rp2040_rgb_controller.uf2 to the Pico (data -> GPIO10)
#   2. Power the strip from an external 5V/12V supply (not the Pico USB)
#   3. Run: tools/openrgb-bridge-setup.py --leds <N>
#
# This script only configures the motherboard header's built-in effects:
#   Usage: ./unlock-addressability.sh [LED_COUNT] [RGB|GRB]
set -euo pipefail
N="${1:-60}"
ORDER="${2:-RGB}"
echo "Polychrome V1 ARGB header is single-color + built-in effects only."
echo "Configuring ARGB Header Config: ${N} LEDs, ${ORDER} order (set via GUI direction)."
echo "Use OpenRGB GUI -> mode 'ARGB Header Config' -> speed=${N}, direction=${ORDER}."
echo "For per-LED control, use the RP2040 bridge (see above)."
