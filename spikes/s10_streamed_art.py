"""Spike s10: artwork bytes for the current track (streamed or library) via ScriptingBridge, decoded by Pillow."""

import io
import time

import ScriptingBridge
from PIL import Image

app = ScriptingBridge.SBApplication.applicationWithBundleIdentifier_("com.apple.Music")
track = app.currentTrack()
print(f"track {track.name()!r} class {track.className()} cloud status {track.cloudStatus()}")
t0 = time.time()
arts = track.artworks()
# rawData() is an SBObject; .get() resolves it to an NSAppleEventDescriptor whose .data() is the bytes (R4).
data = bytes(arts[0].rawData().get().data()) if len(arts) else b""
ms = (time.time() - t0) * 1000
print(f"artworks {len(arts)}, rawData {len(data)} bytes in {ms:.0f} ms, magic {data[:4].hex()}")
image = Image.open(io.BytesIO(data)) if data else None
if image:
    image.load()
    print(f"decoded {image.format} {image.size}")
print(f"RESULT {'PASS' if image else 'FAIL (no artwork bytes)'}")
