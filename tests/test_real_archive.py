"""
Characterization against the maintainer's own generated site.

Opt-in (`pytest -m real`) and auto-skipping, because it needs a real ./output
that no checkout has. Synthetic fixtures prove the code paths work; this
proves they work at real scale — 6k posts, 30k Flickr items, a decade of
edge cases no fixture would think to invent.

Deliberately generic: no hardcoded counts, only cross-consistency between
artifacts that must agree. That way it keeps passing as the archive grows,
and it is the tool for proving the multi-source schema migration lossless
(run it before and after; the same invariants must hold).
"""

import json
import re
from pathlib import Path

import pytest

from tests.helpers import (
    decode_browser_data,
    flickr_items,
    ig_posts,
    ig_stories,
    read_data_json,
    source,
)

OUTPUT = Path(__file__).resolve().parents[1] / "output"

pytestmark = [
    pytest.mark.real,
    pytest.mark.skipif(
        not (OUTPUT / "data.json").exists(),
        reason="no generated site at ./output — run a build first",
    ),
]


@pytest.fixture(scope="module")
def data():
    return read_data_json(OUTPUT)


def test_sidecar_and_browser_posts_agree(data):
    sidecar_posts = ig_posts(OUTPUT)
    posts = decode_browser_data(OUTPUT / "js/posts-data.js", "postData")
    assert len(posts) == len(sidecar_posts)
    assert set(posts) == {str(k) for k in sidecar_posts}


def test_sidecar_and_browser_stories_agree(data):
    sidecar_stories = ig_stories(OUTPUT)
    if not sidecar_stories:
        pytest.skip("no stories in this archive")
    stories = decode_browser_data(OUTPUT / "js/stories-data.js", "storiesData")
    assert len(stories) == len(sidecar_stories)


def test_sidecar_and_browser_flickr_agree(data):
    sidecar_items = flickr_items(OUTPUT)
    if not sidecar_items:
        pytest.skip("no Flickr section in this archive")
    items = decode_browser_data(OUTPUT / "js/flickr-data.js", "flickrData")
    assert len(items) == len(sidecar_items)
    assert set(items) == set(sidecar_items)


def test_nav_counts_match_the_data(data):
    """
    The rendered navigation is the user-visible claim about how much is
    here. It must agree with the data, thousands separators and all.
    """
    html = (OUTPUT / "index.html").read_text(encoding="utf-8")
    expected = f"{len(ig_posts(OUTPUT)):,}"
    assert re.search(
        rf'<span class="stat-count">{re.escape(expected)}</span>\s*posts', html
    ), f"nav does not report {expected} posts"

    if flickr_items(OUTPUT):
        expected = f"{len(flickr_items(OUTPUT)):,}"
        assert re.search(
            rf'<span class="stat-count">{re.escape(expected)}</span>\s*photos', html
        ), f"nav does not report {expected} photos"


def test_no_browser_only_fields_in_the_sidecar(data):
    for name, entries in (("posts", ig_posts(OUTPUT)),
                          ("stories", ig_stories(OUTPUT)),
                          ("flickr", flickr_items(OUTPUT))):
        for key, entry in entries.items():
            assert not ({"th", "dm", "vp"} & set(entry)), f"{name}[{key}]"


def test_every_flickr_item_has_media(data):
    items = flickr_items(OUTPUT)
    if not items:
        pytest.skip("no Flickr section")
    missing = [k for k, v in items.items() if not v.get("m")]
    assert not missing, f"{len(missing)} Flickr items without media: {missing[:5]}"


def test_no_privacy_strings_serialized(data):
    """A Flickr privacy value in the output means the filter leaked."""
    blob = json.dumps(source(OUTPUT, "flickr"))
    assert '"privacy"' not in blob
    assert "friends & family" not in blob


def test_thumbnails_resolve(data):
    """Sampled: every th must name a file that exists."""
    posts = decode_browser_data(OUTPUT / "js/posts-data.js", "postData")
    checked = 0
    for key, entry in posts.items():
        th = entry.get("th")
        if not th:
            continue
        assert (OUTPUT / "thumbnails" / f"{th}.webp").exists(), f"{key} -> {th}"
        checked += 1
        if checked >= 200:
            break
    assert checked, "no th fields found to verify"


def test_media_referenced_by_the_sidecar_resolves(data):
    """
    Sampled across posts and Flickr: every media reference must resolve to a
    file on disk.

    Note what "resolve" means. `m` holds the *logical* reference, which keeps
    the source extension (media/posts/abc.jpg) while the pipeline writes a
    converted sibling (abc.webp) next to it; _get_display_media does that
    substitution at render time. So an `m` entry pointing at a .jpg that does
    not exist is normal and correct — what would be broken is neither the
    literal path nor its .webp sibling existing.
    """
    missing = []
    sources = list(ig_posts(OUTPUT).items())[:100]
    sources += list(flickr_items(OUTPUT).items())[:100]
    for key, entry in sources:
        for m in entry.get("m", []):
            if not m:
                continue
            webp = re.sub(r"\.(jpg|jpeg|png|gif)$", ".webp", m, flags=re.I)
            if not ((OUTPUT / m).exists() or (OUTPUT / webp).exists()):
                missing.append((key, m))
    assert not missing, f"{len(missing)} unresolvable media refs, e.g. {missing[:3]}"


def test_timeline_server_renders_exactly_one_month():
    html = (OUTPUT / "timeline.html").read_text(encoding="utf-8")
    assert html.count('class="timeline-month"') == 1
    assert html.count("<option") > 1


def test_pages_carry_no_inline_style_blocks():
    for page in OUTPUT.glob("*.html"):
        assert "<style" not in page.read_text(encoding="utf-8"), page.name


def test_map_page_pin_count_matches_the_data(data):
    """The map's nav claim must equal the geotagged items across sources."""
    if not (OUTPUT / "map.html").exists():
        pytest.skip("no map page in this build")
    pins = 0
    for entries in (ig_posts(OUTPUT), flickr_items(OUTPUT)):
        for entry in entries.values():
            if entry.get("la") not in ("", None) and entry.get("lo") not in ("", None):
                pins += 1
    assert pins, "map.html exists but nothing is geotagged"
    html = (OUTPUT / "index.html").read_text(encoding="utf-8")
    assert re.search(
        rf'<span class="stat-count">{re.escape(f"{pins:,}")}</span>\s*pins', html
    ), f"nav does not report {pins:,} pins"


def test_map_page_stays_a_shell(data):
    """However many pins, the page must not inline them."""
    if not (OUTPUT / "map.html").exists():
        pytest.skip("no map page in this build")
    size = (OUTPUT / "map.html").stat().st_size
    assert size < 20000, f"map.html is {size} bytes; point data may be inlined"
