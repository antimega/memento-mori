# Maintaining Memento Mori — internals, testing, and gotchas

A precis for whoever works on this next (including future-you). Covers **how the
system works**, **what to test**, and the **gotchas** that were each found the
hard way. README.md is the user-facing guide; this is the maintainer's guide.

---

## 1. What it is

A Python static-site generator that turns an Instagram data export into a
browsable static website. Output is plain HTML + classic `<script>` files +
JSON + generated thumbnails. Design constraints that shape everything:

- **No framework, no build step.** The published site is a folder of HTML and
  classic scripts. It must keep working from a bare filesystem years from now.
- **Works over `file://` and `http://`.** No `fetch`, no ES modules, no dynamic
  import in the published pages — data is loaded via classic `<script>` files
  that assign `window.postData` / `window.storiesData`.
- **Vendored libraries** (Leaflet 1.9.4, marked 12.0.2) under
  `static/vendor/` — no CDN.

---

## 2. Pipeline

Run in Docker (the generator's deps aren't on the host):

```
docker compose run --rm memento-mori --regenerate
```

`docker-compose.yml`: `working_dir: /app/workspace`, `PYTHONPATH=/app`, and a
default `command: --search-dir . --output ./output`. **Any args you pass to
`docker compose run` REPLACE `command:`** — that's why `--regenerate` alone
still finds input/output (the entrypoint has its own defaults). To run Python
directly in the container (e.g. for a one-off check):
`docker compose run --rm --entrypoint python memento-mori <script>.py`.

Stages (`memento_mori/`):

- **`cli.py`** — argparse entrypoint. Flags: `--input`, `--output`,
  `--search-dir`, `--threads`, `--quality`, `--max-dimension`,
  `--thumbnail-size`, `--no-auto-detect`, `--gtag-id`, `--merge`,
  `--city-tags` (defaults to `<output>/city_tags.json`), `--regenerate`,
  `--verbose`/`-v`.
- **`extractor.py`** — locates/unzips the Instagram export.
- **`loader.py`** — parses the Instagram JSON. Handles both the **classic**
  format (`posts_1.json`) and the **new** format (`posts.json` with
  `label_values`, where the venue is keyed by `title: "Place"`, *not* `label`).
  Attaches place/lat/lon to a post when a location record is within ±1s of it;
  coords are rounded to 4dp (~10m, in `_parse_coord`) and `0.0` is rejected.
  Guards
  `if post_entry["t"]:` before `utcfromtimestamp` (new-format entries can lack
  a creation timestamp).
- **`media.py`** — writes thumbnails as `thumbnails/<md5(source_path)>.webp`;
  story thumbnails land under `thumbnails/stories/<md5>.webp` (note the
  subdirectory — see §3, `dm` vs `th`).
- **`merger.py`** — applies `--merge` (folds a new export into an existing
  `output/`), tolerant of missing optional fields.
- **`flickr.py`** — the Flickr importer (`--flickr PATH`, `--flickr-refresh`;
  see §3a). Loader (public-only filter, id-keyed entries), Instagram-dedup,
  API client (one-time sweep, `FLICKR_API_KEY` env only), downloader
  (originals from the CDN URLs in the export metadata; polite/resumable),
  and a media processor subclassing `InstagramMediaProcessor`.
- **`generator.py`** — Jinja2 (autoescape on) renders every page; copies
  `static/**`. Key helpers:
  - `_minify_html` — strips leading indentation and blank lines but **leaves
    single newlines between tags**; protects `<script>/<style>/<textarea>/<pre>`
    and `data-md` blocks verbatim.
  - `_compact_entries` — drops empty optional fields (`pl,tt,im,l,c,la,lo`)
    before serialization; always keeps `i,m,t,d,story_thumb`.
  - `_write_browser_data` — writes `js/posts-data.js` + `js/stories-data.js`
    (see §3). Browser-only enrichment (`th`/`dm`) happens here.
  - `_write_data_json` — writes the `data.json` sidecar (pops `city_tags`).

---

## 3. Data artifacts

