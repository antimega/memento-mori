# memento_mori/merger.py
import json
from datetime import datetime
from pathlib import Path


def load_existing_site_data(output_dir, verbose=False):
    """
    Load the data package of a previously generated site.

    Prefers the data.json sidecar; falls back to parsing the JSON embedded
    in index.html for sites generated before the sidecar existed.

    Args:
        output_dir (str or Path): Directory containing the generated site
        verbose (bool): Whether to print debug information

    Returns:
        dict: {"posts": dict, "stories": dict, "settings": dict,
               "profile": dict or None, "source": "sidecar" or "html"}

    Raises:
        FileNotFoundError: If the output directory has no generated site
    """
    output_dir = Path(output_dir)
    sidecar_path = output_dir / "data.json"
    index_path = output_dir / "index.html"

    if sidecar_path.exists():
        with open(sidecar_path, "r", encoding="utf-8") as f:
            sidecar = json.load(f)
        if verbose:
            print(f"Loaded existing site data from sidecar: {sidecar_path}")
        return {
            "posts": sidecar.get("posts", {}),
            "stories": sidecar.get("stories", {}),
            "settings": sidecar.get("settings", {}),
            "profile": sidecar.get("profile"),
            "source": "sidecar",
        }

    if not index_path.exists():
        raise FileNotFoundError(
            f"No existing site found in {output_dir} (no data.json or index.html). "
            "Generate a site first by running without --merge."
        )

    posts = _parse_embedded_json(index_path, "window.postData")
    stories = _parse_embedded_json(index_path, "window.storiesData")
    if verbose:
        print(f"Loaded existing site data from HTML: {index_path}")
    return {
        "posts": posts,
        "stories": stories,
        "settings": {},
        "profile": None,
        "source": "html",
    }


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
