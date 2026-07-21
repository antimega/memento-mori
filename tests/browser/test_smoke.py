"""End-to-end smokes for the client-side behavior."""

import pytest

pytestmark = pytest.mark.browser


# --------------------------------------------------------------------------
# index / posts grid
# --------------------------------------------------------------------------

def test_index_renders_tiles_and_opens_the_modal(page, base_url):
    page.goto(f"{base_url}/index.html")
    tiles = page.locator(".grid-item")
    assert tiles.count() > 0, "no post tiles rendered"

    tiles.first.click()
    modal = page.locator("#postModal")
    modal.wait_for(state="visible", timeout=5000)
    page.keyboard.press("Escape")
    modal.wait_for(state="hidden", timeout=5000)


def test_index_sorting_reorders_tiles(page, base_url):
    page.goto(f"{base_url}/index.html")
    first_before = page.locator(".grid-item").first.get_attribute("data-timestamp")
    page.locator('.sort-link[data-sort="oldest"]').click()
    first_after = page.locator(".grid-item").first.get_attribute("data-timestamp")
    assert first_before != first_after, "oldest-first did not reorder the grid"
    # tiles must still open after a reorder (delegation, not per-tile binding)
    page.locator(".grid-item").first.click()
    page.locator("#postModal").wait_for(state="visible", timeout=5000)


def test_post_deep_link_opens_the_modal(page, base_url, site):
    ts = site["ig_ts"]["single"]
    page.goto(f"{base_url}/index.html?post={ts}")
    page.locator("#postModal").wait_for(state="visible", timeout=5000)


# --------------------------------------------------------------------------
# timeline: the on-demand month machinery
# --------------------------------------------------------------------------

def test_timeline_paints_one_month_then_builds_others(page, base_url):
    page.goto(f"{base_url}/timeline.html")
    assert page.locator(".timeline-month:not([hidden])").count() == 1

    options = page.locator("#monthSelect option")
    assert options.count() > 1, "fixture needs multiple months"

    # Switch to the oldest month: it is built client-side on demand.
    oldest = options.last.get_attribute("value")
    page.select_option("#monthSelect", oldest)
    page.wait_for_timeout(200)

    visible = page.locator(".timeline-month:not([hidden])")
    assert visible.count() == 1, "month switch left more than one month visible"
    assert visible.first.get_attribute("data-month") == oldest
    assert visible.locator("a").count() > 0, "built month has no tiles"


def test_switching_months_does_not_duplicate_panels(page, base_url):
    page.goto(f"{base_url}/timeline.html")
    options = page.locator("#monthSelect option")
    first = options.first.get_attribute("value")
    last = options.last.get_attribute("value")
    for value in (last, first, last, first):
        page.select_option("#monthSelect", value)
        page.wait_for_timeout(120)
    for value in (first, last):
        assert page.locator(f'.timeline-month[data-month="{value}"]').count() == 1, (
            f"month {value} was built more than once"
        )


def test_unknown_deep_link_falls_back_without_a_ghost_month(page, base_url):
    page.goto(f"{base_url}/timeline.html?post=999999999")
    page.wait_for_timeout(200)
    assert page.locator(".timeline-month:not([hidden])").count() == 1
    assert page.locator("#postModal:visible").count() == 0


def test_flickr_deep_link_on_the_timeline(page, base_url, site):
    """?photo= resolves its month through mmMonthKeyOfTarget, not timestamp math."""
    pid = site["ids"]["plain"]
    page.goto(f"{base_url}/timeline.html?photo={pid}")
    page.locator("#flickrModal").wait_for(state="visible", timeout=5000)


def test_on_this_day_shows_planted_memories(page, base_url):
    page.goto(f"{base_url}/timeline.html")
    toggle = page.locator("#viewOnThisDay")
    assert "(" in toggle.inner_text(), f"no OTD count in {toggle.inner_text()!r}"

    toggle.click()
    otd = page.locator("#onThisDay")
    otd.wait_for(state="visible", timeout=5000)
    tiles = otd.locator(".otd-tile")
    assert tiles.count() > 0, "no memory tiles built"

    tiles.first.click()
    page.locator("#postModal").wait_for(state="visible", timeout=5000)


# --------------------------------------------------------------------------
# flickr pages
# --------------------------------------------------------------------------

