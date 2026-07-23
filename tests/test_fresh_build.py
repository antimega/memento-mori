"""
A fresh Instagram-only build, end to end through the real CLI.

This is the load-bearing integration test: it exercises extractor -> loader ->
media -> generator on genuine files and pins the artifacts the rest of the
suite (and the multi-source restructure) depends on.
"""

import json

import pytest

from tests.helpers import (
    assert_no_browser_only_fields_in_sidecar,
    assert_thumbnails_resolve,
    decode_browser_data,
    ig_posts,
    ig_stories,
    read_data_json,
)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """Build once, assert many times — the media pipeline is the slow part."""
    import sys
    from memento_mori import cli

    root = tmp_path_factory.mktemp("fresh")
    export = root / "ig-export"
    export.mkdir()
    out = root / "output"

    from tests.conftest import make_instagram_export
    ts = make_instagram_export(export)

    argv = sys.argv
    sys.argv = ["memento-mori", "--input", str(export), "--output", str(out),
                "--no-auto-detect"]
    try:
        rc = cli.main()
    finally:
        sys.argv = argv
    assert rc == 0, "fresh build failed"
    return {"out": out, "ts": ts, "export": export}


def test_exit_code_and_core_pages(built):
    out = built["out"]
    # index.html is the timeline (the home page); the posts grid is posts.html.
    for page in ("index.html", "posts.html", "stories.html",
                 "edit.html", "edit-cities.html"):
        assert (out / page).exists(), f"missing {page}"
    assert not (out / "timeline.html").exists(), "timeline.html should now be index.html"


def test_flickr_and_cities_pages_absent(built):
    """Nothing Flickr- or city-shaped should exist without those inputs."""
    out = built["out"]
    for page in ("flickr.html", "tags.html", "albums.html", "cities.html",
                 "js/flickr-data.js"):
        assert not (out / page).exists(), f"{page} generated without its input"


def test_nav_has_no_flickr_row(built):
    html = (built["out"] / "index.html").read_text(encoding="utf-8")
    assert "Flickr" not in html, "Flickr nav row rendered without a Flickr import"
    assert "Instagram testuser" in html, "Instagram nav row label missing"


def test_browser_data_is_json_parse_wrapped(built):
    """
    The data files must stay JSON.parse-wrapped: it is ~2-4x faster to parse
    than an object literal, and the </ escaping stops a caption from closing
    the script tag.
    """
    for name, var in (("js/posts-data.js", "postData"),
                      ("js/stories-data.js", "storiesData")):
        text = (built["out"] / name).read_text(encoding="utf-8")
        assert f"window.{var} = JSON.parse(" in text
        assert "</" not in text, f"{name} contains an unescaped </"
        assert decode_browser_data(built["out"] / name, var)


def test_post_entries_have_expected_shape(built):
    posts = decode_browser_data(built["out"] / "js/posts-data.js", "postData")
    ts = built["ts"]
    assert str(ts["single"]) in posts
    entry = posts[str(ts["single"])]
    for field in ("i", "m", "t", "d"):
        assert field in entry, f"post entry missing {field}"
    assert isinstance(entry["m"], list) and entry["m"]


def test_carousel_keeps_all_media(built):
    posts = decode_browser_data(built["out"] / "js/posts-data.js", "postData")
    entry = posts[str(built["ts"]["carousel"])]
    assert len(entry["m"]) == 3, "carousel lost media"


def test_caption_encoding_is_repaired(built):
    """ftfy + html.unescape run at load: mojibake and entities are fixed."""
    posts = decode_browser_data(built["out"] / "js/posts-data.js", "postData")
    title = posts[str(built["ts"]["single"])]["tt"]
    assert "Café" in title, f"mojibake not repaired: {title!r}"
    assert "&" in title and "&amp;" not in title, f"entity not unescaped: {title!r}"


def test_untitled_post_has_no_empty_title(built):
    """_compact_entries drops empty optional fields rather than shipping ''."""
    posts = decode_browser_data(built["out"] / "js/posts-data.js", "postData")
    entry = posts[str(built["ts"]["no_title"])]
    assert entry.get("tt", "") == "" and "tt" not in entry


def test_place_and_coords_attach_across_one_second(built):
    """
    Place lives in the newer posts.json, the post in the classic posts_1.json,
    and their timestamps differ by a second. The loader's +/-1s tolerance is
    what joins them.
    """
    posts = decode_browser_data(built["out"] / "js/posts-data.js", "postData")
    entry = posts[str(built["ts"]["single"])]
    assert entry.get("pl") == "Porto, Portugal"
    assert entry.get("la") == 41.15
    assert entry.get("lo") == -8.6167


