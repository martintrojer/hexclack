"""The LaunchAgent plist. A wrong KeepAlive restart-loops or never restarts; a missing HOMEBREW_PREFIX
leaves the agent unable to load hidapi (spike s02). Both fail with nothing on the deck."""

import plistlib
import subprocess
from pathlib import Path

from hexclack import agent


def test_plist_is_valid_and_has_the_migration_keys(tmp_path: Path) -> None:
    raw = agent.plist(Path("/Users/someone"), Path("/Users/someone/.local/bin/hexclack"))
    path = tmp_path / "com.hexclack.plist"
    path.write_bytes(raw)
    lint = subprocess.run(["/usr/bin/plutil", "-lint", str(path)], capture_output=True, text=True, check=False)
    assert lint.returncode == 0, lint.stdout
    p = plistlib.loads(raw)
    assert p["Label"] == "com.hexclack"
    assert p["ProgramArguments"] == ["/Users/someone/.local/bin/hexclack", "run"]
    assert p["KeepAlive"] == {"SuccessfulExit": False}
    assert p["ThrottleInterval"] == 30
    assert p["RunAtLoad"] is True
    assert p["EnvironmentVariables"]["HOMEBREW_PREFIX"] == "/opt/homebrew"
    assert p["StandardOutPath"] == p["StandardErrorPath"] == "/Users/someone/Library/Logs/hexclack/hexclack.log"


def test_paths_come_from_home_not_a_literal() -> None:
    raw = agent.plist(Path("/Users/other"), Path("/x/hexclack"))
    assert b"private-user" not in raw