def test_flickr_grid_and_viewer(page, base_url):
    page.goto(f"{base_url}/flickr.html")
    tiles = page.locator(".flickr-tile")
    assert tiles.count() > 0

    tiles.first.click()
    viewer = page.locator("#flickrModal")
    viewer.wait_for(state="visible", timeout=5000)
    page.keyboard.press("Escape")
    viewer.wait_for(state="hidden", timeout=5000)


def test_flickr_viewer_navigates_with_arrows(page, base_url):
    page.goto(f"{base_url}/flickr.html")
    page.locator(".flickr-tile").first.click()
    page.locator("#flickrModal").wait_for(state="visible", timeout=5000)
    before = page.locator("#flickrMedia img").first.get_attribute("src")
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(200)
    after = page.locator("#flickrMedia img").first.get_attribute("src")
    assert before != after, "next did not advance the viewer"


def test_tags_page_chip_selection(page, base_url):
    page.goto(f"{base_url}/tags.html")
    chips = page.locator("#tagIndex .city-chip")
    assert chips.count() > 0, "no tag chips built"

    chips.first.click()
    page.wait_for_timeout(150)
    assert page.locator("#tagGrid .flickr-tile").count() > 0
    assert "#tag=" in page.url, "tag selection did not become linkable"


def test_tags_deep_link_on_a_cold_load(page, base_url):
    """
    Load tags.html#tag=... as the FIRST navigation to that page.

    Arriving at the hash from another page is what a shared link does, and it
    runs the initial-load resolution path. Navigating hash-to-hash while
    already on the page fires hashchange instead — a different handler that
    would mask a break in this one.
    """
    page.goto(f"{base_url}/index.html")
    page.goto(f"{base_url}/tags.html#tag=holiday")
    page.wait_for_timeout(250)
    assert "holiday" in page.locator("#tagTitle").inner_text()
    assert page.locator("#tagGrid .flickr-tile").count() > 0


def test_tags_hashchange_switches_tag(page, base_url):
    """The same-document path: hash changes while the page is already open."""
    page.goto(f"{base_url}/tags.html#tag=holiday")
    page.wait_for_timeout(200)
    page.evaluate("location.hash = '#tag=beach'")
    page.wait_for_timeout(200)
    assert "beach" in page.locator("#tagTitle").inner_text()


def test_albums_deep_link_on_a_cold_load(page, base_url):
    page.goto(f"{base_url}/index.html")
    page.goto(f"{base_url}/albums.html#album=7001")
    page.wait_for_timeout(250)
    assert "Summer" in page.locator("#albumTitle").inner_text()
    assert page.locator("#albumGrid .flickr-tile").count() > 0


def test_tag_filter_box_narrows_the_chips(page, base_url):
    page.goto(f"{base_url}/tags.html")
    total = page.locator("#tagIndex .city-chip").count()
    page.fill("#tagFilter", "holiday")
    page.wait_for_timeout(150)
    visible = page.locator("#tagIndex .city-chip:visible").count()
    assert 0 < visible < total, f"filter showed {visible} of {total}"


# --------------------------------------------------------------------------
# stories
# --------------------------------------------------------------------------

def test_stories_viewer_opens_and_does_not_auto_advance(page, base_url):
    page.goto(f"{base_url}/stories.html")
    page.locator(".story-item").first.click()
    viewer = page.locator("#storyViewer")
    viewer.wait_for(state="visible", timeout=5000)

    shown = page.locator("#storyViewer .media-slide").first.get_attribute("src")
    page.wait_for_timeout(1500)  # auto-advance was 10s; it is now disabled
    assert page.locator("#storyViewer .media-slide").first.get_attribute("src") == shown


# --------------------------------------------------------------------------
# file:// — the archival guarantee
# --------------------------------------------------------------------------

def test_pages_work_from_the_filesystem(page, site):
    """
    The site must open from a bare filesystem, not just a server. This is the
    reason for classic scripts and no fetch anywhere.
    """
    for name in ("index.html", "timeline.html", "flickr.html", "tags.html"):
        page.goto((site["out"] / name).as_uri())
        page.wait_for_timeout(150)
    # tiles still render with no origin
    assert page.locator("#tagIndex .city-chip").count() > 0
