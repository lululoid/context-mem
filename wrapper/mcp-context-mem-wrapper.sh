#!/bin/bash

# 1. Capture PIDs
# PARENT_PID is Android Studio
# MY_PID is this script's PID, which node will inherit via 'exec'
PARENT_PID=$PPID
MY_PID=$$

# 2. Detect the active project
RECENT_PROJECTS_XML=$(find "$HOME/.config/Google/AndroidStudio"* -name "recentProjects.xml" 2>/dev/null | sort -V | tail -n 1)

if [[ -f "$RECENT_PROJECTS_XML" ]]; then
    LATEST_PROJECT_RAW=$(grep -E "entry key=|activationTimestamp" "$RECENT_PROJECTS_XML" | paste - - | sed 's/.*key="\([^"]*\)".*value="\([^"]*\)".*/\2 \1/' | sort -rn | head -n 1 | cut -d' ' -f2-)
    LATEST_PROJECT_PATH=${LATEST_PROJECT_RAW//\$USER_HOME\$/$HOME}
    LATEST_PROJECT_PATH=$(echo "$LATEST_PROJECT_PATH" | tr -d '"')

    if [[ -d "$LATEST_PROJECT_PATH" ]]; then
        cd "$LATEST_PROJECT_PATH"
        export CONTEXT_MEM_DB_PATH="$LATEST_PROJECT_PATH/.context-mem/store.db"
    fi
fi

# 3. Paths
NODE_BIN="/home/tomei_yumeoka/.nvm/versions/node/v24.16.0/bin/node"
SERVER_JS="/home/tomei_yumeoka/.nvm/versions/node/v24.16.0/lib/node_modules/context-mem/dist/cli/index.js"

if [[ $# -eq 0 ]]; then
  CMD="serve"
else
  CMD="$1"
  shift
fi

# 4. Launch Daemonized Python Watchdog (only for 'serve')
if [[ "$CMD" == "serve" ]]; then
  # The python script handles double-fork and session detachment internally
  /usr/bin/python3 /home/tomei_yumeoka/.local/bin/context-mem-watchdog.py "$PARENT_PID" "$MY_PID"
fi

# 5. Start Server
exec "$NODE_BIN" "$SERVER_JS" "$CMD" "$@"
