"""Unit tests for merger.py — the incremental-update primitives."""

import json

import pytest

from memento_mori import merger


class TestComputeDateRange:
    def test_empty_is_unknown(self):
        """
        A site with no posts still needs a range dict — _page_context reads
        ["range"] unconditionally.
        """
        r = merger.compute_date_range({})
        assert r["range"] == "Unknown"
        assert r["oldest"] == "Unknown" and r["newest"] == "Unknown"

    def test_spans_oldest_to_newest(self):
        """
        Precondition: the dict is already newest-first. compute_date_range
        does NOT sort — it reads keys[0] as newest and keys[-1] as oldest.
        Hand it an ascending dict and the range comes out backwards.
        """
        r = merger.compute_date_range({"1710504000": {}, "1527811200": {}})
        assert "2018" in r["oldest"]
        assert "2024" in r["newest"]
        assert r["range"] == f"{r['oldest']} - {r['newest']}"

    def test_tolerates_string_and_int_keys(self):
        assert merger.compute_date_range({1527811200: {}})["range"] != "Unknown"


class TestComputeDelta:
    def test_only_new_keys_returned(self):
        existing = {"1": {"m": ["a"]}, "2": {"m": ["b"]}}
        incoming = {"1": {"m": ["a"]}, "3": {"m": ["c"]}}
        assert set(merger.compute_delta(existing, incoming)) == {"3"}

    def test_nothing_new(self):
        existing = {"1": {}}
        assert merger.compute_delta(existing, {"1": {}}) == {}

    def test_int_vs_str_keys_do_not_duplicate(self):
        """
        Freshly-loaded posts can carry int keys while sidecar data has str
        keys. Treating them as different would reprocess the whole archive.
        """
        existing = {"1": {"m": ["a"]}}
        assert merger.compute_delta(existing, {1: {"m": ["a"]}}) == {}


class TestMergeTimestampDicts:
    def test_union_of_both(self):
        out = merger.merge_timestamp_dicts({"1": {"m": ["a"]}}, {"2": {"m": ["b"]}})
        assert set(out) == {"1", "2"}

    def test_existing_entry_wins_on_conflict(self):
        """
        Deliberately existing-wins, not newest-wins: the existing entry's
        media is already converted into output/ under a shortened filename,
        and a fresh export can shorten to something different. Preferring the
        new entry would point the site at files it never wrote.
        """
        out = merger.merge_timestamp_dicts({"1": {"m": ["old"]}}, {"1": {"m": ["new"]}})
        assert out["1"]["m"] == ["old"]

    def test_reindexes_newest_first(self):
        """`i` drives the viewer's prev/next order, so it is rebuilt here."""
        out = merger.merge_timestamp_dicts({"100": {"m": ["a"]}}, {"300": {"m": ["b"]}})
        assert out["300"]["i"] == 0
        assert out["100"]["i"] == 1

    def test_delta_keys_are_normalized_but_existing_keys_are_not(self):
        """
        Characterizing current behavior: only the incoming delta is coerced
        to str keys; existing keys pass through as-is. Fresh loads use int
        keys and sidecar loads use str, so callers must not assume uniform
        key types here.
        """
        out = merger.merge_timestamp_dicts({1: {"m": ["a"]}}, {2: {"m": ["b"]}})
        assert 1 in out and "2" in out


class TestApplyPostMetadata:
    def test_backfills_place_and_coords(self):
        """
        Entries kept from the existing site gain metadata the new archive
        knows about — that is how a re-download adds places retroactively.
        """
        merged = {"1": {"m": ["a.webp"], "t": 1, "d": "d"}}
        source = {"1": {"pl": "Porto", "la": 41.15, "lo": -8.6167}}
        n = merger.apply_post_metadata(merged, source)
        assert n == 1
        assert merged["1"]["pl"] == "Porto"
        assert merged["1"]["la"] == 41.15

    def test_does_not_clobber_existing_values(self):
        merged = {"1": {"pl": "Existing", "m": ["a"]}}
        merger.apply_post_metadata(merged, {"1": {"pl": "New"}})
        assert merged["1"]["pl"] == "Existing"

    def test_never_overwrites_media(self):
        """Media paths are already shortened in the merged copy; the source
        still has raw export paths. Overwriting would break every image."""
        merged = {"1": {"m": ["media/posts/ab12cd34.webp"]}}
        merger.apply_post_metadata(merged, {"1": {"m": ["media/posts/original.jpg"]}})
        assert merged["1"]["m"] == ["media/posts/ab12cd34.webp"]

    def test_unknown_timestamps_ignored(self):
        merged = {"1": {"m": ["a"]}}
        assert merger.apply_post_metadata(merged, {"999": {"pl": "X"}}) == 0


class TestLoadExistingSiteData:
    def test_reads_the_sidecar(self, tmp_path):
        (tmp_path / "data.json").write_text(json.dumps({
            "profile": {"username": "u"},
            "posts": {"1": {"m": ["a"]}},
            "stories": {},
            "flickr": {"items": {"9": {"t": 1}}, "albums": {}, "meta": {}},
            "settings": {"gtag_id": "G-X"},
        }), encoding="utf-8")
        data = merger.load_existing_site_data(tmp_path)
        assert data["posts"] == {"1": {"m": ["a"]}}
        assert data["settings"]["gtag_id"] == "G-X"
        assert data["flickr"]["items"]["9"]["t"] == 1

    def test_missing_sidecar_and_html_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            merger.load_existing_site_data(tmp_path)

    def test_tolerates_a_minimal_sidecar(self, tmp_path):
        """Optional keys are all .get-guarded — a bare sidecar must not throw."""
        (tmp_path / "data.json").write_text(json.dumps({"posts": {}}), encoding="utf-8")
        data = merger.load_existing_site_data(tmp_path)
        assert data["posts"] == {}
        assert data["stories"] == {}
