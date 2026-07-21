# Maintaining Memento Mori — internals, testing, and gotchas

A precis for whoever works on this next (including future-you). Covers **how the
system works**, **what to test**, and the **gotchas** that were each found the
hard way. README.md is the user-facing guide; this is the maintainer's guide.

---

## 1. What it is

A Python static-site generator that turns personal photo-service exports into a
browsable static website. Two sources are supported and coexist in one site:
**Instagram** (posts + stories) and **Flickr** (public photos/videos, tags,
albums). Output is plain HTML + classic `<script>` files + JSON + generated
thumbnails. Design constraints that shape everything:

- **No framework, no build step.** The published site is a folder of HTML and
  classic scripts. It must keep working from a bare filesystem years from now.
- **Works over `file://` and `http://`.** No `fetch`, no ES modules, no dynamic
  import in the published pages — data is loaded via classic `<script>` files
  that assign `window.postData` / `window.storiesData` / `window.flickrData`.
- **Any subset of sources.** A site can be built from Instagram, from Flickr,
  or from both; nav rows for absent sources hide themselves, and `index.html`
  becomes a redirect stub when Instagram is not present (see §3z). Sources are
  a registry, not a pair of special cases.
- **Vendored libraries** (Leaflet 1.9.4, marked 12.0.2) under
  `static/vendor/` — no CDN.

---

## 2. Pipeline

Run in Docker (the generator's deps aren't on the host):

```
docker compose run --rm memento-mori --regenerate
```

`docker-compose.yml`: `working_dir: /app/workspace`, `PYTHONUNBUFFERED=1`, a
`FLICKR_API_KEY=${FLICKR_API_KEY:-}` passthrough, and a default
`command: --search-dir . --output ./output`. **Any args you pass to
`docker compose run` REPLACE `command:`** — that's why `--regenerate` alone
still finds input/output (the CLI defaults do the right thing on their own).
The `volumes:` block mounts the project folder at `/app/workspace`, plus the
external disk holding the Flickr zips and `originals-cache` **at the same
absolute path as on the host** so symlinks resolve inside the container (see
the external-disk gotcha in §8). The scratchpad directory is *not* mounted —
one-off scripts must live in the project folder. To run Python directly in the
container: `docker compose run --rm --entrypoint python memento-mori <script>.py`.

Stages (`memento_mori/`):

- **`cli.py`** — argparse entrypoint. Flags: `--input`, `--output`,
  `--search-dir`, `--threads`, `--quality`, `--max-dimension`,
  `--thumbnail-size`, `--no-auto-detect`, `--gtag-id`, `--merge`,
  `--city-tags` (defaults to `<output>/city_tags.json`), `--regenerate`,
  `--flickr PATH`, `--flickr-refresh`, `--verbose`/`-v`. Three mutually
  exclusive modes: **fresh** (extract + process + generate), **`--merge`**
  (requires `--input`; folds a new export into `output/`), and
  **`--regenerate`** (rejects `--merge`/`--input`; re-renders from
  `output/data.json`). `--flickr` composes with fresh and regenerate; on a
  plain `--regenerate` the sidecar's existing `flickr` key is carried
  forward untouched, and an Instagram `--merge` does the same.
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
    (see §3). Browser-only enrichment (`th`/`dm`/`vp`) happens here.
  - `_write_flickr_browser_data` — the same for `js/flickr-data.js`, which
    also carries `window.flickrAlbums` (the album-id → title map that
    `albums.js` and the viewer read).
  - `_as_json_parse` — module-level, shared by both writers: emits
    `JSON.parse("…")` with `</` escaped (see §3).
  - `_page_context` — the context every page's `_header`/`_nav`/`_footer`
    share: counts, `has_*` flags, `insta_years`/`flickr_years`
    (`_year_span`), `flickr_alias`, the resolved `bio`, `generation_date`.
    **Add nav data here, not per-page.**
  - `_write_data_json` — writes the `data.json` sidecar (pops `city_tags`).
  - Jinja filter **`commas`** (`f"{n:,}"`) — registered in `__init__`. Every
    user-visible count in the nav and the tags/albums filter placeholders
    uses it; the JS-built equivalents use `.toLocaleString()`. Keep new
    counts consistent with both.

---

## 3. Data artifacts

### 3z. The sources registry (schema v2) — read this first

Everything imported lives under `sources`, keyed by importer name. This is
what makes a site buildable from *any* subset of sources, Flickr-only
included, and what makes adding a third source additive rather than another
round of scattered conditionals.

