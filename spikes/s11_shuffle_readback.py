"""Spike s11: does toggling `shuffle enabled` read back correctly? Restores the original value."""

import subprocess
import time


def osa(script: str) -> str:
    return subprocess.run(
        ["/usr/bin/osascript", "-e", script], capture_output=True, text=True, check=False
    ).stdout.strip()


get = 'tell application "Music" to get shuffle enabled'
toggle = 'tell application "Music" to set shuffle enabled to not shuffle enabled'
values = [osa(get)]
for _ in range(2):
    osa(toggle)
    values.append(osa(get))  # immediate read
    time.sleep(1)
    values.append(osa(get))  # read after 1 s
print(f"start | toggle 1: now, +1s | toggle 2: now, +1s -> {values}")
ok = values[0] != values[2] and values[4] == values[0]
immediate = values[1] == values[2] and values[3] == values[4]
print(f"read-back {'immediate' if immediate else 'LAGS (only correct after a delay)'}")
print(f"RESULT {'PASS' if ok else 'FAIL'}")
