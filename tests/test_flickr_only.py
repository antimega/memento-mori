"""
A site built from Flickr alone — no Instagram archive, no existing output.

This is what the multi-source restructure exists to make possible, and it is
the configuration nothing exercised before: every page, count and nav row has
to work with the Instagram source simply absent.
"""

import json
import sys

import pytest

from tests.conftest import make_flickr_export, make_instagram_export, write_api_cache
from tests.helpers import (
    decode_browser_data,
    flickr_items,
    ig_posts,
    read_data_json,
    source,
)


def _cli(*args):
    from memento_mori import cli
    argv = sys.argv
    sys.argv = ["memento-mori"] + [str(a) for a in args]
    try:
        return cli.main()
    finally:
        sys.argv = argv


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("flickronly")
    flickr = root / "flickr-download"
    flickr.mkdir()
    info = make_flickr_export(flickr)
    write_api_cache(flickr, video_ids=[info["ids"]["video"]])
    out = root / "output"

    argv = sys.argv
    sys.argv = ["memento-mori", "--no-auto-detect", "--flickr", str(flickr),
                "--output", str(out)]
    try:
        from memento_mori import cli
        rc = cli.main()
    finally:
        sys.argv = argv
    assert rc == 0, "flickr-only build failed"
    return {"out": out, "flickr": flickr, "ids": info["ids"], "root": root}


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------

def test_flickr_pages_exist(built):
    # The timeline is the home page at index.html (no separate timeline.html).
    for page in ("flickr.html", "tags.html", "albums.html", "index.html",
                 "js/flickr-data.js"):
        assert (built["out"] / page).exists(), f"missing {page}"


def test_timeline_is_generated_and_populated(built):
    """
    The timeline spans all sources and is the home page (index.html). Gating
    it on Instagram (as the old code did) would ship a nav link to a page that
    was never written.
    """
    html = (built["out"] / "index.html").read_text(encoding="utf-8")
    assert html.count('class="timeline-month"') == 1
    assert "flickr-data.js" in html
    assert "flickr-tile" in html, "newest month has no Flickr tiles"


def test_instagram_pages_are_absent(built):
    for page in ("stories.html",):
        assert not (built["out"] / page).exists(), f"{page} built without Instagram"


def test_index_is_the_timeline_not_a_redirect(built):
    """
    index.html is the timeline home even for a Flickr-only site — the timeline
    spans every source, so it always resolves and no redirect stub is needed.
    """
    html = (built["out"] / "index.html").read_text(encoding="utf-8")
    assert 'http-equiv="refresh"' not in html, "index.html should be the timeline, not a redirect"
    assert 'class="timeline-month"' in html, "index.html is not the timeline"
    assert "flickr-tile" in html, "the Flickr-only home has no Flickr tiles"


def test_editor_is_generated_for_the_bio(built):
    """
    The editor owns the site bio, so it must exist even with no Instagram
    content to tag — a Flickr export's description is often empty.
    """
    assert (built["out"] / "edit.html").exists()
    assert (built["out"] / "edit-cities.html").exists()


# --------------------------------------------------------------------------
# identity and navigation
# --------------------------------------------------------------------------

def test_identity_comes_from_the_flickr_account(built):
    html = (built["out"] / "flickr.html").read_text(encoding="utf-8")
    assert "tester" in html, "site is not named after the Flickr account"
    assert "Flickr bio text" in html, "Flickr description not used as the bio"


def test_nav_has_only_the_flickr_row(built):
    html = (built["out"] / "flickr.html").read_text(encoding="utf-8")
    assert "Flickr tester" in html
    assert "Instagram" not in html, "Instagram nav row rendered with no Instagram"
    for href in ("flickr.html", "tags.html", "albums.html", "index.html"):
        assert href in html, f"nav is missing {href}"


def test_nav_links_all_resolve(built):
    """No dead links: every page the nav points at was actually written."""
    import re
    html = (built["out"] / "flickr.html").read_text(encoding="utf-8")
    nav = re.findall(r'class="nav-link[^"]*"[^>]*href="([^"]+)"', html)
    nav += re.findall(r'href="([^"]+)"[^>]*class="nav-link', html)
    for href in set(nav):
        target = href.split("#")[0].split("?")[0]
        assert (built["out"] / target).exists(), f"nav links to missing {target}"


def test_empty_instagram_data_files_still_written(built):
    """
    index.html (the timeline) loads posts-data.js/stories-data.js unguarded,
    so they must exist and parse even with no Instagram — otherwise every
    script on the page dies on an undefined global.
    """
    assert decode_browser_data(built["out"] / "js/posts-data.js", "postData") == {}
    assert decode_browser_data(
        built["out"] / "js/stories-data.js", "storiesData") == {}


# --------------------------------------------------------------------------
# sidecar and round-trips
# --------------------------------------------------------------------------

