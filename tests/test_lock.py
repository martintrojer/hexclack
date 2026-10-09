"""Single instance. If the lock-held path touched state.json it could reset hang_exits and defeat the
restart-loop rule; if it exited 0, launchd would never retry and the deck would stay dead."""

import fcntl
import os
import subprocess
import sys
from pathlib import Path

LOCK_HELD_EXIT = 75


def run_hexclack(home: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "HOME": str(home)}
    return subprocess.run(
        [sys.executable, "-m", "hexclack", "run", "--config", str(home / "missing.toml")],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def support(home: Path) -> Path:
    path = home / "Library/Application Support/hexclack"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_lock_held_exits_75_without_touching_state(tmp_path: Path) -> None:
    state = support(tmp_path) / "state.json"
    state.write_text('{"hang_exits": 2, "last_exit": "2026-10-05T09:00:00+00:00", "state": "WEDGED"}')
    before = (state.read_bytes(), state.stat().st_mtime_ns)
    with (support(tmp_path) / "lock").open("a+") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        held.write("4242")
        held.flush()
        result = run_hexclack(tmp_path)
    assert result.returncode == LOCK_HELD_EXIT
    assert "already running (pid 4242)" in result.stderr
    assert (state.read_bytes(), state.stat().st_mtime_ns) == before


def test_lock_released_when_the_holder_exits(tmp_path: Path) -> None:
    # Nothing holds the lock: run gets past it and stops at the missing config (exit 1, not 75).
    result = run_hexclack(tmp_path)
    assert result.returncode == 1 and "missing.toml" in result.stderr
    assert (support(tmp_path) / "lock").exists()
