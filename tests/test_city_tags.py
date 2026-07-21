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
        "cities": {},
        "favorites": {"posts": {}, "stories": {}},
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
