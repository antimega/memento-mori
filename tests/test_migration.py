"""
Sidecar schema v1 -> v2 migration.

v1 was Instagram-shaped (posts/stories/profile at the top level, flickr
bolted alongside); v2 puts every import under "sources". Migration runs
automatically on load, so these tests guard data the user never asked to
have converted.
"""

import json

import pytest

from memento_mori import merger


V1 = {
    "profile": {"username": "iguser", "bio": "hello", "website": "https://x"},
    "location": {"location": "London"},
    "posts": {"100": {"i": 0, "m": ["a.webp"], "t": 100, "d": "d"}},
    "stories": {"90": {"i": 0, "m": ["s.webp"], "t": 90, "d": "d"}},
    "post_count": 1,
    "story_count": 1,
    "date_range": {"newest": "x", "oldest": "y", "range": "y - x"},
    "flickr": {
        "items": {"555": {"i": 0, "t": 5, "d": "d", "m": ["f.webp"]}},
        "albums": {"7": {"t": "Album"}},
        "meta": {"path_alias": "flickruser", "imported_at": "2024-01-01"},
    },
    "settings": {"gtag_id": "G-X", "generated_at": "2024-01-01",
                 "schema_version": 1},
}


class TestMigrateSidecar:
    def test_instagram_moves_under_sources(self):
        out = merger.migrate_sidecar(V1)
        ig = out["sources"]["instagram"]
        assert ig["posts"] == V1["posts"]
        assert ig["stories"] == V1["stories"]
        assert ig["profile"]["username"] == "iguser"

    def test_flickr_moves_under_sources(self):
        out = merger.migrate_sidecar(V1)
        fl = out["sources"]["flickr"]
        assert fl["items"] == V1["flickr"]["items"]
        assert fl["albums"] == V1["flickr"]["albums"]
        assert fl["meta"]["path_alias"] == "flickruser"

    def test_flickr_profile_is_synthesized_from_meta(self):
        """
        v1 never stored a Flickr profile. Recovering the alias means a
        migrated Flickr-only site still names itself.
        """
        out = merger.migrate_sidecar(V1)
        assert out["sources"]["flickr"]["profile"]["username"] == "flickruser"

    def test_schema_version_and_location_carried(self):
        out = merger.migrate_sidecar(V1)
        assert out["schema_version"] == 2
        assert out["location"] == {"location": "London"}
        assert out["settings"]["gtag_id"] == "G-X"

    def test_derived_fields_are_dropped(self):
        """
        Counts and date_range were stored duplicates of the data that could
        drift; they are computed at render time now.
        """
        out = merger.migrate_sidecar(V1)
        for gone in ("post_count", "story_count", "date_range", "posts",
                     "stories", "profile", "flickr"):
            assert gone not in out, f"{gone} survived migration at the top level"

    def test_v2_passes_through_unchanged(self):
        v2 = merger.migrate_sidecar(V1)
        assert merger.migrate_sidecar(v2) == v2

    def test_migration_is_lossless_for_item_data(self):
        """The point of the exercise: no item may be lost or altered."""
        out = merger.migrate_sidecar(V1)
        assert out["sources"]["instagram"]["posts"] == V1["posts"]
        assert out["sources"]["instagram"]["stories"] == V1["stories"]
        assert out["sources"]["flickr"]["items"] == V1["flickr"]["items"]

    def test_instagram_only_sidecar(self):
        v1 = {k: v for k, v in V1.items() if k != "flickr"}
        out = merger.migrate_sidecar(v1)
        assert set(out["sources"]) == {"instagram"}

    def test_flickr_only_sidecar_has_no_instagram_source(self):
        v1 = {"flickr": V1["flickr"], "settings": {}}
        out = merger.migrate_sidecar(v1)
        assert set(out["sources"]) == {"flickr"}

    def test_empty_sidecar_yields_no_sources(self):
        assert merger.migrate_sidecar({})["sources"] == {}


class TestBackup:
    def test_v1_sidecar_is_copied_aside(self, tmp_path):
        (tmp_path / "data.json").write_text(json.dumps(V1), encoding="utf-8")
        backup = merger.backup_v1_sidecar(tmp_path)
        assert backup and backup.exists()
        assert json.loads(backup.read_text())["posts"] == V1["posts"]

    def test_backup_is_written_only_once(self, tmp_path):
        """
        A second run must not overwrite the preserved original with an
        already-migrated file — that would silently destroy the thing the
        backup exists to protect.
        """
        (tmp_path / "data.json").write_text(json.dumps(V1), encoding="utf-8")
        merger.backup_v1_sidecar(tmp_path)
        (tmp_path / "data.json").write_text(
            json.dumps(merger.migrate_sidecar(V1)), encoding="utf-8")
        assert merger.backup_v1_sidecar(tmp_path) is None
        assert "posts" in json.loads((tmp_path / "data.v1.bak.json").read_text())

    def test_v2_sidecar_is_not_backed_up(self, tmp_path):
        (tmp_path / "data.json").write_text(
            json.dumps(merger.migrate_sidecar(V1)), encoding="utf-8")
        assert merger.backup_v1_sidecar(tmp_path) is None
        assert not (tmp_path / "data.v1.bak.json").exists()

    def test_missing_sidecar_is_not_an_error(self, tmp_path):
        assert merger.backup_v1_sidecar(tmp_path) is None


class TestSiteIdentity:
    def test_instagram_wins_when_both_present(self):
        sources = {
            "flickr": {"profile": {"username": "flickruser"}},
            "instagram": {"profile": {"username": "iguser"}},
        }
        assert merger.site_identity(sources)["username"] == "iguser"

    def test_falls_through_to_flickr(self):
        sources = {"flickr": {"profile": {"username": "flickruser"}}}
        assert merger.site_identity(sources)["username"] == "flickruser"

    def test_skips_a_source_with_no_username(self):
        sources = {
            "instagram": {"profile": {"username": ""}},
            "flickr": {"profile": {"username": "flickruser"}},
        }
        assert merger.site_identity(sources)["username"] == "flickruser"

    def test_unknown_source_still_names_the_site(self):
        """A future importer must not leave the site called 'Unknown'."""
        sources = {"future": {"profile": {"username": "someone"}}}
        assert merger.site_identity(sources)["username"] == "someone"

    def test_no_sources_falls_back(self):
        assert merger.site_identity({})["username"] == "Unknown"


class TestLoadExistingSiteData:
    def test_v1_sidecar_is_migrated_on_load(self, tmp_path):
        (tmp_path / "data.json").write_text(json.dumps(V1), encoding="utf-8")
        data = merger.load_existing_site_data(tmp_path)
        assert set(data["sources"]) == {"instagram", "flickr"}

    def test_convenience_views_still_work(self, tmp_path):
        """The merge flow reads existing["posts"]; that must keep working."""
        (tmp_path / "data.json").write_text(json.dumps(V1), encoding="utf-8")
        data = merger.load_existing_site_data(tmp_path)
        assert data["posts"] == V1["posts"]
        assert data["stories"] == V1["stories"]
        assert data["profile"]["username"] == "iguser"
        assert data["flickr"]["items"] == V1["flickr"]["items"]
        assert data["settings"]["gtag_id"] == "G-X"
