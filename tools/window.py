import os
import sys
import time

import cadence


def is_open(environ, now):
    if environ.get("GHEYMAT_HOURS", "on") == "off":
        return True
    return cadence.in_window(now)


def main(environ=None, now=None, out=None):
    environ = os.environ if environ is None else environ
    now = time.time() if now is None else now
    out = sys.stdout if out is None else out
    state = is_open(environ, now)
    path = environ.get("GITHUB_OUTPUT", "")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"open={'true' if state else 'false'}\n")
    if not state:
        print("Outside publishing hours", file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
