# Architecture

hexclack owns one Stream Deck Mini directly through the Python StreamDeck library. The Elgato application must not own the same device.

## Execution

- The device owner serializes USB reads and writes. Gestures and navigation are handled by the deck state machine.
- A small worker pool runs shell, AppleScript, HTTP and music actions off the device thread. Duplicate presses of an in-flight key are dropped.
- Widget pollers publish events to a dispatcher. Each widget subscribes to its own event source and redraws only when its display changes.
- The watchdog detects disconnected or wedged devices, retries with backoff and notifies the user when a replug is needed.
- Idle state changes from keys to a clock screen saver and then screen-off. Optional ambient-light readings control backlight brightness; errors fall back to the configured brightness.

## Configuration and privacy

[config.md](config.md) describes the TOML schema. Loading rejects unknown fields, invalid types and dangling references. Icon paths are relative to the config directory. Personal station aliases resolve to URLs while loading the config, so action workers use the selected config without mutable global account state.

The default config and user artwork live outside the checkout. Pi-hole passwords are retrieved from Keychain; authenticated sessions are reused per host. Publishing an example with placeholders is not a way to protect a real credential: never commit secrets, and rotate any that have been exposed.

## Music

The [music module](music.md) is shared by deck actions and the `sd-music` CLI. GUI/USB dependencies are loaded only where needed. Music automation must not launch the application just to poll its state. Event bursts are debounced and delayed reads correct transient state after a transport action.

## Rendering

Key images are 80×80 RGB. Static tiles are cached by their specification, size and renderer version. Next/previous/shuffle symbols are drawn with Pillow, without vendored artwork. User-supplied icon files and live album artwork are loaded at runtime, not shipped in the repository.

## Operation

A macOS LaunchAgent runs the daemon with logs in `~/Library/Logs/hexclack/`. A single-instance lock prevents competing daemon processes. Neither launchd nor the watchdog can guarantee recovery from a firmware wedge: unplugging/replugging may be required.

`make gate` runs formatting, lint, type checks and tests. USB, launchd and Music automation still need manual checks on macOS with the actual hardware.
