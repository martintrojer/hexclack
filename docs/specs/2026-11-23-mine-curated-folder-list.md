# Mine/Curated folder playlist list (double-tap)

## Problem

Mine and Curated page top-level folders with one random pick per folder. Older or non-picked playlists in a folder are unreachable without leaving hexclack and reopening for a new roll. Folder paging already exists; the missing piece is listing every playlist inside a chosen folder.

## Approach

Keep tap = play the pick. Add **double-tap on a category key → replace the category page with an ephemeral playlist list** built from the groups already loaded in the category session. No second Music query, no stack/Back.

**Why:** matches Bot (tap play / double list); data is already in memory for picks; replace keeps Home one-shot and avoids ephemeral nesting. Re-open Mine/Curated for another folder or a fresh roll.

## Scope

**In**

- Category keys: `gestures` with tap = play pick (name+folder), double = `nav` `{ ephemeral_category = "<cat>" }` that opens that folder’s playlist list from `category_list.groups`.
- List chrome: existing Favourites-style playlist list (Home, plain titles, Next when needed; no Prev, no dated rows, no shuffled colors).
- Play from the list with `name` + `folder` (extend `PlaylistEntry` with optional `folder`).
- Sort playlists alphabetically by name.
- Any: tap only (no double). Single-playlist folders still allow double (one-item list).
- Docs (`music.md`) for the gesture.
- Deck tests: double opens list; tap still plays; Home clears; folder on list play actions.

**Out**

- Stacking category page under the list / Back to category.
- Hold on category keys.
- Re-querying Music on double.
- Nested Music folder drill-down beyond top-level categories.
- Changes to Bot list, Favourites, or Any behaviour beyond “no double”.

## Key decisions

| Decision | Choice | Why |
| --- | --- | --- |
| Primary gestures | tap play / double list | Consistent with Bot; additive |
| List source | In-memory session groups | Already loaded; no extra AppleScript |
| Persistence / exit | Replace category session; Home → deck home | Existing `_clear_ephemeral`; one-shot Home |
| List UI | Favourites-style plain titles | Not dated Bot drops |
| Disambiguation | Pass `folder` on list play | Same as category picks |
| Order | Alphabetical by name | Stable; library order unused after grouping |
| Any | Tap only | Pool random, not a folder |

## Open questions

None.

## Implementation checklist

1. Optional `folder` on `PlaylistEntry`; parse from playlist_list payload; `_playlist_list_keys` passes it to play.
2. Category keys use `gestures` (tap play, double `{ ephemeral_category }`); `nav` opens sorted playlist list from session groups then replace.
3. Docs (`music.md`) for Mine/Curated double.
4. Tests: double → list with folders; tap unchanged; Any no double; Home clears.
