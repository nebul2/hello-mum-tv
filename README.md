# hello-mum-tv

Video-call an elderly parent **on their own TV**, without them having to do anything.

A Raspberry Pi sits behind a Roku TV. When a family member presses "Call Mum" on a web
page, the TV switches itself on, changes to the Pi's input, turns the volume up, shows
the caller full screen with **big live subtitles**, and afterwards puts the TV back
exactly as it was. The same page is a simple remote for the TV, so family can find the
right channel or fix the volume from anywhere.

Built for one bedridden mum who can no longer manage a remote or a phone. Shared in
case it helps another family. It is a home project: small, dependency-light, meant to
run unattended for months.

## What it does

- **Look in first**: pressing Call Mum makes the TV say "X is about to call, wave your
  hands if you don't want this", and shows the caller a pixelated view of the room that
  sharpens a little over a few seconds. Call now, or Not now. So nobody walks in on
  personal care.
- **Call Mum**: WebRTC video call from any phone or laptop browser to the TV.
  Auto-answers. Wakes the TV, remembers what was on, restores it after.
- **Live subtitles** of the caller's speech on the TV (offline, [Vosk](https://alphacephei.com/vosk/)),
  rolled up in two large lines.
- **Call volume**: sets a known loud level for the call and steps back afterwards.
- **Camera zoom and pan** from the caller's page (digital, UVC controls); every call
  starts and ends on the wide view.
- **Room loudness bar** for the caller, so you can tell how loud the TV really is.
- **Family remote**: power, volume with presets, channels, app launches, d-pad,
  "show clock", and a live peek of what the Pi is showing.
- **Idle screen**: day, part of day, time and date in very large type, for orientation.
- **Self-healing kiosk**: waits for the server at boot, restarts a stuck browser,
  switches a dropped HDMI output back on, reloads itself after a deploy.