```json
{ "schema_version": 2,
  "location": {"location": "Unknown"},
  "sources": {
    "instagram": { "profile": {…}, "posts": {…}, "stories": {…} },
    "flickr":    { "profile": {…}, "items": {…}, "albums": {…}, "meta": {…} }
  },
  "settings": { "gtag_id": …, "generated_at": …, "schema_version": 2 } }
```

Three rules follow from it:

- **Identity is derived, never stored.** The site's username/bio/website come
  from the first source profile along `SOURCE_PRIORITY` (`merger.site_identity`),
  computed on every render. A stored copy could go stale the moment a source
  was added, refreshed, or removed. The `city_tags.json` tri-state `bio`
  override still sits on top.
- **Nothing derivable is persisted.** `post_count`, `story_count` and
  `date_range` left the sidecar — counts are computed in `_page_context`, and
  no template ever consumed `date_range`. Duplicated state that can drift is
  worse than a cheap recount.
- **Migration is automatic.** `merger.migrate_sidecar` converts any v1 sidecar
  in memory on load, and `backup_v1_sidecar` copies the original to
  `data.v1.bak.json` **once** before the first v2 write. The generator also
  migrates its input package, so a caller holding v1 data still works. Verified
  lossless on the real archive: 6,283 posts / 6,062 stories / 30,335 Flickr
  items / 148 albums identical across the migration, and every generated HTML
  page byte-identical.

**Adding a source** (the checklist this restructure exists for):

| Layer | What to add |
|---|---|
| Importer | A module returning a `sources.<key>` section, optionally with a `profile` |
| `cli.py` | A flag, plus a branch in the collection step |
| `generator.py` | `SOURCE_PRIORITY` entry, a `_nav_row_<key>` builder listed in `NAV_ROW_BUILDERS`, page generators, a browser-data writer, timeline day-bucket + tile ctx |
| Templates | Its pages, its timeline section, its tile markup (**parity contract** — see §5) |
| JS | `mmTiles.<key>` builder, a viewer, an `on-this-day.js` PROVIDERS entry |
| `merger.py` | **Nothing.** Non-Instagram sources are carried through `--merge` by a generic loop |

**The clobber guard.** A fresh run rebuilds `data.json` from only what it was
given, so `_check_fresh_would_not_clobber` refuses when the existing sidecar
holds sources this run doesn't provide. Before it existed, a plain Instagram
rebuild over a combined site silently dropped the entire Flickr section.

| File | Purpose | Browser-loaded? |
|---|---|---|
| `data.json` | full sidecar for `--merge`/`--regenerate`; keeps `story_thumb`; `city_tags` popped out | **No** |
| `js/posts-data.js` | `window.postData = JSON.parse("…")` — ~2.3 MB | Yes (index, timeline, cities) |
| `js/stories-data.js` | `window.storiesData = JSON.parse("…")` — ~1.4 MB | Yes (stories, timeline, cities) |
| `js/flickr-data.js` | `window.flickrData` + `window.flickrAlbums` — **~9 MB** at 30k items | Yes (flickr, tags, albums, timeline) |
| `city_tags.json` | human annotations: bio, tags, favourites, per-city coords + Markdown | loaded only into the editor pages as an inline embed |

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

**Shared page chrome:** `_header.html` (masthead: plain-text site title —
it used to link off-site — plus the profile bio), `_nav.html` (the three-row
navigation: overview
row, then one row per imported service with a data-driven label —
`Instagram <username> (years):` / `Flickr <alias> (years):` — each row
hidden when its import is absent; include with `{% set active_page %}`
first) and `_footer.html`. All seven public templates include both; the
editor pages have their own minimal chrome (their logo still links back to index.html). The header and footer are white full-bleed bands whose inner `.header-content`/`.footer-content` share `<main>`'s max-width and padding, so the title, page content and footer all sit on one left edge; the header is **static** (it holds no nav, and a fixed one would pin the bio permanently). The profile **bio** shown at
the top is the Instagram bio unless `city_tags.json` carries a `bio` key
(tri-state: absent = no override, present — even empty — is
authoritative); it is editable from edit.html and travels through the
editor's overlay/export like everything else.

**`city_tags.json` shape:**
```json
{ "version": 1,
  "bio": "optional site bio override",
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
  deferred; Leaflet powers the modal's per-post location map). Sort buttons —
  **Newest / Oldest / Random only** — reorder tiles in place. (The old Most
  Likes / Most Comments / Most Views buttons were removed: never wired up,
  and the counts are empty in this archive.) Deep link `?post=TS[&image=N]`.

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
  description (`white-space:pre-line`), tag chips (each linking to
  `tags.html#tag=<tag>` — a same-document hash change on the tags page
  itself, where the viewer closes and hashchange switches the tag), album
  links, license (when
  not the default), and a location map. View/fave counts are deliberately
  not imported, and the viewer has no Flickr backlink — the tile `href`
  still points at the photopage as the no-JS fallback. Flickr items ALSO
  appear on the
  timeline (see above); deep links are `?photo=<id>` on both pages.

