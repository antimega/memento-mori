# memento_mori/flickr.py
"""
Flickr archive importer.

Reads a Flickr data export (flickr_metadata/*.json + data-download-*/ media
folders), filters to the user's own PUBLIC items, and produces the id-keyed
"flickr" section of the data package. Fully local by design: media is stored
and served from the site like the Instagram content (hotlinking was considered
and rejected — see the plan; the site must outlive Flickr).

Key facts this module is built around (measured against the real export):
- Entries are keyed by Flickr photo id, NOT timestamp: 46 public items share
  a date_taken second with another and a ts-keyed dict would drop them.
- Every photo's metadata carries a direct original CDN URL (o-secret), so
  photos can be downloaded without the API. Videos cannot: their "original"
  URL serves a JPEG poster frame, and nothing in the export marks them as
  videos — only a local file extension or the API 'media' field can.
- geo lat/long are degrees x 1,000,000 as integer strings ("51561666").
- date_taken/"date_imported" are "YYYY-MM-DD HH:MM:SS" naive local stamps.
"""

import json
import re
import os
import html
from bisect import bisect_left
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from ftfy import fix_text


# Media extensions that mark a local export file as a video
_VIDEO_EXTS = ("mov", "mp4", "m4v", "avi", "webm")

# Local media filename -> photo id extraction, tried in order:
#   titled photos:   <slug>_<id>_o.<ext>   (also 26 legacy files with no ext)
#   untitled photos: <id>_<10-hex-secret>_o.<ext>
#   videos:          <slug>_<id>.<ext>     (no _o suffix)
_MEDIA_PATTERNS = (
    re.compile(r"_(\d+)_o(\.\w+)?$", re.I),
    re.compile(r"^(\d{6,})_[0-9a-f]{10}_o\.\w+$", re.I),
    re.compile(r"_(\d+)\.(%s)$" % "|".join(_VIDEO_EXTS), re.I),
)

# Instagram's 2011-2012 auto-cross-poster tag fingerprint
_IG_MACHINE_TAG = "uploaded:by=instagram"


