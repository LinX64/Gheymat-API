import os
import subprocess
import sys
import time

import cadence
import window

WORKFLOW = "gheymat-latest.yml"
MAX_SLEEP = 230
EARLY = 0
LATE = 20


def gh(argv):
    return subprocess.run(["gh", *argv], capture_output=True, text=True, timeout=60).returncode


def main(environ=None, now=None, sleep=time.sleep, run=gh):
    environ = os.environ if environ is None else environ
    now = time.time() if now is None else now
    if environ.get("GITHUB_REF") != "refs/heads/master":
        return 0
    if window.is_open(environ, now):
        wait = 0
    else:
        wait = min(max(0, cadence.next_open(now) - now + LATE), MAX_SLEEP)
    if wait:
        print(f"Outside publishing hours, waiting {int(wait)} seconds")
        sleep(wait)
    code = run(["workflow", "run", WORKFLOW, "--ref", "master"])
    return 0 if code == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
