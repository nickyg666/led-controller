#!/usr/bin/env python3
"""Bridge RP2040 WS2811 controller <-> MQTT for Home Assistant discovery."""
import json
import os
import select
import sys
import time
import glob
import termios
import traceback

import paho.mqtt.client as mqtt

BROKER = "127.0.0.1"
PORT = 1883
TOPIC = "rp2040_led"
PREFIX = "homeassistant/light/" + TOPIC

EFFECTS = ["static","breath","rainbow","strobe","candle","wave","police","random",
           "storm","temp","chase","fire","sparkle","comet","theater","running",
           "meteor","bounce","confetti","sinelon","juggle","plasma","ripple",
           "wipe","fade","fireworks","snake","pulse","glitter","pride","ocean",
           "aurora","lava","matrix","k2000","heartbeat","colorcycle","twinkle",
           "sparklewave","stroberainbow","gradient","demo"]

ser_fd = None


def find_device():
    if os.path.exists("/dev/rp2040-rgb"):
        return "/dev/rp2040-rgb"
    ds = sorted(glob.glob("/dev/ttyACM*"))
    return ds[0] if ds else None


SERIAL_DEV = None


def open_serial(dev):
    global SERIAL_DEV
    SERIAL_DEV = dev


def send_serial(cmd):
    global SERIAL_DEV
    if SERIAL_DEV is None:
        SERIAL_DEV = find_device() if 'find_device' in globals() else None
    if not SERIAL_DEV:
        # try to find
        import glob, os as _os
        if _os.path.exists("/dev/rp2040-rgb"):
            SERIAL_DEV = "/dev/rp2040-rgb"
        else:
            ds = sorted(glob.glob("/dev/ttyACM*"))
            SERIAL_DEV = ds[0] if ds else None
    if not SERIAL_DEV:
        print("no serial device", flush=True)
        return
    try:
        fd = os.open(SERIAL_DEV, os.O_RDWR | os.O_NOCTTY)
    except OSError as e:
        print(f"open err: {e}", flush=True)
        return
    try:
        attrs = termios.tcgetattr(fd)
        attrs[1] = termios.OPOST | termios.ONLCR
        attrs[3] = termios.CREAD | termios.CLOCAL
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 1
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        # flush
        while True:
            r, _, _ = select.select([fd], [], [], 0.05)
            if not r:
                break
            os.read(fd, 4096)
        os.write(fd, (cmd + "\r\n").encode())
        time.sleep(0.1)
    except OSError as e:
        print(f"serial err: {e}", flush=True)
    finally:
        try:
            os.close(fd)
        except Exception:
            pass

state = {"state": "OFF", "brightness": 255, "color": {"r": 255, "g": 0, "b": 0}, "base_color": {"r": 255, "g": 0, "b": 0}, "effect": "static"}


def publish_state(client):
    payload = {
        "state": state["state"],
        "brightness": state["brightness"],
        "color_mode": "rgb",
        "color": state["base_color"],
        "effect": state["effect"],
    }
    client.publish(f"{TOPIC}/state", json.dumps(payload), retain=True)


def on_message(client, userdata, msg):
    print(f"RECV {msg.topic}: {msg.payload.decode()}", flush=True)
    try:
        data = json.loads(msg.payload.decode())
    except Exception:
        data = {}
    global state
    try:
        if msg.topic == f"{TOPIC}/set":
            if isinstance(data, str):
                if data == "ON":
                    state["state"] = "ON"
                    send_serial(f"BRIGHTNESS {state['brightness']}")
                    sc = state["base_color"]
                    send_serial(f"RGB {sc['r']} {sc['g']} {sc['b']}")
                elif data == "OFF":
                    state["state"] = "OFF"
                    send_serial("OFF")
                    send_serial("PWMRGB 0 0 0")
            elif isinstance(data, dict):
                if "state" in data:
                    state["state"] = data["state"]
                    if data["state"] == "OFF":
                        send_serial("OFF")
                        send_serial("PWMRGB 0 0 0")
                if "color" in data:
                    c = data["color"]
                    r = c.get("r", 0)
                    g = c.get("g", 0)
                    b = c.get("b", 0)
                    state["base_color"] = {"r": r, "g": g, "b": b}
                    state["color"] = {"r": r, "g": g, "b": b}
                    send_serial(f"RGB {r} {g} {b}")
                if "brightness" in data:
                    state["brightness"] = data["brightness"]
                    send_serial(f"BRIGHTNESS {state['brightness']}")
                if "effect" in data:
                    eff = data["effect"]
                    if eff in EFFECTS:
                        state["effect"] = eff
                        send_serial(f"ANIM {eff}")
                if data.get("state") == "ON" and "color" not in data and "effect" not in data and "brightness" not in data:
                    send_serial(f"BRIGHTNESS {state['brightness']}")
                    sc = state["base_color"]
                    send_serial(f"RGB {sc['r']} {sc['g']} {sc['b']}")
        publish_state(client)
    except Exception as e:
        print(f"ERR in handler: {e}", flush=True)
        traceback.print_exc()


def on_connect(client, userdata, flags, rc, props=None):
    disc = {
        "name": "PC lights",
        "unique_id": "pc_lights_v2",
        "command_topic": f"{TOPIC}/set",
        "state_topic": f"{TOPIC}/state",
        "brightness": True,
        "brightness_scale": 255,
        "color_mode": "rgb",
        "supported_color_modes": ["rgb"],
        "effect": True,
        "effect_list": EFFECTS,
        "schema": "json",
    }
    client.publish(f"{PREFIX}/config", json.dumps(disc), retain=True)
    client.subscribe(f"{TOPIC}/set")
    publish_state(client)


def find_device():
    if os.path.exists("/dev/rp2040-rgb"):
        return "/dev/rp2040-rgb"
    ds = sorted(glob.glob("/dev/ttyACM*"))
    return ds[0] if ds else None


def main():
    dev = find_device()
    if not dev:
        print("No device found", file=sys.stderr)
        sys.exit(1)
    open_serial(dev)
    print(f"Serial: {dev}", flush=True)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(BROKER, PORT, 60)
    print(f"MQTT: {BROKER}:{PORT}", flush=True)
    try:
        client.loop_forever()
    except Exception as e:
        print(f"loop err: {e}", flush=True)
        import traceback; traceback.print_exc()


if __name__ == "__main__":
    main()
