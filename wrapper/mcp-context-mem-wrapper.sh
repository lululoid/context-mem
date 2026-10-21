#!/bin/bash

PARENT_PID=$PPID
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROXY_PY="$SCRIPT_DIR/context-mem-proxy.py"

if [[ -f "$PROXY_PY" ]]; then
  exec /usr/bin/python3 "$PROXY_PY" "$PARENT_PID" "$@"
else
  exec /usr/bin/python3 /home/tomei_yumeoka/.local/bin/context-mem-proxy.py "$PARENT_PID" "$@"
fi