class _HTMLToText(HTMLParser):
    """
    Flatten Flickr's limited description HTML to plain text: <br>/<p> become
    newlines and links become "label (url)". The result is rendered client-side
    via textContent into a white-space:pre-line container — never innerHTML.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._href = None
        self._link_text = []

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.parts.append("\n")
        elif tag == "a":
            self._href = dict(attrs).get("href")
            self._link_text = []

    def handle_endtag(self, tag):
        if tag == "p":
            self.parts.append("\n")
        elif tag == "a":
            label = "".join(self._link_text).strip()
            if self._href and label and label != self._href:
                self.parts.append(f"{label} ({self._href})")
            else:
                self.parts.append(label or self._href or "")
            self._href = None
            self._link_text = []

    def handle_data(self, data):
        if self._href is not None:
            self._link_text.append(data)
        else:
            self.parts.append(data)

    @classmethod
    def convert(cls, raw):
        if not raw:
            return ""
        p = cls()
        p.feed(raw)
        p.close()
        # Unclosed <a> at EOF: flush whatever was collected
        if p._href is not None:
            p.handle_endtag("a")
        text = "".join(p.parts)
        # Collapse >2 consecutive newlines, trim
        text = re.sub(r"\n{3,}", "\n\n", text)
        return fix_text(text).strip()


def _parse_flickr_date(value):
    """'YYYY-MM-DD HH:MM:SS' -> aware UTC datetime, or None."""
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
    except (TypeError, ValueError):
        return None


def _parse_geo(geo_list):
    """
    Flickr export geo: [{"latitude": "51561666", "longitude": "-1799667", ...}]
    — degrees x 1,000,000 as integer strings. Returns (lat, lng) or None.
    """
    if not geo_list:
        return None
    g = geo_list[0]
    try:
        lat = int(g["latitude"]) / 1_000_000
        lng = int(g["longitude"]) / 1_000_000
    except (KeyError, TypeError, ValueError):
        return None
    if lat == 0.0 or lng == 0.0:  # null island = junk
        return None
    return round(lat, 5), round(lng, 5)


class FlickrDataLoader:
    """Loads and filters the Flickr export's metadata."""

    def __init__(self, flickr_path, verbose=False):
        self.flickr_path = Path(flickr_path)
        self.meta_dir = self.flickr_path / "flickr_metadata"
        self.verbose = verbose
        if not self.meta_dir.is_dir():
            raise FileNotFoundError(
                f"No flickr_metadata directory in {self.flickr_path}"
            )

    def load_account(self):
        """
        Identity fields from account_profile.json.

        Beyond nsid/path_alias (needed for the API sweep and photopage URLs)
        this returns the fields that let Flickr supply the *site's* identity
        when it is the only source: real name, bio and website. Flickr's
        export has no avatar, so profile_picture stays empty.
        """
        path = self.meta_dir / "account_profile.json"
        with open(path, encoding="utf-8") as f:
            profile = json.load(f)
        return {
            "nsid": profile.get("nsid", ""),
            "path_alias": profile.get("path_alias")
            or profile.get("screen_name", ""),
            "real_name": profile.get("real_name", ""),
            "description": profile.get("description", ""),
            "website_url": profile.get("website_url", ""),
        }

    def load_items(self):
        """
        Parse every photo_<id>.json, keep only privacy == "public".

        Returns (items, aux):
          items: {id: entry} with the public fields (t, d, tt, ds, tg, al,
                 la, lo, v, f, lic) — i is assigned later, m by the media step.
          aux:   {id: {"original": url, "rotation": int, "imported": epoch,
                       "ig_tagged": bool}} — loader-internal, never serialized.
        """
        items = {}
        aux = {}
        privacy_counts = {}
        skipped_dates = []

        for path in sorted(self.meta_dir.glob("photo_*.json")):
            try:
                with open(path, encoding="utf-8") as f:
                    j = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue

            privacy = j.get("privacy", "")
            privacy_counts[privacy] = privacy_counts.get(privacy, 0) + 1
            # Hard public-only filter: private and friend&family never pass
            if privacy != "public":
                continue

            pid = str(j.get("id", "")).strip()
            if not pid:
                continue

            taken = _parse_flickr_date(j.get("date_taken"))
            if taken is None:
                skipped_dates.append(pid)
                continue

            entry = {
                "t": int(taken.timestamp()),
                "d": taken.strftime("%B %d, %Y at %I:%M %p"),
            }

            title = fix_text(html.unescape(j.get("name") or "")).strip()
            if title:
                entry["tt"] = title

            desc = _HTMLToText.convert(j.get("description") or "")
            if desc:
                entry["ds"] = desc

            tags = [
                t.get("tag", "").strip()
                for t in (j.get("tags") or [])
                if t.get("tag", "").strip()
            ]
            if tags:
                entry["tg"] = tags

            albums = [
                str(a.get("id"))
                for a in (j.get("albums") or [])
                if a.get("id")
            ]
            if albums:
                entry["al"] = albums

            geo = _parse_geo(j.get("geo"))
            if geo:
                entry["la"], entry["lo"] = geo

            # View/fave counts are deliberately not imported — they are
            # Flickr engagement metrics, not part of the archive.

            license_ = (j.get("license") or "").strip()
            if license_ and license_ != "All Rights Reserved":
                entry["lic"] = license_

            imported = _parse_flickr_date(j.get("date_imported"))
            lowered = [t.lower() for t in tags]
            items[pid] = entry
            aux[pid] = {
                "original": j.get("original") or "",
                "rotation": j.get("rotation") or 0,
                "imported": int(imported.timestamp()) if imported else None,
                "ig_tagged": any(_IG_MACHINE_TAG in t for t in lowered)
                or "instagramapp" in lowered
                or ("square" in lowered and "square format" in lowered),
            }

        audit = ", ".join(
            f"{k or '(none)'}: {v}" for k, v in sorted(privacy_counts.items())
        )
        print(f"Flickr privacy audit — {audit}")
        print(f"Flickr public items loaded: {len(items)}")
        if skipped_dates:
            print(
                f"Warning: {len(skipped_dates)} items skipped "
                f"(unparseable date_taken): {skipped_dates[:5]}"
            )
        return items, aux

    def load_albums(self, referenced_ids):
        """
        {album_id: {"t": title}} for albums referenced by imported items,
        skipping Flickr's synthetic "not in an album N" catch-alls.
        """
        path = self.meta_dir / "albums.json"
        if not path.exists():
            return {}
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        albums = {}
        for a in data.get("albums") or []:
            aid = str(a.get("id", ""))
            title = fix_text(html.unescape(a.get("title") or "")).strip()
            if not aid or aid not in referenced_ids:
                continue
            if re.match(r"^not in an album \d+$", title, re.I):
                continue
            albums[aid] = {"t": title}
        return albums

    @staticmethod
    def _match_media_name(name, known_ids):
        """Photo id from a media filename, or None (validated against
        known_ids — never guessed)."""
        for pat in _MEDIA_PATTERNS:
            m = pat.search(name)
            if m and m.group(1) in known_ids:
                return m.group(1)
        return None

    def index_local_media(self, known_ids):
        """
        Map photo id -> local media source from the export's media parts.

        Handles both extracted `data-download-*` FOLDERS and un-extracted
        `data-download-*.zip` ZIP files (drop the zips in as downloaded —
        no manual unzipping needed). Folder files win over zip members for
        the same id. Zip members are recorded as ("zip", zip_path, member)
        and materialized into originals-cache/ on demand (only the items
        actually being imported get extracted).
        """
        index = {}
        unmatched = 0
        for folder in sorted(self.flickr_path.glob("data-download-*")):
            if not folder.is_dir():
                continue
            for f in folder.iterdir():
                if not f.is_file() or f.name.startswith("."):
                    continue
                pid = self._match_media_name(f.name, known_ids)
                if pid:
                    index[pid] = f
                else:
                    unmatched += 1

        zip_members = 0
        import zipfile
        for zpath in sorted(self.flickr_path.glob("data-download-*.zip")):
            try:
                with zipfile.ZipFile(zpath) as zf:
                    for member in zf.namelist():
                        base = Path(member).name
                        if not base or base.startswith("."):
                            continue
                        pid = self._match_media_name(base, known_ids)
                        if pid and pid not in index:
                            index[pid] = ("zip", zpath, member)
                            zip_members += 1
            except zipfile.BadZipFile:
                print(f"Warning: unreadable zip skipped: {zpath.name}")

        files = sum(1 for v in index.values() if not isinstance(v, tuple))
        print(
            f"Flickr local media indexed: {files} files"
            + (f" + {zip_members} zip members" if zip_members else "")
            + " matched"
        )
        if unmatched:
            print(
                f"Note: {unmatched} local media files matched no imported "
                f"item (non-public items' media, or unrecognized names)"
            )
        return index


