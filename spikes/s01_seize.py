"""Spike s01 (design.md section 9 item 1): can hexclack open the Mini while the Elgato app runs?

Run it twice: once with the Elgato app running, once after `pkill -x "Stream Deck"`.
It opens the Mini, paints key 0 red for 2 s, reads the firmware version, and closes. It never
writes anything to the profile and only touches key 0.
"""

import subprocess
import sys
import time

from PIL import Image
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.ImageHelpers import PILHelper

elgato = subprocess.run(["pgrep", "-x", "Stream Deck"], capture_output=True).returncode == 0
print(f"Elgato app running: {elgato}")
decks = [d for d in DeviceManager().enumerate() if d.product_id() == 0x90]
print(f"Minis enumerated: {len(decks)}")
if not decks:
    sys.exit("FAIL: no Mini found")
deck = decks[0]
try:
    deck.open()
except Exception as err:
    sys.exit(f"RESULT open failed: {type(err).__name__}: {err}")
try:
    print(f"serial {deck.get_serial_number()!r} firmware {deck.get_firmware_version()!r}")
    deck.set_key_image(0, PILHelper.to_native_key_format(deck, Image.new("RGB", (80, 80), "red")))
    print("key 0 painted red: look at the top-left key now")
    time.sleep(2)
    print("RESULT open+draw+read ok")
finally:
    deck.close()