def test_sidecar_has_only_the_flickr_source(built):
    data = read_data_json(built["out"])
    assert data["schema_version"] == 2
    assert set(data["sources"]) == {"flickr"}
    assert data["sources"]["flickr"]["profile"]["username"] == "tester"


def test_regenerate_round_trip(built, tmp_path_factory):
    """A Flickr-only sidecar must re-render without the export present."""
    assert _cli("--output", built["out"], "--regenerate") == 0
    assert len(flickr_items(built["out"])) == 8
    assert (built["out"] / "flickr.html").exists()


def test_privacy_still_enforced(built):
    from tests.helpers import grep_tree
    for id_key in ("private", "friends"):
        pid = str(built["ids"][id_key])
        assert not grep_tree(built["out"], pid), f"{id_key} leaked"


# --------------------------------------------------------------------------
# the upgrade path
# --------------------------------------------------------------------------

def test_merging_instagram_later_upgrades_the_site(tmp_path):
    """
    Flickr-only today, combined tomorrow: merging Instagram adds the posts
    grid at posts.html, folds the posts into the timeline home (index.html),
    flips identity to Instagram, and leaves the Flickr section untouched.
    """
    flickr = tmp_path / "flickr-download"
    flickr.mkdir()
    info = make_flickr_export(flickr)
    write_api_cache(flickr, video_ids=[info["ids"]["video"]])
    out = tmp_path / "output"
    assert _cli("--no-auto-detect", "--flickr", flickr, "--output", out) == 0

    before_flickr = flickr_items(out)
    # Flickr-only: the home is the timeline, and there is no posts grid yet.
    assert "http-equiv=\"refresh\"" not in (out / "index.html").read_text(encoding="utf-8")
    assert not (out / "posts.html").exists(), "posts grid exists before any Instagram import"

    export = tmp_path / "ig-export"
    export.mkdir()
    make_instagram_export(export)
    assert _cli("--merge", "--input", export, "--output", out) == 0

    assert (out / "posts.html").exists(), "merge did not add the posts grid"
    assert "grid-item" in (out / "posts.html").read_text(encoding="utf-8"), \
        "posts.html is not the posts grid"
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "http-equiv=\"refresh\"" not in index, "home is not the timeline after the merge"
    assert "Instagram testuser" in index and "Flickr tester" in index
    assert flickr_items(out) == before_flickr, "merge disturbed the Flickr section"
    assert ig_posts(out), "merge added no posts"


# --------------------------------------------------------------------------
# guards
# --------------------------------------------------------------------------

def test_fresh_flickr_only_refuses_to_clobber_an_instagram_site(tmp_path):
    """
    A fresh run rebuilds from only what it is given. Running Flickr-only over
    a site that has Instagram would drop it, so the run is refused.
    """
    export = tmp_path / "ig-export"
    export.mkdir()
    make_instagram_export(export)
    out = tmp_path / "output"
    assert _cli("--input", export, "--output", out, "--no-auto-detect") == 0

    flickr = tmp_path / "flickr-download"
    flickr.mkdir()
    make_flickr_export(flickr)
    assert _cli("--no-auto-detect", "--flickr", flickr, "--output", out) == 1
    # and the existing site is untouched
    assert set(read_data_json(out)["sources"]) == {"instagram"}


def test_fresh_instagram_refuses_to_clobber_a_flickr_section(tmp_path):
    """
    The previously-silent data-loss case: a plain Instagram rebuild over a
    combined site used to drop the whole Flickr section from the sidecar.
    """
    export = tmp_path / "ig-export"
    export.mkdir()
    make_instagram_export(export)
    flickr = tmp_path / "flickr-download"
    flickr.mkdir()
    info = make_flickr_export(flickr)
    write_api_cache(flickr, video_ids=[info["ids"]["video"]])
    out = tmp_path / "output"
    assert _cli("--input", export, "--output", out, "--no-auto-detect",
                "--flickr", flickr) == 0

    assert _cli("--input", export, "--output", out, "--no-auto-detect") == 1
    assert len(flickr_items(out)) == 8, "Flickr section was lost"


def test_fresh_run_reproviding_everything_is_allowed(tmp_path):
    """The guard blocks loss, not legitimate rebuilds."""
    export = tmp_path / "ig-export"
    export.mkdir()
    make_instagram_export(export)
    flickr = tmp_path / "flickr-download"
    flickr.mkdir()
    info = make_flickr_export(flickr)
    write_api_cache(flickr, video_ids=[info["ids"]["video"]])
    out = tmp_path / "output"
    args = ("--input", export, "--output", out, "--no-auto-detect",
            "--flickr", flickr)
    assert _cli(*args) == 0
    assert _cli(*args) == 0, "re-running the same fresh build was refused"


def test_no_sources_at_all_is_an_error(tmp_path):
    out = tmp_path / "output"
    assert _cli("--no-auto-detect", "--output", out) == 1
