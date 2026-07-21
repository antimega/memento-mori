"""
The persistence paths: --regenerate and --merge.

These are the tests the multi-source restructure most needs, because it
rewrites the sidecar schema and the CLI's mode handling. If these keep
passing across that change, the data survived it.
"""

import json
import shutil
import sys

import pytest

from tests.conftest import make_flickr_export, make_instagram_export, write_api_cache
from tests.helpers import mask_dates, read_data_json, tree_files


def _cli(*args):
    from memento_mori import cli
    argv = sys.argv
    sys.argv = ["memento-mori"] + [str(a) for a in args]
    try:
        return cli.main()
    finally:
        sys.argv = argv


def _snapshot(out):
    """Every output file, date stamps masked, keyed by relative path."""
    return {
        str(p.relative_to(out)): mask_dates(p.read_bytes())
        for p in tree_files(out)
    }


@pytest.fixture
def site(tmp_path):
    """A combined site, freshly built, ready to regenerate or merge into."""
    export = tmp_path / "ig-export"
    export.mkdir()
    ts = make_instagram_export(export)
    flickr = tmp_path / "flickr-download"
    flickr.mkdir()
    info = make_flickr_export(flickr)
    write_api_cache(flickr, video_ids=[info["ids"]["video"]])
    out = tmp_path / "output"
    rc = _cli("--input", export, "--output", out, "--no-auto-detect",
              "--flickr", flickr)
    assert rc == 0
    return {"out": out, "export": export, "flickr": flickr,
            "ts": ts, "ids": info["ids"], "tmp": tmp_path}


# --------------------------------------------------------------------------
# --regenerate
# --------------------------------------------------------------------------

def test_regenerate_is_idempotent(site):
    """
    Regenerating from the sidecar must reproduce the site byte for byte
    (modulo the three date stamps). This is the single strongest guard on the
    generator: any accidental ordering or formatting change shows up here.
    """
    before = _snapshot(site["out"])
    assert _cli("--output", site["out"], "--regenerate") == 0
    after = _snapshot(site["out"])

    assert set(before) == set(after), (
        f"file set changed: only-before={sorted(set(before) - set(after))} "
        f"only-after={sorted(set(after) - set(before))}"
    )
    differing = [k for k in before if before[k] != after[k]]
    assert not differing, f"regenerate changed: {differing}"


def test_regenerate_without_the_flickr_input(site):
    """
    The Flickr section must survive from the sidecar alone — the export is
    not needed to re-render, only to re-import.
    """
    shutil.rmtree(site["flickr"])
    assert _cli("--output", site["out"], "--regenerate") == 0

    data = read_data_json(site["out"])
    assert len(data["flickr"]["items"]) == 8
    for page in ("flickr.html", "tags.html", "albums.html", "js/flickr-data.js"):
        assert (site["out"] / page).exists(), f"{page} lost on regenerate"


def test_regenerate_requires_a_sidecar(site, tmp_path):
    empty = tmp_path / "empty-out"
    empty.mkdir()
    assert _cli("--output", empty, "--regenerate") == 1


def test_regenerate_rejects_input_and_merge(site):
    assert _cli("--output", site["out"], "--regenerate",
                "--input", site["export"]) == 1
    assert _cli("--output", site["out"], "--regenerate", "--merge") == 1


def test_regenerate_preserves_gtag(tmp_path):
    """gtag_id lives in settings and must carry across a re-render."""
    export = tmp_path / "e"
    export.mkdir()
    make_instagram_export(export)
    out = tmp_path / "out"
    assert _cli("--input", export, "--output", out, "--no-auto-detect",
                "--gtag-id", "G-TESTID123") == 0
    assert _cli("--output", out, "--regenerate") == 0
    assert read_data_json(out)["settings"]["gtag_id"] == "G-TESTID123"
    assert "G-TESTID123" in (out / "index.html").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# --merge
# --------------------------------------------------------------------------

def test_merge_adds_new_posts_and_keeps_flickr(site, tmp_path):
    """
    The upgrade path: a newer export folds in without disturbing what is
    already there — and without dropping the Flickr section.
    """
    before = read_data_json(site["out"])
    before_posts = set(before["posts"])

    newer = tmp_path / "ig-export-2"
    newer.mkdir()
    # Same content plus one post a day later, so the delta is exactly one.
    from tests.conftest import _classic_post, write_jpeg, BASE_TS
    new_ts = BASE_TS + 86400
    write_jpeg(newer / "media" / "posts" / "brandnew.jpg", color=(10, 200, 200))
    make_instagram_export(newer, extra_posts=[
        _classic_post("media/posts/brandnew.jpg", new_ts, title="Brand new"),
    ])

    assert _cli("--input", newer, "--output", site["out"], "--merge") == 0

    after = read_data_json(site["out"])
    assert set(after["posts"]) == before_posts | {str(new_ts)}
    assert after["post_count"] == len(after["posts"])
    assert len(after["flickr"]["items"]) == 8, "merge dropped the Flickr section"
    assert after["flickr"]["items"] == before["flickr"]["items"]


def test_merge_requires_input(site):
    assert _cli("--output", site["out"], "--merge") == 1


def test_merge_preserves_city_tags(site, tmp_path):
    """User annotations are the whole reason merge exists — they must survive."""
    ts = str(site["ts"]["single"])
    (site["out"] / "city_tags.json").write_text(json.dumps({
        "version": 1,
        "posts": {ts: "Porto"},
        "stories": {},
        "cities": {"Porto": {"text": "**Lovely**"}},
        "favorites": {"posts": {ts: True}, "stories": {}},
    }), encoding="utf-8")

    newer = tmp_path / "ig-export-3"
    newer.mkdir()
    make_instagram_export(newer)
    assert _cli("--input", newer, "--output", site["out"], "--merge") == 0

    assert (site["out"] / "cities.html").exists()
    html = (site["out"] / "cities.html").read_text(encoding="utf-8")
    assert "Porto" in html
    assert "cities.html" in (site["out"] / "index.html").read_text(encoding="utf-8")
