"""The Cocoa run-loop thread: macOS wake notifications (and, from P5, Music's playerInfo).

This is the only daemon module that imports pyobjc. pyobjc ships no type stubs and builds its
modules at run time, so members are reached through the module objects (docs/music.md section 3).
"""

import logging
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)


def start(on_wake: Callable[[], None], on_sleep: Callable[[], None], on_music: Callable[[], None]) -> None:
    """on_sleep before macOS sleeps (must return quickly), on_wake after it wakes, on_music on each
    com.apple.Music.playerInfo notification (spike s03: arrives within ~0.1 s of a change)."""

    def loop() -> None:
        import AppKit  # pyobjc: dynamic module, no stubs; members are looked up at run time
        import Foundation
        from PyObjCTools import AppHelper

        NSObject = Foundation.NSObject

        def guard(what: str, fn: Callable[[], None]) -> None:
            # Never let an exception escape into the Objective-C runtime: it would end this thread and
            # with it sleep/wake and music events (infodisp 1b0d05f).
            try:
                fn()
            except Exception:
                log.exception("%s callback failed", what)

        class Observer(NSObject):
            def woke_(self, _note: object) -> None:
                log.info("wake")
                guard("wake", on_wake)

            def willSleep_(self, _note: object) -> None:
                log.info("sleep")
                guard("sleep", on_sleep)

            def music_(self, _note: object) -> None:
                guard("music", on_music)

        observer = Observer.new()
        center = AppKit.NSWorkspace.sharedWorkspace().notificationCenter()
        center.addObserver_selector_name_object_(observer, "woke:", AppKit.NSWorkspaceDidWakeNotification, None)
        center.addObserver_selector_name_object_(observer, "willSleep:", AppKit.NSWorkspaceWillSleepNotification, None)
        Foundation.NSDistributedNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            observer, "music:", "com.apple.Music.playerInfo", None
        )
        AppHelper.runConsoleEventLoop(installInterrupt=False)

    threading.Thread(target=loop, name="cocoa", daemon=True).start()
