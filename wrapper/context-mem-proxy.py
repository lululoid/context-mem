#!/usr/bin/python3
"""
MCP Stdio Proxy and Dynamic Database Switcher for context-mem.
Maintains persistent stdio connection with IDE and hot-swaps child server when active project changes.
"""

import os
import sys
import time
import glob
import shutil
import threading
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime

LOG_FILE = "/tmp/context-mem-proxy.log"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))


def resolve_node_bin() -> str:
    """Resolves node binary path."""
    return (
        shutil.which("node")
        or "/home/tomei_yumeoka/.nvm/versions/node/v24.16.0/bin/node"
        or "node"
    )


def resolve_server_js() -> str:
    """Resolves context-mem CLI entrypoint path."""
    local_dist = os.path.join(REPO_ROOT, "dist", "cli", "index.js")
    if os.path.exists(local_dist):
        return local_dist
    return "/home/tomei_yumeoka/.nvm/versions/node/v24.16.0/lib/node_modules/context-mem/dist/cli/index.js"


NODE_BIN = resolve_node_bin()
SERVER_JS = resolve_server_js()


def log(msg: str) -> None:
    """Logs timestamped messages to log file with rotation."""
    try:
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 1024 * 1024:
            os.remove(LOG_FILE)
        with open(LOG_FILE, "a") as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: {msg}\n")
    except Exception:
        pass


