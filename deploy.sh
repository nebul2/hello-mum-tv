#!/bin/sh
# Copy this folder to the Pi and restart the server, but never during a call or while
# a volume preset is running.   ./deploy.sh [ssh-host]     (default: $MUMPI_HOST or mum-pi)
set -eu
HOST=${1:-${MUMPI_HOST:-mum-pi}}
cd "$(dirname "$0")"

rsync -a --exclude '.*' --exclude __pycache__ --exclude '*.md' --exclude LICENSE \
    --exclude config.example.json --exclude deploy.sh ./ "$HOST":tvremote/

ssh "$HOST" '
    c=$(curl -s -m 5 "localhost:8080/api/call?role=x"); v=$(curl -s -m 8 localhost:8080/api/status)
    case "$c$v" in
        *idle*"\"busy\": false"*|"") ;;
        *) echo "busy (call or volume preset): files copied, server NOT restarted"; exit 1 ;;
    esac
    # the service runs as this user, so no sudo needed: systemd respawns it in 5 s
    kill "$(systemctl show -p MainPID --value tvremote)"
    sleep 9
    curl -sf -m 5 localhost:8080/api/health && echo " <- server is back"
'
