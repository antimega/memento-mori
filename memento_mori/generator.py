# memento_mori/generator.py
import os
import json
import shutil
import datetime
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, ChoiceLoader
from markupsafe import Markup
import re
import hashlib
import base64
import statistics

from memento_mori.merger import SCHEMA_VERSION, migrate_sidecar, site_identity


def _slugify(name):
    """Make a safe anchor slug from a city name."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or hashlib.md5(name.encode()).hexdigest()[:8]


def _escape_inline_json(data):
    """JSON-encode for embedding inside a <script> block via |safe."""
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def _as_json_parse(data):
    # JSON.parse of a string literal parses roughly 2x faster than
    # evaluating a multi-MB JS object literal. Double json.dumps turns the
    # JSON payload into a valid JS string literal.
    payload = json.dumps(json.dumps(data, ensure_ascii=False))
    return "JSON.parse(" + payload.replace("</", "<\\/") + ")"


# Optional entry fields dropped from serialized output when empty, to shrink
# the JSON. Always kept: i, m, t, d, story_thumb (read directly by viewers).
_OPTIONAL_ENTRY_FIELDS = ("pl", "tt", "im", "l", "c", "la", "lo")

# A standard md5 thumbnail path, e.g. thumbnails/<32 hex>.webp
_THUMB_URL_RE = re.compile(r"^thumbnails/([0-9a-f]{32})\.webp$")


def _thumb_field(url):
    """
    Map a server-resolved tile display URL to the browser-only field the
    client needs to rebuild that exact URL for months rendered on demand:
      ("th", md5hex) when it's a standard md5 thumbnail (the common case),
      ("dm", url)    for any other resolved URL (webp variant, video-scan
                     thumbnail under a different name, SVG placeholder),
      (None, None)   for an empty URL.
    Kept out of data.json — this is display metadata for timeline-months.js.
    """
    if not url:
        return None, None
    m = _THUMB_URL_RE.match(url)
    if m:
        return "th", m.group(1)
    return "dm", url


def _compact_entries(entries):
    """
    Return a copy of a posts/stories dict with empty optional fields removed.

    Consumers use guarded access (truthy checks in the viewers, .get() in the
    generator/merger), so a missing key behaves exactly like an empty one.
    """
    compact = {}
    for key, entry in entries.items():
        compact[key] = {
            k: v
            for k, v in entry.items()
            if k not in _OPTIONAL_ENTRY_FIELDS or v not in ("", None)
        }
    return compact


def _minify_html(html):
    """
    Strip insignificant whitespace from generated HTML: remove leading
    indentation and blank lines. Inline spacing between elements is kept
    (only line-leading whitespace is removed, which the browser collapses
    anyway), and regions whose whitespace is significant — script, style,
    textarea, pre, and Markdown (data-md) blocks — are preserved verbatim.
    """
    placeholders = []

    def _stash(match):
        placeholders.append(match.group(0))
        return f"\x00{len(placeholders) - 1}\x00"

    html = re.sub(
        r"<(script|style|textarea|pre)\b[^>]*>.*?</\1>",
        _stash,
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    html = re.sub(
        r"<div[^>]*\bdata-md\b[^>]*>.*?</div>",
        _stash,
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )

    html = re.sub(r"\n[ \t]+", "\n", html)
    html = re.sub(r"\n{2,}", "\n", html)

    return re.sub(r"\x00(\d+)\x00", lambda m: placeholders[int(m.group(1))], html)


class InstagramSiteGenerator:
    """
    Class for generating the static website from processed Instagram data.

    This class handles:
    - Creating HTML using templates
    - Copying static assets (CSS, JS)
    - Verifying the completeness of the output
    """

    def __init__(self, data_package, output_dir, template_dir=None, static_dir=None,
                 gtag_id=None, theme_dir=None):
        """
        Initialize the generator with data and path options.

        The package is source-shaped (schema v2): everything imported lives
        under `sources`, keyed by importer name. A v1 package is migrated on
        the way in, so callers holding old data still work.

        `theme_dir` is an optional overlay for site-specific customisation.
        Templates in `<theme_dir>/templates` shadow same-named defaults (only
        the files that differ need to exist there), and static assets in
        `<theme_dir>/static` are copied on top of the defaults after them,
        so a same-named theme file wins. `theme_dir=None` leaves behaviour
        byte-identical to a build without a theme.
        """
        self.data_package = migrate_sidecar(data_package)
        self.output_dir = Path(output_dir)
        self.gtag_id = gtag_id  # Store the Google tag ID
        self.cities = {}  # Populated by generate() from city_tags

        # Handles onto the sources this build has. Read these rather than
        # reaching into data_package: a missing source is an empty dict, so
        # every page generator can ask "do I have content?" without each
        # caller repeating the same .get() chains.
        self.sources = self.data_package.get("sources") or {}
        self.instagram = self.sources.get("instagram") or {}
        self.posts = self.instagram.get("posts") or {}
        self.stories = self.instagram.get("stories") or {}
        self.flickr = self.sources.get("flickr") or {}
        self.flickr_items = self.flickr.get("items") or {}

        # Find template directory
        if template_dir is None:
            # Try to find templates relative to this file or common locations
            module_dir = Path(__file__).parent
            template_dir = module_dir / "templates"

            if not template_dir.exists():
                for path in [
                    Path("templates"),
                    Path("./templates"),
                    Path("../templates"),
                ]:
                    if path.exists():
                        template_dir = path
                        break

        # Find static directory
        if static_dir is None:
            module_dir = Path(__file__).parent
            static_dir = module_dir / "static"

            if not static_dir.exists():
                for path in [Path("static"), Path("./static"), Path("../static")]:
                    if path.exists():
                        static_dir = path
                        break

        self.template_dir = Path(template_dir)
        self.static_dir = Path(static_dir)
        self.theme_dir = Path(theme_dir) if theme_dir else None

        print(f"Using template directory: {self.template_dir}")
        print(f"Using static directory: {self.static_dir}")
        if self.theme_dir:
            print(f"Using theme directory: {self.theme_dir}")

        # Set up Jinja environment. With a theme, its templates shadow the
        # defaults: ChoiceLoader tries the theme dir first, then falls through.
        template_loaders = []
        if self.theme_dir:
            theme_templates = self.theme_dir / "templates"
            if theme_templates.is_dir():
                template_loaders.append(FileSystemLoader(str(theme_templates)))
        template_loaders.append(FileSystemLoader(str(self.template_dir)))
        loader = template_loaders[0] if len(template_loaders) == 1 else ChoiceLoader(template_loaders)
        self.jinja_env = Environment(loader=loader, autoescape=True)
        # Thousand separators for the large counts in the nav
        self.jinja_env.filters["commas"] = lambda n: f"{n:,}"

    def generate(self):
        """Generate the complete static website and verify output."""
        try:
            # Create output directory
            self.output_dir.mkdir(parents=True, exist_ok=True)

            # Create CSS and JS directories in output
            (self.output_dir / "css").mkdir(exist_ok=True)
            (self.output_dir / "js").mkdir(exist_ok=True)

            # Copy static assets
            self._copy_static_assets()

            # Group tagged content by city (empty when no tags file exists)
            self.cities = self._build_cities()

            # Write the shared post/story data scripts the pages load
            self._write_browser_data()

            # The Instagram posts grid lives at posts.html, when there is
            # Instagram content to fill it.
            if self.posts or self.stories:
                self._generate_html()

            # Generate stories HTML if we have stories data
            if self.stories:
                self._generate_stories_html()

            # index.html is the timeline — the site's home page. It spans every
            # source, so it is gated on content from ANY of them (not on
            # Instagram, which once left a Flickr-only site with a dead "days"
            # link), and it exists for every non-empty site — so index.html
            # always resolves without needing a redirect stub.
            if self._has_content():
                self._generate_timeline_html()

            # Generate the Flickr section when an import is present
            if self.flickr_items:
                self._write_flickr_browser_data()
                self._generate_flickr_html()
                self._generate_tags_html()
                self._generate_albums_html()

            # Generate the cities page when anything is tagged
            if self.cities:
                self._generate_cities_html()

            # Generate the map page when anything is geotagged
            if self._geotagged_count():
                self._generate_map_html()

            # The editor is also gated on any source: it owns the site bio,
            # which every flavor needs to be able to edit.
            if self._has_content():
                self._generate_edit_html()

            # Write the machine-readable sidecar used by --merge
            self._write_data_json()

            print(f"Website successfully generated at {self.output_dir}")
            return True

        except Exception as e:
            print(f"Error generating website: {str(e)}")
            return False

    def _has_content(self):
        """True when any source actually imported something."""
        return bool(self.posts or self.stories or self.flickr_items)

    def _write_data_json(self):
        """
        Write the full data package to a data.json sidecar in the output.

        Later --merge runs read this to know what the site already contains
        (and to carry settings like the gtag ID forward) without having to
        parse the generated HTML.

        Schema v2: every import lives under "sources". Nothing derivable is
        stored — counts and the site identity are computed at render time, so
        they cannot drift out of step with the data they describe.
        """
        sources = {}
        for key, section in self.sources.items():
            section = dict(section)
            if key == "instagram":
                # Drop empty optional fields to keep the sidecar small
                section["posts"] = _compact_entries(section.get("posts") or {})
                section["stories"] = _compact_entries(section.get("stories") or {})
            sources[key] = section

        sidecar = {
            "schema_version": SCHEMA_VERSION,
            "location": self.data_package.get("location") or {"location": "Unknown"},
            "sources": sources,
            "settings": {
                "gtag_id": self.gtag_id,
                "generated_at": datetime.datetime.now().strftime("%Y-%m-%d"),
                "schema_version": SCHEMA_VERSION,
            },
        }

        with open(self.output_dir / "data.json", "w", encoding="utf-8") as f:
            json.dump(sidecar, f, ensure_ascii=False)

        print(f"Wrote data sidecar: {self.output_dir / 'data.json'}")

    def _write_browser_data(self):
        """
        Write the post/story data as shared classic scripts that set
        window.postData / window.storiesData. Every page that needs the data
        loads these once (cached across pages) instead of inlining its own
        copy, and it works over file:// where fetch() would not.
        """
        posts = _compact_entries(self.posts)
        stories = _compact_entries(self.stories)

        # Enrich each entry with the thumbnail the browser needs to rebuild the
        # tile image for on-demand timeline months, mirroring the same media
        # resolution used by _post_tile_ctx / _story_tile_ctx. These are fresh
        # compacted copies, so nothing leaks into the in-memory package or the
        # data.json sidecar (which compacts separately).
        for entry in posts.values():
            key, val = _thumb_field(self._get_display_media(entry)["url"])
            if key:
                entry[key] = val
            # Poster (first-frame thumbnail) per video media item, so the modal
            # shows a still instead of a blank box before playback. Keyed by
            # media index; browser-only (never data.json), like th/dm.
            posters = {}
            for idx, media in enumerate(entry.get("m", [])):
                if media and re.search(r"\.(mp4|mov|avi|webm)$", media, re.I):
                    thumb = "thumbnails/" + hashlib.md5(media.encode()).hexdigest() + ".webp"
                    if os.path.exists(os.path.join(self.output_dir, thumb)):
                        posters[idx] = thumb
            if posters:
                entry["vp"] = posters
        for entry in stories.values():
            # story_thumb is a server-only field (no browser code reads it); its
            # resolved value is captured into th/dm below, so drop it from the
            # browser copy to avoid shipping the path twice. data.json keeps it.
            story_thumb = entry.pop("story_thumb", None)
            if story_thumb and os.path.exists(
                os.path.join(self.output_dir, story_thumb)
            ):
                url = story_thumb
            else:
                url = self._get_display_media(entry)["url"]
            key, val = _thumb_field(url)
            if key:
                entry[key] = val

        js_dir = self.output_dir / "js"
        with open(js_dir / "posts-data.js", "w", encoding="utf-8") as f:
            f.write("window.postData = " + _as_json_parse(posts) + ";\n")
        with open(js_dir / "stories-data.js", "w", encoding="utf-8") as f:
            f.write("window.storiesData = " + _as_json_parse(stories) + ";\n")

        # Remove the old combined file if regenerating a pre-split site
        stale = js_dir / "timeline-data.js"
        if stale.exists():
            stale.unlink()

        print(f"Wrote browser data: {js_dir / 'posts-data.js'}, {js_dir / 'stories-data.js'}")

    def _copy_static_assets(self):
        """Copy CSS and JS files to the output directory."""
        # Copy CSS
        css_dir = self.static_dir / "css"
        if css_dir.exists():
            for css_file in css_dir.glob("*.css"):
                shutil.copy2(css_file, self.output_dir / "css" / css_file.name)
                print(f"Copied CSS: {css_file.name}")

        # Copy JS
        js_dir = self.static_dir / "js"
        if js_dir.exists():
            for js_file in js_dir.glob("*.js"):
                shutil.copy2(js_file, self.output_dir / "js" / js_file.name)
                print(f"Copied JS: {js_file.name}")
            
            # Ensure stories.js exists, create it if not
            stories_js = js_dir / "stories.js"
            if not stories_js.exists():
                # Create a minimal stories.js file if it doesn't exist
                with open(stories_js, "w") as f:
                    f.write("// Stories viewer functionality\n")
                print(f"Created placeholder: stories.js")
            
            # Copy stories.js to output
            shutil.copy2(stories_js, self.output_dir / "js" / "stories.js")
            print(f"Copied JS: stories.js")

        # Copy vendored libraries (e.g. Leaflet for the cities map)
        vendor_dir = self.static_dir / "vendor"
        if vendor_dir.exists():
            shutil.copytree(vendor_dir, self.output_dir / "vendor", dirs_exist_ok=True)
            print("Copied vendor assets")

        # Overlay theme static assets on top of the defaults. Same-named files
        # win; the theme only needs to carry the assets that actually differ.
        if self.theme_dir:
            self._overlay_theme_static()

    def _overlay_theme_static(self):
        """Copy `<theme_dir>/static` over the just-copied default assets.

        Mirrors the default sub-structure (css/, js/, vendor/, and any other
        top-level dirs or files the theme adds). Every part is optional.
        """
        theme_static = self.theme_dir / "static"
        if not theme_static.is_dir():
            return
        for item in sorted(theme_static.iterdir()):
            dest = self.output_dir / item.name
            if item.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)
            print(f"Overlaid theme static: {item.name}")

    def _generate_html(self):
        """Generate posts.html (the Instagram posts grid)."""
        # Post/story data is loaded from the shared js/posts-data.js file
        # (written by _write_browser_data), not inlined.
        template = self.jinja_env.get_template("posts.html")
        html_content = template.render(
            grid_html=self._render_grid(),
            **self._page_context(),
        )

        with open(self.output_dir / "posts.html", "w", encoding="utf-8") as f:
            f.write(_minify_html(html_content))

        print(f"Generated HTML file: {self.output_dir / 'posts.html'}")

    def _render_grid(self):
        """Render the grid HTML using the grid.html template."""
        posts_data = self.posts
        lazy_after = 30  # Start lazy loading after this many posts

        # Check if posts_data is valid
        if not posts_data or not isinstance(posts_data, dict):
            print("Warning: No valid posts data found for grid rendering")
            return ""

        # Prepare data for the grid template
        grid_posts = []
        for i, (timestamp, post) in enumerate(posts_data.items()):
            # Determine which media to use for the grid thumbnail
            display_media = self._get_display_media(post, i >= lazy_after)

            grid_posts.append(
                {
                    "index": post["i"],
                    "timestamp": str(timestamp),
                    "display_media": display_media["url"],
                    "is_video": display_media["is_video"],
                    "media_count": len(post["m"]),
                    "likes": post.get("l", ""),
                    "place": post.get("pl", ""),
                    "lazy_load": Markup(' loading="lazy"') if i >= lazy_after else "",
                }
            )

        # Render grid template
        grid_template = self.jinja_env.get_template("grid.html")
        return grid_template.render(posts=grid_posts)

    def _get_display_media(self, post, use_lazy_loading=False):
        """Determine which media to use for the grid thumbnail."""
        result = {"url": "", "is_video": False}

        if not post["m"] or len(post["m"]) == 0:
            return result

        first_media = post["m"][0]
        result["url"] = first_media

        # Check if first media is a video
        result["is_video"] = bool(
            re.search(r"\.(mp4|mov|avi|webm)$", first_media, re.I)
            if first_media
            else False
        )

        # Check if we have a thumbnail for this media
        if first_media:
            thumb_filename = hashlib.md5(first_media.encode()).hexdigest() + ".webp"
            thumb_path = f"thumbnails/{thumb_filename}"

            if os.path.exists(os.path.join(self.output_dir, thumb_path)):
                # Use the thumbnail instead of the original
                result["url"] = thumb_path
            elif not result["is_video"]:
                # Check if we have a WebP version of the original image
                webp_path = re.sub(
                    r"\.(jpg|jpeg|png|gif)$", ".webp", first_media, flags=re.I
                )
                if os.path.exists(os.path.join(self.output_dir, webp_path)):
                    result["url"] = webp_path

            # If it's a video, look for a thumbnail among all media items
            if (
                result["is_video"] and result["url"] == first_media
            ):  # No thumbnail found yet
                for media_item in post["m"]:
                    if re.search(r"\.(jpg|jpeg|png|webp|gif)$", media_item, re.I):
                        # Check if we have a thumbnail for this image
                        img_thumb_filename = (
                            hashlib.md5(media_item.encode()).hexdigest() + ".webp"
                        )
                        img_thumb_path = f"thumbnails/{img_thumb_filename}"

                        if os.path.exists(
                            os.path.join(self.output_dir, img_thumb_path)
                        ):
                            result["url"] = img_thumb_path
                            break
                        else:
                            result["url"] = media_item
                            break

                # If no thumbnail found, use a SVG placeholder
                if result["url"] == first_media:
                    # Create a simple SVG with a play button
                    svg = (
                        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400" viewBox="0 0 400 400">'
                        '<rect width="400" height="400" fill="#333333"/>'
                        '<circle cx="200" cy="200" r="60" fill="#ffffff" fill-opacity="0.8"/>'
                        '<polygon points="180,160 180,240 240,200" fill="#333333"/>'
                        "</svg>"
                    )

                    # Encode the SVG properly for use in an img src attribute
                    result["url"] = (
                        "data:image/svg+xml;base64,"
                        + base64.b64encode(svg.encode()).decode()
                    )

        return result
    def _generate_stories_html(self):
        """Generate a separate HTML file for stories."""
        stories_data = self.stories
        
        if not stories_data:
            print("No stories data found, skipping stories.html generation")
            return
        
        # Prepare stories data for the template
        stories_list = []
        lazy_after = 30  # Start lazy loading after this many stories
        
        for i, (timestamp, story) in enumerate(stories_data.items()):
            # Check for story-specific thumbnail
            story_thumb = story.get("story_thumb", None)
            
            if story_thumb and os.path.exists(os.path.join(self.output_dir, story_thumb)):
                # Use the 9:16 story thumbnail
                media_url = story_thumb
            else:
                # Fall back to regular thumbnail or original media
                display_media = self._get_display_media(story, i >= lazy_after)
                media_url = display_media["url"]
            
            # Determine if it's a video
            is_video = bool(re.search(r"\.(mp4|mov|avi|webm)$", story["m"][0], re.I)) if story["m"] else False
            
            stories_list.append({
                "index": story["i"],
                "media": media_url,
                "is_video": is_video,
                "date": story.get("d", ""),
                "caption": story.get("tt", ""),
                "timestamp": timestamp,
                "lazy_load": Markup(' loading="lazy"') if i >= lazy_after else "",
                "original_media": story["m"][0] if story["m"] else "",  # Include original media path
            })
        
        # Render the stories template
        template = self.jinja_env.get_template("stories_page.html")
        html_content = template.render(
            stories=stories_list,
            **self._page_context(),
        )

        # Write HTML file
        with open(self.output_dir / "stories.html", "w", encoding="utf-8") as f:
            f.write(_minify_html(html_content))

        print(f"Generated stories HTML file: {self.output_dir / 'stories.html'}")

    @staticmethod
    def _day_of(timestamp_key):
        """Calendar day (UTC) for a posts/stories dict key."""
        return datetime.datetime.utcfromtimestamp(int(timestamp_key)).date()

    def _timeline_day_count(self):
        """Number of distinct calendar days with a post, story, or Flickr
        item (all three appear on the timeline)."""
        posts = self.posts
        stories = self.stories
        flickr = self.flickr_items
        days = {self._day_of(k) for k in posts} | {
            self._day_of(k) for k in stories
        }
        days |= {
            datetime.datetime.utcfromtimestamp(e["t"]).date()
            for e in flickr.values()
            if e.get("m")
        }
        return len(days)

    def _post_tile_ctx(self, timestamp, post):
        """Template context for one post tile (shared by timeline/cities/editor)."""
        display_media = self._get_display_media(post)
        return {
            "index": post["i"],
            "timestamp": str(timestamp),
            "display_media": display_media["url"],
            "is_video": display_media["is_video"],
            "media_count": len(post["m"]),
            "place": post.get("pl", ""),
            "lazy_load": Markup(' loading="lazy"'),
        }

    def _story_tile_ctx(self, timestamp, story):
        """Template context for one story tile (shared by timeline/cities/editor)."""
        # Same 9:16 thumbnail fallback as the stories page
        story_thumb = story.get("story_thumb")
        if story_thumb and os.path.exists(os.path.join(self.output_dir, story_thumb)):
            media_url = story_thumb
        else:
            media_url = self._get_display_media(story)["url"]

        is_video = (
            bool(re.search(r"\.(mp4|mov|avi|webm)$", story["m"][0], re.I))
            if story["m"]
            else False
        )
        return {
            "index": story["i"],
            "timestamp": str(timestamp),
            "media": media_url,
            "is_video": is_video,
            "original_media": story["m"][0] if story["m"] else "",
            "lazy_load": Markup(' loading="lazy"'),
        }

    def _build_day_list(self, include_flickr=False):
        """
        Group all posts and stories (and, for the timeline, Flickr items) by
        calendar day, newest day first. Source dicts are already sorted
        newest-first, so per-day order falls out of encounter order. The
        first ~30 tiles load eagerly. The editor keeps include_flickr=False
        (it only tags Instagram content).
        """
        posts_data = self.posts
        stories_data = self.stories

        def _bucket(day):
            return days.setdefault(
                day, {"posts": [], "stories": [], "flickr": []}
            )

        days = {}
        for timestamp, post in posts_data.items():
            _bucket(self._day_of(timestamp))["posts"].append(
                self._post_tile_ctx(timestamp, post)
            )

        for timestamp, story in stories_data.items():
            _bucket(self._day_of(timestamp))["stories"].append(
                self._story_tile_ctx(timestamp, story)
            )

        if include_flickr:
            flickr = self.flickr_items
            for pid, entry in sorted(
                flickr.items(), key=lambda kv: kv[1]["i"]
            ):
                if not entry.get("m"):
                    continue
                day = datetime.datetime.utcfromtimestamp(entry["t"]).date()
                _bucket(day)["flickr"].append(
                    self._flickr_tile_ctx(pid, entry)
                )

        lazy_after = 30
        tile_counter = 0
        day_list = []

        for day in sorted(days.keys(), reverse=True):
            bucket = days[day]
            for tile in bucket["posts"] + bucket["stories"] + bucket["flickr"]:
                if tile_counter < lazy_after:
                    tile["lazy_load"] = ""
                tile_counter += 1
            day_list.append(
                {
                    "heading": day.strftime("%B %d, %Y"),
                    "month_key": day.strftime("%Y-%m"),
                    "month_label": day.strftime("%B %Y"),
                    "posts": bucket["posts"],
                    "stories": bucket["stories"],
                    "flickr": bucket["flickr"],
                    "post_count": len(bucket["posts"]),
                    "story_count": len(bucket["stories"]),
                    "flickr_count": len(bucket["flickr"]),
                }
            )
        return day_list

    @staticmethod
    def _year_span(epochs):
        """'(earliest)-(latest)' year label for a list of unix epochs."""
        if not epochs:
            return ""
        years = sorted(
            {datetime.datetime.utcfromtimestamp(t).year for t in epochs}
        )
        if years[0] == years[-1]:
            return str(years[0])
        return f"{years[0]}-{years[-1]}"

    def _nav_row_instagram(self):
        """Nav row for the Instagram source, or None when it has no content."""
        if not (self.posts or self.stories):
            return None
        epochs = [int(t) for t in self.posts] + [int(t) for t in self.stories]
        profile = (self.instagram.get("profile") or {})
        links = [("posts", "posts.html", len(self.posts), "posts")]
        if self.stories:
            links.append(("stories", "stories.html", len(self.stories), "stories"))
        return {
            "label": f"Instagram {profile.get('username', '')} "
                     f"({self._year_span(epochs)}):",
            "links": links,
        }

    def _nav_row_flickr(self):
        """Nav row for the Flickr source, or None when it has no content."""
        if not self.flickr_items:
            return None
        alias = (self.flickr.get("profile") or {}).get("username") \
            or self.flickr.get("meta", {}).get("path_alias", "")
        epochs = [e["t"] for e in self.flickr_items.values()]
        links = [("photos", "flickr.html", len(self.flickr_items), "photos")]
        tags = self._flickr_tags()
        if tags:
            links.append(("tags", "tags.html", len(tags), "tags"))
        albums = self.flickr.get("albums") or {}
        if albums:
            links.append(("albums", "albums.html", len(albums), "albums"))
        return {
            "label": f"Flickr {alias} ({self._year_span(epochs)}):",
            "links": links,
        }

    # One builder per source, in the order the rows should appear. Adding a
    # source's nav presence is an entry here plus its builder — the template
    # loops over whatever this produces and needs no edit.
    NAV_ROW_BUILDERS = ["_nav_row_instagram", "_nav_row_flickr"]

    def _geotagged_count(self):
        """
        How many items across all sources carry usable coordinates.

        Drives the map page and its nav link. Stories are excluded
        deliberately: only a handful ever carry EXIF coordinates, and they
        would drag the story viewer onto the map page for a rounding error's
        worth of pins.
        """
        def has_geo(entry):
            return entry.get("la") not in ("", None) and entry.get("lo") not in ("", None)

        total = sum(1 for e in self.posts.values() if has_geo(e))
        total += sum(1 for e in self.flickr_items.values() if has_geo(e))
        return total

    def _flickr_tags(self):
        tags = set()
        for entry in self.flickr_items.values():
            tags.update(entry.get("tg") or [])
        return tags

    def _page_context(self):
        """Template context shared by every page's header/nav (_nav.html)."""
        # Identity is derived from the sources on every render rather than
        # stored, so it cannot go stale when a source is added or refreshed.
        profile_info = site_identity(self.sources)
        cities = getattr(self, "cities", {}) or {}
        pin_count = self._geotagged_count()
        flickr_tags = self._flickr_tags()
        flickr_albums = self.flickr.get("albums") or {}

        # Bio: the editor's exported bio (city_tags.json) is authoritative
        # when the key is present; otherwise the identity source's bio
        city_tags = self.data_package.get("city_tags") or {}
        bio = profile_info.get("bio", "")
        if city_tags.get("bio") is not None:
            bio = city_tags["bio"]

        nav_rows = []
        for builder in self.NAV_ROW_BUILDERS:
            row = getattr(self, builder)()
            if row:
                nav_rows.append(row)

        return {
            "username": profile_info.get("username", "Unknown"),
            "bio": bio,
            "profile": profile_info,
            "nav_rows": nav_rows,
            "post_count": len(self.posts),
            "story_count": len(self.stories),
            "has_stories": bool(self.stories),
            "has_instagram": bool(self.posts or self.stories),
            "day_count": self._timeline_day_count(),
            "has_cities": bool(cities),
            "city_count": len(cities),
            "has_pins": pin_count > 0,
            "pin_count": pin_count,
            "has_flickr": bool(self.flickr_items),
            "flickr_count": len(self.flickr_items),
            "has_flickr_tags": bool(flickr_tags),
            "flickr_tag_count": len(flickr_tags),
            "has_flickr_albums": bool(flickr_albums),
            "flickr_album_count": len(flickr_albums),
            "generation_date": datetime.datetime.now().strftime("%Y-%m-%d"),
            "gtag_id": self.gtag_id,
        }

    def _build_month_list(self, include_flickr=False):
        """
        Group the day list into months (newest first) for paginated pages.
        """
        months = []
        for day in self._build_day_list(include_flickr=include_flickr):
            if not months or months[-1]["key"] != day["month_key"]:
                months.append(
                    {
                        "key": day["month_key"],
                        "label": day["month_label"],
                        "days": [],
                        "item_count": 0,
                    }
                )
            months[-1]["days"].append(day)
            months[-1]["item_count"] += (
                day["post_count"] + day["story_count"] + day["flickr_count"]
            )
        return months

    def _generate_timeline_html(self):
        """
        Generate index.html: the timeline (the site's home page) — all posts,
        stories and Flickr items grouped by calendar day, newest day first,
        each kind in its own row per day, paginated month by month.
        """
        # The timeline hosts all three viewers, which read window.postData /
        # window.storiesData / window.flickrData from the shared data scripts.
        months = self._build_month_list(include_flickr=True)

        template = self.jinja_env.get_template("index.html")
        html_content = template.render(months=months, **self._page_context())

        with open(self.output_dir / "index.html", "w", encoding="utf-8") as f:
            f.write(_minify_html(html_content))

        print(f"Generated timeline HTML file: {self.output_dir / 'index.html'}")

    # -- Flickr section ----------------------------------------------------
    # Flickr entries are keyed by photo id (NOT timestamp — 46 public items
    # share a date_taken second) and rendered on their own page, separate
    # from the Instagram posts/stories.

    def _flickr_photopage(self, pid):
        alias = self.flickr.get("meta", {}).get(
            "path_alias", ""
        )
        return f"https://www.flickr.com/photos/{alias}/{pid}/"

    def _flickr_tile_ctx(self, pid, entry):
        """Template context for one flickr tile (parity: mmFlickrTile in
        static/js/flickr-months.js — change both together)."""
        m0 = entry.get("m", [None])[0]
        thumb = ""
        if m0:
            thumb_name = hashlib.md5(m0.encode()).hexdigest() + ".webp"
            thumb_path = f"thumbnails/{thumb_name}"
            thumb = (
                thumb_path
                if os.path.exists(os.path.join(self.output_dir, thumb_path))
                else m0
            )
        return {
            "id": pid,
            "display_media": thumb,
            "is_video": bool(entry.get("vd")),
            "title": entry.get("tt", ""),
            "photopage": self._flickr_photopage(pid),
            "lazy_load": Markup(' loading="lazy"'),
        }

    def _generate_flickr_html(self):
        """
        Generate flickr.html: a posts.html-style grid of every item. Only
        the first chunk is server-rendered (30,335 tiles would be a ~7 MB
        page); flickr-grid.js appends the rest progressively from
        window.flickrData as the user scrolls, and handles sorting.
        """
        items = self.flickr_items
        eager = 30       # load immediately, like posts.html
        server_chunk = 60  # server-rendered so the grid paints during parse

        first_tiles = []
        skipped = 0
        for pid, entry in sorted(items.items(), key=lambda kv: kv[1]["i"]):
            if not entry.get("m"):
                skipped += 1
                continue
            if len(first_tiles) >= server_chunk:
                break
            tile = self._flickr_tile_ctx(pid, entry)
            if len(first_tiles) < eager:
                tile["lazy_load"] = ""
            first_tiles.append(tile)
        if skipped:
            print(f"Flickr page: {skipped} items have no media yet; not shown")

        template = self.jinja_env.get_template("flickr.html")
        html_content = template.render(
            flickr_tiles=first_tiles,
            **self._page_context(),
        )
        with open(self.output_dir / "flickr.html", "w", encoding="utf-8") as f:
            f.write(_minify_html(html_content))
        print(f"Generated flickr HTML file: {self.output_dir / 'flickr.html'}")

    def _generate_tags_html(self):
        """
        Generate tags.html: the Flickr tag navigator. The chips and per-tag
        grids are built entirely client-side by tags.js from
        window.flickrData, so this only renders the page shell.
        """
        ctx = self._page_context()
        if not ctx["has_flickr_tags"]:
            print("No Flickr tags found; skipping tags.html")
            return
        template = self.jinja_env.get_template("tags.html")
        html_content = template.render(**ctx)
        with open(self.output_dir / "tags.html", "w", encoding="utf-8") as f:
            f.write(_minify_html(html_content))
        print(f"Generated tags HTML file: {self.output_dir / 'tags.html'}")

    def _generate_map_html(self):
        """
        Render map.html: a shell page. Every pin is plotted client-side from
        the la/lo already present in posts-data.js / flickr-data.js, so this
        writes no data of its own.
        """
        template = self.jinja_env.get_template("map.html")
        html_content = template.render(**self._page_context())
        output_path = self.output_dir / "map.html"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(_minify_html(html_content))
        print(f"Generated map HTML file: {output_path}")

    def _generate_albums_html(self):
        """
        Generate albums.html: the Flickr album navigator. Like tags.html,
        the chips and per-album grids are built client-side by albums.js
        from window.flickrData + window.flickrAlbums; this renders the shell.
        """
        ctx = self._page_context()
        if not ctx["has_flickr_albums"]:
            print("No Flickr albums found; skipping albums.html")
            return
        template = self.jinja_env.get_template("albums.html")
        html_content = template.render(**ctx)
        with open(self.output_dir / "albums.html", "w", encoding="utf-8") as f:
            f.write(_minify_html(html_content))
        print(f"Generated albums HTML file: {self.output_dir / 'albums.html'}")

    def _write_flickr_browser_data(self):
        """
        Write js/flickr-data.js: window.flickrData / flickrAlbums /
        flickrMeta. Browser-only fields th/dm (tile thumb) and vp (video
        poster) are added to fresh copies here — never to data.json.
        """
        flickr = self.flickr
        items = {}
        for pid, entry in (flickr.get("items") or {}).items():
            m0 = entry.get("m", [None])[0]
            if not m0:
                continue  # no media source yet — not in the browser data
            copy = dict(entry)
            thumb_name = hashlib.md5(m0.encode()).hexdigest() + ".webp"
            thumb_path = f"thumbnails/{thumb_name}"
            if os.path.exists(os.path.join(self.output_dir, thumb_path)):
                key, val = _thumb_field(thumb_path)
            else:
                key, val = _thumb_field(m0)
            if key:
                copy[key] = val
            if copy.get("vd") and os.path.exists(
                os.path.join(self.output_dir, thumb_path)
            ):
                copy["vp"] = thumb_path
            items[pid] = copy

        payload = {
            "path_alias": flickr.get("meta", {}).get("path_alias", ""),
        }
        js_dir = self.output_dir / "js"
        with open(js_dir / "flickr-data.js", "w", encoding="utf-8") as f:
            f.write("window.flickrData = " + _as_json_parse(items) + ";\n")
            f.write(
                "window.flickrAlbums = "
                + _as_json_parse(flickr.get("albums") or {})
                + ";\n"
            )
            f.write("window.flickrMeta = " + _as_json_parse(payload) + ";\n")
        print(f"Wrote flickr browser data: {js_dir / 'flickr-data.js'}")

    def _build_cities(self):
        """
        Group tagged posts/stories/Flickr items by city from the city_tags
        data.

        Returns {name: {"posts": [tile_ctx...], "flickr": [...],
                        "stories": [...], "lat": float|None,
                        "lng": float|None, "newest": int}}
        with items sorted newest-first per city (favourites first).
        Coordinates come from a manual override in the tags file when
        present, otherwise the median of the tagged items' coordinates —
        Flickr items contribute to that median like any other.
        """
        tags = self.data_package.get("city_tags") or {}
        if not (tags.get("posts") or tags.get("stories") or tags.get("flickr")):
            return {}

        cities = {}
        skipped = 0
        raw = {}  # name -> {"posts": [(key, entry)], "stories", "flickr", "coords"}

        def bucket_for(name):
            return raw.setdefault(
                name, {"posts": [], "stories": [], "flickr": [], "coords": []}
            )

        def note_coords(bucket, entry):
            lat, lng = entry.get("la"), entry.get("lo")
            if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
                bucket["coords"].append((lat, lng))

        for kind in ("posts", "stories"):
            # Freshly loaded posts are keyed by int timestamps while
            # JSON-round-tripped data uses strings; normalize for lookup
            source = {
                str(k): v
                for k, v in (getattr(self, kind) or {}).items()
            }
            for ts, name in (tags.get(kind) or {}).items():
                name = (name or "").strip()
                entry = source.get(str(ts))
                if not name or entry is None:
                    skipped += 1
                    continue
                bucket = bucket_for(name)
                bucket[kind].append((str(ts), entry))
                note_coords(bucket, entry)

        # Flickr items are keyed by photo id, not timestamp — no numeric
        # normalization applies, and ordering has to come from the entry's
        # import index rather than from the key.
        for pid, name in (tags.get("flickr") or {}).items():
            name = (name or "").strip()
            entry = self.flickr_items.get(str(pid))
            if not name or entry is None:
                skipped += 1
                continue
            bucket = bucket_for(name)
            bucket["flickr"].append((str(pid), entry))
            note_coords(bucket, entry)

        if skipped:
            print(f"Warning: {skipped} city tags reference unknown or empty items; ignored")

        overrides = tags.get("cities") or {}
        favorites = tags.get("favorites") or {}
        fav_posts = favorites.get("posts") or {}
        fav_stories = favorites.get("stories") or {}
        fav_flickr = favorites.get("flickr") or {}

        for name, bucket in raw.items():
            # Favourited items first, then reverse-chronological within
            # each group
            bucket["posts"].sort(
                key=lambda p: (not fav_posts.get(p[0]), -int(p[0]))
            )
            bucket["stories"].sort(
                key=lambda p: (not fav_stories.get(p[0]), -int(p[0]))
            )
            # "i" is the stable newest-first import index; the photo id in
            # p[0] carries no chronology, so it must not be sorted on.
            bucket["flickr"].sort(
                key=lambda p: (not fav_flickr.get(p[0]), p[1].get("i", 0))
            )

            override = overrides.get(name) or {}
            if isinstance(override.get("lat"), (int, float)) and isinstance(
                override.get("lng"), (int, float)
            ):
                lat, lng = override["lat"], override["lng"]
            elif bucket["coords"]:
                lat = statistics.median(c[0] for c in bucket["coords"])
                lng = statistics.median(c[1] for c in bucket["coords"])
            else:
                lat = lng = None

            post_tiles = []
            for ts, e in bucket["posts"]:
                tile = self._post_tile_ctx(ts, e)
                tile["is_fav"] = bool(fav_posts.get(ts))
                post_tiles.append(tile)

            story_tiles = []
            for ts, e in bucket["stories"]:
                tile = self._story_tile_ctx(ts, e)
                tile["is_fav"] = bool(fav_stories.get(ts))
                story_tiles.append(tile)

            flickr_tiles = []
            for pid, e in bucket["flickr"]:
                tile = self._flickr_tile_ctx(pid, e)
                tile["is_fav"] = bool(fav_flickr.get(pid))
                flickr_tiles.append(tile)

            all_ts = [int(ts) for ts, _ in bucket["posts"] + bucket["stories"]]
            all_ts += [e.get("t", 0) for _, e in bucket["flickr"]]
            cities[name] = {
                "posts": post_tiles,
                "flickr": flickr_tiles,
                "stories": story_tiles,
                "lat": lat,
                "lng": lng,
                "text": (overrides.get(name) or {}).get("text", ""),
                "newest": max(all_ts) if all_ts else 0,
            }
        return cities

    def _generate_cities_html(self):
        """
        Generate cities.html: per-city sections of tagged posts/stories,
        a clickable city index, and a Leaflet map of city locations.
        """
        # Alphabetical by city name
        ordered = sorted(self.cities.items(), key=lambda kv: kv[0].casefold())

        seen_slugs = set()
        city_list = []
        markers = []
        for name, city in ordered:
            slug = _slugify(name)
            candidate = slug
            counter = 2
            while candidate in seen_slugs:
                candidate = f"{slug}-{counter}"
                counter += 1
            slug = candidate
            seen_slugs.add(slug)

            city_list.append(
                {
                    "name": name,
                    "slug": slug,
                    "text": city.get("text", ""),
                    "posts": city["posts"],
                    "flickr": city.get("flickr", []),
                    "stories": city["stories"],
                    "post_count": len(city["posts"]),
                    "flickr_count": len(city.get("flickr", [])),
                    "story_count": len(city["stories"]),
                }
            )
            if city["lat"] is not None and city["lng"] is not None:
                markers.append(
                    {
                        "name": name,
                        "slug": slug,
                        "lat": city["lat"],
                        "lng": city["lng"],
                        "posts": len(city["posts"]),
                        "flickr": len(city.get("flickr", [])),
                        "stories": len(city["stories"]),
                    }
                )

        template = self.jinja_env.get_template("cities.html")
        html_content = template.render(
            cities=city_list,
            city_markers_json=_escape_inline_json(markers),
            **self._page_context(),
        )

        with open(self.output_dir / "cities.html", "w", encoding="utf-8") as f:
            f.write(_minify_html(html_content))

        print(f"Generated cities HTML file: {self.output_dir / 'cities.html'}")

    def _generate_edit_html(self):
        """
        Generate edit.html: the standalone editor used to tag posts and
        stories with city names. Not linked from the public site nav.
        """
        tags = self.data_package.get("city_tags") or {
            "version": 1,
            "posts": {},
            "stories": {},
            "flickr": {},
            "cities": {},
            "favorites": {"posts": {}, "stories": {}, "flickr": {}},
        }
        tags = dict(tags)  # embed-only copy; don't mutate the package
        if "favorites" not in tags:
            tags["favorites"] = {"posts": {}, "stories": {}, "flickr": {}}
        # Embed the EFFECTIVE bio so the editor's textarea starts from what
        # the site currently shows (exported city_tags.json then becomes the
        # authoritative source for it)
        if tags.get("bio") is None:
            tags["bio"] = site_identity(self.sources).get("bio", "")

        months = self._build_month_list()

        template = self.jinja_env.get_template("edit.html")
        html_content = template.render(
            months=months,
            city_tags_json=_escape_inline_json(tags),
            **self._page_context(),
        )

        with open(self.output_dir / "edit.html", "w", encoding="utf-8") as f:
            f.write(_minify_html(html_content))

        print(f"Generated editor HTML file: {self.output_dir / 'edit.html'}")

        # The city-text editor page shares the same embedded tags; its city
        # list is built client-side from that state
        template = self.jinja_env.get_template("edit-cities.html")
        html_content = template.render(
            city_tags_json=_escape_inline_json(tags),
            **self._page_context(),
        )

        with open(self.output_dir / "edit-cities.html", "w", encoding="utf-8") as f:
            f.write(_minify_html(html_content))

        print(f"Generated editor HTML file: {self.output_dir / 'edit-cities.html'}")

        # The Flickr city-tagging page. Unlike the other editor pages it
        # builds its grid client-side from flickr-data.js — 30k items cannot
        # be server-rendered the way the Instagram tiles are.
        if self.flickr_items:
            template = self.jinja_env.get_template("edit-flickr.html")
            html_content = template.render(
                city_tags_json=_escape_inline_json(tags),
                **self._page_context(),
            )
            with open(self.output_dir / "edit-flickr.html", "w", encoding="utf-8") as f:
                f.write(_minify_html(html_content))
            print(f"Generated editor HTML file: {self.output_dir / 'edit-flickr.html'}")
