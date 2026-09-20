# Change requests

Everything pending. One entry per change. Status: `open`, `parked`, `testing`, `done`.
Priority: P0 = must fix before wider family use, P1 = next, P2 = nice to have.

Site-specific values (addresses, names, tailnet) never go in this file.

| CR | Title | Priority | Status |
|----|-------|----------|--------|
| 01 | Clear acceptance by the person being called | P0 | open |
| 02 | Unmissable "camera is on" light | P0 | open |
| 03 | Lock the TV page (`/mum`) to the Pi itself | P0 | done |
| 04 | Restrict shared users to HTTPS only (Tailscale ACL) | P1 | parked |
| 05 | Carer link: notes and contact between carers and family | P1 | open |
| 06 | Echo: test with a truly remote caller, then fix | P1 | testing |
| 07 | Screen feedback for navigating TV apps | P1 | open |
| 08 | Better subtitles (UK English model) | P2 | open |
| 09 | Quiet hours | P1 | open |
| 10 | Clock: "back to TV" and optional night clock | P2 | open |
| 11 | Family onboarding | P1 | open |
| 12 | Public repository preparation | P1 | mostly done |
| 13 | Small stuff | P2 | open |
| 14 | Reframe the camera from the caller's page (zoom, pan, tilt) | P1 | open |
| 15 | Pi HDMI output drops when the TV sleeps | P0 | fix ready, not applied |

---

## CR-01 Clear acceptance by the person being called (P0, open)

**Problem.** The TV auto-answers and the camera goes live at once. The person in the
bed is elderly, may be confused, and cannot use a remote. A one-off "she was OK with
it" is not enough: acceptance has to be clear, repeatable, and respected on a bad day.
Carers and visitors in the room are on camera too.

**This is not legal advice.** In the UK the relevant frame is the Mental Capacity Act
2005: capacity is decision-specific and can fluctuate; where the person lacks capacity
the decision is a best-interests one, normally involving whoever holds a Health and
Welfare LPA, and it should be written down. Care agencies have their own policies on
cameras in a client's home. Check both before wider use.

**Proposed changes.**
1. Announce before the camera starts: ring for N seconds showing the caller's name and
   face, with a spoken "X is calling", and only then start the camera.
2. A way to say no that needs no dexterity: one big physical button (GPIO or USB) that
   declines or ends the call, and a carer-operable "privacy for 30 / 60 min" mode that
   blocks all calls. Blocked callers are told why.
3. Privacy windows on a schedule (personal care, night) when the camera cannot start.
4. Physical lens cover the carer can close; the system must cope with a black image.
5. Transparency: call log (who, when, how long) visible to all family members on the
   remote page. No content is ever logged.
6. A printed notice in the room: there is a camera, when it is on, who can call, how to
   block it. Agree it with the care provider.
7. Record the consent / best-interests decision outside this repo and review it
   regularly.

**Acceptance.** A stranger reading the notice understands the system in 30 seconds. The
person or a carer can refuse or end a call without touching a screen. No call can start
inside a privacy window. Family can see the call log.

## CR-02 Unmissable "camera is on" light (P0, open)

**Problem.** Rule: a light must be on whenever camera or mic is live. Today the software
drives GPIO17 but nothing is wired, and a 5 mm LED would be far too easy to miss. The
webcam's own green LED is not under our control.

**Proposed changes.**
1. A large, bright red light visible from the bed and the doorway (LED module or lamp
   via a transistor / relay board on GPIO17; or a USB-powered beacon switched by GPIO).
2. On-screen banner for the whole call: "CAMERA ON - X can see and hear you".
3. Fail safe: config `REQUIRE_LIGHT = True`; if the light cannot be initialised the
   server refuses calls and says why on the remote page.
4. Light covers every use of camera or mic, including the room loudness meter.
5. Boot self-test: blink the light; show light status on the remote page.
6. Longer term: power the light from the same signal that enables the camera (e.g. a
   USB power switch for the camera receiver), so software cannot show one without the
   other.

**Acceptance.** Anyone walking into the room can tell within a second whether the
camera is live. Unplugging the light makes calls impossible.

## CR-03 Lock the TV page to the Pi itself (P0, done 2026-09-20)

**Problem.** `/mum` auto-answers calls. Anyone with access who opens it in their own
browser answers instead of the TV, with their own camera.

