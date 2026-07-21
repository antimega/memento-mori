"""Shared assertions and decoders for the output tree."""

import json
import re
from pathlib import Path

# The three date stamps the generator writes. Every byte-comparison of two
# builds must mask these or it compares clocks, not behavior.
#   settings.generated_at      generator.py
#   generation_date (footer)   every rendered page
#   flickr.meta.imported_at    the Flickr section
DATE_PATTERNS = [
    re.compile(rb'"generated_at":\s*"[^"]*"'),
    re.compile(rb'"imported_at":\s*"[^"]*"'),
    re.compile(rb'Generated on \d{4}-\d{2}-\d{2}'),
]


def mask_dates(blob):
    for pat in DATE_PATTERNS:
        blob = pat.sub(b"<DATE>", blob)
    return blob


def decode_browser_data(path, var="postData"):
    """
    Unwrap `window.<var> = JSON.parse("....");` back into Python.

    Grepping these files is how a previous debugging session drew a wrong
    conclusion — the payload is a JSON *string literal*, so the real data is
    one decode below the surface. Always come through here.
    """
    text = Path(path).read_text(encoding="utf-8")
    m = re.search(
        r"window\." + re.escape(var) + r"\s*=\s*JSON\.parse\((\".*?\")\);",
        text, re.S,
    )
    assert m, f"{path} does not contain a JSON.parse-wrapped window.{var}"
    return json.loads(json.loads(m.group(1)))


def read_data_json(output_dir):
    return json.loads((Path(output_dir) / "data.json").read_text(encoding="utf-8"))


def tree_files(output_dir, suffixes=None):
    out = []
    for p in sorted(Path(output_dir).rglob("*")):
        if p.is_file() and (suffixes is None or p.suffix in suffixes):
            out.append(p)
    return out


def grep_tree(output_dir, needle, suffixes=(".html", ".js", ".json")):
    """Files under output_dir containing `needle`. Used for leak checks."""
    hits = []
    needle_b = needle.encode() if isinstance(needle, str) else needle
    for p in tree_files(output_dir, suffixes):
        if needle_b in p.read_bytes():
            hits.append(p)
    return hits


def assert_no_browser_only_fields_in_sidecar(output_dir):
    """
    th / dm / vp are browser-only enrichment. They must never reach
    data.json, or a --regenerate would persist resolved paths as if they
    were source data.
    """
    data = read_data_json(output_dir)
    for section in ("posts", "stories"):
        for ts, entry in (data.get(section) or {}).items():
            for field in ("th", "dm", "vp"):
                assert field not in entry, (
                    f"data.json {section}[{ts}] leaked browser-only field {field!r}"
                )
    for pid, entry in ((data.get("flickr") or {}).get("items") or {}).items():
        for field in ("th", "dm", "vp"):
            assert field not in entry, (
                f"data.json flickr[{pid}] leaked browser-only field {field!r}"
            )


def assert_thumbnails_resolve(output_dir, data_file="js/posts-data.js",
                              var="postData", sample=25):
    """Every `th` must name a thumbnail that actually exists on disk."""
    entries = decode_browser_data(Path(output_dir) / data_file, var)
    checked = 0
    for key, entry in entries.items():
        th = entry.get("th")
        if not th:
            continue
        assert re.fullmatch(r"[0-9a-f]{32}", th), f"{key}: malformed th {th!r}"
        p = Path(output_dir) / "thumbnails" / f"{th}.webp"
        assert p.exists(), f"{key}: th points at missing {p}"
        checked += 1
        if checked >= sample:
            break
    return checked
