# Public release

## Decisions

- Use the existing private `~/.config/hexclack/config.toml`, rather than adding template interpolation or overlays. Hosts and recipients are already configurable; only station URLs need a new schema.
- Add optional `[music.stations]`, mapping aliases to full HTTPS Apple Music URLs. Both daemon and CLI use the chosen config. No personal IDs are shipped.
- Publish a small generic starter, with a synthetic full-layout test fixture preserving navigation and gesture coverage.
- Retain Martin Trojer's name and email in package metadata, as explicitly requested.
- Remove copied artwork and plugin PNGs from the public tree. Preserve originals privately and draw transport symbols with Pillow; no new dependency.
- License the project's own code and synthetic assets under MIT.
- Replace private migration/soak/probe notes with current public documentation.
- Verify the public tree before creating one new root commit. Keep a private old-history backup outside the repository. No push until the owner deletes/recreates the GitHub repository.

## Verification

Run `make gate`, validate/render both example and migrated private config, build the distributable and inspect its contents, and independently review the candidate public tree for personal data and copied assets. Hardware and Music playback are not proven by offline tests.

## History boundary

The public initial commit must have no parent and no old refs/history in the new local Git database. Do not use an orphan branch alone while retaining old local refs. Initialize fresh metadata after backing up the old database and finishing delegated work. Push is explicitly out of scope until the recreated remote is ready.
