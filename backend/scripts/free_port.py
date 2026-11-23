"""지정 포트를 LISTEN 중인 프로세스 종료 (Windows/macOS/Linux)."""
from __future__ import annotations

import os
import subprocess
import sys


def pids_on_port(port: int) -> list[int]:
    pids: set[int] = set()
    if sys.platform == "win32":
        try:
            out = subprocess.check_output(["netstat", "-ano"], text=True, encoding="utf-8", errors="replace")
        except Exception:
            return []
        needle = f":{port}"
        for line in out.splitlines():
            if "LISTENING" not in line or needle not in line:
                continue
            parts = line.split()
            if parts and parts[-1].isdigit():
                pids.add(int(parts[-1]))
    else:
        # macOS / Linux
        try:
            # lsof -t -i :<port> returns only PIDs
            out = subprocess.check_output(["lsof", "-t", "-i", f":{port}"], text=True)
            for line in out.splitlines():
                if line.strip().isdigit():
                    pids.add(int(line.strip()))
        except subprocess.CalledProcessError:
            # lsof returns non-zero code if no process is found on the port
            pass
        except Exception:
            pass
    return sorted(pids)


def kill_pids(pids: list[int]) -> list[int]:
    killed: list[int] = []
    for pid in pids:
        if pid <= 0:
            continue
        try:
            if sys.platform == "win32":
                r = subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, text=True)
                if r.returncode == 0:
                    killed.append(pid)
            else:
                # macOS / Linux
                os.kill(pid, 9)
                killed.append(pid)
        except Exception:
            pass
    return killed


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    pids = pids_on_port(port)
    if not pids:
        print(f"port {port}: free")
        return 0
    killed = kill_pids(pids)
    print(f"port {port}: stopped PIDs {killed or pids}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
