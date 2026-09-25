#!/usr/bin/env python3
"""Mum's TV: remote control + "Call Mum" video calls with live subtitles.

Stdlib only, plus two optional extras:
  - vosk     (live subtitles; model folder in ./model)
  - gpiozero (red "on a call" light on GPIO17)

Pages:
  /       remote + Call Mum (open over https via `tailscale serve`)
  /mum    the TV screen, opened by Chromium in kiosk mode on the Pi
"""
import json
import os
import re
import subprocess
import textwrap
import threading
import time
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---- settings -------------------------------------------------------------
# Defaults. Put your own values in config.json next to this file (see
# config.example.json); that file is not tracked, so your network stays private.
TV = "http://192.168.1.50:8060"   # the Roku TV's address, ECP port 8060
PORT = 8080
PI_INPUT = "tvinput.hdmi1"   # TV input the Pi is plugged into (hdmi1/hdmi2/hdmi3)
LED_PIN = 17                 # GPIO for the red "on a call" light
RING_TIMEOUT = 30            # seconds before an unanswered call is dropped
CAMERA_DEV = "/dev/video0"   # webcam, for zoom / pan / tilt during calls (UVC controls)
CAM_ZOOM_MAX = 9             # zoom_absolute range is 0..CAM_ZOOM_MAX
CAM_PT_MAX = 36000           # pan_absolute / tilt_absolute range is -MAX..MAX
CAM_PT_STEP = 7200           # how far one press of an arrow moves the view
CAPTION_LINES = 2            # subtitles never cover more than this many lines of the TV
CAPTION_CHARS = 32           # characters per subtitle line at the TV's font size
CAPTION_KEEP = 6             # seconds a finished sentence stays up
CALLER_TIMEOUT = 15          # seconds without hearing from the caller's page
VOL_PRESETS = {"normal": 18, "loud": 45, "veryloud": 75}   # TV volume steps (0-100), set by ear
CALL_VOLUME = 45             # TV volume during calls; put back afterwards
VOL_MAX = 100                # Roku TV volume range, one step per key press
VOL_KEY_GAP = 0.08           # seconds between key presses on the way down to 0
VOL_UP_GAP = 0.1             # slower on the way up: every press must count
HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(HERE, "model")
STATIC = os.path.join(HERE, "static")
VOL_FILE = os.path.join(HERE, "volume.json")   # remembers the estimate across restarts

KEYS = {
    "PowerOn", "PowerOff", "VolumeUp", "VolumeDown", "VolumeMute",
    "ChannelUp", "ChannelDown", "Home", "Back", "Select",
    "Up", "Down", "Left", "Right", "Play", "Info",
}
APPS = {
    "tvinput.dtv": "Live TV", "11703": "BBC iPlayer", "42329": "ITVX",
    "34785": "Channel 4", "27424": "5", "27181": "Sky News", "837": "YouTube",
    "12": "Netflix", "13": "Prime Video", "22297": "Spotify",
}
CHANNEL_RE = re.compile(r"^\d{1,4}(\.\d{1,3})?$")

CONFIGURABLE = {"TV", "PORT", "PI_INPUT", "LED_PIN", "RING_TIMEOUT", "CALLER_TIMEOUT",
                "VOL_PRESETS", "CALL_VOLUME", "VOL_MAX", "VOL_KEY_GAP", "VOL_UP_GAP",
                "CAPTION_LINES", "CAPTION_CHARS", "CAPTION_KEEP", "APPS",
                "CAMERA_DEV", "CAM_ZOOM_MAX", "CAM_PT_MAX", "CAM_PT_STEP"}
try:
    with open(os.path.join(HERE, "config.json")) as f:
        for _k, _v in json.load(f).items():
            if _k in CONFIGURABLE:
                globals()[_k] = _v
            else:
                print(f"config.json: unknown setting {_k!r} ignored", flush=True)
except FileNotFoundError:
    pass

