"""Spike s03 (design item 3): does Music post com.apple.Music.playerInfo, and how fast?

Listens for 40 s and logs every notification with its delay from start. Press play/pause and
skip in Music (or on the keyboard) while it runs.
"""

import time

import Foundation
from PyObjCTools import AppHelper

START = time.time()
events: list[float] = []


class Observer(Foundation.NSObject):
    def info_(self, note: object) -> None:
        info = note.userInfo()  # type: ignore[attr-defined]
        events.append(time.time())
        osa_state = (
            __import__("subprocess")
            .run(
                ["/usr/bin/osascript", "-e", 'tell application "Music" to get player state'],
                capture_output=True,
                text=True,
            )
            .stdout.strip()
        )
        print(
            f"+{time.time() - START:5.1f}s {info.get('Player State')!s:8} {info.get('Name')!s} (Music: {osa_state})",
            flush=True,
        )


obs = Observer.new()
Foundation.NSDistributedNotificationCenter.defaultCenter().addObserver_selector_name_object_(
    obs, "info:", "com.apple.Music.playerInfo", None
)
print("listening 40 s: press play/pause and skip in Music", flush=True)


def stop(_timer: object) -> None:
    AppHelper.stopEventLoop()


Foundation.NSTimer.scheduledTimerWithTimeInterval_repeats_block_(40, False, stop)
AppHelper.runConsoleEventLoop(installInterrupt=True)
print(f"RESULT {len(events)} playerInfo events", flush=True)
