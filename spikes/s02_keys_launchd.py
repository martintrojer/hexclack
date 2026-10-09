"""Spike s02 (design.md section 9 item 2): do key events arrive, in a terminal and under launchd?

Logs every key-down and key-up to spikes/s02.log (and stdout) for 45 s, then exits.
Each key shows its index so you know which one to press.
"""

import sys
import time
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.ImageHelpers import PILHelper

LOG = Path(__file__).parent / "s02.log"
SECONDS = 45
mode = sys.argv[1] if len(sys.argv) > 1 else "terminal"


def log(msg: str) -> None:
    line = f"{datetime.now():%H:%M:%S.%f} [{mode}] {msg}"
    print(line, flush=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


decks = [d for d in DeviceManager().enumerate() if d.product_id() == 0x90]
if not decks:
    log("FAIL no Mini")
    sys.exit(1)
deck = decks[0]
deck.open()
font = ImageFont.truetype("/System/Library/Fonts/HelveticaNeue.ttc", 36, index=1)
for k in range(deck.key_count()):
    img = Image.new("RGB", (80, 80), "navy")
    ImageDraw.Draw(img).text((40, 40), str(k), font=font, fill="white", anchor="mm")
    deck.set_key_image(k, PILHelper.to_native_key_format(deck, img))
seen: set[tuple[int, bool]] = set()
deck.set_key_callback(
    lambda _d, key, pressed: (seen.add((key, pressed)), log(f"key {key} {'down' if pressed else 'up'}"))
)
log(f"ready: press each of the {deck.key_count()} keys once ({SECONDS} s)")
end = time.time() + SECONDS
while time.time() < end and len(seen) < 2 * deck.key_count():
    time.sleep(0.1)
log(f"RESULT {len({k for k, _ in seen})}/{deck.key_count()} keys seen, {len(seen)} down/up events")
deck.reset()
deck.close()
