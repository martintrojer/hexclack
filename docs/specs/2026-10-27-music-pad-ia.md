# Music pad IA and dynamic library browse

## Problem

The Music top page hardcodes Now / Club / Work playlist keys. Exploration of Apple curated and personal saved playlists is limited; the Stream Deck Mini only has five content slots after Home.

## Approach

Reshape Music home to **Bot / Stations / Saved / Favourites / Explore**. Favourites are a config whitelist of subscription playlist names (ephemeral paged list). Explore and Saved share folder-based browse: top-level Music folders, blacklist-only filtering, Any = random in pool, category = random in folder. No MusicKit, no `stale` ranking on the deck.

**Why:** one-tap favourites preserve muscle memory; explore/saved avoid maintaining hundreds of keys; blacklists scale better than whitelists for discovery.

## Scope

**In**

- Music page IA in fixtures/docs; private configs migrate favourites lists.
- `[music.curated]` favourites + explore blacklists; `[music.saved]` blacklists.
- `favourites` music action → ephemeral playlist list (plain titles).
- Generalize Bot list ephemeral chrome for plain names and category browse.
- `explore` with `source = curated|saved` → category page (Home, Any, folders, Next).
- Random play in group (shuffle off); busy-dim only.
- CLI `sd-music explore curated|saved` for debugging.
- Tests with mocked AppleScript.

**Out**

- MusicKit / catalog search; deck `stale` ranking; Saved favourites whitelist; curator trigger; nested folder drill-down; listing every playlist inside a category on a second page.

## Key decisions

| Decision | Choice | Why |
| --- | --- | --- |
| Top slots | Bot, Stations, Saved, Favourites, Explore | Five content keys; curated split into favourites vs explore |
| Favourites | Whitelist in config, ephemeral page | Replaces Now/Club/Work key tables |
| Explore grain | Top-level folder | Fits Mini paging; full paths were ~22 categories |
| Filters | Blacklist folders/names (+ baked-in defaults) | Avoid playlist whitelists for discovery |
| Saved v1 | Explore only; blacklist `Bot` | Bot pad stays exclusive |
| Play | Random playlist in group, shuffle off | Stupid and fast; list-in-category later if needed |
| Wait UX | Existing busy-dim | ~10s query is acceptable |

## Implementation checklist

1. Spec (this file) + config schema for curated/saved.
2. Generalize ephemeral playlist list; favourites action + layout stubs.
3. Browse helpers + AppleScript folder listing; explore curated/saved; category ephemeral UI.
4. Docs (`music.md`, `config.md`) and tests.
