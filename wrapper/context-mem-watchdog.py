#!/usr/bin/python3
import os
import sys
import time
import signal
import subprocess
from datetime import datetime

LOG_FILE = "/tmp/context-mem-watchdog.log"

def log(message):
    try:
        # Prevent log file from growing infinitely (> 1MB)
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 1024 * 1024:
            os.remove(LOG_FILE)

        with open(LOG_FILE, "a") as f:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(f"{timestamp}: {message}\n")
    except:
        pass

def is_process_running(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

def get_fsnotifier_pid(parent_pid):
    try:
        # Look specifically for fsnotifier child of the IDE
        output = subprocess.check_output(["/usr/bin/pgrep", "-P", str(parent_pid), "-f", "fsnotifier"])
        return int(output.decode().strip().split('\n')[0])
    except:
        return None

def cleanup(server_pid):
    log(f"SHUTDOWN DETECTED. Cleaning up Server PID {server_pid}")

    # 1. Kill children of the server (e.g. dashboard, npm subshells)
    try:
        subprocess.run(["/usr/bin/pkill", "-P", str(server_pid)], stderr=subprocess.DEVNULL)
    except:
        pass

    # 2. Terminate the server
    try:
        log(f"Sending SIGTERM to {server_pid}")
        os.kill(server_pid, signal.SIGTERM)
        time.sleep(2)
    except OSError:
        pass

    # 3. Force kill if still alive
    if is_process_running(server_pid):
        try:
            log(f"Server {server_pid} STUCK. Sending SIGKILL.")
            os.kill(server_pid, signal.SIGKILL)
        except OSError:
            pass

    # 4. Final sweep for any orphaned context-mem processes in this session
    try:
        subprocess.run(["/usr/bin/pkill", "-f", "context-mem/dashboard/server.js"], stderr=subprocess.DEVNULL)
    except:
        pass

    log("Cleanup finished. Daemon exiting.")

def daemonize():
    """Standard double-fork daemon pattern."""
    try:
        pid = os.fork()
        if pid > 0:
            # Exit first parent
            sys.exit(0)
    except OSError as e:
        log(f"Fork #1 failed: {e}")
        sys.exit(1)

    # Decouple from parent environment
    os.chdir("/")
    os.setsid()
    os.umask(0)

    # Do second fork
    try:
        pid = os.fork()
        if pid > 0:
            # Exit from second parent
            sys.exit(0)
    except OSError as e:
        log(f"Fork #2 failed: {e}")
        sys.exit(1)

    # Redirect standard file descriptors to /dev/null
    sys.stdout.flush()
    sys.stderr.flush()
    si = open(os.devnull, 'r')
    so = open(os.devnull, 'a+')
    se = open(os.devnull, 'a+')
    os.dup2(si.fileno(), sys.stdin.fileno())
    os.dup2(so.fileno(), sys.stdout.fileno())
    os.dup2(se.fileno(), sys.stderr.fileno())

def main():
    if len(sys.argv) < 3:
        sys.exit(1)

    ide_pid = int(sys.argv[1])
    server_pid = int(sys.argv[2])

    # Transform into a true daemon
    daemonize()

    log(f"DAEMON LIVE. PID={os.getpid()} PPID={os.getppid()}. Monitoring IDE ({ide_pid}) for Server ({server_pid})")

    check_count = 0
    while True:
        check_count += 1

        # 1. Main IDE process check
        if not is_process_running(ide_pid):
            log(f"IDE process {ide_pid} vanished. Closing server.")
            cleanup(server_pid)
            break

        # 2. Canary check: fsnotifier
        # IDE usually terminates fsnotifier before it starts waiting for child processes to close.
        if get_fsnotifier_pid(ide_pid) is None:
            log(f"Canary fsnotifier for IDE {ide_pid} gone. Shutdown likely.")
            time.sleep(3) # Short validation window
            if get_fsnotifier_pid(ide_pid) is None:
                log("fsnotifier still gone. Triggering preemptive cleanup.")
                cleanup(server_pid)
                break

        # 3. Safety: check if server process is still alive
        if not is_process_running(server_pid):
            log(f"Server process {server_pid} already dead. Watchdog done.")
            break

        time.sleep(5)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"CRASH: {str(e)}")
