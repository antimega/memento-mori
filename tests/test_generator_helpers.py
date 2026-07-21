"""Pure-function unit tests for generator.py's helpers."""

import json

import pytest

from memento_mori.generator import (
    _as_json_parse,
    _compact_entries,
    _minify_html,
    _slugify,
    _thumb_field,
    InstagramSiteGenerator,
)


class TestCompactEntries:
    def test_drops_empty_optional_fields(self):
        out = _compact_entries({"1": {
            "i": 0, "m": ["a.webp"], "t": 1, "d": "day",
            "pl": "", "tt": "", "im": "", "l": "", "c": "", "la": "", "lo": "",
        }})
        assert set(out["1"]) == {"i", "m", "t", "d"}

    def test_keeps_populated_optional_fields(self):
        out = _compact_entries({"1": {
            "i": 0, "m": ["a.webp"], "t": 1, "d": "day",
            "pl": "Porto", "la": 41.15, "lo": -8.6167, "tt": "hi",
        }})
        assert out["1"]["pl"] == "Porto"
        assert out["1"]["la"] == 41.15

    def test_keeps_zero_index(self):
        """i=0 is falsy but is a real index — dropping it breaks the viewer."""
        out = _compact_entries({"1": {"i": 0, "m": ["a"], "t": 1, "d": "d"}})
        assert out["1"]["i"] == 0

    def test_does_not_mutate_input(self):
        src = {"1": {"i": 0, "m": ["a"], "t": 1, "d": "d", "tt": ""}}
        _compact_entries(src)
        assert "tt" in src["1"], "compaction leaked into the in-memory package"


class TestAsJsonParse:
    def test_round_trips(self):
        data = {"1": {"tt": "hello", "m": ["a.webp"]}}
        js = _as_json_parse(data)
        assert js.startswith("JSON.parse(")
        inner = js[len("JSON.parse("):-1]
        assert json.loads(json.loads(inner)) == data

    def test_escapes_closing_script_sequences(self):
        """
        An unescaped </script> inside a caption would end the script element
        and dump the rest of the data into the page as text.
        """
        js = _as_json_parse({"1": {"tt": "</script><b>x</b>"}})
        assert "</" not in js
        assert "<\\/" in js

    def test_preserves_non_ascii(self):
        js = _as_json_parse({"1": {"tt": "Café — naïve"}})
        inner = js[len("JSON.parse("):-1]
        assert json.loads(json.loads(inner))["1"]["tt"] == "Café — naïve"


class TestThumbField:
    def test_root_md5_thumbnail_becomes_th(self):
        h = "0" * 32
        assert _thumb_field(f"thumbnails/{h}.webp") == ("th", h)

    def test_story_subdirectory_becomes_dm(self):
        """
        Story thumbnails live one directory down, which the th pattern
        deliberately does not match — they must fall through to dm or the
        client resolver would build the wrong path.
        """
        url = "thumbnails/stories/" + "a" * 32 + ".webp"
        assert _thumb_field(url) == ("dm", url)

    def test_arbitrary_media_becomes_dm(self):
        assert _thumb_field("media/posts/abc.webp") == ("dm", "media/posts/abc.webp")

    def test_empty_yields_nothing(self):
        assert _thumb_field("") == (None, None)


class TestMinifyHtml:
    def test_collapses_indentation_between_tags(self):
        out = _minify_html("<div>\n    <p>x</p>\n</div>")
        assert "    " not in out

    def test_preserves_script_contents(self):
        src = '<script>\n  var a = {"k":  "v"};\n</script>'
        assert 'var a = {"k":  "v"};' in _minify_html(src)

    def test_preserves_textarea_and_pre(self):
        for tag in ("textarea", "pre"):
            src = f"<{tag}>\n  spaced   text\n</{tag}>"
            assert "spaced   text" in _minify_html(src)

    def test_preserves_text_node_content(self):
        """Place names and captions are text nodes — never collapse them."""
        out = _minify_html("<span>Porto, Portugal</span>")
        assert "Porto, Portugal" in out


class TestYearSpan:
    def test_empty(self):
        assert InstagramSiteGenerator._year_span([]) == ""

    def test_single_year(self):
        # 2018-06-01 and 2018-09-01
        assert InstagramSiteGenerator._year_span([1527811200, 1535760000]) == "2018"

    def test_span(self):
        # 2018 .. 2024
        assert InstagramSiteGenerator._year_span([1527811200, 1710504000]) == "2018-2024"


class TestSlugify:
    def test_lowercases_and_hyphenates(self):
        assert _slugify("New York City") == "new-york-city"

    def test_strips_punctuation(self):
        assert "," not in _slugify("Porto, Portugal")
