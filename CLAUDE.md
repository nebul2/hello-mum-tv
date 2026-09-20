# Remote care TV (mum-pi)

A Raspberry Pi behind an elderly, mostly bedridden parent's Roku TV. Family can control
the TV remotely and video-call the TV: it wakes, auto-answers, shows the caller full
screen with live subtitles, then puts the TV back as it was. Runs unattended for months.

- Pending work: `CHANGE_REQUESTS.md`. Check it before starting anything new.
- Site details (addresses, hostnames, people): `CLAUDE.local.md`, git-ignored. This repo
  may go public: never put names, addresses, tailnet names or health details in any
  tracked file, commit message or screenshot.

## Layout (this folder = source of truth, deployed to ~/tvremote on the Pi)
- `tvremote.py`: stdlib HTTP server on :8080 (systemd `tvremote.service`, runs from
  `~/tvremote/venv`, which has vosk; Vosk model in `~/tvremote/model`; venv, model and
  `volume.json` live only on the Pi). Settings are constants at the top of the file.
- `static/remote.html` at `/`: family remote (power, volume + presets, channels,
  whitelisted apps, d-pad, show clock, live peek of the Pi screen) and the "Call Mum"
  WebRTC caller view (subtitles, volume estimate, room loudness bar).
- `static/mum.html` at `/mum`: the TV screen in Chromium kiosk. Idle = day, part of day,
  clock, date. Auto-answers calls. Reloads itself after a deploy.
- `kiosk.sh`: started from `~/.config/labwc/autostart`. Waits for the server, respawns
  Chromium, restarts it if `/api/health` says the page stopped polling.
- Callers use HTTPS from `tailscale serve` (needed for camera access). Signalling is HTTP
  polling, non-trickle ICE, no ICE servers: both ends are on the tailnet.

## Things that are not obvious
- Roku ECP cannot report volume. A preset presses down 100 times, pauses, then counts up;
  after that our own presses are counted ("about N"). The TV's own remote makes it drift.
  Calls reset to `CALL_VOLUME` and step back afterwards; `volume.json` lets an
  interrupted call be restored at next start.
- Live TV is Roku app `595596` with `ui-location="tvinput.dtv"`, not app id `tvinput.dtv`.
  This TV reports the channel but no programme title.
- Room loudness: `mum.html` opens a second, unprocessed mic stream during calls and
  posts a 0-100 number. Numbers only.
- `/api/screen` is a `grim` screenshot of the Pi's own display, held in memory ~2 s.
- Restart without sudo: `kill $(systemctl show -p MainPID --value tvremote)`; systemd
  respawns it in 5 s. Never restart during a call or a volume preset (check
  `/api/call?role=x` is idle and `/api/status` has `"busy": false`).
- Don't `pkill -f` a pattern over ssh: it matches its own shell.

## Rules
- The TV may be in use. Before any command that changes it (power, input, volume, app),
  say what will happen and wait for OK, unless told she is asleep.
- Read-only exploration of the Pi and LAN is fine. Ask before installing packages,
  editing system config, or rebooting.
- Never expose anything to the public internet. No port forwarding, no Funnel.
- Never touch the router config or factory reset anything.
- Camera / mic: never record or store audio or video. Live only, during calls only, and
  a clearly visible light must be on whenever either is in use. Not fully met yet:
  see CR-01 (acceptance) and CR-02 (light). Treat both as blockers for wider use.
- Health information (carer notes etc.) stays on the Pi, never in this repo.
- Keep it simple and dependency-light.
- Edit here, deploy with rsync, restart the service. Never edit on the Pi.

## How to talk to me
Talk like cave man: short sentences, simple words, drop filler and articles.
Say only what matters. Keep code, commands, file paths and error messages exact and complete.
Still warn me clearly about risks.
