# memento_mori/merger.py
import json
import shutil
from datetime import datetime
from pathlib import Path

# Sidecar schema version. v1 was Instagram-shaped: posts/stories/profile at
# the top level with an optional "flickr" key bolted alongside. v2 puts every
# import under "sources", so a new source is a registry entry rather than
# another special case threaded through the CLI and generator.
SCHEMA_VERSION = 2

# Which source's profile provides the site's identity (username, bio,
# website) when several are present. First match wins.
SOURCE_PRIORITY = ["instagram", "flickr"]


def migrate_sidecar(sidecar):
    """
    Return a v2-shaped sidecar, converting v1 in memory if needed.

    v1 detection is simply the absence of "sources". The mapping:
      posts/stories/profile  -> sources.instagram
      flickr                 -> sources.flickr (profile synthesized from meta)
      location/settings      -> carried through
    Dropped: post_count/story_count (derived from the data) and date_range
    (no template consumes it). Both were stored duplicates that could drift.

    v2 input passes through untouched, so this is safe to call on every load.
    """
    if "sources" in sidecar:
        return sidecar

    sources = {}

    posts = sidecar.get("posts") or {}
    stories = sidecar.get("stories") or {}
    profile = sidecar.get("profile")
    if posts or stories or profile:
        sources["instagram"] = {
            "profile": profile or {},
            "posts": posts,
            "stories": stories,
        }

    flickr = sidecar.get("flickr")
    if flickr:
        flickr = dict(flickr)
        # v1 never stored a Flickr profile; synthesize the identity fields
        # that are recoverable so a Flickr-only site can name itself after
        # migration rather than falling back to "Unknown".
        if not flickr.get("profile"):
            alias = (flickr.get("meta") or {}).get("path_alias", "")
            flickr["profile"] = {
                "username": alias,
                "name": "",
                "bio": "",
                "website": "",
                "profile_picture": "",
            }
        sources["flickr"] = flickr

    migrated = {
        "schema_version": SCHEMA_VERSION,
        "location": sidecar.get("location") or {"location": "Unknown"},
        "sources": sources,
    }
    if sidecar.get("settings"):
        migrated["settings"] = sidecar["settings"]
    return migrated


def backup_v1_sidecar(output_dir):
    """
    Copy a v1 data.json aside once, before it is overwritten in v2 form.

    Migration is automatic, so the user never asked for it and has no other
    copy. Written once and never overwritten: a later v2 run must not clobber
    the original with an already-migrated file.
    """
    output_dir = Path(output_dir)
    sidecar = output_dir / "data.json"
    backup = output_dir / "data.v1.bak.json"
    if not sidecar.exists() or backup.exists():
        return None
    try:
        with open(sidecar, encoding="utf-8") as f:
            if "sources" in json.load(f):
                return None          # already v2, nothing to preserve
    except (OSError, json.JSONDecodeError):
        return None
    shutil.copy2(sidecar, backup)
    print(f"   Backed up the pre-migration sidecar to {backup}")
    return backup


