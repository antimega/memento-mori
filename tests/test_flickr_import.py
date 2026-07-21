"""
A combined Instagram + Flickr build.

The privacy assertions here are the most important in the suite: the whole
import is predicated on "public items only", and a leak would publish
someone's private photos. They are written to fail loudly on the *content*
of the output tree, not on internal state.

Everything runs offline. The API cache fixture stands in for the network
sweep, and every imported item has local media, so the downloader has nothing
to fetch.
"""

import json
import sys

import pytest
from PIL import Image

from tests.conftest import make_flickr_export, make_instagram_export, write_api_cache
from tests.helpers import (
    assert_no_browser_only_fields_in_sidecar,
    decode_browser_data,
    flickr_items,
    grep_tree,
    read_data_json,
    source,
)

SENTINEL_KEY = "SENTINELAPIKEY0000deadbeef"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    from memento_mori import cli

    root = tmp_path_factory.mktemp("combined")
    export = root / "ig-export"
    export.mkdir()
    make_instagram_export(export)

    flickr = root / "flickr-download"
    flickr.mkdir()
    info = make_flickr_export(flickr)
    write_api_cache(flickr, video_ids=[info["ids"]["video"]])

    out = root / "output"

    # A key IS set here, deliberately: with the cache present no sweep runs,
    # and the sentinel lets us prove the key never reaches the output tree.
    import os
    os.environ["FLICKR_API_KEY"] = SENTINEL_KEY
    argv = sys.argv
    sys.argv = ["memento-mori", "--input", str(export), "--output", str(out),
                "--no-auto-detect", "--flickr", str(flickr)]
    try:
        rc = cli.main()
    finally:
        sys.argv = argv
        os.environ.pop("FLICKR_API_KEY", None)
    assert rc == 0, "combined build failed"
    return {"out": out, "flickr": flickr, "ids": info["ids"]}


# --------------------------------------------------------------------------
# privacy: the assertions that matter most
# --------------------------------------------------------------------------

def test_private_items_never_reach_the_output(built):
    """
    Private and friends&family items must be absent from every published
    file — by id and by their (distinctive) titles.
    """
    for id_key, marker in (("private", "SECRETPRIVATE"), ("friends", "SECRETFRIENDS")):
        pid = str(built["ids"][id_key])
        hits = grep_tree(built["out"], pid)
        assert not hits, f"{id_key} id {pid} leaked into {hits}"
        hits = grep_tree(built["out"], marker)
        assert not hits, f"{id_key} title leaked into {hits}"


def test_no_privacy_strings_serialized(built):
    """The privacy field is a filter input, never output."""
    data = read_data_json(built["out"])
    blob = json.dumps(data)
    assert '"privacy"' not in blob
    assert "friends & family" not in blob


def test_api_key_never_leaks(built):
    hits = grep_tree(built["out"], SENTINEL_KEY)
    assert not hits, f"Flickr API key leaked into {hits}"


# --------------------------------------------------------------------------
# import correctness
# --------------------------------------------------------------------------

def test_flickr_pages_generated(built):
    for page in ("flickr.html", "tags.html", "albums.html", "js/flickr-data.js"):
        assert (built["out"] / page).exists(), f"missing {page}"


def test_public_item_count(built):
    """8 public items in the fixture; 2 non-public excluded."""
    items = flickr_items(built["out"])
    assert len(items) == 8, sorted(items)


def test_every_item_has_media(built):
    items = flickr_items(built["out"])
    for pid, entry in items.items():
        assert entry.get("m"), f"flickr item {pid} has no media"


def test_same_second_collision_keeps_both(built):
    """
    Two items share a date_taken second. Entries are keyed by photo id
    precisely so neither is dropped — a timestamp-keyed dict would lose one.
    """
    items = flickr_items(built["out"])
    a, b = str(built["ids"]["collide_a"]), str(built["ids"]["collide_b"])
    assert a in items and b in items
    assert items[a]["t"] == items[b]["t"], "fixture no longer collides"


def test_geo_scaling_and_rounding(built):
    """Flickr geo is degrees x 1e6 as integer strings; divide, round to 5dp."""
    items = flickr_items(built["out"])
    entry = items[str(built["ids"]["geo"])]
    assert entry["la"] == 22.285
    assert entry["lo"] == 114.15217


def test_description_html_flattened_to_text(built):
    """<br> becomes a newline; a link becomes 'label (url)'. Never raw HTML."""
    items = flickr_items(built["out"])
    desc = items[str(built["ids"]["plain"])]["ds"]
    assert "<br>" not in desc and "<a " not in desc
    assert "Line one\nLine two" in desc
    assert "link (https://example.com)" in desc


