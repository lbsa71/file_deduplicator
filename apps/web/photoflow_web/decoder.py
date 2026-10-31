"""Apply process limits before starting an untrusted media decoder."""

import os
import resource
import sys
import signal
import subprocess
import time


def configure_limits(platform=sys.platform):
    limits = [(resource.RLIMIT_CPU, 60), (resource.RLIMIT_FSIZE, 16 * 1024**2),
              (resource.RLIMIT_NOFILE, 64)]
    # Darwin rejects RLIMIT_AS. Its RSS limit is advisory, so supervise resident
    # memory below instead of silently running an unbounded decoder.
    if platform != "darwin":
        limits.append((resource.RLIMIT_AS, 512 * 1024**2))
    for kind, maximum in limits:
        _, hard = resource.getrlimit(kind)
        limit = maximum if hard == resource.RLIM_INFINITY else min(maximum, hard)
        resource.setrlimit(kind, (limit, limit))
    os.environ["VIPS_CONCURRENCY"] = "1"


def tree_memory(snapshot, root):
    rows = [tuple(map(int, line.split())) for line in snapshot.splitlines() if line.strip()]
    if any(len(row) != 3 or row[2] < 0 for row in rows):
        raise ValueError("Invalid decoder process accounting")
    descendants = {root}
    while True:
        found = {pid for pid, parent, _ in rows if parent in descendants}
        if found <= descendants:
            break
        descendants.update(found)
    return sum(rss * 1024 for pid, _, rss in rows if pid in descendants)


def supervise(command, memory_limit=512 * 1024**2, timeout=25):
    process = subprocess.Popen(command, start_new_session=True)
    deadline = time.monotonic() + timeout
    try:
        while process.poll() is None:
            snapshot = subprocess.run(["/bin/ps", "-axo", "pid=,ppid=,rss="],
                                      check=True, capture_output=True, text=True, timeout=2)
            if tree_memory(snapshot.stdout, process.pid) > memory_limit:
                return 137
            if time.monotonic() >= deadline:
                return 124
            try:
                process.wait(timeout=0.05)
            except subprocess.TimeoutExpired:
                pass
        return process.returncode if process.returncode >= 0 else 128 - process.returncode
    finally:
        # Include descendants even if their parent exited or exceeded a budget.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


def main():
    configure_limits()
    command = sys.argv[1:]
    if not command:
        raise ValueError("A decoder command is required")
    if sys.platform == "darwin":
        video = os.path.basename(command[0]) == "ffmpeg"
        sys.exit(supervise(command, timeout=55 if video else 25))
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
