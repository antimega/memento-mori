"""
city_tags.json: the editor's export, and the only user-authored input.

It carries city tags, favourites, per-city coordinates and Markdown, and the
site bio. Everything here flows through --regenerate, which is the loop the
editor is built around.
"""

import json
import sys

import pytest

from tests.conftest import make_instagram_export
from tests.helpers import read_data_json


def _cli(*args):
    from memento_mori import cli
    argv = sys.argv
    sys.argv = ["memento-mori"] + [str(a) for a in args]
    try:
        return cli.main()
    finally:
        sys.argv = argv


@pytest.fixture
def site(tmp_path):
    export = tmp_path / "ig-export"
    export.mkdir()
    ts = make_instagram_export(export)
    out = tmp_path / "output"
    assert _cli("--input", export, "--output", out, "--no-auto-detect") == 0
    return {"out": out, "ts": ts}


def _write_tags(out, **overrides):
    tags = {
        "version": 1,
        "posts": {},
        "stories": {},
        "flickr": {},
        "cities": {},
        "favorites": {"posts": {}, "stories": {}, "flickr": {}},
    }
    tags.update(overrides)
    (out / "city_tags.json").write_text(json.dumps(tags), encoding="utf-8")


def test_no_tags_means_no_cities_page(site):
    assert not (site["out"] / "cities.html").exists()
    assert "cities.html" not in (site["out"] / "index.html").read_text(encoding="utf-8")


def test_tagging_creates_the_cities_page_and_nav_link(site):
    _write_tags(site["out"], posts={str(site["ts"]["single"]): "Porto"})
    assert _cli("--output", site["out"], "--regenerate") == 0

    assert (site["out"] / "cities.html").exists()
    assert "Porto" in (site["out"] / "cities.html").read_text(encoding="utf-8")
    assert "cities.html" in (site["out"] / "index.html").read_text(encoding="utf-8")


def test_city_markdown_is_rendered_as_text_for_the_client(site):
    """
    The blurb is stored raw and parsed client-side by marked, so the page
    must contain the Markdown source (escaped), not pre-rendered HTML.
    """
    _write_tags(
        site["out"],
        posts={str(site["ts"]["single"]): "Porto"},
        cities={"Porto": {"text": "**bold** and [a link](https://example.com)"}},
    )
    assert _cli("--output", site["out"], "--regenerate") == 0

    html = (site["out"] / "cities.html").read_text(encoding="utf-8")
    assert "**bold**" in html
    assert "data-md" in html
    assert "marked" in html, "the Markdown renderer is not loaded"


def test_city_coordinate_override(site):
    _write_tags(
        site["out"],
        posts={str(site["ts"]["single"]): "Porto"},
        cities={"Porto": {"lat": 41.15, "lng": -8.62}},
    )
    assert _cli("--output", site["out"], "--regenerate") == 0
    html = (site["out"] / "cities.html").read_text(encoding="utf-8")
    assert "41.15" in html and "-8.62" in html


def test_favourites_sort_first(site):
    ts = site["ts"]
    _write_tags(
        site["out"],
        posts={str(ts["single"]): "Porto", str(ts["carousel"]): "Porto"},
        favorites={"posts": {str(ts["carousel"]): True}, "stories": {}},
    )
    assert _cli("--output", site["out"], "--regenerate") == 0

    html = (site["out"] / "cities.html").read_text(encoding="utf-8")
    # The favourited (older) post must appear before the newer one.
    assert html.index(str(ts["carousel"])) < html.index(str(ts["single"]))