# ---------------------------------------------------------------------------
# Flickr API client (one-time metadata sweep)
# ---------------------------------------------------------------------------

class FlickrAPIClient:
    """
    Minimal unsigned REST client for the one-time metadata sweep.

    The sweep exists because the export can't distinguish videos from photos:
    it fetches each public item's media type + original dimensions
    (~61 paginated calls), and a playback URL for each video (getSizes).
    Results are cached to flickr_api_cache.json (all-or-nothing write) and
    the API is never called again unless the cache is missing or a refresh
    is requested. The key comes from the FLICKR_API_KEY environment variable
    only — it must never appear in the repo, data.json, or the output site.
    """

    REST = "https://api.flickr.com/services/rest/"
    # Preference order for video playback sources from getSizes
    _VIDEO_PREF = ("1080p", "720p", "hd mp4", "site mp4", "360p", "mobile mp4")

    def __init__(self, api_key, cache_path, verbose=False):
        self.api_key = api_key
        self.cache_path = Path(cache_path)
        self.verbose = verbose

    def load_cache(self):
        """Return the cached sweep ({id: {...}}), or None if absent/bad."""
        if not self.cache_path.exists():
            return None
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                cache = json.load(f)
            return cache.get("photos") or None
        except (OSError, json.JSONDecodeError):
            print(f"Warning: unreadable API cache {self.cache_path}")
            return None

    def _call(self, method, **params):
        import time
        import urllib.parse
        import urllib.request

        query = {
            "method": method,
            "api_key": self.api_key,
            "format": "json",
            "nojsoncallback": "1",
            **params,
        }
        url = self.REST + "?" + urllib.parse.urlencode(query)
        last_err = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url, timeout=30) as resp:
                    data = json.load(resp)
                if data.get("stat") != "ok":
                    raise RuntimeError(
                        f"{method}: {data.get('code')} {data.get('message')}"
                    )
                return data
            except Exception as e:  # noqa: BLE001 — retried, then re-raised
                last_err = e
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"Flickr API call failed: {method}: {last_err}")

    def sweep(self, nsid):
        """
        Enumerate all public items (media type + o_dims), then fetch a
        playback URL for each video. Writes the cache atomically at the end —
        a failed sweep leaves no half-true cache behind.
        """
        import time

        photos = {}
        page, pages = 1, 1
        while page <= pages:
            data = self._call(
                "flickr.people.getPhotos",
                user_id=nsid,
                extras="media,o_dims",
                per_page="500",
                page=str(page),
            )
            block = data["photos"]
            pages = int(block["pages"])
            for p in block["photo"]:
                photos[str(p["id"])] = {
                    "media": p.get("media", "photo"),
                    "w": int(p.get("o_width") or 0) or None,
                    "h": int(p.get("o_height") or 0) or None,
                }
            print(
                f"  API sweep page {page}/{pages} "
                f"({len(photos)} items)", flush=True,
            )
            page += 1
            time.sleep(0.2)

        videos = [pid for pid, p in photos.items() if p["media"] == "video"]
        print(f"  API sweep: {len(photos)} public items, {len(videos)} videos")
        for n, pid in enumerate(videos, 1):
            try:
                sizes = self._call("flickr.photos.getSizes", photo_id=pid)
                candidates = [
                    s for s in sizes["sizes"]["size"]
                    if s.get("media") == "video" and s.get("source")
                ]
                candidates.sort(
                    key=lambda s: self._rank(str(s.get("label") or ""))
                )
                if candidates:
                    photos[pid]["video_url"] = candidates[0]["source"]
            except RuntimeError as e:
                print(f"  getSizes failed for video {pid}: {e}")
            if n % 25 == 0:
                print(f"  video URLs {n}/{len(videos)}", flush=True)
            time.sleep(0.2)

        payload = {
            "swept_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "nsid": nsid,
            "photos": photos,
        }
        tmp = self.cache_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        tmp.replace(self.cache_path)
        print(f"  API cache written: {self.cache_path}")
        return photos

    @classmethod
    def _rank(cls, label):
        label = label.lower()
        for i, pref in enumerate(cls._VIDEO_PREF):
            if pref in label:
                return i
        return len(cls._VIDEO_PREF)