- **Private by design**: nothing is exposed to the internet. Family reach it over
  [Tailscale](https://tailscale.com); the Pi is shared with them as a single machine.

## Please read first: consent, cameras and care

This puts a remotely activated camera and microphone in the room of a vulnerable
person. Treat that seriously.

- Nothing is ever recorded or stored. Camera and mic are live only during a call.
- A clearly visible "camera on" light is part of the design. **It is not finished**:
  see CR-01 (clear acceptance by the person being called) and CR-02 (unmissable light)
  in [CHANGE_REQUESTS.md](CHANGE_REQUESTS.md). Until those are done, think hard about
  who you give access to.
- Carers and visitors are on camera too. Tell them. Put up a notice. Check your care
  provider's policy.
- The person's agreement matters, and with dementia it has to be revisited, not
  assumed. In the UK, look at the Mental Capacity Act 2005 and who holds a Health and
  Welfare LPA. Other countries have their own rules.
- This is not a medical device, not a monitoring or safety system, and nothing here is
  legal advice.

## Hardware

- Raspberry Pi 5 (4 GB is plenty), Raspberry Pi OS 64-bit desktop (Bookworm / Trixie,
  labwc / Wayland).
- A Roku TV or Roku player on the same network ("Control by mobile apps" enabled, fast
  start / warm standby on, so it can be woken over the network).
- A USB webcam with a microphone, placed by the TV. A plain wired USB (UVC) webcam is
  all you need. A "wireless" webcam brings no benefit here: the Pi sits right behind
  the TV anyway, and a radio link only adds a battery to charge, latency and one more
  thing to fail. Worth paying for instead: **zoom and pan** (UVC `zoom_absolute`,
  `pan_absolute`, `tilt_absolute`; check with `v4l2-ctl --list-ctrls`), which the
  caller's page can drive, a wide lens, and a decent microphone. A physical lens cover
  is a plus.
- Optional: a bright light on GPIO17 that is on during calls.

Other TVs would need their own control code in place of the Roku ECP calls in
`tvremote.py`.

## How it fits together

```
caller's browser --HTTPS (tailscale serve)--> tvremote.py on the Pi :8080
                                                |-- Roku ECP (HTTP :8060) -> TV power, input, volume, apps
                                                |-- static/remote.html     the family page   /
                                                '-- static/mum.html        the TV page       /mum (Pi only)
Chromium kiosk on the Pi shows /mum on the TV, answers calls, sends caller audio to
Vosk for subtitles. Signalling is plain HTTP polling; media is WebRTC peer to peer
over the tailnet (no STUN / TURN servers).
```

- `tvremote.py`: the whole server, Python standard library only (plus optional `vosk`
  and `gpiozero`).
- `kiosk.sh`: keeps Chromium and the display alive.
- `tools/force-hdmi.sh`: keeps the Pi's HDMI output on when the TV sleeps. You will
  almost certainly need it: without it the TV wakes to "no signal" (see CR-15).
- `config.json` (yours, untracked) / `config.example.json`: site settings.
- `deploy.sh`: copy to the Pi and restart, never during a call.

## Install (outline)

On the Pi:

```sh
mkdir -p ~/tvremote && cd ~/tvremote          # copy this repo's files here (see deploy.sh)
python3 -m venv --system-site-packages venv
venv/bin/pip install vosk
# a Vosk model, unpacked so that ~/tvremote/model/am exists:
wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
unzip vosk-model-small-en-us-0.15.zip && mv vosk-model-small-en-us-0.15 model

cp config.example.json config.json            # set your TV's address and HDMI input

sed "s/__USER__/$USER/g" tvremote.service | sudo tee /etc/systemd/system/tvremote.service
sudo systemctl daemon-reload && sudo systemctl enable --now tvremote

echo "$HOME/tvremote/kiosk.sh &" >> ~/.config/labwc/autostart   # TV page at login
sudo tailscale serve --bg 8080                # HTTPS for callers, tailnet only
```

Set the Pi to log in to the desktop automatically, make PipeWire's default output the
HDMI port and default input the webcam mic, give the TV and Pi fixed addresses, and
reboot. Then open `https://<your-pi>.<your-tailnet>.ts.net` from a device on your
tailnet.

Family members: install Tailscale, accept a share invite for the Pi, open the page,
add it to the home screen. Never use Tailscale Funnel or port forwarding for this.

After the first boot run `sudo sh ~/tvremote/tools/force-hdmi.sh HDMI-A-1` (or
`HDMI-A-2`, whichever port `wlr-randr` shows the TV on) and reboot, and keep the cable
in that port.

## Hacking on it (no Pi or TV needed)

The server is one standard-library Python file and runs on any laptop:

```sh
git clone https://github.com/nebul2/hello-mum-tv && cd hello-mum-tv
echo '{"TV": "http://127.0.0.1:9"}' > config.json    # a TV address that goes nowhere
python3 tvremote.py
```

Open `http://localhost:8080/mum` in one tab (the "TV") and `http://localhost:8080/` in
another (the caller), press Call Mum: `localhost` counts as secure, so camera and mic
work and you can call yourself. Without a Roku the remote says "Can't reach the TV",
without `vosk` there are no subtitles, without `grim` / `v4l2-ctl` no screen peek or
camera moves; everything else works. **Never point a dev copy at a real TV in someone's
bedroom.**

Send changes as pull requests. House rules: standard library only unless there is a
very good reason; nothing that records or stores audio or video, ever; no addresses,
names, tailnet names or health details in code, commits, issues or screenshots; test
calls, volume and TV power on your own kit, not on the live system. Deploys to the live
Pi are done by one person, with `deploy.sh`, never during a call.

## Settings

Defaults are constants at the top of `tvremote.py`; override them in `config.json`
(untracked): TV address, HDMI input, volume presets, call volume, subtitle size, app
list. The Roku cannot report its volume, so presets drive it to zero and count back up,
and the page shows an honest "about N".

## Status and contributing

In use by one family since September 2026. Rough edges and plans are in
[CHANGE_REQUESTS.md](CHANGE_REQUESTS.md): consent flow and camera light first, then a
carer notice board, quiet hours, deep links into streaming apps, camera zoom and pan,
better UK subtitles. Issues and pull requests welcome. Please keep it simple, keep it
dependency-light, and never add anything that records.

`CLAUDE.md` holds working notes for AI-assisted development of this repo.

## Licence

MIT. See [LICENSE](LICENSE).