class TestBioTriState:
    """
    bio is tri-state: absent means "no override, use the Instagram bio";
    present - even empty - is authoritative. An empty string is a real
    choice (hide the bio), not a missing value.
    """

    def test_absent_uses_the_instagram_bio(self, site):
        _write_tags(site["out"], posts={})
        assert _cli("--output", site["out"], "--regenerate") == 0
        assert "A test bio" in (site["out"] / "index.html").read_text(encoding="utf-8")

    def test_present_overrides(self, site):
        _write_tags(site["out"], bio="An overridden bio")
        assert _cli("--output", site["out"], "--regenerate") == 0
        html = (site["out"] / "index.html").read_text(encoding="utf-8")
        assert "An overridden bio" in html
        assert "A test bio" not in html

    def test_empty_string_is_authoritative(self, site):
        _write_tags(site["out"], bio="")
        assert _cli("--output", site["out"], "--regenerate") == 0
        html = (site["out"] / "index.html").read_text(encoding="utf-8")
        assert "A test bio" not in html, "empty bio override was ignored"


def test_editor_embeds_the_effective_bio(site):
    """The editor's textarea must start from what the site currently shows."""
    _write_tags(site["out"], bio="Editor sees this")
    assert _cli("--output", site["out"], "--regenerate") == 0
    assert "Editor sees this" in (site["out"] / "edit.html").read_text(encoding="utf-8")


def test_city_tags_never_reaches_the_sidecar(site):
    """
    data.json is generator input, not user state — city_tags is popped so a
    regenerate always reads the editor's file as the source of truth.
    """
    _write_tags(site["out"], posts={str(site["ts"]["single"]): "Porto"})
    assert _cli("--output", site["out"], "--regenerate") == 0
    assert "city_tags" not in read_data_json(site["out"])


def test_missing_explicit_city_tags_file_is_an_error(site, tmp_path):
    assert _cli("--output", site["out"], "--regenerate",
                "--city-tags", tmp_path / "nope.json") == 1


# --------------------------------------------------------------------------
# Flickr city tagging
# --------------------------------------------------------------------------

@pytest.fixture
def flickr_site(tmp_path):
    """A combined site, so cities can hold both Instagram and Flickr items."""
    from tests.conftest import make_flickr_export, write_api_cache
    export = tmp_path / "ig-export"
    export.mkdir()
    ts = make_instagram_export(export)
    flickr = tmp_path / "flickr-download"
    flickr.mkdir()
    info = make_flickr_export(flickr)
    write_api_cache(flickr, video_ids=[info["ids"]["video"]])
    out = tmp_path / "output"
    assert _cli("--input", export, "--output", out, "--no-auto-detect",
                "--flickr", flickr) == 0
    return {"out": out, "ts": ts, "ids": info["ids"]}


def test_flickr_items_can_be_tagged_with_a_city(flickr_site):
    out, ids = flickr_site["out"], flickr_site["ids"]
    _write_tags(out, flickr={str(ids["plain"]): "Venice"})
    assert _cli("--output", out, "--regenerate") == 0

    html = (out / "cities.html").read_text(encoding="utf-8")
    assert "Venice" in html
    assert f'data-id="{ids["plain"]}"' in html, "tagged Flickr item not rendered"
    assert "flickr-tile" in html


def test_flickr_section_sits_between_posts_and_stories(flickr_site):
    """The user-specified order: posts, then Flickr, then stories."""
    out, ts, ids = flickr_site["out"], flickr_site["ts"], flickr_site["ids"]
    _write_tags(
        out,
        posts={str(ts["single"]): "Venice"},
        stories={str(ts["story"]): "Venice"},
        flickr={str(ids["plain"]): "Venice"},
    )
    assert _cli("--output", out, "--regenerate") == 0

    html = (out / "cities.html").read_text(encoding="utf-8")
    section = html[html.index('id="city-venice"'):]
    section = section[:section.index("</section>")]
    posts_at = section.index("timeline-tile")
    flickr_at = section.index("flickr-tile")
    stories_at = section.index("timeline-story-tile")
    assert posts_at < flickr_at < stories_at, (
        f"section order is wrong: posts={posts_at} flickr={flickr_at} "
        f"stories={stories_at}"
    )