# ---------------------------------------------------------------------------
# Instagram cross-post deduplication
# ---------------------------------------------------------------------------

def dedupe_against_instagram(items, aux, ig_timestamps, flickr_path,
                             tolerance=180):
    """
    Remove Flickr items that replicate Instagram posts present in the site.

    The export's date stamps are naive local time; the true offset from UTC is
    calibrated empirically: try each whole-hour offset, count how many public
    items' date_imported land within ±tolerance of an actual IG post, and use
    the offset only if it clearly beats the noise floor. Never silent:
    maintains a user-editable exclusion file and writes an audit report.

    Returns the (possibly reduced) items dict.
    """
    flickr_path = Path(flickr_path)
    exclude_path = flickr_path / "flickr_exclude.json"
    report_path = flickr_path / "flickr_dedup_report.json"

    # Load the user-editable exclusion file (ids -> reason)
    exclude = {}
    if exclude_path.exists():
        try:
            with open(exclude_path, encoding="utf-8") as f:
                exclude = json.load(f).get("exclude", {}) or {}
        except (OSError, json.JSONDecodeError):
            print(f"Warning: could not read {exclude_path}; ignoring it")

    ig_ts = sorted(int(t) for t in ig_timestamps) if ig_timestamps else []

    def match_count(offset_s):
        n = 0
        for pid, a in aux.items():
            if a["imported"] is None:
                continue
            t = a["imported"] + offset_s
            i = bisect_left(ig_ts, t - tolerance)
            if i < len(ig_ts) and ig_ts[i] <= t + tolerance:
                n += 1
        return n

    auto_matched = {}
    if ig_ts:
        counts = {h: match_count(h * 3600) for h in range(-12, 13)}
        best_h = max(counts, key=counts.get)
        best = counts[best_h]
        second = max(v for h, v in counts.items() if h != best_h)
        if best >= 25 and best >= 2 * second:
            offset = best_h * 3600
            for pid, a in aux.items():
                if a["imported"] is None:
                    continue
                t = a["imported"] + offset
                i = bisect_left(ig_ts, t - tolerance)
                if i < len(ig_ts) and ig_ts[i] <= t + tolerance:
                    auto_matched[pid] = ig_ts[i]
            print(
                f"Flickr dedup: offset {best_h:+d}h matched "
                f"{len(auto_matched)} Instagram cross-posts "
                f"(noise floor {second})"
            )
        else:
            print(
                f"Flickr dedup: no clear timezone offset "
                f"(best {best} at {best_h:+d}h vs noise {second}) — "
                f"skipping automatic dedup"
            )

    # Merge auto-matches into the exclusion file (idempotent)
    changed = False
    for pid in auto_matched:
        if pid not in exclude:
            exclude[pid] = "auto: date_imported matches an Instagram post"
            changed = True
    if changed or not exclude_path.exists():
        with open(exclude_path, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "exclude": exclude}, f, indent=1)

    # Apply exclusions
    removed = [pid for pid in exclude if pid in items]
    for pid in removed:
        del items[pid]

    # Audit report: what was removed, what was deliberately kept, and (later,
    # when API dims are known) square-format review candidates
    ig_tagged_kept = [
        pid for pid, a in aux.items() if a["ig_tagged"] and pid in items
    ]
    report = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "excluded": {
            pid: {
                "reason": exclude[pid],
                "matched_instagram_ts": auto_matched.get(pid),
            }
            for pid in sorted(removed)
        },
        "instagram_tagged_kept": sorted(ig_tagged_kept),
        "square_candidates": [],  # filled when API dimensions are available
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)

    print(
        f"Flickr dedup: removed {len(removed)} duplicates of Instagram "
        f"posts; kept {len(ig_tagged_kept)} Instagram-tagged items with no "
        f"IG counterpart (report: {report_path.name})"
    )
    return items


