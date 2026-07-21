"""Unit tests for the Flickr loader, geo parsing, HTML flattening and dedup."""

import json
from pathlib import Path

import pytest

from memento_mori.flickr import (
    FlickrDataLoader,
    _HTMLToText,
    _parse_flickr_date,
    _parse_geo,
    dedupe_against_instagram,
    finalize_items,
)

_html_to_text = _HTMLToText.convert
from tests.conftest import make_flickr_export


class TestParseGeo:
    """Contract: a (lat, lng) tuple on success, bare None on any failure."""

    def test_scales_from_integer_microdegrees(self):
        # /1e6 then rounded to 5dp (~1m) — see test_rounds_to_five_places
        lat, lng = _parse_geo([{"latitude": "51561666", "longitude": "-143719"}])
        assert lat == 51.56167
        assert lng == -0.14372

    def test_rounds_to_five_places(self):
        lat, lng = _parse_geo([{"latitude": "22285000", "longitude": "114152166"}])
        assert lat == 22.285
        assert lng == 114.15217

    def test_rejects_zero_island(self):
        """0.0/0.0 is Flickr's 'no geo' sentinel, not a place in the Atlantic."""
        assert _parse_geo([{"latitude": "0", "longitude": "0"}]) is None

    def test_rejects_single_zero_axis(self):
        assert _parse_geo([{"latitude": "51561666", "longitude": "0"}]) is None

    def test_empty_list(self):
        assert _parse_geo([]) is None

    def test_malformed_values(self):
        assert _parse_geo([{"latitude": "abc", "longitude": "1"}]) is None

    def test_missing_key(self):
        assert _parse_geo([{"latitude": "51561666"}]) is None


class TestParseFlickrDate:
    def test_parses_export_format(self):
        assert _parse_flickr_date("2018-06-01 10:00:00") is not None

    def test_rejects_junk(self):
        assert _parse_flickr_date("") is None
        assert _parse_flickr_date("not a date") is None
        assert _parse_flickr_date("0000-00-00 00:00:00") is None


class TestHtmlToText:
    def test_br_becomes_newline(self):
        assert _html_to_text("a<br>b") == "a\nb"

    def test_paragraphs_separate(self):
        assert "\n" in _html_to_text("<p>one</p><p>two</p>")

    def test_link_keeps_label_and_url(self):
        out = _html_to_text('<a href="https://example.com">click</a>')
        assert "click" in out and "https://example.com" in out

    def test_entities_unescaped(self):
        assert "&" in _html_to_text("a &amp; b")
        assert "&amp;" not in _html_to_text("a &amp; b")

    def test_plain_text_untouched(self):
        assert _html_to_text("just text") == "just text"


class TestLoadItems:
    @pytest.fixture
    def loaded(self, tmp_path):
        root = tmp_path / "flickr"
        root.mkdir()
        info = make_flickr_export(root, with_media=False, with_zip=False)
        loader = FlickrDataLoader(root)
        items, aux = loader.load_items()
        return {"items": items, "aux": aux, "ids": info["ids"], "root": root}

    def test_only_public_items_load(self, loaded):
        assert len(loaded["items"]) == 8
        assert str(loaded["ids"]["private"]) not in loaded["items"]
        assert str(loaded["ids"]["friends"]) not in loaded["items"]

    def test_keyed_by_photo_id(self, loaded):
        assert str(loaded["ids"]["plain"]) in loaded["items"]

    def test_title_and_description(self, loaded):
        entry = loaded["items"][str(loaded["ids"]["plain"])]
        assert entry["tt"] == "A plain photo"
        assert "<br>" not in entry["ds"]

    def test_untitled_item_has_no_title_field(self, loaded):
        entry = loaded["items"][str(loaded["ids"]["untitled"])]
        assert not entry.get("tt")

    def test_tags_are_plain_strings(self, loaded):
        entry = loaded["items"][str(loaded["ids"]["plain"])]
        assert entry["tg"] == ["holiday", "beach"] or set(entry["tg"]) == {"holiday", "beach"}
        assert all(isinstance(t, str) for t in entry["tg"])

    def test_album_ids_only(self, loaded):
        entry = loaded["items"][str(loaded["ids"]["plain"])]
        assert entry["al"] == ["7001"]

    def test_default_license_omitted(self, loaded):
        assert "lic" not in loaded["items"][str(loaded["ids"]["plain"])]

    def test_missing_date_taken_skips_the_item(self, tmp_path):
        root = tmp_path / "f2"
        (root / "flickr_metadata").mkdir(parents=True)
        (root / "flickr_metadata" / "photo_1.json").write_text(json.dumps({
            "id": "1", "privacy": "public", "date_taken": "", "name": "x",
            "tags": [], "albums": [], "geo": [],
        }), encoding="utf-8")
        items, _ = FlickrDataLoader(root).load_items()
        assert items == {}

    def test_missing_metadata_dir_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            FlickrDataLoader(tmp_path / "nope")


