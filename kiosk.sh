#!/bin/sh
# Mum's TV screen kiosk, started from ~/.config/labwc/autostart.
# Waits for tvremote to be up (so no browser error page at boot), keeps Chromium
# running, and restarts it if the page stops checking in with the server
# (crashed tab, error page, hung browser).
URL=http://localhost:8080/mum
HEALTH=http://localhost:8080/api/health

# The TV going to sleep can leave the Pi's HDMI output switched off, so the TV shows
# "no signal" when it wakes. Switch any connected-but-disabled output back on.
fix_display() {
    wlr-randr 2>/dev/null | awk '/^[^ ]/{o=$1} /Enabled: no/{print o}' | while read -r o; do
        wlr-randr --output "$o" --on
    done
}

# HDMI audio sometimes vanishes (kernel: "Unknown ELD version 0" when the TV switches
# input), leaving PipeWire on "Dummy Output" and the TV silent. Restarting the audio
# services brings the HDMI sink back.
fix_audio() {
    if wpctl status 2>/dev/null | grep -q "Dummy Output"; then
        echo "$(date +%T) audio sink lost, restarting pipewire"
        systemctl --user restart wireplumber pipewire pipewire-pulse
        sleep 5
    fi
    # the Pi has no speaker: send full level over HDMI and let the TV's volume rule
    wpctl set-volume @DEFAULT_AUDIO_SINK@ 1.0 2>/dev/null
    wpctl set-mute @DEFAULT_AUDIO_SINK@ 0 2>/dev/null
}

while :; do
    until curl -sf -m 5 -o /dev/null "$URL"; do sleep 2; done
    fix_display
    fix_audio

    chromium --kiosk --noerrdialogs --disable-infobars --no-first-run \
        --disable-session-crashed-bubble --hide-crash-restore-bubble \
        --password-store=basic --autoplay-policy=no-user-gesture-required \
        --use-fake-ui-for-media-stream "$URL" &
    pid=$!

    bad=0
    while kill -0 "$pid" 2>/dev/null; do
        sleep 10
        fix_display
        fix_audio
        # Only judge the page while the server is answering; if the server is
        # down the page keeps polling and recovers by itself.
        age=$(curl -sf -m 5 "$HEALTH" | sed -n 's/.*"mum_age": *\([0-9]*\).*/\1/p')
        if [ -n "$age" ] && [ "$age" -gt 60 ]; then bad=$((bad + 1)); else bad=0; fi
        [ "$bad" -ge 3 ] && break
    done

    kill "$pid" 2>/dev/null
    pkill -x chromium 2>/dev/null
    sleep 3
done
