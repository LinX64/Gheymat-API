import datetime
import json
import os
import subprocess
import sys
import time

import window

WORKFLOW = "gheymat-latest.yml"
ACTIVE_WITHIN = 600


def gh(argv):
    result = subprocess.run(["gh", *argv], capture_output=True, text=True, timeout=60)
    return result.returncode, result.stdout


def active_runs(runs, now):
    count = 0
    for run in runs:
        if run.get("status") == "completed":
            continue
        created = datetime.datetime.fromisoformat(run["createdAt"].replace("Z", "+00:00")).timestamp()
        if now - created < ACTIVE_WITHIN:
            count += 1
    return count


def main(environ=None, now=None, run=gh):
    environ = os.environ if environ is None else environ
    now = time.time() if now is None else now
    if not window.is_open(environ, now):
        print("Outside publishing hours")
        return 0
    code, output = run(["run", "list", "--workflow", WORKFLOW, "--limit", "20", "--json", "status,createdAt"])
    if code != 0:
        print("Could not list runs")
        return 1
    if active_runs(json.loads(output or "[]"), now):
        print("A publish run is active")
        return 0
    print("No publish run is active, starting one")
    code, _ = run(["workflow", "run", WORKFLOW, "--ref", "master"])
    return 0 if code == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