- **`tags.html`** — the Flickr tag navigator. Entirely client-built by
  `tags.js` from `window.flickrData`: ~8k chips (count-sorted, reusing the
  cities `.city-chip` styling, in a scrollable `.tag-index`), a filter box,
  and a progressive per-tag grid. Reuses `window.mmFlickrGridTile` (exposed
  at top-level eval by `flickr-grid.js`, which otherwise no-ops here — no
  `#flickrGrid`) so tile markup stays single-sourced, and sets
  `window.mmFlickrOrder` to the selected tag's ids so the viewer's
  prev/next cycles within the tag. Tag selection is hash-linkable
  (`#tag=<encoded>`), written only on user selection like the cities page.

- **`albums.html`** — the Flickr album navigator, a structural sibling of
  tags.html (`albums.js` mirrors `tags.js` — change them in step): 148
  album chips (newest activity first, filterable), progressive per-album
  grid, hash-linkable `#album=<id>`, viewer prev/next scoped via
  `mmFlickrOrder`. The viewer's tag and album chips sit under small
  "Tags"/"Albums" section labels (`.flickr-section-label`, hidden when
  empty); its album links point here (chip-styled, a same-document switch
  when already on this page) rather than at flickr.com.

  Both navigators format counts with `.toLocaleString()` in **three** spots —
  the chip count, the `<h2>` heading, and (server-side, via the `commas`
  filter) the filter placeholder. Change them together or the same number
  renders two different ways on one screen.

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
- **Vertical alignment is load-bearing.** `header`/`footer` are white
  full-bleed bands; their inner `.header-content`/`.footer-content` share
  `<main>`'s `max-width: 975px` + `padding: 0 20px`, so the site title, bio,
  page content, and footer all land on one left edge. Change the measure in
  one place and all three must follow. The header is deliberately **static**,
  not fixed — it now holds the bio, which a fixed header would pin to the
  viewport forever. (The old `--header-height` variable is gone.)
- **The three-row nav is one CSS grid.** `.nav-rows` is
  `grid-template-columns: repeat(4, max-content)`; each `.nav-row` is
  `display: contents` so its cells join the *parent* grid — that's what makes
  the links line up in columns across rows (days above posts above photos).
  A `.nav-service-label` pins column 1; row 1 emits an empty label cell to
  keep its links in the same columns. Under 600px the whole thing flips to
  flex columns, where `display:contents` would break the layout.
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

## 7. What to test

### 7a. The automated suite (run this first)

```bash
# unit + integration (fast, offline, no personal data) — inside the image
docker compose run --rm --entrypoint python memento-mori -m pytest tests -q

# same, on a host: needs libmagic (brew install libmagic / apt install libmagic1)
pip install -e ".[test]" && pytest -q

# browser smokes: real Chromium, host or CI only (not in the image)
pip install -e ".[browser]" && playwright install chromium && pytest -m browser -q

# characterization against YOUR real ./output (auto-skips without one)
pytest -m real -q
```

GitHub Actions runs the first and third of these on every push and PR
(`.github/workflows/tests.yml`). The `browser` and `real` markers are
deselected by default (see `pyproject.toml`) because each needs something a
plain checkout lacks.

**How the suite is built** (`tests/`):
- Fixtures are **generated in code**, not committed — the pipeline genuinely
  decodes what it is handed (PIL opens every image, cv2 every video), and
  generating them keeps personal data out of the repo. The only committed
  binary is `tests/fixtures/tiny.mp4`.
- **Every fixture is copied per test.** Folder-mode extraction rewrites the
  export in place (`fix_file_extensions`), and the Flickr importer writes
  `flickr_exclude.json` / `flickr_dedup_report.json` / `originals-cache/`
  into its own *input* directory. Inputs are outputs here.
- Tests stay **offline**: the API sweep only fires with a key AND no cache, and
  `download_missing` fetches nothing when every item has local media. A
  generated `flickr_api_cache.json` stands in for the sweep.
- `--regenerate` **idempotence** is the strongest single guard: two builds must
  match byte for byte across all output files, with only the three date stamps
  masked (`tests/helpers.py:DATE_PATTERNS`).
- When adding a test, **check it fails** against a deliberate break. A tags
  deep-link test passed against a broken handler because navigating hash-to-hash
  on the same page fires `hashchange`, not the initial-load path — hence the
  separate `test_tags_deep_link_on_a_cold_load`.

### 7b. Manual checks (what the suite does not cover)

