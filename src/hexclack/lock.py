"""Single instance (docs/design.md section 3): an exclusive flock taken before anything else.

Taken before reading state.json, posting a notification or touching the device. If another
hexclack holds it, exit 75 (EX_TEMPFAIL): launchd's KeepAlive (SuccessfulExit=false) retries
every ThrottleInterval, so the agent takes over once a foreground `hexclack run` exits, and the
lock still prevents two device owners. 75 is distinct from the hang exit 70 and never touches
hang_exits.
"""

import fcntl
import os
import sys
from pathlib import Path
from typing import IO

LOCK_FILE = Path.home() / "Library/Application Support/hexclack/lock"
LOCK_HELD_EXIT = 75  # EX_TEMPFAIL

_held: IO[str] | None = None  # kept open for the life of the process; closing it releases the lock


def acquire(path: Path = LOCK_FILE) -> None:
    """Take the lock or exit 75. Prints one line when held (one log line per launchd retry)."""
    global _held
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.seek(0)
        pid = handle.read().strip() or "?"
        print(f"hexclack is already running (pid {pid})", file=sys.stderr)
        sys.exit(LOCK_HELD_EXIT)
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    _held = handle
