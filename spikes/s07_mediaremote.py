"""Spike s07 (design item 7): is MediaRemote usable from a plain process? Record only; the design avoids it."""

import ctypes
import platform
import subprocess
import threading

print(
    "macOS",
    platform.mac_ver()[0],
    subprocess.run(["sw_vers", "-buildVersion"], capture_output=True, text=True).stdout.strip(),
)
lib = ctypes.cdll.LoadLibrary("/System/Library/PrivateFrameworks/MediaRemote.framework/MediaRemote")
print("framework loaded:", bool(lib))
print("MRMediaRemoteGetNowPlayingInfo symbol:", hasattr(lib, "MRMediaRemoteGetNowPlayingInfo"))

import Foundation  # noqa: E402 - pyobjc, after the ctypes check
import objc  # noqa: E402

done = threading.Event()
result: dict[str, object] = {}
bundle = Foundation.NSBundle.bundleWithPath_("/System/Library/PrivateFrameworks/MediaRemote.framework")
funcs: dict[str, object] = {}
objc.loadBundleFunctions(bundle, funcs, [("MRMediaRemoteGetNowPlayingInfo", b"v@?")])
fn = funcs.get("MRMediaRemoteGetNowPlayingInfo")
if fn is None:
    print("RESULT function not loadable")
else:

    def callback(info: object) -> None:
        result["info"] = info
        done.set()

    queue = Foundation.NSOperationQueue.mainQueue()
    try:
        fn(queue, callback)  # type: ignore[operator]
    except TypeError as err:
        print("call signature mismatch:", err)
    Foundation.NSRunLoop.currentRunLoop().runUntilDate_(Foundation.NSDate.dateWithTimeIntervalSinceNow_(3))
    info = result.get("info")
    keys = sorted(str(k) for k in info) if info else []
    print(f"RESULT {'data' if keys else 'denied or empty'}: {len(keys)} keys {keys[:4]}")