# ---- optional extras ------------------------------------------------------
try:
    from vosk import KaldiRecognizer, Model, SetLogLevel
    SetLogLevel(-1)
    MODEL = Model(MODEL_DIR) if os.path.isdir(MODEL_DIR) else None
except Exception:
    MODEL = None

try:
    from gpiozero import LED
    LIGHT = LED(LED_PIN)
except Exception:
    LIGHT = None


def light(on):
    if LIGHT:
        try:
            LIGHT.on() if on else LIGHT.off()
        except Exception:
            pass


# ---- TV -------------------------------------------------------------------
def tv(path, post=False, timeout=4):
    req = urllib.request.Request(
        TV + path, data=b"" if post else None, method="POST" if post else "GET"
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def tv_power():
    return ET.fromstring(tv("/query/device-info")).findtext("power-mode")


def tv_app():
    app = ET.fromstring(tv("/query/active-app")).find("app")
    return (app.get("id") if app is not None else None), (
        (app.text or "").strip() if app is not None else None)


def status():
    s = {"reachable": False}
    try:
        s["power"] = tv_power()
        s["reachable"] = True
        s["app_id"], s["app"] = tv_app()
        # Live TV shows up as its own app id with ui-location="tvinput.dtv"
        app = ET.fromstring(tv("/query/active-app")).find("app")
        if app is not None and "tvinput.dtv" in (app.get("id"), app.get("ui-location")):
            try:
                ch = ET.fromstring(tv("/query/tv-active-channel")).find("channel")
                if ch is not None:
                    s["channel"] = f'{ch.findtext("number") or ""} {ch.findtext("name") or ""}'.strip()
                    s["program"] = (ch.findtext("program-title") or "").strip()
            except Exception:
                pass
    except Exception as e:
        s["error"] = str(e)
    s["vol"] = dict(vol)
    return s


# ---- volume estimate --------------------------------------------------------
# The Roku can't report its volume. A preset drives it to 0 and counts back up, so
# we know where it is; after that we count our own +/- presses. Mum's own remote
# can change it behind our back, so this is only ever "about N".
vol_lock = threading.Lock()
vol = {"est": None, "busy": False}
pending = {"restore": None}   # volume to go back to after a call; saved so a crash can't leave the TV loud
boot_restore = None
try:
    with open(VOL_FILE) as f:
        _saved = json.load(f)
    vol["est"] = _saved.get("est")
    boot_restore = _saved.get("restore")
except (OSError, ValueError):
    pass


def vol_save():
    try:
        with open(VOL_FILE, "w") as f:
            json.dump({"est": vol["est"], "restore": pending["restore"]}, f)
    except OSError:
        pass


def vol_claim():
    with vol_lock:
        if vol["busy"]:
            return False
        vol["busy"] = True
        return True


def vol_nudge(key, n):
    if vol["est"] is not None and not vol["busy"]:
        step = n if key == "VolumeUp" else -n
        vol["est"] = max(0, min(VOL_MAX, vol["est"] + step))
        vol_save()


def vol_preset(target):
    try:
        for _ in range(VOL_MAX):
            tv("/keypress/VolumeDown", post=True)
            time.sleep(VOL_KEY_GAP)
        vol["est"] = 0
        time.sleep(1.5)       # let the TV finish the queue of downs, or it drops an up
        for i in range(target):
            tv("/keypress/VolumeUp", post=True)
            vol["est"] = i + 1
            time.sleep(VOL_UP_GAP)
    except Exception as e:
        vol["est"] = None
        print(f"volume preset failed: {e}", flush=True)
    finally:
        vol["busy"] = False
        vol_save()


def call_volume_up(c):
    """Call started: remember the volume, then reset to a known CALL_VOLUME."""
    global boot_restore
    if call is not c or not vol_claim():
        return
    before = boot_restore if boot_restore is not None else vol["est"]
    boot_restore = None
    pending["restore"] = c["prev_vol"] = before if before is not None else VOL_PRESETS["normal"]
    vol_save()
    vol_preset(CALL_VOLUME)


def call_volume_back(c):
    """Call ended: step back to the volume from before the call."""
    if c.get("prev_vol") is None:
        return
    for _ in range(90):                 # a preset may still be running
        if vol_claim():
            break
        time.sleep(1)
    else:
        return
    try:
        if vol["est"] is None:
            vol["busy"] = False
            if vol_claim():
                vol_preset(c["prev_vol"])
        else:
            while vol["est"] != c["prev_vol"]:
                up = vol["est"] < c["prev_vol"]
                tv("/keypress/VolumeUp" if up else "/keypress/VolumeDown", post=True)
                vol["est"] += 1 if up else -1
                time.sleep(VOL_UP_GAP)
        pending["restore"] = None
    except Exception as e:
        print(f"volume restore failed: {e}", flush=True)
    finally:
        vol["busy"] = False
        vol_save()


# ---- camera view ------------------------------------------------------------
# The caller can zoom and move the (digital) view during a call. Every call starts
# and ends on the wide view, so nobody is left zoomed in on part of the room.
cam_lock = threading.Lock()
cam = {"zoom": 0, "pan": 0, "tilt": 0}
CAM_ACTIONS = {"zoomin": ("zoom", 1), "zoomout": ("zoom", -1), "right": ("pan", 1),
               "left": ("pan", -1), "down": ("tilt", 1), "up": ("tilt", -1), "reset": None}


def cam_move(action):
    with cam_lock:
        if action == "reset":
            cam.update(zoom=0, pan=0, tilt=0)
        else:
            axis, sign = CAM_ACTIONS[action]
            if axis == "zoom":
                cam["zoom"] = max(0, min(CAM_ZOOM_MAX, cam["zoom"] + sign))
                if cam["zoom"] == 0:
                    cam.update(pan=0, tilt=0)     # the wide view cannot be moved
            else:
                cam[axis] = max(-CAM_PT_MAX, min(CAM_PT_MAX, cam[axis] + sign * CAM_PT_STEP))
        try:
            subprocess.run(
                ["v4l2-ctl", "-d", CAMERA_DEV, "-c",
                 f"zoom_absolute={cam['zoom']},pan_absolute={cam['pan']},tilt_absolute={cam['tilt']}"],
                capture_output=True, timeout=3)
        except Exception as e:
            print(f"camera control failed: {e}", flush=True)
        return dict(cam)


# ---- peek at the Pi's screen ------------------------------------------------
# A small live picture of what the Pi is showing on the TV, for the family remote.
# Held in memory for a couple of seconds only; never written to disk.
shot_lock = threading.Lock()
shot = {"at": 0.0, "png": b""}


def screenshot():
    with shot_lock:
        if time.time() - shot["at"] > 2:
            env = dict(os.environ, XDG_RUNTIME_DIR=f"/run/user/{os.getuid()}",
                       WAYLAND_DISPLAY="wayland-0")
            r = subprocess.run(["grim", "-s", "0.4", "-"], env=env,
                               capture_output=True, timeout=5)
            shot["png"] = r.stdout if r.returncode == 0 else b""
            shot["at"] = time.time()
        return shot["png"]


# ---- calls ----------------------------------------------------------------
lock = threading.Lock()
stt_lock = threading.Lock()
call = {"state": "idle"}
last_end = {}
mum_seen = time.time()   # last time the TV screen page checked in (kiosk.sh watches this)
# The page also sends a frame counter. Chromium can keep polling with a hung renderer
# (white screen, never answers a call); the counter stops, and kiosk.sh restarts it.
mum_frames = {"n": -1, "changed": time.time()}
page_stuck = {"at": 0.0}


def page_ver():
    """Changes when mum.html is redeployed, so the TV screen reloads itself."""
    try:
        return int(os.path.getmtime(os.path.join(STATIC, "mum.html")))
    except OSError:
        return 0


def tv_to_call(c):
    """Wake the TV and show the Pi's screen, remembering what was on."""
    try:
        if tv_power() != "PowerOn":
            c["was_off"] = True
            tv("/keypress/PowerOn", post=True)
            time.sleep(5)
        else:
            c["prev_app"], _ = tv_app()
        tv(f"/launch/{PI_INPUT}", post=True)
        call_volume_up(c)
    except Exception as e:
        print(f"TV switch failed: {e}", flush=True)


def tv_restore(c):
    """Put the TV back how it was, unless someone changed it during the call."""
    call_volume_back(c)
    try:
        now_app, _ = tv_app()
        if now_app != PI_INPUT:
            return
        if c.get("was_off"):
            tv("/keypress/PowerOff", post=True)
        elif c.get("prev_app"):
            tv(f"/launch/{c['prev_app']}", post=True)
        else:
            tv("/keypress/Home", post=True)
    except Exception as e:
        print(f"TV restore failed: {e}", flush=True)


def end_call(reason, cid=None):
    global call, last_end
    with lock:
        if call["state"] == "idle" or (cid and call.get("id") != cid):
            return
        old, call = call, {"state": "idle"}
        last_end = {"id": old["id"], "reason": reason}
    light(False)
    threading.Thread(target=cam_move, args=("reset",), daemon=True).start()
    mins = (time.time() - old["started"]) / 60
    print(f"call from {old['caller']} ended after {mins:.1f} min: {reason}", flush=True)
    threading.Thread(target=tv_restore, args=(old,), daemon=True).start()


def watchdog():
    global boot_restore
    while True:
        time.sleep(3)
        c = call
        # a call was cut short by a restart: put the volume back once the TV is on
        if boot_restore is not None and c["state"] == "idle":
            try:
                if tv_power() == "PowerOn" and vol_claim():
                    target, boot_restore = boot_restore, None
                    print(f"restoring volume {target} after interrupted call", flush=True)
                    vol_preset(target)
            except Exception:
                pass
        if c["state"] == "ringing" and time.time() - c["started"] > RING_TIMEOUT:
            if time.time() - mum_seen < 5:
                page_stuck["at"] = time.time()
                print("TV page is polling but did not answer: asking kiosk to restart it", flush=True)
            end_call("no answer", c["id"])
        elif c["state"] == "active" and time.time() - c["seen"] > CALLER_TIMEOUT:
            end_call("caller gone", c["id"])


def caption(c):
    # Roll-up captions, like live TV subtitles: each sentence is wrapped into short
    # lines from its start, so lines stay put while the last one grows, and only the
    # newest CAPTION_LINES are shown however long the caller talks without a pause.
    now = time.time()
    texts = [t for ts, t in c.get("finals", []) if now - ts < CAPTION_KEEP]
    if c.get("partial"):
        texts.append(c["partial"])
    lines = [ln for t in texts for ln in textwrap.wrap(t, CAPTION_CHARS)]
    return "\n".join(lines[-CAPTION_LINES:])


def call_view(role, cid, frames=None):
    global mum_seen
    c = call
    v = {"state": c["state"], "stt": MODEL is not None}
    if role == "mum":
        mum_seen = time.time()
        v["ver"] = page_ver()
        if frames is not None and frames != mum_frames["n"]:
            mum_frames.update(n=frames, changed=time.time())
    if role == "caller" and cid and last_end.get("id") == cid:
        v["ended"] = last_end["reason"]
    if c["state"] == "idle":
        return v
    v.update(id=c["id"], caller=c["caller"], caption=caption(c))
    if role == "caller":
        v["vol"] = dict(vol)
        v["cam"] = dict(cam)
        if time.time() - c.get("level_at", 0) < 3:
            v["level"] = c["level"]
    if role == "mum" and c["state"] == "ringing":
        v["offer"] = c["offer"]
    if role == "caller" and cid == c["id"]:
        c["seen"] = time.time()
        if c["answer"]:
            v["answer"] = c["answer"]
    return v


# ---- web ------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass   # the browser went away mid-answer; nothing to do

    def _json(self, code, obj):
        self._send(code, json.dumps(obj))

    def _body(self, limit=1_000_000):
        n = min(int(self.headers.get("Content-Length") or 0), limit)
        return self.rfile.read(n) if n else b""

    def _who(self):
        return self.headers.get("Tailscale-User-Login") or self.client_address[0]

    def _on_pi(self):
        """True only for the kiosk browser on the Pi itself. Requests that came in
        through `tailscale serve` also arrive from 127.0.0.1, but carry proxy headers."""
        return (self.client_address[0] in ("127.0.0.1", "::1")
                and not self.headers.get("X-Forwarded-For")
                and not self.headers.get("Tailscale-User-Login"))

    def _tv_only(self):
        self._json(403, {"error": "this only works on the TV itself"})

    def _file(self, name):
        with open(os.path.join(STATIC, name), "rb") as f:
            self._send(200, f.read(), "text/html; charset=utf-8")

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/":
            self._file("remote.html")
        elif u.path == "/mum":
            # the TV page auto-answers calls, so nobody else may open it
            if not self._on_pi():
                return self._tv_only()
            self._file("mum.html")
        elif u.path == "/api/status":
            self._json(200, status())
        elif u.path == "/api/screen":
            try:
                png = screenshot()
            except Exception:
                png = b""
            if png:
                self._send(200, png, "image/png")
            else:
                self._json(503, {"error": "no screenshot"})
        elif u.path == "/api/health":
            now = time.time()
            self._json(200, {
                "ok": True, "mum_age": int(now - mum_seen),
                "frozen": int(now - mum_frames["changed"]),   # seconds since the page last drew a frame
                "page_stuck": now - page_stuck["at"] < 120,    # a call went unanswered while the page was polling
            })
        elif u.path == "/api/call":
            role = q.get("role", [""])[0]
            if role == "mum" and not self._on_pi():
                return self._tv_only()
            try:
                frames = int(q["frames"][0]) if "frames" in q else None
            except ValueError:
                frames = None
            self._json(200, call_view(role, q.get("id", [""])[0], frames))
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        global call
        u = urllib.parse.urlparse(self.path)
        parts = u.path.strip("/").split("/")
        q = urllib.parse.parse_qs(u.query)

        # --- live subtitles: raw 16 kHz mono PCM from the TV screen page
        if u.path == "/api/stt":
            if not self._on_pi():
                return self._tv_only()
            data, c = self._body(), call
            if c["state"] == "idle" or c.get("id") != q.get("id", [""])[0] or not c.get("rec"):
                return self._json(200, {"caption": ""})
            with stt_lock:
                if c["rec"].AcceptWaveform(data):
                    text = json.loads(c["rec"].Result()).get("text", "")
                    if text:
                        c["finals"] = (c["finals"] + [(time.time(), text)])[-5:]
                    c["partial"] = ""
                else:
                    c["partial"] = json.loads(c["rec"].PartialResult()).get("partial", "")
            return self._json(200, {"caption": caption(c)})

        # --- camera view, only for the caller of the call in progress
        if parts[:2] == ["api", "camera"] and len(parts) == 3:
            c = call
            if c["state"] != "active" or c["id"] != q.get("id", [""])[0]:
                return self._json(409, {"error": "no call"})
            if parts[2] not in CAM_ACTIONS:
                return self._json(400, {"error": "not allowed"})
            return self._json(200, cam_move(parts[2]))

        # --- call control
        if parts[:2] == ["api", "call"] and len(parts) == 3:
            try:
                body = json.loads(self._body() or b"{}")
            except ValueError:
                return self._json(400, {"error": "bad request"})
            if parts[2] in ("answer", "level") and not self._on_pi():
                return self._tv_only()
            if parts[2] == "start":
                name = re.sub(r"[^\w .'-]", "", str(body.get("name", "")))[:30].strip() or "Family"
                offer = str(body.get("offer", ""))
                if not offer:
                    return self._json(400, {"error": "no offer"})
                with lock:
                    if call["state"] != "idle":
                        return self._json(409, {"error": "busy"})
                    call = {
                        "state": "ringing", "id": uuid.uuid4().hex[:12], "caller": name,
                        "offer": offer, "answer": None, "started": time.time(),
                        "seen": time.time(), "prev_app": None, "was_off": False,
                        "rec": KaldiRecognizer(MODEL, 16000) if MODEL else None,
                        "finals": [], "partial": "",
                    }
                    c = call
                light(True)
                cam_move("reset")
                print(f"call from {name} ({self._who()}) started", flush=True)
                threading.Thread(target=tv_to_call, args=(c,), daemon=True).start()
                return self._json(200, {"id": c["id"]})
            if parts[2] == "answer":
                with lock:
                    if call["state"] == "ringing" and call["id"] == body.get("id"):
                        call["answer"] = str(body.get("answer", ""))
                        call["state"] = "active"
                        call["seen"] = time.time()
                        return self._json(200, {"ok": True})
                return self._json(409, {"error": "no such call"})
            if parts[2] == "level":
                # room loudness from the TV screen page: a number only, no audio
                c = call
                if c["state"] == "active" and c["id"] == body.get("id"):
                    try:
                        c["level"] = max(0, min(100, int(body.get("level", 0))))
                        c["level_at"] = time.time()
                    except (TypeError, ValueError):
                        pass
                return self._json(200, {"ok": True})
            if parts[2] == "end":
                end_call(str(body.get("reason", "hung up"))[:60], body.get("id"))
                return self._json(200, {"ok": True})

        # --- remote control
        try:
            if len(parts) == 3 and parts[:2] == ["api", "key"] and parts[2] in KEYS:
                n = max(1, min(5, int(q.get("n", ["1"])[0])))
                if vol["busy"] and parts[2].startswith("Volume"):
                    return self._json(409, {"error": "volume preset running"})
                for _ in range(n):
                    tv(f"/keypress/{parts[2]}", post=True)
                    time.sleep(0.15)
                if parts[2] in ("VolumeUp", "VolumeDown"):
                    vol_nudge(parts[2], n)
                action = f"key {parts[2]} x{n}"
            elif len(parts) == 3 and parts[:2] == ["api", "volume"] and parts[2] in VOL_PRESETS:
                with vol_lock:
                    if vol["busy"]:
                        return self._json(409, {"error": "volume preset running"})
                    vol["busy"] = True
                threading.Thread(target=vol_preset, args=(VOL_PRESETS[parts[2]],), daemon=True).start()
                action = f"volume preset {parts[2]} ({VOL_PRESETS[parts[2]]})"
            elif parts == ["api", "launch", "clock"]:
                # show the Pi's screen (day / time / date), waking the TV if needed
                if tv_power() != "PowerOn":
                    tv("/keypress/PowerOn", post=True)
                    time.sleep(5)
                tv(f"/launch/{PI_INPUT}", post=True)
                action = "launch clock"
            elif len(parts) == 3 and parts[:2] == ["api", "launch"] and parts[2] in APPS:
                tv(f"/launch/{parts[2]}", post=True)
                action = f"launch {APPS[parts[2]]}"
            elif len(parts) == 3 and parts[:2] == ["api", "channel"] and CHANNEL_RE.match(parts[2]):
                tv(f"/launch/tvinput.dtv?ch={parts[2]}", post=True)
                action = f"channel {parts[2]}"
            else:
                return self._json(400, {"error": "not allowed"})
        except Exception as e:
            return self._json(502, {"reachable": False, "error": str(e)})
        print(f"{self._who()} {action}", flush=True)
        time.sleep(0.8)
        self._json(200, status())

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"Mum's TV on :{PORT}  subtitles={'on' if MODEL else 'off'}  "
          f"light={'on' if LIGHT else 'off'}", flush=True)
    threading.Thread(target=watchdog, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
