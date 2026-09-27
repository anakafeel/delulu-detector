#!/usr/bin/env bash
# Fresh live Poker Face. Stops any booth already holding the Arduino, the
# webcam, or the UI port, then starts one new session.
# Arduino on /dev/ttyACM0, Logitech Brio at camera 2, UI on http://127.0.0.1:8765
set -euo pipefail
cd "$(dirname "$0")"

UI_PORT=8765
SERIAL=/dev/ttyACM0
CAMERA_DEV=/dev/video2

if [[ -n "${DELULU_PYTHON:-}" ]]; then
  PY="$DELULU_PYTHON"
elif [[ -x .venv/bin/python ]]; then
  PY=".venv/bin/python"
elif [[ -x /home/saim/delulu-hwtest/delulu-detector/.venv/bin/python ]]; then
  PY="/home/saim/delulu-hwtest/delulu-detector/.venv/bin/python"
else
  echo "No venv python. Create .venv or set DELULU_PYTHON." >&2
  exit 1
fi

booth_pids() {
  ps -eo pid=,cmd= | awk '/python/ && /pi\/main\.py/ && !/awk/ { print $1 }'
}

bridge_pids() {
  ps -eo pid=,cmd= | awk '/presage\/bridge\.mjs/ && !/awk/ { print $1 }'
}

stop_pids() {
  local signal="$1"
  shift
  local pid
  for pid in "$@"; do
    [[ -n "$pid" ]] || continue
    kill "-${signal}" "$pid" 2>/dev/null || true
  done
}

stop_booth() {
  local pids
  pids=$(booth_pids || true)
  if [[ -z "${pids}" ]]; then
    return 0
  fi
  echo "Stopping the booth already running (pids: ${pids//$'\n'/ })."
  # shellcheck disable=SC2086
  stop_pids TERM ${pids}
  local i
  for i in 1 2 3 4 5 6 7 8 9 10; do
    pids=$(booth_pids || true)
    [[ -z "${pids}" ]] && break
    sleep 0.4
  done
  pids=$(booth_pids || true)
  if [[ -n "${pids}" ]]; then
    echo "The old booth did not exit. Killing it."
    # shellcheck disable=SC2086
    stop_pids KILL ${pids}
    sleep 0.3
  fi
  pids=$(bridge_pids || true)
  if [[ -n "${pids}" ]]; then
    # shellcheck disable=SC2086
    stop_pids TERM ${pids}
    sleep 0.3
    pids=$(bridge_pids || true)
    if [[ -n "${pids}" ]]; then
      # shellcheck disable=SC2086
      stop_pids KILL ${pids}
    fi
  fi
}

device_busy() {
  local path="$1"
  [[ -e "$path" ]] || return 1
  fuser "$path" >/dev/null 2>&1
}

port_busy() {
  ss -ltn | awk -v port=":${UI_PORT}\$" '$4 ~ port { found=1 } END { exit !found }'
}

wait_free() {
  local i busy
  for i in $(seq 1 25); do
    busy=""
    if port_busy; then
      busy="port ${UI_PORT}"
    fi
    if device_busy "$SERIAL"; then
      busy="${busy:+$busy, }${SERIAL}"
    fi
    if device_busy "$CAMERA_DEV"; then
      busy="${busy:+$busy, }${CAMERA_DEV}"
    fi
    if [[ -z "$busy" ]]; then
      return 0
    fi
    sleep 0.2
  done
  echo "Still in use after stopping the old booth: ${busy}." >&2
  exit 1
}

maybe_build() {
  local newest=0 dist=0
  if [[ -f frontend/dist/index.html ]]; then
    dist=$(stat -c %Y frontend/dist/index.html)
  fi
  if [[ -d frontend/src ]]; then
    newest=$(find frontend/src frontend/public frontend/index.html -type f -printf '%T@\n' 2>/dev/null | sort -n | tail -1 | cut -d. -f1)
  fi
  newest=${newest:-0}
  if [[ ! -f frontend/dist/index.html || "$newest" -gt "$dist" ]]; then
    echo "Frontend is newer than frontend/dist. Building it."
    (cd frontend && npm run build)
  fi
}

stop_booth
wait_free
maybe_build

exec env PYTHONPATH=pi "$PY" -u pi/main.py \
  --port "$SERIAL" \
  --round 5 \
  --camera 2 \
  --ui \
  --ui-host 127.0.0.1 \
  "$@"