class TestAlbums:
    def test_only_referenced_and_real_albums(self, tmp_path):
        root = tmp_path / "flickr"
        root.mkdir()
        make_flickr_export(root, with_media=False, with_zip=False)
        loader = FlickrDataLoader(root)
        items, _ = loader.load_items()
        referenced = {a for e in items.values() for a in e.get("al", [])}
        albums = loader.load_albums(referenced)
        assert "7001" in albums and albums["7001"]["t"] == "Summer"
        assert "7002" not in albums, "synthetic 'not in an album' kept"


class TestFinalizeItems:
    def test_orders_newest_first_and_indexes(self):
        items = {
            "100": {"t": 10, "m": ["a"]},
            "200": {"t": 30, "m": ["b"]},
            "300": {"t": 20, "m": ["c"]},
        }
        finalize_items(items)
        assert items["200"]["i"] == 0
        assert items["300"]["i"] == 1
        assert items["100"]["i"] == 2

    def test_ties_break_by_descending_id(self):
        """Same second: deterministic order, not dict insertion order."""
        items = {"100": {"t": 5, "m": ["a"]}, "200": {"t": 5, "m": ["b"]}}
        finalize_items(items)
        assert items["200"]["i"] < items["100"]["i"]


class TestDedupe:
    def _aux(self, ids, imported):
        return {str(i): {"imported": t, "ig_tagged": False}
                for i, t in zip(ids, imported)}

    def test_no_instagram_timestamps_is_a_no_op(self, tmp_path):
        items = {"1": {"t": 1}, "2": {"t": 2}}
        aux = self._aux([1, 2], [100, 200])
        out = dedupe_against_instagram(items, aux, [], tmp_path)
        assert len(out) == 2

    def test_exclusion_file_is_always_honored(self, tmp_path):
        """
        The manual escape hatch works at any scale — it does not depend on
        the statistical calibration finding an offset.
        """
        (tmp_path / "flickr_exclude.json").write_text(json.dumps({
            "exclude": {"2": "by hand"}
        }), encoding="utf-8")
        items = {"1": {"t": 1}, "2": {"t": 2}}
        aux = self._aux([1, 2], [100, 200])
        out = dedupe_against_instagram(items, aux, [], tmp_path)
        assert set(out) == {"1"}

    def test_clear_offset_triggers_auto_exclusion(self, tmp_path):
        """
        30 items imported exactly 1h before 30 Instagram posts, spread wide
        enough that no other offset matches. That clears the guard
        (best >= 25 and best >= 2 * second) and dedup fires.
        """
        base = 1_600_000_000
        ig = [base + i * 86_400 for i in range(30)]
        ids = list(range(1, 31))
        imported = [t - 3600 for t in ig]
        items = {str(i): {"t": 1} for i in ids}
        aux = self._aux(ids, imported)

        out = dedupe_against_instagram(items, aux, ig, tmp_path)

        assert out == {}, "all 30 cross-posts should have been excluded"
        report = json.loads((tmp_path / "flickr_dedup_report.json").read_text())
        assert len(report["excluded"]) == 30
        exclude = json.loads((tmp_path / "flickr_exclude.json").read_text())
        assert len(exclude["exclude"]) == 30

    def test_weak_signal_skips_auto_dedup(self, tmp_path):
        """
        Below the threshold nothing is removed — the calibration must not
        act on noise.
        """
        base = 1_600_000_000
        ig = [base + i * 86_400 for i in range(5)]
        ids = list(range(1, 6))
        items = {str(i): {"t": 1} for i in ids}
        aux = self._aux(ids, [t - 3600 for t in ig])

        out = dedupe_against_instagram(items, aux, ig, tmp_path)
        assert len(out) == 5, "auto-dedup fired below its confidence threshold"

    def test_report_is_always_written(self, tmp_path):
        dedupe_against_instagram({"1": {"t": 1}}, self._aux([1], [10]), [], tmp_path)
        assert (tmp_path / "flickr_dedup_report.json").exists()