| File | Purpose | Browser-loaded? |
|---|---|---|
| `data.json` | full sidecar for `--merge`/`--regenerate`; keeps `story_thumb`; `city_tags` popped out | **No** |
| `js/posts-data.js` | `window.postData = JSON.parse("…")` | Yes (index, timeline, cities) |
| `js/stories-data.js` | `window.storiesData = JSON.parse("…")` | Yes (stories, timeline, cities) |
| `city_tags.json` | human annotations: tags, favourites, per-city coords + Markdown | loaded only into the editor pages as an inline embed |

**The `JSON.parse` trick.** The data files are emitted as
`window.postData = JSON.parse(<a JS string literal>)`, where the string is
`json.dumps(json.dumps(data))` with `</` escaped to `<\/`. Parsing a string
literal is ~2–4× faster than evaluating a multi-MB object literal.

**Entry schema** (keyed by string timestamp):

- Post: `{ i (stable index), m (media paths), t, d (readable date),
  optional pl, tt, im, l, c, la, lo }`
- Story: `{ i, m, t, d, optional tt }` (in `data.json` it also has
  `story_thumb`; see below)

**Browser-only thumbnail fields (`th` / `dm`)** — added by `_write_browser_data`
**only** (never in `data.json`) so the timeline can rebuild a tile's image
client-side without a server `os.path.exists` check:

- `th` = 32-hex md5 when the resolved display image is a standard
  `thumbnails/<md5>.webp` (100% of posts in the reference archive).
- `dm` = the full resolved URL for anything else. **All stories use `dm`**
  because their thumbnail lives at `thumbnails/stories/<md5>.webp`, which the
  `th` pattern (md5 at the root) deliberately doesn't match.
- Client resolver: `th ? "thumbnails/"+th+".webp" : dm ? dm : (isVideo(m[0]) ? SVG : m[0])`.
- `story_thumb` is **stripped from the browser copy** (no JS reads it — `dm`
  already carries its value); it stays in `data.json` for regeneration.
- `vp` = per-video **poster** map `{media_index: "thumbnails/<md5>.webp"}`,
  added to posts that contain video(s) (also browser-only). `modal.js` sets it
  as the `<video poster>` so a still shows before playback (post videos don't
  autoplay). Regenerated by `_write_browser_data`, so a fast `--regenerate`
  refreshes it — no full media re-run needed.

### 3a. Flickr section

`data.json` carries a top-level `"flickr"` key (passed through untouched by
Instagram `--merge`; restored by plain `--regenerate`; re-imported by
`--regenerate --flickr PATH`):

```json
"flickr": { "items": { "<photo_id>": {...} },
            "albums": { "<album_id>": { "t": "title" } },
            "meta":   { "path_alias": "antimega", ... } }
```

- **Entries are keyed by Flickr photo id, NOT timestamp** — 46 public items
  share a `date_taken` second; a ts-keyed dict would silently drop them.
  Deep links are `?photo=<id>`.
- Entry fields: `i` (index, newest-first), `t` (unix, `date_taken` as UTC),
  `d` (readable), `m` — always the actual output file, no sibling-extension
  guessing: `["media/flickr/<id>.webp"]` for images, `<id>.mov/.mp4` for
  videos — and omit-when-empty `tt`
  title, `ds` description (plain text — Flickr HTML flattened at load),
  `tg` tags, `al` album ids, `la`/`lo`, `lic` (omitted when
  "All Rights Reserved"), `vd`:1 video flag, `vu` remote playback URL (only
  videos lacking a local file; the viewer ignores non-stream URLs like the
  Flash-era `stewart.swf` ones). Browser-only in `js/flickr-data.js`
  (~9 MB at 30k items): `th`/`dm`/`vp`, same semantics as Instagram.
- Import scope: own items only (faves have no `photo_<id>.json`), strictly
  `privacy == "public"`. Instagram cross-posts are auto-excluded by
  timestamp match at an empirically calibrated tz offset; exclusions live
  in the user-editable `flickr-download/flickr_exclude.json` with an audit
  trail in `flickr_dedup_report.json` (incl. review-only square candidates).
