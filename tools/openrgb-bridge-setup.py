#!/usr/bin/env python3
"""Configure OpenRGB to drive the RP2040 WS2811 bridge as a Serial LED Strip.

Usage:
    python3 openrgb-bridge-setup.py --leds 60 [--port /dev/rp2040-rgb] [--baud 115200]
"""
import argparse
import glob
import json
import os
import subprocess
import sys

CONFIG = os.path.expanduser("~/.config/OpenRGB/OpenRGB.json")


def find_port() -> str | None:
    if os.path.exists("/dev/rp2040-rgb"):
        return "/dev/rp2040-rgb"
    by_id = sorted(glob.glob("/dev/serial/by-id/*Pico*") +
                   glob.glob("/dev/serial/by-id/*RP2040*") +
                   glob.glob("/dev/serial/by-id/*2e8a*"))
    if by_id:
        return by_id[0]
    devs = sorted(glob.glob("/dev/ttyACM*"))
    return devs[0] if devs else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--leds", type=int, required=True, help="Number of WS2811 segments")
    ap.add_argument("--port", help="Serial port (auto-detected if omitted)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--name", default="RP2040 WS2811 Bridge")
    args = ap.parse_args()

    port = args.port or find_port()
    if not port:
        print("ERR: no RP2040 serial port found. Plug the board in or pass --port.",
              file=sys.stderr)
        return 1

    if not os.path.exists(CONFIG):
        print(f"ERR: {CONFIG} not found. Run OpenRGB once first.", file=sys.stderr)
        return 1

    with open(CONFIG) as f:
        cfg = json.load(f)

    cfg.setdefault("LEDStripDevices", {}).setdefault("devices", [])
    devices = cfg["LEDStripDevices"]["devices"]

    # Replace any existing entry pointing at the same port or with the same name.
    devices = [d for d in devices
               if d.get("port") != port and d.get("name") != args.name]
    devices.append({
        "name": args.name,
        "port": port,
        "baud": args.baud,
        "num_leds": args.leds,
        "protocol": "adalight",
    })
    cfg["LEDStripDevices"]["devices"] = devices

    with open(CONFIG, "w") as f:
        json.dump(cfg, f, indent=4)
    print(f"Configured OpenRGB Serial LED Strip: {port} ({args.leds} LEDs, adalight)")
    print("Restart OpenRGB (or run with --server) to detect the device.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
