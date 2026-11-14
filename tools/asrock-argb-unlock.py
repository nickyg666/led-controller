#!/usr/bin/env python3
"""Directly program the ASRock Polychrome V1 controller's 5V ARGB header.

Unlocks addressable effects on the motherboard port by setting the LED count
and color order on the controller itself (bypassing OpenRGB's single-LED model).

Usage:
    python3 asrock-argb-unlock.py --leds 60 --order RGB [--effect rainbow]
"""
import argparse
import smbus
import time

BUS = 2
DEV = 0x6A

REG_MODE = 0x30
REG_ZONE_SELECT = 0x31
REG_SET_ALL = 0x32
REG_ZONE_SIZE = 0x33
REG_ARGB_GRB = 0x35

ZONE_ADDR = 0x05  # Addressable Header

EFFECTS = {
    "off": 0x10,
    "static": 0x11,
    "breathing": 0x12,
    "strobe": 0x13,
    "spectrum": 0x14,
    "random": 0x15,
    "music": 0x17,
    "wave": 0x18,
    "spring": 0x19,
    "meteor": 0x1A,
    "stack": 0x1B,
    "cram": 0x1C,
    "scan": 0x1D,
    "neon": 0x1E,
    "water": 0x1F,
    "rainbow": 0x20,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--leds", type=int, required=True, help="Number of WS2811 LEDs")
    ap.add_argument("--order", choices=["RGB", "GRB"], default="RGB",
                    help="Color order: RGB for WS2811, GRB for WS2812B")
    ap.add_argument("--effect", choices=list(EFFECTS), default="rainbow",
                    help="Built-in addressable effect to run")
    ap.add_argument("--bus", type=int, default=BUS)
    ap.add_argument("--size-only", action="store_true",
                    help="Only set size/color order, do not change effect")
    args = ap.parse_args()

    if args.leds < 1 or args.leds > 100:
        print("ERR: leds must be 1-100")
        return 1

    bus = smbus.SMBus(args.bus)

    # Read current zone sizes to preserve other zones.
    sizes = list(bus.read_block_data(DEV, REG_ZONE_SIZE))
    if len(sizes) != 6:
        sizes = [0] * 6
    sizes[ZONE_ADDR] = args.leds

    # Write size config.
    bus.write_block_data(DEV, REG_ZONE_SIZE, sizes)
    time.sleep(0.01)
    verify = list(bus.read_block_data(DEV, REG_ZONE_SIZE))
    if verify[ZONE_ADDR] != args.leds:
        print(f"WARN: size verify mismatch: {verify[ZONE_ADDR]} != {args.leds}")

    # Set color order: 0=RGB (WS2811), 1=GRB (WS2812B).
    grb = 1 if args.order == "GRB" else 0
    bus.write_block_data(DEV, REG_ARGB_GRB, [grb])
    time.sleep(0.01)
    co = bus.read_block_data(DEV, REG_ARGB_GRB)[0]
    print(f"Color order set: {'GRB' if co else 'RGB'} (readback {co})")

    if not args.size_only:
        # Select addressable zone.
        bus.write_block_data(DEV, REG_ZONE_SELECT, [ZONE_ADDR])
        time.sleep(0.01)
        # Set all register 0.
        bus.write_block_data(DEV, REG_SET_ALL, [0x00])
        time.sleep(0.01)
        # Write mode.
        mode = EFFECTS[args.effect]
        bus.write_block_data(DEV, REG_MODE, [mode])
        time.sleep(0.001)
        print(f"Effect '{args.effect}' (0x{mode:02X}) applied to Addressable Header.")

    print(f"ARGB header configured: {args.leds} LEDs, {args.order} order.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