**Change.** Serve `/mum`, `/api/call?role=mum`, `/api/call/answer`, `/api/call/level`
and `/api/stt` only to loopback clients that did not come through the Tailscale proxy
(no `Tailscale-User-Login` header, remote address 127.0.0.1). Everyone else gets 403.

**Acceptance.** `/mum` from a phone returns 403; calls still auto-answer on the TV.

**Result.** `_on_pi()` in `tvremote.py`. 403 verified over HTTPS, over the tailnet on
:8080, over the LAN, and with a spoofed proxy header from the Pi; kiosk still gets 200.

## CR-04 Restrict shared users to HTTPS only (P1, parked)

Default Tailscale policy lets a shared user reach every open port on the Pi (web over
plain HTTP, SSH, rpcbind). Wanted: `autogroup:shared` may reach only tcp:443 on the Pi;
members keep full access. Parked by the owner pending a wider Tailscale redesign.
Related: bind the web server to loopback so only `tailscale serve` exposes it (check
that the kiosk and LAN carer page in CR-05 still work).

## CR-05 Carer link (P1, open)

**Goal.** Carers on site and family far away can reach each other through the system:
talk while the carer is in the room, and pass on things like medication changes.

**Proposed shape.**
1. `/carer` page, reachable on the home Wi-Fi without Tailscale (QR code on the wall),
   protected by a PIN. Plain HTTP on the LAN means no camera from the carer's phone,
   which is fine: the room already has one.
2. Notice board, both directions: carer notes (visit done, ate well, medication changed
   to ...) and family notes for carers. Newest first, author and time, optional
   "important" flag that family must acknowledge.
3. "Please call now" button: marks the carer as on site and alerts family. Alert channel
   to be chosen: shows on the remote page at minimum; push via a self-hosted or
   privacy-respecting notifier is a separate decision because it leaves the tailnet.
4. Family sees a "carer on site" badge and can call the TV as usual; the carer can accept
   on the TV with the physical button from CR-01.
5. Text only. No voice notes: the no-recording rule stands.

**Data care.** Notes contain health information. Stored only on the Pi, outside the
repo, with a retention limit (e.g. 90 days), included in no logs, never in screenshots
or issues. This is a family convenience, not a clinical record: it does not replace the
care provider's medication chart.

**Open questions.** Who may read old notes? Do agency carers need the agency's approval
to use it? One shared PIN or one per carer? How are family alerted when no page is open?

## CR-06 Echo (P1, testing)

TV speaker sits next to the camera mic. All calls so far were made from inside the
house, so echo has not been judged. Test with a remote caller, then in order:
move / aim the camera away from the speakers; TV sound mode Standard, processing off;
Game mode on the Pi's HDMI input to cut latency; optional "Reduce echo" half-duplex
ducking toggle in the call view; last resort a USB speakerphone near the bed.

## CR-07 Screen feedback for navigating TV apps (P1, open)

Roku ECP offers no screenshot and the TV has no HDMI out, so launching iPlayer and
steering it blind is not practical. Test in this order (each test changes the TV):
1. Deep links: `POST /launch/<app>?contentId=<id>&mediaType=<type>`. Prove with YouTube,
   then iPlayer using the programme id from the web URL. Goal: paste a programme link on
   the remote page, it plays on the TV, no menus.
2. `POST /search/browse?title=...&provider-id=<app>&launch=true`.
3. Show playback state from `/query/media-player` (playing / paused, position, duration).
4. Second cheap camera aimed at the TV screen, snapshots only while someone is
   navigating. Same camera rules and light as CR-02.
5. Not recommended for now: playing content on the Pi instead of the Roku.

## CR-08 Better subtitles (P2, open)

Current Vosk model is small US English; UK names and accents come out rough. Try a
larger or UK-tuned model and measure CPU and delay on the Pi 5 during a call. Needs a
download on the Pi.

## CR-09 Quiet hours (P1, open)

A call wakes the TV and sets the volume to the call level at any hour. Add configurable
quiet hours: caller gets "It is 03:10 at Mum's. Call anyway?" and must confirm. Shares
the schedule mechanism with CR-01 privacy windows (which block, not just warn).

## CR-10 Clock extras (P2, open)

"Back to TV" button that returns to whatever was on before "Show clock". Optional: show
the clock automatically late at night to help orientation. The second changes the TV
unprompted, so it needs an explicit decision.

## CR-11 Family onboarding (P1, open)

