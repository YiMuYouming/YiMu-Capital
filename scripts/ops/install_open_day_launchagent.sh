#!/usr/bin/env bash
set -euo pipefail

LABEL="com.yimu.open-day"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEMPLATE="${PROJECT_ROOT}/launchd/${LABEL}.plist"
TARGET="${HOME}/Library/LaunchAgents/${LABEL}.plist"
DOMAIN="gui/$(id -u)"
LOG_DIR="${HOME}/Library/Logs"

if [[ ! -f "${TEMPLATE}" ]]; then
  echo "missing plist template: ${TEMPLATE}" >&2
  exit 1
fi

mkdir -p "${HOME}/Library/LaunchAgents" "${LOG_DIR}"
staged="$(mktemp "${TMPDIR:-/tmp}/yimu-open-day.XXXXXX.plist")"
trap 'rm -f "${staged}"' EXIT

/usr/bin/sed \
  -e "s|__PROJECT_ROOT__|${PROJECT_ROOT}|g" \
  -e "s|__HOME__|${HOME}|g" \
  "${TEMPLATE}" > "${staged}"
/usr/bin/plutil -lint "${staged}"

if [[ -e "${TARGET}" ]]; then
  if ! /usr/bin/plutil -extract YIMUManaged raw -o - "${TARGET}" 2>/dev/null | /usr/bin/grep -qx 'true'; then
    echo "refusing to replace unmanaged LaunchAgent: ${TARGET}" >&2
    exit 1
  fi
  launchctl bootout "${DOMAIN}" "${TARGET}" >/dev/null 2>&1 || true
fi

/bin/cp "${staged}" "${TARGET}"
/usr/bin/plutil -lint "${TARGET}"
launchctl bootstrap "${DOMAIN}" "${TARGET}"
# This only starts the installed guard.  At install time the publisher's
# trading-day and 08:50-09:20 gates make the current 00:xx invocation skip.
launchctl kickstart "${DOMAIN}/${LABEL}"
launchctl print "${DOMAIN}/${LABEL}" | /usr/bin/sed -n '1,100p'
