# Bot category playlist list (ephemeral)

## Problem

Bot category keys only expose `latest` (tap) and category `shuffle` (hold). Older dated drops in `Bot/<category>` exist in Music but are not reachable from the deck without leaving hexclack. The library changes ad hoc (another agent creates playlists); there is no reliable hook to regenerate static deck keys.

## Approach

Keep one-press latest/shuffle on the category key. Add **double-tap → open an ephemeral list** built by querying Music at open time. No on-disk list, no generated TOML, no playlist creation inside hexclack.

**Why ephemeral:** the set changes outside hexclack. A cache or generated file brings stale timestamps and refresh policy for little gain when we already accept AppleScript latency on other music actions.

## Scope

**In**

- Category key gestures: tap = latest, hold = shuffle, double = open list.
- On double: list dated playlists for that category (existing name + `YYYY Month D` suffix), newest first; show an in-memory folder; play a chosen playlist by exact name.
- Home at `0,0` (existing global home). Next only when more playlists remain than free slots; prefer hiding Next on the last page so the slot can be a playlist.
- Busy/error behaviour follows existing music actions (dim key, worker, error flash; stay on Bot on failure).
- Labels from the date suffix for readability; full name for playback.
- Unit + deck tests with mocked AppleScript.

**Out**

- Creating or refreshing Bot playlists in Music.
- Deck button to trigger the external curator agent.
- Disk cache, generated config, Refresh key, Shuffle on the list page, parent Back, Prev.
- Changing how Bot categories appear on the Bot pad (still static layout).
- Live Music in `make gate`.

## Key decisions

| Decision | Choice | Why |
| --- | --- | --- |
| Primary gestures | tap latest / hold shuffle unchanged | Common case stays one gesture; archive is additive |
| Open list | double-tap | Fits existing gesture set; ~300ms tap delay accepted (same as Skip) |
| List source | Query Music every open | Ad hoc creation; avoids stale files |
| Persistence | Ephemeral runtime state only | No timestamps/cache invalidation |
| List chrome | Home + playlists (+ Next if needed) | Shuffle stays on category hold; no Refresh if we re-query every open |
| Play action | Existing `playlist` by full name | No new bot mode |
| Loading UX | Current patterns only | Pauses already normal for Music; no spinner/placeholder screen |
| Overflow | Next, no Prev | Home exits; reopen for a fresh query; YAGNI Prev |
| Naming | Existing dated suffix | Same parser as `latest` |

## Open questions

None. Label format is `2026 Oct 2` (year included). Names ending in `Month D` without a year are renamed in Music to insert the year.

## Implementation checklist

1. List + sort + page-slice helpers (reuse/extend `playlist_date` / listing AppleScript).
2. Ephemeral screen state on the deck (category, names, page); clear on Home / leave.
3. Wire category `double` → list action → navigate when ready; failures flash like other music errors.
4. Render list keys (date labels, Next when needed); play via `playlist` name.
5. Update private/fixture Bot keys with double gesture; docs (`music.md` / `config.md`) for the gesture and ephemeral list.
6. Tests: pure paging/sort; deck double/Home/Next/play; mocked osascript.
