#!/bin/bash

# Arguments: $1=IDE_PID, $2=SERVER_PID
IDE_PID=$1
SERVER_PID=$2
LOG_FILE="/tmp/context-mem-watchdog.log"

echo "$(date): Watchdog started. Monitoring IDE ($IDE_PID) for Server ($SERVER_PID)" > "$LOG_FILE"

while true; do
  # 1. Check if the IDE process is still alive
  if ! /usr/bin/ps -p "$IDE_PID" > /dev/null; then
    echo "$(date): IDE process $IDE_PID disappeared. Triggering cleanup." >> "$LOG_FILE"
    break
  fi

  # 2. Check for fsnotifier as an early warning
  # We look for fsnotifier specifically as a child of the IDE_PID
  if ! /usr/bin/pgrep -P "$IDE_PID" -f "fsnotifier" > /dev/null; then
    echo "$(date): fsnotifier for IDE $IDE_PID disappeared. Shutdown likely. Waiting 5s for confirmation..." >> "$LOG_FILE"
    sleep 5
    if ! /usr/bin/pgrep -P "$IDE_PID" -f "fsnotifier" > /dev/null; then
        echo "$(date): fsnotifier still gone. Triggering cleanup." >> "$LOG_FILE"
        break
    fi
  fi

  # 3. Check if the server process is still alive (safety exit)
  if ! /usr/bin/kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "$(date): Server process $SERVER_PID already exited. Watchdog stopping." >> "$LOG_FILE"
    exit 0
  fi

  sleep 5
done

# Cleanup Phase
echo "$(date): Cleaning up Server $SERVER_PID..." >> "$LOG_FILE"

# Try graceful termination first
/usr/bin/pkill -P "$SERVER_PID" 2>/dev/null
/usr/bin/kill "$SERVER_PID" 2>/dev/null
sleep 2

# Force kill if still alive
if /usr/bin/kill -0 "$SERVER_PID" 2>/dev/null; then
  echo "$(date): Server $SERVER_PID still alive after SIGTERM. Force killing." >> "$LOG_FILE"
  /usr/bin/pkill -9 -P "$SERVER_PID" 2>/dev/null
  /usr/bin/kill -9 "$SERVER_PID" 2>/dev/null
fi

echo "$(date): Cleanup complete. Watchdog exiting." >> "$LOG_FILE"