One message for the group, a three-step follow-up for those who self-install, in-person
setup for the rest (VPN on demand, home-screen icon, name typed once, one test call).
Do CR-03 before the first invite goes out. Consider a short HOWTO page served by the Pi.

## CR-12 Public repository preparation (P1, open)

**2026-09-20:** published as `hello-mum-tv` (MIT). Done: untracked `config.json` +
`config.example.json`, templated service unit, README, LICENSE, `deploy.sh`, fresh
history, private-string scan. Left: `install.sh`; app buttons, channel names and preset
numbers are still hard-coded in `static/remote.html`; a screenshot with no faces.

1. Move site values out of code into an untracked `config.json` (TV address, HDMI input,
   channel and app lists, volume presets, call volume) with a tracked
   `config.example.json`.
2. `tvremote.service` and `kiosk.sh`: no hard-coded user or home path (template or
   `%h` / `$HOME`).
3. README: what it is, photo or screenshot with no faces, hardware list, install steps,
   the privacy rules, "not a medical device, not legal advice".
4. LICENSE (owner to choose; MIT is the simple default).
5. `install.sh` / `deploy.sh` so setup and deploy are one command each.
6. Before the first push: search history and files for names, addresses, tailnet name,
   health details. Start the repo fresh rather than importing any earlier history.

## CR-13 Small stuff (P2, open)

- Screen peek: ~100 KB per frame every 5 s; use a smaller / JPEG frame for mobile data.
- Volume estimate drifts if the TV's own remote is used; show "last known at HH:MM".
- Presets take 20-40 s; consider stepping from the estimate when it was set recently.
- Allow restarting the service without a password (narrow sudoers rule or user unit).
- Refuse to restart / deploy while a call or preset is running (script check).
- Remote page: show when someone else is already on a call, and who.

## CR-14 Reframe the camera from the caller's page (P1, open)

**Found (read-only `v4l2-ctl -d /dev/video0 --list-ctrls-menus`).** The webcam exposes
UVC controls: `zoom_absolute` 0-9, `pan_absolute` and `tilt_absolute` -36000..36000 in
steps of 3600 (10 steps each way), plus `backlight_compensation` 0-2, `brightness`,
`contrast`, `gamma`, `sharpness`, continuous autofocus, 50 Hz anti-flicker (already
set). Formats: MJPEG up to 1920x1080, H.264 up to 1080p, YUYV 640x480. Almost certainly
digital zoom / pan / tilt: pan and tilt will only do something once zoomed in, and
quality drops with zoom.

**To test (camera must be live, so during a call, light rules apply).**
1. Does each control really move the picture? Usable zoom range before it goes soft?
2. Can `v4l2-ctl -c zoom_absolute=N` change it while Chromium is streaming? (Normally
   yes for UVC.) Do values survive a replug or reboot, or reset to default?
3. Does capturing at 1080p and zooming beat 720p unzoomed for seeing a face?

**Proposed change.** In the call view: zoom - / +, a small pan / tilt pad, "reset view",
and a backlight toggle for a bright window behind the bed. Server endpoint
`POST /api/camera/<control>/<value>`: whitelist of controls, values clamped to the
ranges above, only while a call is active, runs `v4l2-ctl`. Reset to defaults when the
call ends, so every call starts with the same wide view. Optional later: named views
("bed", "chair", "door") saved in the untracked config.

**Privacy note.** Zooming changes what the caller can see of the room and of carers.
Default wide view and reset after each call are part of CR-01's "no surprises".

## CR-15 Pi HDMI output drops when the TV sleeps (P0, fix ready, not applied)

**Seen 2026-09-20.** When the Roku TV goes to standby the compositor disables the Pi's
HDMI output (`wlr-randr`: `Enabled: no`, connector still "connected"). While the TV
sleeps the output cannot be re-enabled (`failed to apply configuration`). On the next
call the TV wakes to "no signal"; enabling the output mid-call froze Chromium.

**In place.** `kiosk.sh` re-enables any connected-but-disabled output every 10 s (works
only once the TV is awake) and its watchdog restarts a frozen Chromium after ~90 s. So
the first call after a sleep can still fail once.

**Fix.** Force the connector on so it never drops:
`sudo sh ~/tvremote/tools/force-hdmi.sh <connector>` then reboot. Needs the owner's sudo.

**Acceptance.** TV in standby for 10 min: `wlr-randr` still shows `Enabled: yes`; the
next call shows the caller on the TV within seconds of it waking.

