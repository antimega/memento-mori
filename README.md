# Memento Mori - Instagram and Flickr Archive Viewer

**Memento Mori** is a tool that converts your Instagram data export into a beautiful, standalone viewer that resembles the Instagram interface. The name "Memento Mori" (Latin for "remember that you will die") reflects the ephemeral nature of our digital content. You can see an example at https://gregr.org/instagram/.

It now adds Flickr importing as well, with a separate photos page and a merged timeline page.


## Quick Start
Get your Instagram data export zip, throw it in with this code, and run this command:
```bash
docker compose run --rm memento-mori
#Then open output/index.html in your browser
```

## ⚠️ IMPORTANT SECURITY WARNING ⚠️

**DO NOT** share your raw Instagram export online! It contains sensitive data you probably don't want to share:

- Phone numbers
- Precise location data
- Personal messages
- Email addresses
- Other private information

Only share the generated output folder after processing with this tool. Note that the generated site includes the location data attached to your posts: place names, and coordinates rounded to ~10 m (4 decimal places). Each post that has coordinates shows a small location map in its detail view, and the optional city maps plot these locations too. A Flickr import adds more of the same: only your **public** Flickr items are ever included, but their geotags (street-level for most), titles, descriptions, and tags are all published in the site. This is the same information you originally attached when posting, but it is fairly precise — review it before publishing.

## How It Works
Memento Mori processes your Instagram data export and generates a static site with your posts and stories, copying all your media files into an organized structure that can be viewed offline or hosted on your own website.

