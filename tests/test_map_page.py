"""
The map page: generated only when something is geotagged, and its nav count
must match the data.

The interactive behaviour (clustering, selection, viewers) lives in the
browser layer — these are the artifact-level guarantees.
"""

import json
import sys

import pytest

from tests.conftest import make_flickr_export, make_instagram_export, write_api_cache
from tests.helpers import flickr_items, ig_posts, read_data_json


def _cli(*args):
    from memento_mori import cli
    argv = sys.argv
    sys.argv = ["memento-mori"] + [str(a) for a in args]
    try:
        return cli.main()
    finally:
        sys.argv = argv


def _geo_count(out):
    n = 0
    for entries in (ig_posts(out), flickr_items(out)):
        for entry in entries.values():
            if entry.get("la") not in ("", None) and entry.get("lo") not in ("", None):
                n += 1
    return n


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("mapsite")
    export = root / "ig-export"
    export.mkdir()
    make_instagram_export(export)
    flickr = root / "flickr-download"
    flickr.mkdir()
    info = make_flickr_export(flickr, filler=10, filler_geo=(48.8584, 2.2945))
    write_api_cache(flickr, video_ids=[info["ids"]["video"]])
    out = root / "output"
    argv = sys.argv
    sys.argv = ["memento-mori", "--input", str(export), "--output", str(out),
                "--no-auto-detect", "--flickr", str(flickr)]
    try:
        from memento_mori import cli
        assert cli.main() == 0
    finally:
        sys.argv = argv
    return {"out": out}


def test_map_page_generated(built):
    assert (built["out"] / "map.html").exists()
    assert (built["out"] / "js" / "map.js").exists()


def test_markercluster_is_vendored(built):
    vendor = built["out"] / "vendor" / "leaflet.markercluster"
    for name in ("leaflet.markercluster.js", "MarkerCluster.css",
                 "MarkerCluster.Default.css"):
        assert (vendor / name).exists(), f"missing vendored {name}"


def test_map_page_is_a_shell(built):
    """
    Pins are plotted client-side from posts-data.js / flickr-data.js, so the
    page must stay tiny however many pins there are — no embedded point list.
    """
    html = (built["out"] / "map.html").read_text(encoding="utf-8")
    assert len(html) < 20000, f"map.html is {len(html)} bytes; is data inlined?"
    assert 'id="pinMap"' in html
    assert 'id="mapGrid"' in html


def test_map_loads_what_it_needs(built):
    """Both viewers' partials and both tile builders must be present."""
    html = (built["out"] / "map.html").read_text(encoding="utf-8")
    for needed in ("js/posts-data.js", "js/flickr-data.js",
                   "js/timeline-months.js", "js/flickr-grid.js",
                   "js/modal.js", "js/flickr-viewer.js", "js/map.js",
                   "vendor/leaflet/leaflet.js",
                   "vendor/leaflet.markercluster/leaflet.markercluster.js"):
        assert needed in html, f"map.html does not load {needed}"
    assert 'id="postModal"' in html, "post modal partial missing"
    assert 'id="flickrModal"' in html, "flickr viewer partial missing"
    # markercluster reads window.L at eval, so it must come after Leaflet
    assert html.index("vendor/leaflet/leaflet.js") < \
        html.index("vendor/leaflet.markercluster/leaflet.markercluster.js")


def test_nav_pin_count_matches_the_data(built):
    expected = f"{_geo_count(built['out']):,}"
    html = (built["out"] / "index.html").read_text(encoding="utf-8")
    assert f'<span class="stat-count">{expected}</span> pins' in html, (
        f"nav does not report {expected} pins"
    )
    assert "map.html" in html


def test_no_map_page_without_geotags(tmp_path):
    """A build with nothing geotagged gets no map page and no pins link."""
    export = tmp_path / "ig-export"
    export.mkdir()
    make_instagram_export(export, with_place=False, with_exif_coords=False)
    out = tmp_path / "output"
    assert _cli("--input", export, "--output", out, "--no-auto-detect") == 0

    assert _geo_count(out) == 0, "fixture unexpectedly has geotagged items"
    assert not (out / "map.html").exists()
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "map.html" not in html
    assert "pins" not in html