def is_process_running(pid: int) -> bool:
    """Checks if process PID is active."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def find_project_by_name(project_name: str) -> str | None:
    """Finds matching project path in recentProjects.xml by project name."""
    xml_files = glob.glob(os.path.expanduser("~/.config/Google/AndroidStudio*/options/recentProjects.xml"))
    home_dir = os.path.expanduser("~")
    for xml_file in xml_files:
        try:
            tree = ET.parse(xml_file)
            for entry in tree.getroot().findall(".//entry"):
                raw_key = entry.get("key", "")
                project_path = raw_key.replace("$USER_HOME$", home_dir)
                if os.path.basename(project_path).casefold() == project_name.casefold():
                    return project_path
        except Exception:
            continue
    return None


def get_latest_project_from_xml() -> str | None:
    """Returns the most recently activated project path from Android Studio XML configs."""
    xml_files = glob.glob(os.path.expanduser("~/.config/Google/AndroidStudio*/options/recentProjects.xml"))
    best_path, max_ts = None, -1
    home_dir = os.path.expanduser("~")

    for xml_file in xml_files:
        try:
            tree = ET.parse(xml_file)
            for entry in tree.getroot().findall(".//entry"):
                raw_key = entry.get("key", "")
                project_path = raw_key.replace("$USER_HOME$", home_dir)
                for option in entry.findall(".//option"):
                    if option.get("name") in ("activationTimestamp", "projectOpenTimestamp"):
                        try:
                            ts = int(option.get("value", "0"))
                            if ts > max_ts and os.path.isdir(project_path):
                                max_ts, best_path = ts, project_path
                        except ValueError:
                            pass
        except Exception:
            continue
    return best_path


def get_active_project_path(ide_pid: int) -> str | None:
    """Detects active project path via window title, recentProjects.xml, or IDE CWD."""
    try:
        title_bytes = subprocess.check_output(
            ["/usr/bin/xdotool", "getactivewindow", "getwindowname"],
            stderr=subprocess.DEVNULL
        )
        title = title_bytes.decode("utf-8", errors="ignore").strip()
        if title:
            proj_name = title.split(" – ")[0].split(" - ")[0].strip()
            if proj_name:
                matched_path = find_project_by_name(proj_name)
                if matched_path and os.path.isdir(matched_path):
                    return matched_path
    except Exception:
        pass

    latest_path = get_latest_project_from_xml()
    if latest_path and os.path.isdir(latest_path):
        return latest_path

    try:
        cwd = os.readlink(f"/proc/{ide_pid}/cwd")
        if os.path.isdir(cwd):
            return cwd
    except Exception:
        pass

    return None


class StdioProxy:
    """Proxies stdio between IDE and context-mem server, hot-swapping DB on project change."""

    def __init__(self, ide_pid: int, server_args: list[str]):
        self.ide_pid = ide_pid
        self.server_args = server_args
        self.lock = threading.Lock()
        self.current_project_path = None
        self.child_process = None
        self.running = True

    def start_child(self, project_path: str) -> None:
        """Spawns child server configured for target project directory."""
        env = os.environ.copy()
        db_path = os.path.join(project_path, ".context-mem", "store.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        env["CONTEXT_MEM_DB_PATH"] = db_path

        cmd = [NODE_BIN, SERVER_JS] + self.server_args
        log(f"Starting child in '{project_path}' with DB '{db_path}' (node={NODE_BIN}, script={SERVER_JS})")

        process = subprocess.Popen(
            cmd,
            cwd=project_path,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0
        )
        self.child_process = process
        self.current_project_path = project_path

    def stop_child(self) -> None:
        """Terminates active child process."""
        if self.child_process:
            try:
                log(f"Stopping child PID {self.child_process.pid}")
                self.child_process.terminate()
                self.child_process.wait(timeout=2)
            except Exception:
                try:
                    self.child_process.kill()
                except Exception:
                    pass
            self.child_process = None

    def restart_child(self, new_project_path: str) -> None:
        """Hot-swaps child server to new project directory."""
        with self.lock:
            self.stop_child()
            self.start_child(new_project_path)

    def forward_stdin(self) -> None:
        """Forwards stdin from IDE to child process."""
        while self.running:
            try:
                line = sys.stdin.buffer.readline()
                if not line:
                    log("IDE stdin closed (EOF). Stopping proxy.")
                    self.running = False
                    break

                with self.lock:
                    if self.child_process and self.child_process.stdin:
                        try:
                            self.child_process.stdin.write(line)
                            self.child_process.stdin.flush()
                        except Exception as e:
                            log(f"Error writing to child stdin: {e}")
            except Exception as e:
                log(f"Error reading sys.stdin: {e}")
                break

    def forward_stdout(self) -> None:
        """Forwards stdout from child process to IDE."""
        while self.running:
            with self.lock:
                proc = self.child_process

            if not proc or not proc.stdout:
                time.sleep(0.05)
                continue

            try:
                line = proc.stdout.readline()
                if line:
                    sys.stdout.buffer.write(line)
                    sys.stdout.buffer.flush()
                else:
                    time.sleep(0.05)
            except Exception:
                time.sleep(0.05)

    def watch_project(self) -> None:
        """Monitors active project path and triggers hot-swap on change."""
        while self.running:
            time.sleep(3)
            if not self.running:
                break

            if self.ide_pid > 0 and not is_process_running(self.ide_pid):
                log(f"IDE PID {self.ide_pid} exited. Stopping proxy.")
                self.running = False
                break

            active_path = get_active_project_path(self.ide_pid)
            if active_path and active_path != self.current_project_path:
                log(f"Project change detected: '{self.current_project_path}' -> '{active_path}'")
                self.restart_child(active_path)

    def run(self) -> None:
        """Starts proxy loop and background monitors."""
        initial_path = get_active_project_path(self.ide_pid) or os.path.expanduser("~")
        self.start_child(initial_path)

        t_stdin = threading.Thread(target=self.forward_stdin, daemon=True)
        t_stdout = threading.Thread(target=self.forward_stdout, daemon=True)
        t_watch = threading.Thread(target=self.watch_project, daemon=True)

        t_stdin.start()
        t_stdout.start()
        t_watch.start()

        log(f"Proxy active. IDE PID={self.ide_pid}, initial project='{initial_path}'")

        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            log("Proxy interrupted by signal.")
        finally:
            self.running = False
            self.stop_child()
            log("Proxy shutdown complete.")


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(1)

    ide_pid = int(sys.argv[1])
    server_args = sys.argv[2:] if len(sys.argv) > 2 else ["serve"]

    proxy = StdioProxy(ide_pid, server_args)
    proxy.run()


if __name__ == "__main__":
    main()
