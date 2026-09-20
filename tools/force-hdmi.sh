#!/bin/sh
# Keep one of the Pi's HDMI outputs switched on even when the TV sleeps or is off.
# Without this the Pi can drop the output when the TV sleeps, and the TV then shows
# "no signal" on the next call. Adds video=<connector>:<mode>D to the kernel command
# line ("D" = force the digital output on). Takes effect after a reboot.
#
#   sudo sh force-hdmi.sh HDMI-A-2 [1920x1080@60]
#
# Force only the port the TV is plugged into: forcing an empty port creates a phantom
# second screen. Connector names: wlr-randr, or ls /sys/class/drm.
set -eu
CONN=${1:?usage: sudo sh force-hdmi.sh HDMI-A-2 [1920x1080@60]}
MODE=${2:-1920x1080@60}
F=/boot/firmware/cmdline.txt
BAK="$F.bak-$(date +%Y%m%d-%H%M%S)"

[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
if grep -q "video=$CONN:" "$F"; then
    echo "already set, nothing changed:"; cat "$F"; echo; exit 0
fi

cp "$F" "$BAK"
# cmdline.txt must stay one single line
printf '%s video=%s:%sD\n' "$(tr -d '\n' < "$F")" "$CONN" "$MODE" > "$F.new"
[ "$(wc -l < "$F.new")" -eq 1 ] || { echo "refusing: result is not one line"; rm -f "$F.new"; exit 1; }
mv "$F.new" "$F"

echo "backup: $BAK"
echo "new $F:"; cat "$F"
echo "undo:   sudo cp $BAK $F"
echo "now reboot for it to take effect"