def test_tags_and_albums(built):
    data = source(built["out"], "flickr")
    items = data["items"]
    entry = items[str(built["ids"]["plain"])]
    assert set(entry["tg"]) == {"holiday", "beach"}
    assert entry["al"] == ["7001"]
    albums = data["albums"]
    assert albums["7001"]["t"] == "Summer"
    assert "7002" not in albums, "synthetic 'not in an album' should be skipped"


def test_default_license_omitted(built):
    """'All Rights Reserved' is the default and is not worth a field."""
    items = flickr_items(built["out"])
    assert "lic" not in items[str(built["ids"]["plain"])]
    assert items[str(built["ids"]["geo"])]["lic"] == "Attribution License"


def test_view_and_fave_counts_not_imported(built):
    blob = json.dumps(source(built["out"], "flickr"))
    for field in ('"count_views"', '"count_faves"', '"count_comments"'):
        assert field not in blob


def test_video_identified_from_cache(built):
    """
    Videos are indistinguishable from photos in the export metadata; only the
    API sweep (cached here) marks them. This proves the cache path works with
    no network.
    """
    items = flickr_items(built["out"])
    entry = items[str(built["ids"]["video"])]
    assert entry.get("vd") == 1, "video not flagged"
    assert entry["m"][0].endswith(".mp4")
    assert "vu" not in entry, "local video should not carry a remote fallback URL"


def test_zip_part_item_imported(built):
    """
    Media inside an un-extracted data-download-*.zip is indexed in place and
    materialized on demand.
    """
    items = flickr_items(built["out"])
    assert str(built["ids"]["zipped"]) in items
    cache = built["flickr"] / "originals-cache"
    assert cache.exists() and any(cache.iterdir()), "zip member never materialized"


def test_untitled_filename_pattern_indexed(built):
    items = flickr_items(built["out"])
    entry = items[str(built["ids"]["untitled"])]
    assert entry.get("m"), "untitled-pattern file not matched to its item"
    assert "tt" not in entry, "untitled item should carry no title"


def test_exif_rotation_applied_exactly_once(built):
    """
    The fixture is landscape (red left half, blue right half) carrying EXIF
    orientation 6 and metadata rotation 0. Exactly one correction turns it
    portrait with red on top; applying both (the historical double-rotation
    bug) does not.
    """
    items = flickr_items(built["out"])
    path = built["out"] / items[str(built["ids"]["rotated"])]["m"][0]
    with Image.open(path) as img:
        img = img.convert("RGB")
        w, h = img.size
        assert h > w, f"expected portrait after rotation, got {img.size}"
        # Sample well inside each half so lossy re-encoding at the seam
        # cannot decide the result.
        top = img.getpixel((w // 2, h // 4))
        bottom = img.getpixel((w // 2, h * 3 // 4))
    assert top[0] > top[2], f"top should be reddish, got {top}"
    assert bottom[2] > bottom[0], f"bottom should be bluish, got {bottom}"


# --------------------------------------------------------------------------
# output artifacts
# --------------------------------------------------------------------------

def test_flickr_browser_data_wrapped_and_enriched(built):
    text = (built["out"] / "js/flickr-data.js").read_text(encoding="utf-8")
    assert "window.flickrData = JSON.parse(" in text
    assert "window.flickrAlbums" in text, "album title map missing"
    assert "</" not in text
    items = decode_browser_data(built["out"] / "js/flickr-data.js", "flickrData")
    assert any("th" in e or "dm" in e for e in items.values())


def test_sidecar_has_no_browser_only_fields(built):
    assert_no_browser_only_fields_in_sidecar(built["out"])


def test_nav_shows_both_services(built):
    html = (built["out"] / "index.html").read_text(encoding="utf-8")
    assert "Instagram testuser" in html
    assert "Flickr tester" in html, "Flickr nav row missing its alias label"
    for href in ("flickr.html", "tags.html", "albums.html"):
        assert href in html


def test_timeline_wires_up_flickr(built):
    """
    Only the newest month is server-rendered, and in this fixture that month
    is Instagram's (2024-03) while the Flickr items sit in 2018 — so the
    timeline should carry the Flickr *machinery* and list the Flickr months,
    with the tiles themselves built client-side on demand.
    """
    html = (built["out"] / "timeline.html").read_text(encoding="utf-8")
    assert "flickr-data.js" in html, "timeline does not load the Flickr data"
    assert "flickr-viewer.js" in html, "timeline does not load the Flickr viewer"
    assert 'id="flickrModal"' in html, "Flickr viewer partial not included"
    assert 'value="2018-06"' in html, "Flickr months missing from the month select"
    # exactly one server-rendered month, regardless of how many exist
    assert html.count('class="timeline-month"') == 1


def test_exclude_file_and_report_written(built):
    """Dedup always leaves an audit trail in the input directory."""
    assert (built["flickr"] / "flickr_exclude.json").exists()
    assert (built["flickr"] / "flickr_dedup_report.json").exists()