def finalize_items(items):
    """Sort newest-first by (t desc, id desc) and assign stable indexes."""
    ordered = sorted(
        items.items(), key=lambda kv: (-kv[1]["t"], -int(kv[0]))
    )
    final = {}
    for i, (pid, entry) in enumerate(ordered):
        entry["i"] = i
        final[pid] = entry
    return final


# ---------------------------------------------------------------------------
# Media: download missing originals + convert into the site
# ---------------------------------------------------------------------------

from .media import InstagramMediaProcessor  # noqa: E402


class FlickrMediaProcessor(InstagramMediaProcessor):
    """
    Downloads missing public originals from the CDN URLs in the export
    metadata and converts everything into the site's local media store
    (media/flickr/<id>.webp + shared thumbnails/), reusing the parent's WebP
    quality settings, thumbnail generator, and thread handling.

    Never walks the 12 GB export tree and never runs fix_file_extensions
    over it — sources are resolved by id via the loader's media index.
    """

    def __init__(self, flickr_path, output_dir, thread_count=None,
                 quality=70, max_dimension=1920):
        super().__init__(flickr_path, output_dir, thread_count,
                         quality, max_dimension)
        self.flickr_path = Path(flickr_path)
        self.cache_dir = self.flickr_path / "originals-cache"
        self.failures_path = self.flickr_path / "download_failures.json"
        (self.output_dir / "media" / "flickr").mkdir(
            parents=True, exist_ok=True
        )

    def _build_file_index(self):
        # Parent walks extraction_dir at init; the flickr export is 12 GB
        # and sources are resolved by id instead — skip entirely.
        return {}

    # -- zip sources -------------------------------------------------------

    def materialize_zip_sources(self, items, local_index):
        """
        Extract zip-member sources into originals-cache/<id>.<ext> so the
        rest of the pipeline only ever sees real file Paths. Only imported
        items are extracted (public, not deduped); each zip is opened once;
        idempotent (existing cache files are reused, not re-extracted).
        """
        import zipfile

        by_zip = {}
        for pid in items:
            src = local_index.get(pid)
            if isinstance(src, tuple) and src[0] == "zip":
                by_zip.setdefault(src[1], []).append((pid, src[2]))

        if not by_zip:
            return local_index

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        extracted = reused = 0
        for zpath, members in sorted(by_zip.items()):
            with zipfile.ZipFile(zpath) as zf:
                for pid, member in members:
                    ext = Path(member).suffix.lower()
                    dest = self.cache_dir / f"{pid}{ext}"
                    if dest.exists():
                        local_index[pid] = dest
                        reused += 1
                        continue
                    part = dest.with_suffix(dest.suffix + ".part")
                    with zf.open(member) as src, open(part, "wb") as out:
                        while True:
                            chunk = src.read(1 << 16)
                            if not chunk:
                                break
                            out.write(chunk)
                    part.replace(dest)
                    local_index[pid] = dest
                    extracted += 1
        print(
            f"Flickr zips: extracted {extracted} items into "
            f"{self.cache_dir.name}/ ({reused} already cached) from "
            f"{len(by_zip)} zip file(s)"
        )
        return local_index

    # -- download ----------------------------------------------------------

    def download_missing(self, items, aux, local_index, retry_failed=False):
        """
        Fetch originals for items with no local file into originals-cache/.
        Resumable (skips existing), atomic (.part + rename), and remembers
        hard failures so they aren't re-attempted every run.
        """
        import urllib.request
        from concurrent.futures import ThreadPoolExecutor
        from tqdm import tqdm

        self.cache_dir.mkdir(parents=True, exist_ok=True)

        failures = {}
        if self.failures_path.exists() and not retry_failed:
            try:
                with open(self.failures_path, encoding="utf-8") as f:
                    failures = json.load(f)
            except (OSError, json.JSONDecodeError):
                failures = {}

        todo = []
        for pid in items:
            if pid in local_index or pid in failures:
                continue
            url = aux.get(pid, {}).get("original") or ""
            if not url:
                failures.setdefault(pid, "no original URL in metadata")
                continue
            ext = Path(url).suffix.lower() or ".jpg"
            dest = self.cache_dir / f"{pid}{ext}"
            if dest.exists():
                local_index[pid] = dest
                continue
            todo.append((pid, url, dest))

        if not todo:
            print("Flickr download: nothing to fetch")
        else:
            print(f"Flickr download: fetching {len(todo)} originals "
                  f"into {self.cache_dir} (rate-limited; this is a "
                  f"multi-hour one-time job) ...")

            import threading
            import time

            # Politeness controls. The CDN tarpits aggressive clients (an
            # early 8-worker/10-req-s version got throttled within a
            # minute), so: few workers, ~2 req/s overall pacing, and a
            # shared backoff that pauses the whole pool on 429/5xx.
            # Only 404/410 are PERMANENT failures; throttling never is.
            pace_lock = threading.Lock()
            next_slot = [time.monotonic()]
            throttle_until = [0.0]
            # Adaptive pacing: begin gently (the CDN holds a grudge after
            # any burst), speed up on sustained success, back off hard on
            # 429. Bounds: 0.5s (2 req/s) .. 16s.
            interval = [3.0]

            def wait_turn():
                with pace_lock:
                    now = time.monotonic()
                    start = max(next_slot[0], throttle_until[0], now)
                    next_slot[0] = start + interval[0]
                time.sleep(max(0.0, start - time.monotonic()))

            consecutive_429 = [0]

            def note_success():
                with pace_lock:
                    interval[0] = max(0.5, interval[0] * 0.98)
                    consecutive_429[0] = 0

            def note_429():
                # Every rejected request may refresh the CDN's penalty
                # window, so after sustained 429s stop poking it entirely
                # (20-minute nap), then resume gently.
                with pace_lock:
                    old = interval[0]
                    interval[0] = min(16.0, interval[0] * 2)
                    consecutive_429[0] += 1
                    if consecutive_429[0] >= 10:
                        nap = 1200.0
                        throttle_until[0] = max(
                            throttle_until[0], time.monotonic() + nap
                        )
                        consecutive_429[0] = 0
                        interval[0] = 3.0
                        print(
                            "  sustained 429s — napping 20 min to let the "
                            "CDN penalty expire", flush=True,
                        )
                    return old, interval[0]

            def note_throttled(retry_after, level):
                # Cap the pool-wide pause: enough to placate the CDN,
                # not enough to look like a hang (an uncapped version
                # compounded early 429s into ~8 silent minutes)
                pause = min(max(retry_after, 15.0 * (level + 1)), 120.0)
                with pace_lock:
                    throttle_until[0] = max(
                        throttle_until[0], time.monotonic() + pause
                    )
                print(f"  throttled (HTTP backoff {pause:.0f}s)", flush=True)
                return pause

            def fetch(job):
                pid, url, dest = job
                part = dest.with_suffix(dest.suffix + ".part")
                req = urllib.request.Request(
                    url, headers={"User-Agent": "memento-mori/1.0"}
                )
                throttle_level = 0
                try:
                    for attempt in range(8):
                        wait_turn()
                        try:
                            with urllib.request.urlopen(req, timeout=60) as r, \
                                    open(part, "wb") as out:
                                expected = int(
                                    r.headers.get("Content-Length") or 0
                                )
                                got = 0
                                while True:
                                    chunk = r.read(1 << 16)
                                    if not chunk:
                                        break
                                    out.write(chunk)
                                    got += len(chunk)
                            # A dropped connection can EOF silently; never
                            # keep a short body (5 truncated files once
                            # poisoned the cache this way)
                            if expected and got != expected:
                                raise OSError(
                                    f"truncated: {got}/{expected} bytes"
                                )
                            part.replace(dest)
                            note_success()
                            return pid, dest, None
                        except urllib.error.HTTPError as e:
                            if e.code in (404, 410):
                                return pid, None, f"HTTP {e.code}"
                            # 429/5xx: slow the pool and retry
                            retry_after = 0.0
                            try:
                                retry_after = float(
                                    e.headers.get("Retry-After", 0)
                                )
                            except (TypeError, ValueError):
                                pass
                            if e.code == 429:
                                old, new = note_429()
                                print(
                                    f"  HTTP 429 — pacing "
                                    f"{old:.1f}s -> {new:.1f}s", flush=True,
                                )
                            else:
                                print(f"  HTTP {e.code} on {url}", flush=True)
                            note_throttled(retry_after, throttle_level)
                            throttle_level += 1
                        except Exception:  # noqa: BLE001 — retried
                            time.sleep(2 * (attempt + 1))
                finally:
                    if part.exists():
                        part.unlink()
                # Ran out of attempts this run; NOT recorded as permanent —
                # the next run will try again
                return pid, None, None

            transient = 0
            workers = min(self.thread_count, 3)
            with ThreadPoolExecutor(max_workers=workers) as ex:
                for pid, dest, err in tqdm(
                    ex.map(fetch, todo), total=len(todo),
                    desc="Downloading originals", unit="files",
                ):
                    if dest:
                        local_index[pid] = dest
                    elif err:
                        failures[pid] = err
                    else:
                        transient += 1
            if transient:
                print(f"Flickr download: {transient} transient failures "
                      f"(will retry on the next run)")

        with open(self.failures_path, "w", encoding="utf-8") as f:
            json.dump(failures, f, indent=1, sort_keys=True)
        if failures:
            print(f"Flickr download: {len(failures)} permanent failures "
                  f"recorded in {self.failures_path.name}")
        return local_index

    # -- convert -----------------------------------------------------------

    def _process_image(self, source, dest, rotation):
        """
        Original -> media/flickr/<id>.webp, capped at max_dimension.

        Orientation (verified empirically against Flickr's own renders):
        when a file carries an EXIF orientation, the metadata `rotation`
        DUPLICATES it — apply exactly one fix, never both. EXIF transpose
        when the tag exists; the metadata rotation only when it doesn't.
        The output is a derived image, so no smaller-file fallback.
        """
        from PIL import Image, ImageFile, ImageOps

        # A handful of 2004-2006-era originals are stored slightly
        # truncated on Flickr itself (missing a few tail bytes). Decode
        # what's there rather than dropping a 20-year-old photo.
        ImageFile.LOAD_TRUNCATED_IMAGES = True

        with Image.open(source) as img:
            try:
                exif_oriented = img.getexif().get(274, 1) != 1
            except Exception:  # noqa: BLE001 — malformed EXIF = not oriented
                exif_oriented = False
            img = ImageOps.exif_transpose(img)
            if not exif_oriented and rotation in (90, 180, 270):
                img = img.rotate(-rotation, expand=True)
            w, h = img.size
            if w > self.max_dimension or h > self.max_dimension:
                scale = self.max_dimension / max(w, h)
                img = img.resize(
                    (int(w * scale), int(h * scale)), Image.LANCZOS
                )
            if img.mode in ("RGBA", "LA") or (
                img.mode == "P" and "transparency" in img.info
            ):
                if img.mode != "RGBA":
                    img = img.convert("RGBA")
            else:
                img = img.convert("RGB")
            # Atomic write: an interrupted run once left 0-byte .webp files
            # that the exists-check then treated as done forever
            tmp = dest.with_suffix(".tmp.webp")
            img.save(tmp, "WEBP", quality=self.quality, method=6)
            tmp.replace(dest)

    def process(self, items, aux, local_index, api_cache=None, limit=None):
        """
        Convert every sourced item into the output tree and update entries
        in place: m = [output path], vd/vu for videos. Items with no source
        anywhere are left media-less (reported; the page skips them).
        Idempotent: existing outputs are not redone.
        """
        from concurrent.futures import ThreadPoolExecutor
        from tqdm import tqdm

        api_cache = api_cache or {}
        media_dir = self.output_dir / "media" / "flickr"
        sourced = [pid for pid in items if pid in local_index]
        missing = [pid for pid in items if pid not in local_index]
        if limit:
            sourced = sourced[:limit]

        def convert(pid):
            source = local_index[pid]
            info = api_cache.get(pid) or {}
            is_video_file = source.suffix.lower().lstrip(".") in _VIDEO_EXTS
            rotation = aux.get(pid, {}).get("rotation") or 0
            def _missing(p):
                # A 0-byte file is a corpse from an interrupted run, not
                # a finished output
                return not p.exists() or p.stat().st_size == 0

            try:
                if is_video_file:
                    dest = media_dir / f"{pid}{source.suffix.lower()}"
                    if _missing(dest):
                        import shutil
                        shutil.copy2(source, dest)
                else:
                    dest = media_dir / f"{pid}.webp"
                    if _missing(dest):
                        self._process_image(source, dest, rotation)
                m0 = f"media/flickr/{dest.name}"
                # Thumbnail keyed on the stored m[0] string (md5), same
                # convention as Instagram, generated from the converted file
                # so orientation is always consistent
                self.generate_thumbnail(dest, m0, quiet=True)
                entry = items[pid]
                entry["m"] = [m0]
                if info.get("media") == "video" or is_video_file:
                    entry["vd"] = 1
                    if not is_video_file and info.get("video_url"):
                        # Local source is only the poster frame; playback
                        # comes from Flickr until its export part arrives
                        entry["vu"] = info["video_url"]
                return None
            except Exception as e:  # noqa: BLE001 — collected, reported
                return f"{pid}: {e}"

        errors = []
        with ThreadPoolExecutor(max_workers=self.thread_count) as ex:
            for err in tqdm(
                ex.map(convert, sourced), total=len(sourced),
                desc="Converting flickr media", unit="files",
            ):
                if err:
                    errors.append(err)

        if errors:
            print(f"Flickr convert: {len(errors)} errors "
                  f"(first 5): {errors[:5]}")
        if missing:
            print(f"Flickr convert: {len(missing)} items have no media "
                  f"source yet (kept without media)")
        return {"converted": len(sourced) - len(errors),
                "errors": len(errors), "missing": len(missing)}


