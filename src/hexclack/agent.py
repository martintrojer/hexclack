"""The macOS LaunchAgent. plistlib builds the file, so it is always valid XML."""

import os
import plistlib
import subprocess
from pathlib import Path

LABEL = "com.hexclack"
THROTTLE_S = 30  # launchd waits this long between restarts: the lock-held (75) and hang (70) exits rely on it


def plist_path(home: Path) -> Path:
    return home / "Library/LaunchAgents" / f"{LABEL}.plist"


def log_path(home: Path) -> Path:
    return home / "Library/Logs/hexclack/hexclack.log"


def plist(home: Path, executable: Path) -> bytes:
    log = str(log_path(home))
    return plistlib.dumps(
        {
            "Label": LABEL,
            "ProgramArguments": [str(executable), "run"],
            # launchd has no Homebrew environment; without this the streamdeck library cannot find
            # libhidapi.dylib (spike s02: ProbeError under launchd until this was set).
            "EnvironmentVariables": {"HOMEBREW_PREFIX": "/opt/homebrew"},
            "RunAtLoad": True,
            # Restart on a non-zero exit only: 70 (hung call) and 75 (lock held) retry, a clean stop does not.
            "KeepAlive": {"SuccessfulExit": False},
            "ThrottleInterval": THROTTLE_S,
            "StandardOutPath": log,
            "StandardErrorPath": log,
        }
    )


def _launchctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["/bin/launchctl", *args], capture_output=True, text=True, check=False)


def install(home: Path | None = None, executable: Path | None = None) -> Path:
    home = home or Path.home()
    exe = executable or home / ".local/bin/hexclack"
    if not exe.exists():
        raise FileNotFoundError(f"{exe} not found: run `uv tool install --editable .` from the checkout first")
    log_path(home).parent.mkdir(parents=True, exist_ok=True)
    path = plist_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plist(home, exe))
    domain = f"gui/{os.getuid()}"
    _launchctl("bootout", f"{domain}/{LABEL}")  # reinstall: replace a loaded agent, ignore "not loaded"
    result = _launchctl("bootstrap", domain, str(path))
    if result.returncode != 0:
        raise RuntimeError(f"launchctl bootstrap failed: {result.stderr.strip()}")
    return path


def uninstall(home: Path | None = None) -> None:
    home = home or Path.home()
    _launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
    plist_path(home).unlink(missing_ok=True)