## Key Features
- **Familiar Interface**: Grid layout with post details and carousel for multiple images
- **Stories Support**: View your Instagram Stories in a 9:16 viewer, advancing at your own pace
- **Timeline View**: Every post and story grouped by date, newest first, paginated month by month — plus an **On This Day** view showing memories from the same calendar day in previous years
- **Cities**: Tag posts and stories by city and get a dedicated page with a clickable index and an interactive map; write a Markdown blurb for each city
- **Flickr import**: Fold your Flickr archive in as its own separate section — public photos and videos only, browsed month by month, with titles, descriptions, tags, albums, and location maps; Instagram cross-posts are automatically de-duplicated
- **Favourites**: Star your best posts and stories so they surface first within each city
- **Places & Maps**: Shows the tagged location under each post thumbnail, and a small location map inside the post view, drawn from your archive's location data
- **Incremental Updates**: Merge a fresh export into an existing site without reprocessing everything, and re-render the site in seconds after editing
- **Media Optimization**: Converts images to WebP, generates thumbnails, and supports video playback (videos show a still preview and don't autoplay)
- **Organization**: Sort posts newest, oldest, or random, with shareable links to specific posts, images, and stories
- **Profile Information**: Displays bio, website, and follower count from your Instagram profile
- **Technical Improvements**:
  - Fixes encoding issues and mislabeled file formats
  - Shortens filenames for smaller HTML size
  - Processes files in parallel with a responsive design that works on all devices
  - Robust error handling with verbose debugging option

## How to Use Memento Mori

### 1. Get Your Instagram Data
1. Request and download your Instagram data archive
2. Place the zip within the folder of this repo

### 2. Preferred Method: Using Docker (Easiest)
Docker Compose is the easiest way to run Memento Mori without installing any dependencies. Many thanks to [CarsonDavis](https://github.com/CarsonDavis) for building out all the dockerizing code (as well as generally making my code better):
```bash
# Build the Docker image
docker compose build

# Run with default settings
docker compose run --rm memento-mori

# Run with specific arguments (relative paths refer to the project folder)
docker compose run --rm memento-mori --input ./your-export-folder --output ./my-site --quality 90

# Add Google Analytics tracking
docker compose run --rm memento-mori --gtag-id G-DX1ZWTC9NZ

# Merge a newer export into the existing site in ./output
# (only the new posts/stories are processed; existing media is kept)
docker compose run --rm memento-mori --merge --input ./your-new-export-folder

# Serve the output folder locally to preview in your browser
python3 -m http.server -d output
```

By default, Docker will:
- Search for exports in the project directory
- Output the generated site to the './output' directory

### 3. Alternative Method: Direct Python Installation
If you prefer running the tool directly without Docker:
```bash
# Install package and dependencies
pip install -e .

# Or install dependencies manually
pip install ftfy==6.3.1 Jinja2==3.0.3 MarkupSafe==2.1.5 opencv_python==4.10.0.84 Pillow==11.1.0 tqdm==4.67.1 python_magic==0.4.27

# Run the CLI
python -m memento_mori.cli

# Serve the output folder locally to preview in your browser
python3 -m http.server -d output
```

### CLI Arguments
The CLI supports the following arguments:
```
Options:
--input PATH Path to data (ZIP or folder). If not specified, auto-detection will be used.
--output PATH Output directory for generated website [default: ./output]
--threads INTEGER Number of parallel processing threads [default: core count - 1]
--search-dir PATH Directory to search for exports when auto-detecting [default: current directory]
--quality INTEGER WebP conversion quality (1-100) [default: 70]
--max-dimension INTEGER Maximum dimension for images in pixels [default: 1920]
--thumbnail-size WxH Size of thumbnails [default: 292x292]
--no-auto-detect Disable auto-detection (requires --input to be specified)
--gtag-id ID     Google Analytics tag ID (e.g., 'G-DX1ZWTC9NZ') to add tracking to the generated site
--merge          Merge a newer export (--input, required) into an existing generated site in --output
--city-tags PATH Path to city tags JSON exported from the editor [default: <output>/city_tags.json]
--regenerate     Re-render the site HTML from the existing output's data.json (fast; no archive needed)
--flickr PATH    Path to a Flickr data export folder to import as a separate section
                 (combinable with --regenerate to add Flickr to an existing site)
--flickr-refresh Re-run the Flickr API metadata sweep and retry failed media downloads
--verbose, -v    Enable verbose output for debugging
```

Note: Auto-detection is enabled by default and will look for exports in the current directory. Use `--no-auto-detect` if you want to disable this feature and specify an input path manually.

### Example Commands
```bash
# Auto-detect export in current directory
python -m memento_mori.cli

# Specify input file/folder and output directory
python -m memento_mori.cli --input path/to/export.zip --output my-site

# Use specific number of threads and image quality
python -m memento_mori.cli --threads 8 --quality 90

# Merge a newer export into an already-generated site (deduplicates by
# timestamp and only processes media for the new posts/stories). The site
# remembers its settings in output/data.json, so --gtag-id carries over.
python -m memento_mori.cli --merge --input path/to/new-export --output ./output

# Specify search directory for auto-detection
python -m memento_mori.cli --search-dir ~/Downloads

# Use custom thumbnail size
python -m memento_mori.cli --thumbnail-size 400x400

# Specify maximum image dimension
python -m memento_mori.cli --max-dimension 1600

# Disable auto-detection (requires specifying input)
python -m memento_mori.cli --no-auto-detect --input path/to/export.zip

# Add Google Analytics tracking
python -m memento_mori.cli --gtag-id G-DX1ZWTC9NZ

# Enable verbose debugging output
python -m memento_mori.cli --verbose
```

## Viewing Your Generated Site
After the tool finishes processing your Instagram data, open `index.html` from the output directory (default: `./output`) in your browser. The profile stats double as navigation between the pages:

- **posts** (`index.html`) — the main grid, sortable by newest, oldest, or random. Click any post to open it in a modal, which shows a small map of its location when coordinates are available.
- **stories** (`stories.html`) — your Stories in a 9:16 viewer; advance them yourself with the arrows or by clicking.
- **days** (`timeline.html`) — every post, story, and Flickr item grouped by date, newest first, paginated one month at a time (back to 2001 once Flickr is imported), with an **On This Day** toggle for memories from previous years. Each day shows posts, then stories, then a "Flickr photos and videos" section.
- **photos** (`flickr.html`) — appears once you've imported a Flickr archive (see below); your public Flickr photos and videos in one grid like the posts page (loading progressively as you scroll), sortable newest/oldest/random, with a viewer showing the title, description, tags, albums, and location.
- **cities** (`cities.html`) — appears once you've tagged posts with cities (see below); shows one city at a time with an interactive map and a clickable index.

You can upload the entire output directory to any static web host to share it online. (The editor pages — see below — are generated too; delete `edit.html` and `edit-cities.html` before publishing if you don't want them public. `data.json` is only used by `--merge`/`--regenerate` and is never loaded by the site, so you can also leave it out of a published copy to save a few MB — just keep your own copy for future updates.)

Most static hosts serve these text files with gzip/brotli compression automatically, which shrinks the transferred size by roughly 85% — so the over-the-wire cost is far smaller than the on-disk size.

## Updating an Existing Site
When you download a fresh export from Instagram later on, you don't need to rebuild from scratch. Use `--merge` to fold the new posts and stories into your existing site — only the new media is processed, and your city tags, favourites, and city text are preserved:
```bash
docker compose run --rm memento-mori --merge --input ./your-new-export-folder
```
Instagram's timestamps are stable across downloads, so tags applied to your old export still line up with the merged content.

If you only changed `city_tags.json` (or want to re-render after upgrading the tool) and don't need to process any new media, `--regenerate` rebuilds all the HTML from the existing output in seconds:
```bash
docker compose run --rm memento-mori --regenerate
```

## Importing a Flickr Archive

Memento Mori can fold a [Flickr data export](https://www.flickr.com/account) into the site as its own section (a **photos** entry in every page's navigation), kept fully separate from the Instagram posts and stories.

1. Request your Flickr data and download at least the **account data** part (the JSON metadata). Media parts are optional — see below. Put it all in one folder, e.g. `./flickr-download/`, containing `flickr_metadata/` and any media parts — either as extracted `data-download-*` folders **or as the `data-download-*.zip` files exactly as Flickr serves them** (no unzipping needed; only your public items are extracted, which also saves disk).
2. (Recommended) Get a free [Flickr API key](https://www.flickr.com/services/api/) — it's the only way to identify which of your items are videos and fetch their playback URLs. One metadata sweep runs once and is cached; the key never appears in the generated site.
3. Run the import (combinable with `--regenerate` so your Instagram content is untouched):
   ```bash
   FLICKR_API_KEY=yourkey docker compose run --rm memento-mori --regenerate --flickr ./flickr-download
   ```

What it does:

- Imports **only your own, public** items — private and friends&family photos are excluded, as are other people's photos you favourited.
- **Downloads any missing originals** straight from the CDN links in your own metadata (politely rate-limited; resumable, so you can interrupt and re-run). You don't need to download all of Flickr's media export parts by hand — though any you do download are used directly, and they're the only offline source for videos.
- Converts everything through the same WebP/thumbnail pipeline as the Instagram media, applies Flickr's rotation fixes, and shows titles, descriptions, tags, album links, view/fave counts, and a location map for geotagged photos (Flickr coordinates are precise to street level — see the security note above).
- **De-duplicates Instagram cross-posts**: Flickr copies of posts already in your Instagram archive are excluded automatically (by upload-time matching). Every exclusion is listed in `flickr-download/flickr_dedup_report.json`, and you can add or remove ids by hand in `flickr_exclude.json` and regenerate.

Later runs are fast: the metadata re-parses in about a minute, and downloads/conversions/API results are all cached.

## Cities, Favourites & the Editor

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
3. **City text** (`edit-cities.html`): write a short blurb for each city. **Markdown** is supported (headings, emphasis, links, lists) with a live preview.
4. **Export.** Click **Export city_tags.json** and save the download as `output/city_tags.json`.
5. **Regenerate** (takes seconds — no archive or media reprocessing needed):
   ```bash
   docker compose run --rm memento-mori --regenerate
   # or: python -m memento_mori.cli --regenerate
   ```

A **cities** link now appears in every page's profile stats. The cities page shows one city at a time — click a city chip or a map marker to switch. Within each city, posts and stories are listed newest-first, with favourites pulled to the top and marked with a ★, and your city blurb rendered under the heading.

### Notes

- **Map pins** are computed automatically from your posts' location data (coordinates are rounded to ~10 m; a city's pin is the median of its tagged posts). To override a pin manually, add coordinates to the city in `city_tags.json`:
  ```json
  "cities": { "Berlin": { "lat": 52.52, "lng": 13.40 } }
  ```
- The maps (the city map and each post's location map) load OpenStreetMap tiles, so they need an internet connection. Everything else in the site works fully offline.
- Unexported edits live in your browser's localStorage, so you can come back to them later — but **export before clearing your browser data**. Use **Clear local changes** in the editor to discard them.
- The `city_tags.json` format is plain and hand-editable:
  ```json
  {
    "version": 1,
    "posts":     { "<timestamp>": "London" },
    "stories":   { "<timestamp>": "Porto" },
    "favorites": { "posts": { "<timestamp>": true }, "stories": {} },
    "cities":    { "London": { "lat": 51.51, "lng": -0.13, "text": "Home." } }
  }
  ```