# ---------------------------------------------------------------------------
# Facade
# ---------------------------------------------------------------------------

def import_flickr(flickr_path, output_dir, ig_timestamps=None,
                  thread_count=None, quality=70, max_dimension=1920,
                  api_key=None, refresh=False, verbose=False, limit=None):
    """
    Full Flickr import: load + filter metadata, dedupe against Instagram,
    sweep the API when needed, download missing originals, convert media,
    and return the data package's "flickr" section.
    """
    flickr_path = Path(flickr_path)
    loader = FlickrDataLoader(flickr_path, verbose=verbose)
    account = loader.load_account()

    items, aux = loader.load_items()
    items = dedupe_against_instagram(
        items, aux, ig_timestamps or [], flickr_path
    )

    # API cache: the only source of video identification + playback URLs
    client = FlickrAPIClient(
        api_key or "", flickr_path / "flickr_api_cache.json",
        verbose=verbose,
    )
    api_cache = client.load_cache()
    if (api_cache is None or refresh) and api_key:
        api_cache = client.sweep(account["nsid"])
    if api_cache is None:
        api_cache = {}
        print(
            "Warning: no Flickr API cache and no FLICKR_API_KEY — videos "
            "cannot be identified; unknown videos import as poster images"
        )

    # Square-format dedup candidates (review-only) into the report
    _update_square_candidates(flickr_path, items, aux, api_cache)

    local_index = loader.index_local_media(set(items.keys()))
    processor = FlickrMediaProcessor(
        flickr_path, output_dir, thread_count, quality, max_dimension
    )
    processor.materialize_zip_sources(items, local_index)
    processor.download_missing(items, aux, local_index,
                               retry_failed=refresh)
    stats = processor.process(items, aux, local_index, api_cache,
                              limit=limit)

    items = finalize_items(items)
    referenced = set()
    for e in items.values():
        referenced.update(e.get("al", []))

    return {
        # Each source carries its own profile; the generator picks the
        # site's identity from these by SOURCE_PRIORITY, so a Flickr-only
        # site names itself from the Flickr account.
        "profile": {
            "username": account["path_alias"],
            "name": account.get("real_name", ""),
            "bio": account.get("description", ""),
            "website": account.get("website_url", ""),
            "profile_picture": "",
        },
        "items": items,
        "albums": loader.load_albums(referenced),
        "meta": {
            "path_alias": account["path_alias"],
            "imported_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "api_swept_at": None if not api_cache else "cached",
            "stats": stats,
        },
    }


def _update_square_candidates(flickr_path, items, aux, api_cache):
    """
    Fill the dedup report's review-only square candidates: IG-era items
    (>= Nov 2013) whose originals are square per the API dims and which
    were not already excluded by timestamp matching.
    """
    if not api_cache:
        return
    report_path = Path(flickr_path) / "flickr_dedup_report.json"
    try:
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)
    except (OSError, json.JSONDecodeError):
        return
    ig_era = datetime(2013, 11, 1, tzinfo=timezone.utc).timestamp()
    candidates = []
    for pid, entry in items.items():
        info = api_cache.get(pid) or {}
        if (
            entry["t"] >= ig_era
            and info.get("w")
            and info["w"] == info.get("h")
        ):
            candidates.append(pid)
    report["square_candidates"] = sorted(candidates)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