def test_flickr_favourites_sort_first_and_show_a_star(flickr_site):
    out, ids = flickr_site["out"], flickr_site["ids"]
    first, second = str(ids["plain"]), str(ids["geo"])
    # Favourite the one that would otherwise sort second
    _write_tags(
        out,
        flickr={first: "Venice", second: "Venice"},
        favorites={"posts": {}, "stories": {}, "flickr": {second: True}},
    )
    assert _cli("--output", out, "--regenerate") == 0

    html = (out / "cities.html").read_text(encoding="utf-8")
    section = html[html.index('id="city-venice"'):]
    section = section[:section.index("</section>")]
    assert section.index(f'data-id="{second}"') < section.index(f'data-id="{first}"'), \
        "favourited Flickr item did not sort first"
    assert "fav-indicator" in section


def test_flickr_only_tags_still_build_the_cities_page(flickr_site):
    """
    The cities build used to bail out unless posts or stories were tagged;
    a Flickr-only tagging has to produce a page too.
    """
    out, ids = flickr_site["out"], flickr_site["ids"]
    _write_tags(out, flickr={str(ids["plain"]): "Venice"})
    assert _cli("--output", out, "--regenerate") == 0

    assert (out / "cities.html").exists()
    assert "cities.html" in (out / "index.html").read_text(encoding="utf-8")


def test_city_chip_count_includes_flickr(flickr_site):
    out, ts, ids = flickr_site["out"], flickr_site["ts"], flickr_site["ids"]
    _write_tags(
        out,
        posts={str(ts["single"]): "Venice"},
        flickr={str(ids["plain"]): "Venice", str(ids["geo"]): "Venice"},
    )
    assert _cli("--output", out, "--regenerate") == 0

    html = (out / "cities.html").read_text(encoding="utf-8")
    chip = html[html.index('data-city="venice"'):]
    chip = chip[:chip.index("</button>")]
    assert ">3<" in chip.replace(" ", ""), f"chip count should be 3: {chip!r}"


def test_unknown_flickr_id_is_skipped_without_failing(flickr_site):
    out, ids = flickr_site["out"], flickr_site["ids"]
    _write_tags(out, flickr={"99999999999": "Venice",
                             str(ids["plain"]): "Venice"})
    assert _cli("--output", out, "--regenerate") == 0
    html = (out / "cities.html").read_text(encoding="utf-8")
    assert f'data-id="{ids["plain"]}"' in html
    assert "99999999999" not in html


def test_cities_page_loads_the_flickr_viewer(flickr_site):
    """Tiles are inert without the viewer, its data, and the modal partial."""
    out, ids = flickr_site["out"], flickr_site["ids"]
    _write_tags(out, flickr={str(ids["plain"]): "Venice"})
    assert _cli("--output", out, "--regenerate") == 0

    html = (out / "cities.html").read_text(encoding="utf-8")
    assert "js/flickr-data.js" in html
    assert "js/flickr-viewer.js" in html
    assert 'id="flickrModal"' in html


def test_flickr_editor_page_is_generated(flickr_site):
    out = flickr_site["out"]
    assert (out / "edit-flickr.html").exists()
    assert (out / "js" / "editor-flickr.js").exists()
    html = (out / "edit-flickr.html").read_text(encoding="utf-8")
    # the only editor page that loads a data file
    assert "js/flickr-data.js" in html
    assert "js/flickr-grid.js" in html
    for page in ("edit.html", "edit-cities.html"):
        nav = (out / page).read_text(encoding="utf-8")
        assert "edit-flickr.html" in nav, f"{page} has no Flickr cities nav link"


def test_no_flickr_editor_page_without_flickr(tmp_path):
    export = tmp_path / "ig-export"
    export.mkdir()
    make_instagram_export(export)
    out = tmp_path / "output"
    assert _cli("--input", export, "--output", out, "--no-auto-detect") == 0
    assert not (out / "edit-flickr.html").exists()
    assert "edit-flickr.html" not in (out / "edit.html").read_text(encoding="utf-8")