Regenerate, then `python3 -m http.server` in `output/`. The in-app browser pane
caches assets aggressively — **serve on a fresh port** (or cache-bust) after a
CSS/JS change or you'll test stale files. The editor's localStorage round-trip,
visual/CSS regressions, and the network paths (API sweep, CDN downloader
pacing) are all still manual.

**Artifacts.** Reference sizes for the current archive (6,283 posts / 30,335
flickr items): `timeline.html` ~69 KB with exactly one `.timeline-month` div
and a full `<select>`; `flickr.html` ~24 KB; `tags.html` / `albums.html`
~4.3 KB each (pure shells — everything is client-built); `index.html` ~1.8 MB
and `stories.html` ~2.6 MB (both server-render every tile, by design).
`data.json` contains no `th`/`dm`/`vp`; a `posts-data.js` entry has `th` and
`thumbnails/<th>.webp` exists; no `<style>` blocks or `profile-picture` markup
in any output HTML.

**Page chrome (every public page).** Masthead shows the plain-text title +
bio and does *not* link off-site; the title, nav, content, and footer all
share one left edge at desktop and at <600px; the active page's nav link
carries `.active` + `aria-current="page"`; a service row disappears entirely
when its import is absent (test by regenerating from a sidecar with the
`flickr` key removed); the footer credits both repos. All counts ≥1,000 show
thousands separators — nav, tags/albums filter placeholders, chips, and
headings alike.

**Tags / albums navigators.** Chips render count-sorted (tags) or
newest-activity-first (albums); the filter box hides non-matching chips;
selecting a chip swaps the grid, updates the `<h2>`, and writes
`#tag=`/`#album=`; a deep link opens straight to that selection; an unknown
hash falls back to the first chip with no error; the viewer's prev/next
cycles *within* the selection (`mmFlickrOrder`), and a tag chip inside the
viewer navigates to `tags.html#tag=…` — closing the viewer first when
already on that page.

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

- **Safari does not focus a link when you click it; Chromium does.** So a
  viewer's `lastFocused` is often an ancestor (`<main tabindex="-1">`), and
  restoring focus to it on close scrolls that element into view — throwing
  the reader from the bottom of the page to the top. All three viewers use
  `focus({ preventScroll: true })` for this reason. It reproduces **only**
  in WebKit, which is why the browser CI job runs both engines.
- **Playwright scrolls an element into view before clicking it.** A test that
  scrolls down and then clicks an arbitrary tile moves the page itself, which
  looks exactly like a scroll bug — it sent one investigation chasing a
  non-existent clamp. Click something already in the viewport
  (`_click_tile_in_viewport` in the browser tests).

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
- **Zero-byte outputs are "done" forever unless you check.** An interrupted
  run left 7 empty `.webp` files that every later run happily skipped. The
  converter now writes to a temp file and atomically renames, and
  `_missing()` treats a 0-byte file as missing. Any new skip-if-exists
  cache needs the same two guards.
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
- **On This Day scopes Flickr prev/next via `window.mmFlickrOrder`.** The
  viewer's fallback order is "the visible month panel's tiles", and an On
  This Day item is from a previous year by definition — never in that panel —
  so without setting the order the arrows silently do nothing. `showView`
  clears it again when returning to the timeline.
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
- **The editor's bio box is in-flow, not a panel.** `.editor-panel` is
  `position: fixed`; reusing it for the bio textarea turned it into a
  floating overlay. It has its own `.editor-bio` rule for this reason.

---

## 9. File map (quick reference)

```
memento_mori/
  cli.py extractor.py loader.py media.py merger.py file_mapper.py generator.py
  flickr.py   (Flickr importer: loader, dedup, API client, downloader/processor)
  templates/  index.html grid.html stories_page.html timeline.html cities.html
              flickr.html tags.html albums.html edit.html edit-cities.html
              _header.html _nav.html _footer.html          (shared chrome)
              _post_modal.html _story_viewer.html _flickr_viewer.html
              (stories.html — UNUSED; the stories page is stories_page.html)
  static/js/  posts-data*/stories-data*/flickr-data* (generated at build)
              modal.js stories.js month-nav.js timeline-months.js on-this-day.js
              flickr-grid.js flickr-viewer.js tags.js albums.js
              editor-common.js editor.js editor-cities.js
  static/css/ style.css
  static/vendor/ leaflet/ marked/
flickr-download/  (input, gitignored: flickr_metadata/, data-download-*/,
                   originals-cache/, flickr_api_cache.json,
                   flickr_exclude.json, flickr_dedup_report.json)
```
*posts-data.js / stories-data.js / flickr-data.js are written by the generator, not committed.*
