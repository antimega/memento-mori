"""
Browser-layer fixtures: build one site, serve it, drive it with Playwright.

Half this application is client-side — on-demand month building, the three
viewers, deep links, the tag/album navigators, On This Day. None of it is
reachable from Python, and all of it is what the multi-source restructure
will disturb. These smokes cover the paths where a silent JS break would
otherwise ship.

Marked `browser` and deselected by default (see pyproject.toml): they need
pytest-playwright and a downloaded Chromium, which a plain checkout lacks.
"""

import contextlib
import functools
import http.server
import socket
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.conftest import (  # noqa: E402
    _classic_post,
    copy_tiny_video,
    make_flickr_export,
    make_instagram_export,
    write_api_cache,
    write_jpeg,
)

pytestmark = pytest.mark.browser


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def site(tmp_path_factory):
    """
    A combined site with content spread across several months, plus posts
    planted on today's calendar day in previous years so On This Day always
    has something to show.
    """
    from memento_mori import cli

    root = tmp_path_factory.mktemp("browsersite")
    export = root / "ig-export"
    export.mkdir()

    now = datetime.now(timezone.utc)
    otd_posts = []
    otd_ts = []
    for years_ago in (1, 2):
        when = now.replace(year=now.year - years_ago, hour=12, minute=0,
                           second=0, microsecond=0)
        ts = int(when.timestamp())
        otd_ts.append(ts)
        name = f"otd_{years_ago}.jpg"
        write_jpeg(export / "media" / "posts" / name, color=(90, 20 + years_ago * 40, 140))
        otd_posts.append(_classic_post(f"media/posts/{name}", ts,
                                       title=f"Memory from {years_ago}y ago"))

    ig_ts = make_instagram_export(export, extra_posts=otd_posts)

    flickr = root / "flickr-download"
    flickr.mkdir()
    # Plant a Flickr item on today's calendar day three years back, so On
    # This Day has a Flickr memory as well as Instagram ones.
    flickr_otd = now.replace(year=now.year - 3, hour=9, minute=0, second=0,
                             microsecond=0)
    # filler makes flickr.html long enough to scroll past the point where
    # body overflow:hidden clamps the offset — the short page a minimal
    # fixture produces cannot reproduce that class of bug.
    info = make_flickr_export(
        flickr, otd_date=flickr_otd.strftime("%Y-%m-%d %H:%M:%S"), filler=120)
    write_api_cache(flickr, video_ids=[info["ids"]["video"]])

    out = root / "output"
    argv = sys.argv
    sys.argv = ["memento-mori", "--input", str(export), "--output", str(out),
                "--no-auto-detect", "--flickr", str(flickr)]
    try:
        assert cli.main() == 0, "browser fixture build failed"
    finally:
        sys.argv = argv

    return {"out": out, "ig_ts": ig_ts, "otd_ts": otd_ts, "ids": info["ids"]}


@pytest.fixture(scope="session")
def base_url(site):
    """Serve the built site on a free port for the session."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(site["out"]))
    port = _free_port()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def page(page):
    """
    Wrap Playwright's page so any console error or uncaught exception fails
    the test. A silent TypeError in a viewer is exactly the regression this
    layer exists to catch, and it would otherwise leave the page merely
    looking a bit wrong.
    """
    errors = []
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}")
            if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page._mm_errors = errors
    yield page
    assert not errors, "browser errors:\n" + "\n".join(errors)
