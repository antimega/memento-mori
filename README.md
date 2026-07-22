# Memento Mori — a viewer for your own photo archives

**Memento Mori** turns the data exports you can download from photo services into a single, standalone, offline-capable website. The name (Latin for "remember that you will die") reflects the ephemeral nature of our digital content: services shut down, accounts get locked, terms change. This tool gives you a copy that is yours, in plain files, that keeps working with no network and no accounts.

It currently imports two sources, which live side by side in one site:

| Source | What comes in | Pages it adds |
|---|---|---|
| **Instagram** | Posts (incl. carousels and video), Stories, captions, places, coordinates, profile bio | posts, stories |
| **Flickr** | Your **public** photos and videos, titles, descriptions, tags, albums, geotags | photos, tags, albums |

Both feed a shared **days** timeline and an optional **cities** page. You can see an example of the original Instagram-only version at https://gregr.org/instagram/.

## Quick Start

Drop your Instagram export zip into this folder and run:

```bash
docker compose run --rm memento-mori
# then open output/index.html in your browser
```

Then, if you have a Flickr archive too, put it in `./flickr-download/` and run:

```bash
docker compose run --rm memento-mori --regenerate --flickr ./flickr-download
```

Either source works on its own — you can build a Flickr-only site with no Instagram export at all, and add Instagram later. Full details for both are in [Getting your data](#getting-your-data) below.

## ⚠️ IMPORTANT SECURITY WARNING ⚠️

**DO NOT** share your raw data exports online! They contain sensitive data you probably don't want to share:

- Phone numbers
- Precise location data
- Private messages and email addresses
- Non-public photos, and photos shared only with friends and family
- Other private information

Only share the generated `output` folder after processing with this tool. Note that the generated site still includes the location data attached to your content: place names, and coordinates rounded to ~10 m (4 decimal places). Each post that has coordinates shows a small location map in its detail view, and the optional city maps plot these locations too.

A Flickr import adds more of the same: only your **public** Flickr items are ever included, but their geotags (street-level for most), titles, descriptions, and tags are all published in the site. This is the same information you originally attached when posting, but it is fairly precise — review it before publishing.

## Key Features

- **Familiar interface**: grid layout with post details and a carousel for multiple images
- **Stories support**: view your Instagram Stories in a 9:16 viewer, advancing at your own pace
- **Timeline view**: every post, story, and Flickr item grouped by date, newest first, paginated month by month — plus an **On This Day** view showing memories from the same calendar day in previous years
- **Flickr section**: your public photos and videos as their own grid, plus tag and album navigators, with titles, descriptions, and location maps
- **Cities**: tag content by city and get a dedicated page with a clickable index and an interactive map; write a Markdown blurb for each city
- **Favourites**: star your best items so they surface first within each city
- **Places & maps**: the tagged location under each thumbnail, a small location map inside the detail view, and a **map page** plotting every geotagged photo and post from every source as clustered pins — click a cluster to browse what you shot there
- **Incremental updates**: merge a fresh export into an existing site without reprocessing everything, and re-render the whole site in seconds after editing
- **Media optimization**: converts images to WebP, generates thumbnails, and supports video playback (videos show a still preview and don't autoplay)
- **Cross-post de-duplication**: Flickr copies of Instagram posts already in the site are detected and excluded
- **Works offline**: no build step, no framework, no server — the site opens straight from the filesystem (`file://`) as well as over HTTP. Only the map tiles need a network connection.

## Getting your data

Everything below assumes the project folder (the one containing `docker-compose.yml`) is your working directory. Docker mounts that folder into the container, so **relative paths like `./output` or `./flickr-download` refer to the project folder on your machine**.

### Instagram

**1. Request the export.** In the Instagram app or on the web, go to **Settings → Accounts Center → Your information and permissions → Download your information**. Request:

- Your **posts** and **stories** (at minimum), plus **personal information** for the profile bio
- Format: **JSON** (⚠️ *not* HTML — the HTML format cannot be imported)
- Media quality: **High** if you want the best originals

Instagram emails you a download link, usually within a few hours to a couple of days. Large accounts come as several zips (`instagram-<user>-<date>-part1.zip`, `part2.zip`, …).

**2. Put it in the project folder.** Either leave the zip(s) as they are, or extract them into a folder — both work:

```
memento-mori/
├── docker-compose.yml
├── instagram-yourname-2026-07-01.zip     ← the zip, as downloaded
└── output/                               ← created for you
```

or

```
memento-mori/
└── your-export-folder/
    ├── personal_information/
    │   └── personal_information/
    │       └── personal_information.json     ← bio, username, profile pic
    ├── your_instagram_activity/
    │   ├── content/
    │   │   ├── posts_1.json                  ← posts (may be posts_1..N)
    │   │   └── stories.json                  ← stories
    │   └── media/                            ← the actual image/video files
    └── connections/…
```

The exact nesting varies between Instagram export versions — the importer searches for these files by pattern rather than assuming one layout, so you don't need to rearrange anything. Multiple `posts_*.json` files are all picked up.

**3. Import.** With auto-detection (the default), the tool scans the project folder for anything that looks like an Instagram export:

```bash
docker compose run --rm memento-mori
```

Or point it at a specific zip or folder:

```bash
docker compose run --rm memento-mori --input ./your-export-folder
docker compose run --rm memento-mori --input ./instagram-yourname-2026-07-01.zip
```

This is the run that creates the site. It extracts the archive, converts every image to WebP, generates thumbnails, and writes `output/`.

### Flickr

**1. Request the export.** Go to [flickr.com/account](https://www.flickr.com/account) → **Your Flickr Data** → **Request my Flickr data**. Flickr prepares two kinds of download:

- **Account data** — one zip of JSON metadata. **This is required.**
- **Photos and videos** — your media, split into many numbered parts (`data-download-1.zip`, `data-download-2.zip`, …). A large account can be 150+ parts and tens of gigabytes. **These are optional** — see step 3.

**2. Put it in one folder.** Create `./flickr-download/` in the project folder and unpack *only* the account-data zip into it, so its JSON lands in `flickr_metadata/`. Leave the media parts as `.zip` files exactly as Flickr served them — the importer reads them in place and extracts only the items it actually needs, which saves a lot of disk:

```
memento-mori/
└── flickr-download/
    ├── flickr_metadata/
    │   ├── account_profile.json           ← your NSID and URL alias
    │   ├── albums.json                    ← album titles and membership
    │   ├── photo_51234567890.json         ← one file per item: title,
    │   ├── photo_51234567891.json           description, tags, geo,
    │   └── …                                privacy, rotation, CDN URL
    ├── data-download-1.zip                ← media parts, as downloaded
    ├── data-download-2.zip                  (optional — see below)
    └── …
```

Already-extracted `data-download-*/` **folders** work equally well, and you can mix the two. If the media parts are too big for your main disk, put them on an external drive and symlink or alias them into `flickr-download/` — but note you'll then need to add that drive's path as a volume in `docker-compose.yml`, mounted at the *same absolute path*, so host symlinks resolve inside the container too. The `volumes:` block there shows the pattern.

**3. Get a Flickr API key (recommended).** Grab a free key at [flickr.com/services/api](https://www.flickr.com/services/api/). It is used for a single cached metadata sweep and is **the only way to tell which of your items are videos** — the export itself has no video flag, and a video's "original" file in the metadata is just its poster JPEG. Without a key, videos import as still images. The key is read from the environment only; it never appears in the generated site.

**4. Import.** Combine `--flickr` with `--regenerate` so your already-processed Instagram content is reused untouched:

```bash
FLICKR_API_KEY=yourkey docker compose run --rm memento-mori --regenerate --flickr ./flickr-download
```

Or import both sources in a single fresh run:

```bash
FLICKR_API_KEY=yourkey docker compose run --rm memento-mori --input ./your-export-folder --flickr ./flickr-download
```

Or build a **Flickr-only site** with no Instagram archive at all:

```bash
FLICKR_API_KEY=yourkey docker compose run --rm memento-mori --no-auto-detect --flickr ./flickr-download
```

`--no-auto-detect` tells it not to go looking for an Instagram export. (If you have one in the folder and *don't* pass that flag, it builds a combined site instead.) It is also worth passing when your Flickr media parts live in the project folder, since auto-detection would otherwise open every one of them looking for an Instagram archive.

You can add Instagram later with `--merge` — the site upgrades in place, keeps every Flickr link working, and starts using your Instagram profile for the site's name and bio.

**About the media parts.** You don't have to download all of them. Every item's metadata contains a direct link to its original file, so the importer **downloads anything missing straight from Flickr's CDN** — politely rate-limited, resumable, and idempotent, so you can interrupt it and re-run. Downloading the parts by hand is faster for a big archive, and it is the only offline source for videos. Originals land in `flickr-download/originals-cache/` and are kept outside `output/`.

**What the import does:**

- Imports **only your own, public** items. Private and friends&family items are excluded, as are other people's photos you favourited.
- Converts everything through the same WebP/thumbnail pipeline as the Instagram media and applies Flickr's rotation fixes.
- Publishes titles, descriptions, tags, album links, licence, and a location map for geotagged items.
- **De-duplicates Instagram cross-posts** by upload-time matching. Every exclusion is listed in `flickr-download/flickr_dedup_report.json`; you can add or remove ids by hand in `flickr-download/flickr_exclude.json` and regenerate.

Later runs are fast: the metadata re-parses in about a minute, and downloads, conversions, and API results are all cached. Re-run with `--flickr-refresh` to redo the API sweep and retry failed downloads.

## Running it

### Preferred method: Docker (easiest)

Docker Compose runs Memento Mori without installing any dependencies. Many thanks to [CarsonDavis](https://github.com/CarsonDavis) for building out all the dockerizing code (as well as generally making my code better):

```bash
# Build the image (once)
docker compose build

# Run with default settings (auto-detect an Instagram export here)
docker compose run --rm memento-mori

# Specific paths and quality (relative paths refer to the project folder)
docker compose run --rm memento-mori --input ./your-export-folder --output ./my-site --quality 90

# Add a Flickr archive to the existing site
FLICKR_API_KEY=yourkey docker compose run --rm memento-mori --regenerate --flickr ./flickr-download

# Merge a newer Instagram export into the existing site in ./output
# (only new posts/stories are processed; existing media is kept)
docker compose run --rm memento-mori --merge --input ./your-new-export-folder

# Re-render the HTML only — seconds, no media work
docker compose run --rm memento-mori --regenerate

# Add Google Analytics tracking
docker compose run --rm memento-mori --gtag-id G-DX1ZWTC9NZ

# Preview the result in your browser
python3 -m http.server -d output
```

⚠️ Any arguments you pass to `docker compose run` **replace** the `command:` line in `docker-compose.yml` — they are not added to it. That's why every example above spells out the paths it needs.

By default, Docker will search for exports in the project directory and write the site to `./output`.

### Alternative: direct Python installation

```bash
# Install package and dependencies
pip install -e .

# Or install dependencies manually
pip install ftfy==6.3.1 Jinja2==3.0.3 MarkupSafe==2.1.5 opencv_python==4.10.0.84 Pillow==11.1.0 tqdm==4.67.1 python_magic==0.4.27

# Run the CLI (same arguments as the Docker examples)
python -m memento_mori.cli
python -m memento_mori.cli --input path/to/export.zip --output my-site
FLICKR_API_KEY=yourkey python -m memento_mori.cli --regenerate --flickr ./flickr-download

# Preview
python3 -m http.server -d output
```

### Running the tests

```bash
# unit + integration, inside the Docker image (no extra setup)
docker compose run --rm --entrypoint python memento-mori -m pytest tests -q

# or on your machine (needs libmagic: brew install libmagic / apt install libmagic1)
pip install -e ".[test]"
pytest -q
```

The suite builds small synthetic Instagram and Flickr exports and runs the real
pipeline over them, so it needs no personal data and never touches the network.
There is also an opt-in browser layer (`pip install -e ".[browser]" &&
playwright install chromium && pytest -m browser`) and, if you have a generated
site in `./output`, a set of consistency checks against it (`pytest -m real`).

### CLI arguments

```
Options:
--input PATH             Path to an Instagram export (ZIP or folder). If omitted,
                         auto-detection is used. Optional when --flickr is given.
--output PATH            Output directory for the generated site [default: ./output]
--flickr PATH            Path to a Flickr export folder to import as a separate
                         section (combine with --regenerate to add Flickr to an
                         already-generated site)
--flickr-refresh         Re-run the Flickr API metadata sweep and retry failed
                         media downloads
--merge                  Merge a newer Instagram export (--input, required) into the
                         existing site in --output
--regenerate             Re-render the site HTML from the existing output's data.json
                         (fast; no archive or media processing needed)
--city-tags PATH         Path to city tags JSON exported from the editor
                         [default: <output>/city_tags.json]
--threads INTEGER        Number of parallel processing threads [default: cores - 1]
--search-dir PATH        Directory to search when auto-detecting [default: .]
--no-auto-detect         Disable auto-detection (requires --input)
--quality INTEGER        WebP conversion quality (1-100) [default: 70]
--max-dimension INTEGER  Maximum image dimension in pixels [default: 1920]
--thumbnail-size WxH     Thumbnail size [default: 292x292]
--gtag-id ID             Google Analytics tag ID (e.g. 'G-DX1ZWTC9NZ')
--theme PATH             Theme directory overlaid on the built-in templates and
                         static assets (see Theming below)
--verbose, -v            Verbose output for debugging
```

Environment variables:

```
FLICKR_API_KEY           Flickr API key, used only for the one-time cached
                         metadata sweep. Never written into the generated site.
```

## Theming

`--theme <dir>` layers your own look and markup on top of the built-in output,
so you can restyle a site without editing the generator or hand-patching its
output after every run. It works in every mode — fresh builds, `--merge`, and
`--regenerate` — so the usual "re-render into the same folder" workflow keeps
applying your customisations for free.

A theme directory has up to two parts, both optional:

```
my-theme/
  templates/     Jinja templates that shadow same-named defaults. Only the
                 files you actually change need to exist here; everything else
                 falls through to the built-in template. Handy names to
                 override: _header.html, _nav.html, _footer.html, and the
                 page templates (index.html, timeline.html, …).
  static/        Files copied over the default CSS/JS/vendor assets after they
                 are written, so a same-named file wins. Mirror the output
                 layout: static/css/style.css replaces the stock stylesheet;
                 static/css/extra.css (a new name) is simply added.
```

```bash
# Restyle via a theme, re-rendering HTML only (seconds, no media work)
python -m memento_mori.cli --regenerate --theme ./my-theme
```

Without `--theme`, output is byte-for-byte identical to before the feature
existed. A common pattern is to keep the generated site in its own repo, point
`--output` at it, and keep the theme directory alongside it under version
control — the generated files stay disposable, the theme holds every edit.

## Viewing your generated site

Open `index.html` from the output directory (default: `./output`). The stats under the title double as navigation, grouped by source:

- **days** (`timeline.html`) — every post, story, and Flickr item grouped by date, newest first, one month at a time, with an **On This Day** toggle for memories from previous years. Each day shows posts, then stories, then a "Flickr photos and videos" section.
- **cities** (`cities.html`) — appears once you've tagged content with cities (see below); one city at a time with an interactive map and a clickable index.
- **pins** (`map.html`) — every geotagged item across all your sources on one clustered map. Click a cluster to list its photos and posts underneath (they open in the usual viewers); double-click to zoom in. Appears whenever anything is geotagged.
- **posts** (`index.html`) — the main Instagram grid, sortable by newest, oldest, or random. Click any post to open it in a modal, which shows a small map of its location when coordinates are available.
- **stories** (`stories.html`) — your Instagram Stories in a 9:16 viewer; advance them yourself with the arrows or by clicking.
- **photos** (`flickr.html`) — your public Flickr photos and videos in one grid (loading progressively as you scroll), sortable newest/oldest/random, with a viewer showing the title, description, tags, albums, and location.
- **tags** (`tags.html`) — a tag navigator for the Flickr archive: every tag as a clickable chip (most-used first, with a filter box), showing the selected tag's items. Selections are linkable (`tags.html#tag=venice`).
- **albums** (`albums.html`) — the same for Flickr albums (most recent first, filterable); the viewer links each photo's albums here. Selections are linkable (`albums.html#album=<id>`).

Rows for a source you haven't imported are simply hidden.

You can upload the entire output directory to any static web host to share it online. Before publishing, consider removing:

- `edit.html` and `edit-cities.html` — the private editor pages (see below)
- `data.json` — only used by `--merge`/`--regenerate`, never loaded by the site, so leaving it out saves a few MB. **Keep your own copy** for future updates.

Most static hosts serve these text files with gzip/brotli compression automatically, which shrinks the transferred size by roughly 85% — so the over-the-wire cost is far smaller than the on-disk size.

## Updating an existing site

When you download a fresh Instagram export later on, you don't need to rebuild from scratch. `--merge` folds the new posts and stories into your existing site — only new media is processed, and your city tags, favourites, city text, and Flickr section are all preserved:

```bash
docker compose run --rm memento-mori --merge --input ./your-new-export-folder
```

Instagram's timestamps are stable across downloads, so tags applied to your old export still line up with the merged content.

For a fresh Flickr export, re-run the import — items are keyed by photo id, so re-importing updates in place and newly downloaded media parts upgrade existing entries:

```bash
FLICKR_API_KEY=yourkey docker compose run --rm memento-mori --regenerate --flickr ./flickr-download --flickr-refresh
```

If you only changed `city_tags.json` (or want to re-render after upgrading the tool), `--regenerate` rebuilds all the HTML from the existing output in seconds:

```bash
docker compose run --rm memento-mori --regenerate
```

## Cities, favourites & the editor

Alongside the viewer, Memento Mori generates a private **editor** (`edit.html` and `edit-cities.html`) for organising your archive. Nothing you do in the editor touches the site directly — it produces a single `city_tags.json` file that you save and regenerate from, so it's fast to iterate and easy to version.

### The workflow

1. **Open the editor.** Serve the output folder and open `edit.html`:
   ```bash
   python3 -m http.server -d output
   # then browse to http://localhost:8000/edit.html
   ```
2. **Tag & favourite** (`edit.html`):
   - Type a city name, then click posts/stories to tag them. Click again to untag.
   - Use a day's **tag posts** / **tag stories** buttons to tag a whole day at once.
   - Switch to **★ Favourite** mode and click tiles to star your favourites.
   - Browse a month at a time with the month picker at the top.
3. **Profile description**: the text shown at the top of every page starts as your Instagram bio; edit it in the box at the top of `edit.html`.
4. **Flickr cities** (`edit-flickr.html`): tag Flickr photos and videos with cities in bulk. Pick one of your Flickr tags — everything under it starts selected — click any photo to drop it, then apply a city or ★ favourite the rest in one go. (Appears once you've imported a Flickr archive.)
5. **City text** (`edit-cities.html`): write a short blurb for each city. **Markdown** is supported (headings, emphasis, links, lists) with a live preview.
6. **Export.** Click **Export city_tags.json** and save the download as `output/city_tags.json`.
7. **Regenerate** (takes seconds — no archive or media reprocessing needed):
   ```bash
   docker compose run --rm memento-mori --regenerate
   # or: python -m memento_mori.cli --regenerate
   ```

A **cities** link now appears in every page's navigation. The cities page shows one city at a time — click a city chip or a map marker to switch. Within each city you get posts, then Flickr photos, then stories — each newest-first, with favourites pulled to the top and marked with a ★, and your city blurb rendered under the heading.

### Notes

- **Map pins** are computed automatically from your content's location data (coordinates are rounded to ~10 m; a city's pin is the median of its tagged items). To override a pin manually, add coordinates to the city in `city_tags.json`:
  ```json
  "cities": { "Berlin": { "lat": 52.52, "lng": 13.40 } }
  ```
- The maps (the city map and each item's location map) load OpenStreetMap tiles, so they need an internet connection. Everything else in the site works fully offline.
- Unexported edits live in your browser's localStorage, so you can come back to them later — but **export before clearing your browser data**. Use **Clear local changes** in the editor to discard them.
- The `city_tags.json` format is plain and hand-editable:
  ```json
  {
    "version": 1,
    "posts":     { "<timestamp>": "London" },
    "stories":   { "<timestamp>": "Porto" },
    "flickr":    { "<photo_id>": "Venice" },
    "favorites": { "posts": { "<timestamp>": true }, "stories": {}, "flickr": {} },
    "cities":    { "London": { "lat": 51.51, "lng": -0.13, "text": "Home." } },
    "bio":       "Optional override for the description under the site title."
  }
  ```