def load_existing_site_data(output_dir, verbose=False):
    """
    Load the data package of a previously generated site, migrated to v2.

    Prefers the data.json sidecar; falls back to parsing the JSON embedded
    in index.html for sites generated before the sidecar existed.

    Args:
        output_dir (str or Path): Directory containing the generated site
        verbose (bool): Whether to print debug information

    Returns:
        dict: {"sources": dict, "location": dict, "settings": dict,
               "source": "sidecar" or "html", plus "posts"/"stories"/
               "profile"/"flickr" convenience views into sources}

    Raises:
        FileNotFoundError: If the output directory has no generated site
    """
    output_dir = Path(output_dir)
    sidecar_path = output_dir / "data.json"
    index_path = output_dir / "index.html"

    if sidecar_path.exists():
        with open(sidecar_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        migrated = migrate_sidecar(raw)
        if verbose:
            print(f"Loaded existing site data from sidecar: {sidecar_path}")
            if "sources" not in raw:
                print("   (migrated a v1 sidecar to the v2 sources schema)")
        return _existing_view(migrated, "sidecar")

    if not index_path.exists():
        raise FileNotFoundError(
            f"No existing site found in {output_dir} (no data.json or index.html). "
            "Generate a site first by running without --merge."
        )

    posts = _parse_embedded_json(index_path, "window.postData")
    stories = _parse_embedded_json(index_path, "window.storiesData")
    if verbose:
        print(f"Loaded existing site data from HTML: {index_path}")
    return _existing_view({
        "schema_version": SCHEMA_VERSION,
        "location": {"location": "Unknown"},
        "sources": {"instagram": {"profile": {}, "posts": posts, "stories": stories}},
    }, "html")


def _existing_view(migrated, origin):
    """
    Wrap a migrated sidecar with the flat keys the merge flow reads.

    The convenience keys are views onto sources, not copies, so the merge
    path can keep reading existing["posts"] while the sidecar itself is
    source-shaped.
    """
    sources = migrated.get("sources") or {}
    instagram = sources.get("instagram") or {}
    return {
        "sources": sources,
        "location": migrated.get("location") or {"location": "Unknown"},
        "settings": migrated.get("settings", {}),
        "posts": instagram.get("posts") or {},
        "stories": instagram.get("stories") or {},
        "profile": instagram.get("profile") or None,
        "flickr": sources.get("flickr"),
        "source": origin,
    }


def site_identity(sources):
    """
    The site's profile: the first source profile along SOURCE_PRIORITY.

    Derived on every render rather than stored, so it cannot go stale when a
    source is added, refreshed or removed. Sources not in the priority list
    are considered last, in insertion order, so a new importer still names
    the site rather than leaving it "Unknown".
    """
    order = SOURCE_PRIORITY + [k for k in sources if k not in SOURCE_PRIORITY]
    for key in order:
        profile = (sources.get(key) or {}).get("profile") or {}
        if profile.get("username"):
            return profile
    return {"username": "Unknown", "bio": "", "website": "",
            "name": "", "profile_picture": ""}


def _parse_embedded_json(html_path, var_name):
    """
    Extract a JSON object assigned to a JS variable in a generated HTML file.

    The generator writes assignments like `window.postData = {...};` on a
    single line via json.dumps, so the payload between the assignment and
    the trailing semicolon is valid JSON.
    """
    prefix = f"{var_name} = "
    with open(html_path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith(prefix):
                payload = stripped[len(prefix):].rstrip(";")
                return json.loads(payload)
    return {}


def compute_delta(existing, new):
    """
    Return the entries of `new` whose timestamp key is not in `existing`.

    Keys are compared as strings (existing data comes from JSON, so its keys
    are strings; freshly loaded data may have int keys) but the delta keeps
    `new`'s original keys so it can be passed straight to the media processor.
    """
    return {k: v for k, v in new.items() if str(k) not in existing}


def merge_timestamp_dicts(existing, processed_delta):
    """
    Union two timestamp-keyed dicts (posts or stories), sort newest-first,
    and reindex the "i" field which the grid and modal JS rely on.

    Existing entries win on any key collision — their media has already been
    processed into the output and filenames can differ across exports.
    """
    merged = {str(k): v for k, v in processed_delta.items()}
    merged.update(existing)

    merged = dict(sorted(merged.items(), key=lambda x: int(x[0]), reverse=True))

    for index, entry in enumerate(merged.values()):
        entry["i"] = index

    return merged


def apply_post_metadata(merged, new_entries, fields=("pl", "la", "lo")):
    """
    Backfill metadata fields (place name, coordinates) from freshly loaded
    entries onto merged entries that lack them — entries kept from an older
    archive (whose format has no such data) or merged before support
    existed. Never overwrites a non-empty value.

    Returns the number of entries updated.
    """
    updated = 0
    for key, entry in new_entries.items():
        existing_entry = merged.get(str(key))
        if existing_entry is None:
            continue
        changed = False
        for field in fields:
            value = entry.get(field)
            if value not in (None, "") and existing_entry.get(field) in (None, ""):
                existing_entry[field] = value
                changed = True
        if changed:
            updated += 1
    return updated


def compute_date_range(posts):
    """
    Compute the display date range from a newest-first posts dict,
    matching the format produced by InstagramDataLoader.load_all_data().
    """
    if not posts:
        return {"newest": "Unknown", "oldest": "Unknown", "range": "Unknown"}

    keys = list(posts.keys())
    newest = datetime.utcfromtimestamp(int(keys[0])).strftime("%B %Y")
    oldest = datetime.utcfromtimestamp(int(keys[-1])).strftime("%B %Y")

    return {
        "newest": newest,
        "oldest": oldest,
        "range": f"{oldest} - {newest}",
    }
