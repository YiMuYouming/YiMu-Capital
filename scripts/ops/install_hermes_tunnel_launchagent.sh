#!/usr/bin/env bash
set -euo pipefail

LABEL="com.yimu.hermes-tunnel"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="$HOME/Library/Logs/YiMu"
REMOTE="agentuser@43.132.146.234"
LOCAL_PORT="8088"
REMOTE_PORT="8088"

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"

if launchctl print "gui/$(id -u)/${LABEL}" >/dev/null 2>&1; then
  launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
fi

# Clear ad-hoc tunnels so launchd can own localhost:8088.
pids="$(lsof -tiTCP:${LOCAL_PORT} -sTCP:LISTEN || true)"
if [[ -n "$pids" ]]; then
  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    cmd="$(ps -p "$pid" -o command= || true)"
    if [[ "$cmd" == *"ssh"* && "$cmd" == *"${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}"* ]]; then
      kill "$pid" || true
    else
      echo "Port ${LOCAL_PORT} is used by non-tunnel process ${pid}: ${cmd}" >&2
      exit 1
    fi
  done <<< "$pids"
fi

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/ssh</string>
    <string>-N</string>
    <string>-o</string>
    <string>ExitOnForwardFailure=yes</string>
    <string>-o</string>
    <string>ServerAliveInterval=15</string>
    <string>-o</string>
    <string>ServerAliveCountMax=2</string>
    <string>-o</string>
    <string>ConnectTimeout=30</string>
    <string>-L</string>
    <string>${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}</string>
    <string>${REMOTE}</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/hermes-tunnel.out.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/hermes-tunnel.err.log</string>
</dict>
</plist>
PLIST

launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl kickstart -k "gui/$(id -u)/${LABEL}"

sleep 1
launchctl print "gui/$(id -u)/${LABEL}" | sed -n '1,80p'
echo
lsof -nP -iTCP:${LOCAL_PORT} -sTCP:LISTEN
echo
curl -sS --max-time 5 "http://127.0.0.1:${LOCAL_PORT}/api/health"
echo