- Sidecar caches under `flickr-download/` (all gitignored): `flickr_api_cache.json`
  (the one-time API sweep — the ONLY source of video identification),
  `originals-cache/` (downloaded originals), `download_failures.json`
  (permanent 404s only — throttling is never recorded as permanent).
- Media parts are accepted as extracted `data-download-*` folders OR raw
  `data-download-*.zip` files. Zip members are indexed in place and only the
  imported (public, non-deduped) items are extracted — into `originals-cache/
  <id>.<ext>`, so the rest of the pipeline only ever sees real Paths. Folder
  files win over zip members for the same id.

**`city_tags.json` shape:**
```json
{ "version": 1,
  "posts":   { "<ts>": "City" },
  "stories": { "<ts>": "City" },
  "cities":  { "City": { "lat": 0.0, "lng": 0.0, "text": "**Markdown**" } },
  "favorites": { "posts": { "<ts>": true }, "stories": {} } }
```

---

## 4. Pages — how each is built and how it renders

All pages: server-rendered semantic HTML, deferred data scripts, viewers opened
by **index**, deep links via `?post=`/`?story=`, UTC date basis throughout.

- **`index.html`** — posts grid. Server-renders **all** post tiles (via
  `grid.html`). Loads `posts-data.js` + `modal.js` + vendored Leaflet (all
  deferred; Leaflet powers the modal's per-post location map). Sort buttons
  (Newest/Oldest/Popular/…) reorder tiles in place. Deep link `?post=TS[&image=N]`.

- **`stories.html`** (from template `stories_page.html`) — stories grid.
  Server-renders **all** story tiles. Loads `stories-data.js` + `stories.js`.
  Deep link `?story=TS`. (Note: `templates/stories.html` exists but is **not**
  used by the generator — the page comes from `stories_page.html`.)

- **`timeline.html`** — the one structurally different page. **Only the newest
  month is server-rendered**; every other month's DOM is built **on demand,
  client-side**, from the already-loaded data. Each day shows three sections:
  posts, stories, then **"Flickr photos and videos (N)"** (flickr tiles carry
  `grid-item timeline-tile flickr-tile`; modal.js's delegation explicitly
  skips `.flickr-tile` so the flickr viewer handles them). With Flickr
  imported the month list extends back to 2001 (~271 months) and the page
  loads `flickr-data.js` (~9 MB) + `flickr-viewer.js` + the flickr viewer
  partial. The `<select>` still lists all months. Deferred head scripts, in
  order: `posts-data`, `stories-data`, [`flickr-data`],
  **`timeline-months`**, `modal`, `stories`, [`flickr-viewer`], `month-nav`,
  `on-this-day`, `leaflet` (for the modal map). Has a
  "Timeline ⇄ On this day" toggle. See §6 — this is the subsystem to understand
  before touching the timeline.

- **`cities.html`** — one city shown at a time (London default; hash
  `#city-slug` written only on user selection). Leaflet map of tagged cities
  (`setTimeout` init, not rAF; `fadeAnimation:false`; `invalidateSize`). Per-city
  Markdown rendered by an inline body script via `marked.parse(el.textContent)`.
  **marked and Leaflet are NOT deferred here** — the inline body script depends
  on `marked` at parse time. Favourited items sort first.

- **`flickr.html`** — the Flickr archive (2001–2019) as an index-style grid.
  Only the first ~60 tiles are server-rendered (30k at once would be ~7 MB);
  `flickr-grid.js` appends the rest in 300-tile batches from
  `js/flickr-data.js` on scroll (IntersectionObserver + an always-on scroll
  listener — IO alone stalls when the sentinel never leaves rootMargin) and
  provides Newest/Oldest/Random sorting. It exposes `window.mmFlickrOrder`
  (the current sort's full id list), which the viewer uses for prev/next so
  navigation spans the whole archive even before tiles are appended. Tiles
  link to the Flickr photopage as the no-JS fallback. The viewer
  (`_flickr_viewer.html` + `flickr-viewer.js`) is a deliberately trimmed
  sibling of modal.js — single-media, no carousel — with the same
  focus-trap/inert/map patterns and own element ids; shows title,
  description (`white-space:pre-line`), tag chips, album links, license (when
  not the default), and a location map. View/fave counts are deliberately
  not imported, and the viewer has no Flickr backlink — the tile `href`
  still points at the photopage as the no-JS fallback. Flickr items ALSO
  appear on the
  timeline (see above); deep links are `?photo=<id>` on both pages.

- **`edit.html` + `edit-cities.html`** — the private tagging/favourites/city-text
  editor. **Loads no data files** — it embeds `window.cityTags` and renders tiles
  server-side (so it's ~4 MB and stays that way; out of scope for the timeline
  rework). State = base tags + a `localStorage` overlay (`MMEditor` in
  `editor-common.js`), exported back to `city_tags.json`. Its month nav persists
  the selected month (`data-store="mm_editor_month"`).

### Client JS model (shared)

- **Event delegation** at the document level (`closest('.grid-item')` /
  `closest('.story-item')`), bound once via a guard flag — sorting/rebuilding
  tiles needs no rebinding.
- **Viewers open by index** (`openModal(i)` / `openStory(i)`). Window hooks let
  other views drive them: `mmOpenPost`, `mmOpenStory`, `mmShowCity`, plus the
  timeline builders `mmBuildMonth`, `mmTiles`, `mmEnsureMonthFor`, `monthKeyOf`.
- **UTC everywhere** (matches Python's `utcfromtimestamp` day grouping).
- **Accessibility**: `inert` on background landmarks while a dialog is open,
  live-query focus traps, `:focus-visible`, skip links, `prefers-reduced-motion`
  handling, `[hidden]{display:none!important}`.
- **Stories do not auto-advance** (changed intentionally). Images and videos
  stay until the user navigates; the progress bar and pause button are hidden
  via CSS. The pause/timer JS still exists in `stories.js` but is inert (its only
  trigger, the pause button, is hidden). Videos play once (`loop=false`).
- **Post modal location map**: `modal.js`'s `updatePostMap` shows a small
  Leaflet map (`#postMap`, above the date) for posts that carry `la`/`lo`
  (~73%); the map instance is created once and reused across posts, hidden for
  posts without coordinates. Tiles come from openstreetmap.org (network needed).

---

## 5. Timeline on-demand months (`timeline-months.js`) — read before editing the timeline

**Why:** server-rendering all ~150 months was ~4.4 MB / ~52k DOM nodes /
~730 ms parse, re-paid on every visit though only one month is ever visible.
Now: newest month server-rendered (paints during parse), rest built on demand.
Result: ~60 KB HTML, ~580 DOM nodes, DOMContentLoaded well under 100 ms.

**Contracts exposed on `window`:**
- `monthKeyOf(ts)` → `"YYYY-MM"` (UTC).
- `mmTiles.post(ts, entry)` / `mmTiles.story(ts, entry)` → one tile element with
  **exact markup parity** to the Jinja tiles in `templates/timeline.html`.
- `mmBuildMonth(key)` → the `[data-month]` panel (existing or freshly built),
  or **`null` for an unknown key** (no ghost months). Inserted in descending
  month order so document order stays chronological.
- `mmEnsureMonthFor(ts)` → build (hidden) the month containing `ts`.

**How the other scripts cooperate:**
- `month-nav.js` re-queries `[data-month]` on **every** `showMonth` (a stale
  NodeList would leave two months visible); builds an absent month via the hook
  if its key is a `<select>` option; deep-links resolve the month by pure UTC
  math (no dependence on a pre-rendered tile). On the editor page the hook is
  absent and all months are present, so it behaves exactly as before.
- `stories.js` `checkUrlForStory` resolves the index from
  `window.storiesData[ts].i` first (the tile may not be built yet).
- `on-this-day.js` builds its tiles from data via `mmTiles`, and calls
  `mmEnsureMonthFor(ts)` **before** opening a viewer (so `openStory`'s live
  `.story-item` query and `navigatePost`'s `.grid-item` walk find the real tile).

**THE maintenance cost — markup dualism.** A tile's markup now lives in **two**
places: the Jinja template (newest month + other pages) and `mmTiles` in JS.
**If you change one, change the other.** The one intentional divergence: the
story tile's `onerror` is a JS property in `mmTiles` (not an attribute), so a
built story tile's `outerHTML` differs from the server's only by that attribute
and by inter-tag whitespace — both harmless. Post tiles are otherwise identical.

---

## 6. CSS notes

- One stylesheet: `static/css/style.css`. No page carries its own `<style>`
  block anymore, and no inline `style="…"` attributes remain except Leaflet's
  own runtime styles and one JS-toggled `display:none` on the story play icon.
- Story styling is a **single source of truth**: a shared `.story-item` base;
  the timeline/cities story tiles layer `.timeline-story-tile` on top; the
  stories-page grid tiles use scoped `.stories-grid .story-item` /
  `.story-media` overrides. (There used to be three drifting copies — that drift
  once shipped a real bug.)
- The **profile picture has been removed** everywhere (headers + modal avatar);
  its CSS, the `postUserPic` lookup, and the generator's `profile_picture`
  resolution are all gone. The picture file is still copied into `output/` by
  the media pipeline but is never referenced.

---

## 7. What to test (regeneration → serve `output/` over http AND check file://)

Regenerate, then `python3 -m http.server` in `output/`. The in-app browser pane
caches assets aggressively — **serve on a fresh port** (or cache-bust) after a
CSS/JS change or you'll test stale files.

**Artifacts.** `timeline.html` ≤ ~150 KB with exactly one `.timeline-month`
div and a full `<select>`; `data.json` contains no `th`/`dm`; a `posts-data.js`
entry has `th` and `thumbnails/<th>.webp` exists; no `<style>` blocks or
`profile-picture` markup in any output HTML.

**Timeline.** Newest month paints; DOM ~600 nodes; switching months builds +
shows exactly one panel with no duplicates; ←/→ disable at the extremes;
`?post=<old ts>` opens the right month + modal + working arrows; `?story=<old
ts>` opens the viewer; `?post=<garbage>` falls back to newest with no ghost
panel. **Tile parity:** a built post tile's `outerHTML` matches the server's
(ignoring inter-tag whitespace); place names with `&`/`'` render literally;
day headings zero-padded; singular/plural row labels correct.

**On this day.** Count matches the data; tiles build with images and no
`data-timestamp`; a post click opens the modal with working arrows; a **story**
click opens the viewer (the regression-prone case); returning to Timeline hides
every panel including ensure-built hidden ones.

**Stories.** Open an image story and a video story: no auto-advance, progress
bar + pause button hidden, video plays once with controls; next/prev buttons,
arrow keys, and click-to-advance still navigate; deep link `?story=` opens.

**Cross-page.** Index sort + modal; cities map + one-city view + viewers +
Markdown; editor tag/favourite/city-text round-trip + `mm_editor_month`
persistence. The post modal shows a location map for posts with coordinates and
hides it for those without (on cities, its map coexists with the city map).
Console clean on every page.

**Flickr.** Counts: `data.json` flickr items == public minus dedup exclusions
minus reported failures (currently 30,335 = 30,387 − 52), all with `m`; a
known-private id absent; zero `"privacy"` strings serialized; grep the output
tree for the API key → zero hits. Page: newest month server-rendered (one
`.timeline-month` in the HTML, full `<select>`), month switching builds
without duplicates, ←/→ disable at 2001-05/2019-08 extremes; built-tile
outerHTML matches the server tile except ` loading="lazy"` on the eager
first-30. Deep link `?photo=6891654969` → Feb 2012 + viewer + `hongkong` tag
+ album link + map on Hong Kong; unknown id → newest month, no ghost. A local
video plays offline; a `vd` item with an unplayable `vu` shows its poster,
not a dead player. `--regenerate` with `flickr-download/` absent reproduces
flickr.html + flickr-data.js from the sidecar; an IG `--merge` keeps the
flickr key.

**Rendering parity after CSS/markup refactors.** Capture computed styles
(a *golden master*) on all affected pages **before** the change, then diff after
— story tiles render differently per page (stories grid vs timeline/cities), so
verify each. Keep the viewport fixed between captures.

---

## 8. Gotchas (each cost real debugging)

- **Docker `run` replaces `command:`** — output must be written inside the
  container's `working_dir`; args don't merge with the compose `command`.
- **New-format Place is under `title: "Place"`, not `label`** — and per-media
  decoy stubs exist. Missing this drops all venue names.
- **int vs str timestamp keys.** Freshly-loaded posts can have int keys while
  JSON-round-tripped data has string keys; a lookup mismatch silently drops
  every tag. Normalize to `str(...)` before cross-referencing (see
  `_build_cities`).
- **JS enumerates integer-like object keys in ascending order.** Any
  newest-first ordering (months, days, tiles) needs an **explicit descending
  sort** — don't rely on insertion order of `window.postData`.
- **Stale NodeList trap.** A NodeList captured at DOMContentLoaded doesn't see
  later-built DOM. `month-nav.js` re-queries every call for exactly this reason.
- **Deferred scripts all run before DOMContentLoaded, in order.** `timeline-months.js`
  defines its `window.*` hooks at top-level eval, so they exist before any DCL
  handler runs.
- **`marked`/Leaflet on cities.html must NOT be deferred** — an inline body
  script uses `marked` at parse time. (Leaflet on index/timeline, by contrast,
  is only used at click time by the modal map, so it *is* deferred there.)
- **Map tiles are fetched from openstreetmap.org** (both the cities map and the
  post-modal map) — they need network and won't render offline or over
  `file://`. Everything else on the site works from a bare filesystem.
- **Leaflet:** init after layout (`setTimeout`, not rAF — rAF never fires in a
  background tab); `fadeAnimation:false` (tiles stuck at opacity 0 otherwise);
  call `invalidateSize`. Its runtime `position:relative` inline style on the map
  div is expected, not ours.
- **`[hidden]` vs `display:flex`.** A component rule like
  `.month-nav{display:flex}` beats the `hidden` attribute; the global
  `[hidden]{display:none!important}` fixes it.
- **`_minify_html` leaves single newlines between tags**, so server tiles carry
  whitespace text nodes that `createElement` tiles don't. Harmless in grid/flex
  layouts, but it means built-tile `outerHTML` won't be byte-identical to the
  server's — compare with inter-tag whitespace normalized.
- **User data is escaped by `createElement`+`textContent`, never `innerHTML`**
  (place names, captions). Keep it that way.
- **`openStory` silently returns at index −1** and `navigatePost` errors if the
  post isn't in the DOM — always `mmEnsureMonthFor(ts)` before opening a viewer
  from a data-driven view (OTD).
- **Browser-pane quirks (not site bugs):** aggressive HTTP caching (serve on a
  new port to bust); `document.hasFocus()===false`; stale paints after
  programmatic scroll. Also: some months have stories but no posts (e.g. the
  newest) — a null `.grid-item` selector there is not a bug.
- **`templates/stories.html` is unused** (the stories page is
  `stories_page.html`). Don't edit the wrong one.
- **CSS/HTML duplication is dangerous.** A per-page inline `<style>` that
  shadowed `style.css` once shipped a real bug (a control stayed visible after
  it was "hidden"). Prefer one rule in `style.css`; when a page genuinely needs
  an override, scope it (e.g. `.stories-grid .story-item`), don't duplicate.
- **GitHub auth isn't available in this environment** — commits/pushes are done
  by the maintainer, not the tooling.

**Flickr-specific gotchas:**

- **Flickr geo is degrees × 1,000,000 as integer strings** (`"51561666"` →
  51.561666). Divide by 1e6; `0.0` is junk.
- **Videos are invisible in the export metadata** — identical schema to
  photos, and their `original` URL serves a JPEG poster frame. Only the API
  sweep (`media` field) or a local file extension identifies them. Without
  the sweep, unknown videos import as poster-image photos (upgraded in place
  by a later sweep — id keys make that safe).
- **The export's `original` URLs use the o-secret**; sized-variant CDN URLs
  need the *regular* secret, which only the API provides. You cannot build
  `_q`/`_b` URLs from the export alone.
- **Orientation: apply exactly ONE fix.** When a file carries an EXIF
  orientation, Flickr's metadata `rotation` field DUPLICATES it (verified by
  pixel-comparing Flickr's own renders). EXIF-transpose when the tag exists;
  the metadata rotation only when it doesn't. Applying both double-rotates.
- **The CDN rate-limits aggressive downloads** — an 8-worker/10-req-s
  attempt was tarpitted within a minute, and every rejected retry refreshes
  the penalty window. The downloader paces adaptively (0.5–16s), naps 20
  minutes after sustained 429s, verifies Content-Length (a dropped
  connection EOFs silently), and only 404/410 are recorded as permanent.
- **Flash-era videos (2008–2010) may be missing from the export entirely**
  and the API only offers their `stewart.swf` player URL. The site *player*
  streams an MP4 from `live.staticflickr.com/video/<id>/<secret>/700.mp4`
  behind a signed short-lived token — capture it from a playing photopage's
  `<video>.currentSrc` and save as `data-download-manual/video_<id>.mp4`
  (any `data-download-*` folder; the id suffix is what matters). The viewer
  treats `.swf`//apps/video/ `vu` values as unplayable (poster + link).
- **A few 2004–06 originals are truncated on Flickr itself** (short by a
  few tail bytes, identically in CDN and export). The converter sets PIL's
  `LOAD_TRUNCATED_IMAGES` to salvage them rather than dropping them.
- **Jinja + dict keys named like dict methods**: `{{ day.items }}` resolves
  the *builtin* `dict.items`, not the key — the flickr month list uses
  `tiles` for exactly this reason. Avoid `items`/`keys`/`values` as
  template-visible dict keys.
- **Never walk or `fix_file_extensions` the 12 GB export tree**
  (`FlickrMediaProcessor._build_file_index` returns `{}` deliberately).
- **External-disk storage works via symlinks + matching compose mounts.**
  macOS Finder *aliases* do NOT work (Python sees an opaque file). The
  export zips and `originals-cache` may be symlinked to an external disk,
  but the symlink target must ALSO be volume-mounted in docker-compose at
  the **same absolute path**, or it dangles inside the container (zips
  read-only, cache writable). Imports then require the disk connected;
  browsing the generated site never does.
- **The flickr tile markup lives in FOUR places** — `templates/flickr.html`
  (grid) + `buildTile` in `flickr-grid.js`, and `templates/timeline.html`
  (timeline row) + `flickrTimelineTile` in `timeline-months.js` (the
  timeline variant adds the `timeline-tile` class). Change all in step.
- **`mmMonthKeyOfTarget`** is how month-nav.js resolves `?photo=` deep-link
  months (photo ids aren't timestamps). timeline-months.js defines it; on a
  hook miss month-nav MUST fall back to timestamp math or `?post=`/`?story=`
  deep links break — keep the fallback.
- **modal.js's `.grid-item` delegation must skip `.flickr-tile`** — flickr
  tiles share the grid styling classes but have no `data-index`; without the
  guard, clicking one calls `openModal(NaN)`.
- **`templates/stories.html` is unused** but `flickr.html` is not —
  don't confuse them when grepping.

---

## 9. File map (quick reference)

```
memento_mori/
  cli.py extractor.py loader.py media.py merger.py file_mapper.py generator.py
  flickr.py   (Flickr importer: loader, dedup, API client, downloader/processor)
  templates/  index.html grid.html stories_page.html timeline.html cities.html
              flickr.html edit.html edit-cities.html
              _post_modal.html _story_viewer.html _flickr_viewer.html
              (stories.html — unused)
  static/js/  posts-data*/stories-data*/flickr-data* (generated at build)
              modal.js stories.js month-nav.js timeline-months.js on-this-day.js
              flickr-grid.js flickr-viewer.js
              editor-common.js editor.js editor-cities.js
  static/css/ style.css
  static/vendor/ leaflet/ marked/
flickr-download/  (input, gitignored: flickr_metadata/, data-download-*/,
                   originals-cache/, flickr_api_cache.json,
                   flickr_exclude.json, flickr_dedup_report.json)
```
*posts-data.js / stories-data.js / flickr-data.js are written by the generator, not committed.*