def test_exif_coordinates_fallback(built):
    """Coordinates with no newer-format entry come from EXIF, rounded to 4dp."""
    posts = decode_browser_data(built["out"] / "js/posts-data.js", "postData")
    entry = posts[str(built["ts"]["exif"])]
    assert entry.get("la") == 51.5174, f"got {entry.get('la')!r}"
    assert entry.get("lo") == -0.1437, f"got {entry.get('lo')!r}"


def test_video_post_gets_a_poster(built):
    posts = decode_browser_data(built["out"] / "js/posts-data.js", "postData")
    entry = posts[str(built["ts"]["video"])]
    assert entry["m"][0].endswith(".mp4")
    assert "vp" in entry, "video post has no poster map"


def test_thumbnails_resolve_on_disk(built):
    assert assert_thumbnails_resolve(built["out"]) > 0, "no th fields to check"


def test_sidecar_has_no_browser_only_fields(built):
    assert_no_browser_only_fields_in_sidecar(built["out"])


def test_sidecar_shape(built):
    """
    Schema v2: every import lives under `sources`, and nothing derivable is
    stored — counts and identity are computed at render time so they cannot
    drift from the data they describe.
    """
    data = read_data_json(built["out"])
    assert data["schema_version"] == 2
    assert set(data["sources"]) == {"instagram"}

    instagram = data["sources"]["instagram"]
    assert instagram["profile"]["username"] == "testuser"
    assert instagram["profile"]["bio"] == "A test bio"
    assert instagram["posts"] and instagram["stories"]

    for derived in ("post_count", "story_count", "date_range"):
        assert derived not in data, f"{derived} is derivable and should not be stored"
    assert "city_tags" not in data, "city_tags must be popped from the sidecar"


def test_stories_present(built):
    stories = decode_browser_data(built["out"] / "js/stories-data.js", "storiesData")
    assert str(built["ts"]["story"]) in stories
    assert str(built["ts"]["story_video"]) in stories


def test_timeline_renders_only_the_newest_month(built):
    """
    The on-demand-months design: exactly one month panel in the HTML, with
    every month still listed in the select.
    """
    html = (built["out"] / "index.html").read_text(encoding="utf-8")
    assert html.count('class="timeline-month"') == 1
    assert '<select' in html and 'id="monthSelect"' in html


def test_grids_seed_only_a_first_chunk_of_tiles(built):
    """
    The posts and stories grids ship a fixed seed of tiles, not the whole
    archive: posts-grid.js / stories-grid.js append the rest from the browser
    data as the reader scrolls.

    Shipping every tile is what made these pages slow to become interactive —
    tens of thousands of DOM nodes re-parsed and re-laid-out on every load,
    which no HTTP caching avoids. Guard the seeding so that can't come back.
    """
    from memento_mori.generator import GRID_SEED

    out = built["out"]
    posts_html = (out / "posts.html").read_text(encoding="utf-8")
    stories_html = (out / "stories.html").read_text(encoding="utf-8")

    tiles = posts_html.count('class="grid-item"')
    story_tiles = stories_html.count('class="story-item"')
    total_posts = len(ig_posts(out))
    total_stories = len(ig_stories(out))

    # The fixture may hold fewer items than the seed; never more than the seed.
    assert tiles == min(GRID_SEED, total_posts), (
        f"posts.html server-rendered {tiles} tiles, expected "
        f"{min(GRID_SEED, total_posts)}"
    )
    assert story_tiles == min(GRID_SEED, total_stories)

    # ...and the builders that append the remainder must actually be loaded.
    assert "js/posts-grid.js" in posts_html
    assert "js/stories-grid.js" in stories_html
    assert 'id="postsGrid"' in posts_html
    assert 'id="storiesGrid"' in stories_html


def test_no_style_blocks_or_profile_picture(built):
    """
    Two invariants from earlier cleanups: all CSS lives in style.css, and the
    profile picture is gone from the markup entirely.
    """
    for page in ("index.html", "posts.html", "stories.html"):
        html = (built["out"] / page).read_text(encoding="utf-8")
        assert "<style" not in html, f"{page} carries an inline <style> block"
        assert "profile-picture" not in html, f"{page} still renders a profile picture"
