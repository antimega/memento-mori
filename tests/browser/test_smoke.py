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
    page.fill("#tagFilter", "filler")
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


def test_on_this_day_includes_flickr_memories(page, base_url):
    """
    On This Day spans every source. Flickr entries are id-keyed with the date
    inside the entry, so they exercise the provider's timeOf hook.
    """
    page.goto(f"{base_url}/timeline.html")
    page.locator("#viewOnThisDay").click()
    otd = page.locator("#onThisDay")
    otd.wait_for(state="visible", timeout=5000)

    # The Flickr memory is planted 3 years back; its tile carries data-id
    # (Flickr) rather than data-index (Instagram).
    flickr_tiles = otd.locator(".otd-tile[data-id]")
    assert flickr_tiles.count() > 0, "no Flickr memories in On this day"

    flickr_tiles.first.click()
    page.locator("#flickrModal").wait_for(state="visible", timeout=5000)
    page.keyboard.press("Escape")
    page.locator("#flickrModal").wait_for(state="hidden", timeout=5000)


def test_on_this_day_story_tiles_keep_their_shape(page, base_url):
    """
    Story tiles are 9:16 and must not pick up the square .otd-tile styling
    that posts and Flickr items use.
    """
    page.goto(f"{base_url}/timeline.html")
    page.locator("#viewOnThisDay").click()
    page.locator("#onThisDay").wait_for(state="visible", timeout=5000)
    stories = page.locator("#onThisDay .timeline-story-tile")
    if stories.count():
        assert stories.first.evaluate(
            "el => el.classList.contains('otd-tile')") is False


# --------------------------------------------------------------------------
# regressions: viewer navigation and scroll restoration
# --------------------------------------------------------------------------

def test_flickr_arrows_work_from_on_this_day(page, base_url):
    """
    Opening a Flickr memory from On This Day must leave prev/next working.

    The viewer's fallback nav order is "the visible month panel's tiles", and
    an On This Day item is from a previous year by definition — so it was
    never in that panel and the arrows silently did nothing.
    """
    page.goto(f"{base_url}/timeline.html")
    page.locator("#viewOnThisDay").click()
    otd = page.locator("#onThisDay")
    otd.wait_for(state="visible", timeout=5000)

    tiles = otd.locator(".otd-tile[data-id]")
    assert tiles.count() > 1, "need at least two Flickr memories to navigate"
    first_id = tiles.first.get_attribute("data-id")

    tiles.first.click()
    page.locator("#flickrModal").wait_for(state="visible", timeout=5000)
    page.locator("#flickrNext").click()
    page.wait_for_timeout(300)

    assert page.evaluate(
        "new URLSearchParams(location.search).get('photo')"
    ) != first_id, "next arrow did not move to another photo"


def test_flickr_arrows_cycle_within_the_memories(page, base_url):
    """
    Prev/next should walk the memories on screen, not the whole archive —
    matching how the tag and album pages scope navigation.
    """
    page.goto(f"{base_url}/timeline.html")
    page.locator("#viewOnThisDay").click()
    page.locator("#onThisDay").wait_for(state="visible", timeout=5000)
    ids = page.locator("#onThisDay .otd-tile[data-id]").evaluate_all(
        "els => els.map(e => e.getAttribute('data-id'))")

    page.locator("#onThisDay .otd-tile[data-id]").first.click()
    page.locator("#flickrModal").wait_for(state="visible", timeout=5000)
    page.locator("#flickrNext").click()
    page.wait_for_timeout(300)
    now = page.evaluate("new URLSearchParams(location.search).get('photo')")
    assert now != ids[0], "next arrow did not move"
    assert now in ids, f"navigated to {now}, which is not one of the memories"


def _click_tile_in_viewport(page, selector):
    """
    Click a tile that is already on screen.

    Playwright scrolls an element into view before clicking it, so clicking
    an arbitrary tile moves the page and looks exactly like a scroll bug.
    That artifact sent an earlier version of this test chasing a clamp that
    did not exist — always click something already visible.
    """
    idx = page.evaluate("""(sel) => {
        const els = [...document.querySelectorAll(sel)];
        for (let i = 0; i < els.length; i++) {
            const r = els[i].getBoundingClientRect();
            if (r.top > 60 && r.bottom < window.innerHeight - 60) return i;
        }
        return -1;
    }""", selector)
    assert idx >= 0, f"no {selector} in the viewport"
    page.locator(selector).nth(idx).click()
    return idx


def test_closing_a_viewer_does_not_scroll_the_page(page, base_url, browser_name):
    """
    Closing a viewer must leave the reader where they were.

    This is a WebKit-only failure in practice: Safari does not focus an <a>
    when it is clicked, so the viewer's saved "element to restore focus to"
    ends up being an ancestor like <main tabindex="-1">, and focusing that
    scrolls it into view — jumping the reader to the top of the page.
    Chromium focuses the link itself and never shows it, so this test is
    close to meaningless unless it also runs with --browser webkit.
    """
    page.goto(f"{base_url}/timeline.html")
    page.locator("#viewOnThisDay").click()
    page.locator("#onThisDay").wait_for(state="visible", timeout=5000)
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(400)

    before = page.evaluate("window.scrollY")
    if before < 400:
        pytest.skip(f"On This Day view too short to detect a jump ({before}px)")

    _click_tile_in_viewport(page, "#onThisDay .otd-tile[data-id]")
    page.locator("#flickrModal").wait_for(state="visible", timeout=5000)
    page.keyboard.press("Escape")
    page.locator("#flickrModal").wait_for(state="hidden", timeout=5000)
    page.wait_for_timeout(400)

    after = page.evaluate("window.scrollY")
    assert abs(after - before) < 150, (
        f"[{browser_name}] closing scrolled the page: was {before}, now {after}"
    )


# --------------------------------------------------------------------------
# map page
# --------------------------------------------------------------------------

def _open_map(page, base_url):
    page.goto(f"{base_url}/map.html")
    page.wait_for_selector(".leaflet-container", timeout=10000)
    page.wait_for_timeout(1200)   # let markercluster finish its chunked add


def _cluster_counts(page):
    return page.evaluate("""() => [...document.querySelectorAll('.marker-cluster')]
        .map(e => parseInt(e.textContent.trim().replace(/[^0-9]/g, '')) || 0)""")


def test_map_plots_every_geotagged_item(page, base_url):
    """
    Cluster bubbles plus lone markers must account for every point — a
    silently dropped source or a coordinate-shape mismatch shows up here.
    """
    _open_map(page, base_url)
    counts = _cluster_counts(page)
    lone = page.locator(".leaflet-marker-icon:not(.marker-cluster)").count()
    assert counts, "no clusters rendered"

    expected = page.evaluate("""() => {
        let n = 0;
        for (const d of [window.postData, window.flickrData]) {
            if (!d) continue;
            for (const k of Object.keys(d)) {
                const e = d[k];
                if (typeof e.la === 'number' && typeof e.lo === 'number') n++;
            }
        }
        return n;
    }""")
    assert sum(counts) + lone == expected, (
        f"mapped {sum(counts)}+{lone} points, data has {expected}"
    )


def test_map_starts_with_a_hint_and_no_selection(page, base_url):
    _open_map(page, base_url)
    assert page.locator("#mapHint").is_visible()
    assert page.locator("#mapTitle").is_hidden()
    assert page.locator("#mapGrid .grid-item").count() == 0


def test_map_cluster_click_populates_the_grid(page, base_url):
    _open_map(page, base_url)
    counts = _cluster_counts(page)
    biggest = counts.index(max(counts))
    page.locator(".marker-cluster").nth(biggest).click()
    page.wait_for_timeout(600)

    title = page.locator("#mapTitle")
    assert title.is_visible()
    assert "item" in title.inner_text()
    tiles = page.locator("#mapGrid .grid-item").count()
    assert tiles > 0, "cluster click rendered no tiles"
    # progressive: never more than one batch up front
    assert tiles <= 300, f"rendered {tiles} tiles in the first batch"
    assert page.locator("#mapHint").is_hidden()


def test_map_flickr_tile_opens_viewer_scoped_to_the_selection(page, base_url):
    """
    The Flickr viewer's prev/next must walk the selected cluster, not the
    whole archive — map.js sets window.mmFlickrOrder for exactly this.
    """
    _open_map(page, base_url)
    counts = _cluster_counts(page)
    page.locator(".marker-cluster").nth(counts.index(max(counts))).click()
    page.wait_for_timeout(600)

    flickr = page.locator("#mapGrid .flickr-tile")
    assert flickr.count() > 1, "need multiple Flickr tiles in the selection"
    order = page.evaluate("window.mmFlickrOrder")
    assert order, "mmFlickrOrder was not scoped to the selection"

    flickr.first.click()
    page.locator("#flickrModal").wait_for(state="visible", timeout=5000)
    before = page.evaluate("new URLSearchParams(location.search).get('photo')")
    page.locator("#flickrNext").click()
    page.wait_for_timeout(400)
    after = page.evaluate("new URLSearchParams(location.search).get('photo')")
    assert after != before, "flickr arrow did not move"
    assert after in order, "flickr arrow navigated outside the selection"


def test_map_post_tile_opens_modal_with_working_arrows(page, base_url):
    """
    Post arrows walk the live .grid-item list. Flickr tiles share that class
    but carry no data-index, so without filtering them out the carousel hits
    NaN and dead-stops — this is the mixed-grid guard.
    """
    _open_map(page, base_url)
    counts = _cluster_counts(page)
    page.locator(".marker-cluster").nth(counts.index(max(counts))).click()
    page.wait_for_timeout(600)

    posts = page.locator("#mapGrid .grid-item[data-index]")
    flickr = page.locator("#mapGrid .flickr-tile")
    if posts.count() < 2 or flickr.count() < 1:
        pytest.skip("need a genuinely mixed selection")

    # Open the LAST post in the grid and step forward. That is where the
    # unfiltered NaNs live: stepping off the end of the posts lands on a
    # Flickr tile's absent data-index unless they are filtered out. Opening
    # the first post would pass either way.
    posts.last.click()
    page.locator("#postModal").wait_for(state="visible", timeout=5000)
    before = page.evaluate("new URLSearchParams(location.search).get('post')")
    page.locator("#modalNext").click()
    page.wait_for_timeout(500)
    after = page.evaluate("new URLSearchParams(location.search).get('post')")

    assert after != before, "post arrow did not move"
    assert after in page.evaluate("Object.keys(window.postData)"), (
        f"post arrow landed on {after!r}, which is not a post"
    )
    assert page.locator("#postModal").is_visible(), "modal closed on navigation"


def test_map_cluster_dblclick_zooms_in(page, base_url):
    _open_map(page, base_url)
    zoom_before = page.evaluate("""() => {
        const el = document.querySelector('.leaflet-container');
        return el ? el.className : '';
    }""")
    counts = _cluster_counts(page)
    page.locator(".marker-cluster").nth(counts.index(max(counts))).dblclick()
    page.wait_for_timeout(1500)
    after = _cluster_counts(page)
    lone = page.locator(".leaflet-marker-icon:not(.marker-cluster)").count()
    assert (after != counts) or lone, (
        f"double-click did not drill in: {counts} -> {after}"
    )


# --------------------------------------------------------------------------
# responsive layout
# --------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["index.html", "timeline.html", "flickr.html",
                                  "tags.html", "map.html", "cities.html"])
def test_no_horizontal_scroll_at_any_width(page, base_url, site, path):
    """
    Sweep the responsive range and assert the page never scrolls sideways.

    This is deliberately generic — it asserts a property, not a breakpoint.
    The nav's desktop layout is a max-content grid with one intrinsic width,
    so if that width ever exceeds the point where the stacked layout takes
    over, a dead zone opens where the nav is simply cut off. That is exactly
    what happened with a 600px breakpoint against a ~771px nav, and a
    breakpoint-shaped assertion would not have noticed.
    """
    if not (site["out"] / path).exists():
        pytest.skip(f"{path} is not part of this build")
    page.goto(f"{base_url}/{path}")
    page.wait_for_timeout(300)

    overflowing = []
    for width in range(320, 1201, 40):
        page.set_viewport_size({"width": width, "height": 900})
        page.wait_for_timeout(60)
        if page.evaluate(
            "document.documentElement.scrollWidth > window.innerWidth + 1"
        ):
            overflowing.append(width)

    assert not overflowing, (
        f"{path} scrolls horizontally at widths: {overflowing}"
    )


def test_nav_is_fully_visible_across_widths(page, base_url):
    """
    The nav itself must fit its container — the symptom being guarded is
    'the top navigation is completely cut off'.
    """
    page.goto(f"{base_url}/index.html")
    page.wait_for_timeout(300)

    clipped = []
    for width in range(320, 1201, 40):
        page.set_viewport_size({"width": width, "height": 900})
        page.wait_for_timeout(60)
        over = page.evaluate("""() => {
            const nav = document.querySelector('.nav-rows');
            const main = document.querySelector('main');
            if (!nav || !main) return 0;
            const cs = getComputedStyle(main);
            const inner = main.clientWidth
                - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
            return nav.scrollWidth - Math.ceil(inner);
        }""")
        if over > 1:
            clipped.append((width, over))

    assert not clipped, f"nav overflows its container at (width, px over): {clipped}"


# --------------------------------------------------------------------------
# Flickr cities: the editor page and the cities-page section
# --------------------------------------------------------------------------

def test_cities_flickr_section_opens_the_viewer(page, base_url, site):
    """
    Flickr tiles in a city must open the viewer, and prev/next must stay
    inside that city — the cities page has no month panels, so the viewer's
    DOM fallback would find nothing without mmFlickrOrder.
    """
    page.goto(f"{base_url}/cities.html#city-venice")
    page.wait_for_timeout(800)

    tiles = page.locator(".city-section:not([hidden]) .flickr-tile")
    assert tiles.count() > 1, "no Flickr tiles in the city section"
    order = page.evaluate("window.mmFlickrOrder")
    assert order and len(order) == tiles.count(), (
        f"mmFlickrOrder ({order}) does not match the city's tiles"
    )

    tiles.first.click()
    page.locator("#flickrModal").wait_for(state="visible", timeout=5000)
    before = page.evaluate("new URLSearchParams(location.search).get('photo')")
    page.locator("#flickrNext").click()
    page.wait_for_timeout(400)
    after = page.evaluate("new URLSearchParams(location.search).get('photo')")
    assert after != before, "flickr arrow did not move"
    assert after in order, "flickr arrow navigated outside the city"


def test_cities_section_order_is_posts_flickr_stories(page, base_url):
    page.goto(f"{base_url}/cities.html#city-venice")
    page.wait_for_timeout(600)
    kinds = page.evaluate("""() => {
        const s = document.querySelector('.city-section:not([hidden])');
        return [...s.querySelectorAll('.timeline-tile, .flickr-tile, .timeline-story-tile')]
            .map(e => e.classList.contains('flickr-tile') ? 'flickr'
                    : e.classList.contains('timeline-story-tile') ? 'story' : 'post');
    }""")
    assert kinds, "no tiles in the city section"
    # each kind appears in one contiguous run, in this order
    first = {k: kinds.index(k) for k in set(kinds)}
    assert first.get("post", -1) < first.get("flickr", 99) < first.get("story", 999), (
        f"unexpected tile order: {kinds}"
    )


def test_flickr_editor_bulk_tags_a_selection(page, base_url, site):
    """
    The whole point of the page: pick a tag, drop a few, tag the rest. The
    selection is tracked over the tag's full id list, not the rendered
    tiles, so this must hold even though the grid renders in batches.
    """
    page.goto(f"{base_url}/edit-flickr.html")
    page.wait_for_timeout(800)

    chips = page.locator("#tagIndex .city-chip")
    assert chips.count() > 0, "no tag chips built"

    page.fill("#tagFilter", "filler")
    page.wait_for_timeout(300)
    page.locator("#tagIndex .city-chip:visible").first.click()
    page.wait_for_timeout(400)

    total = page.locator("#flickrEditGrid .grid-item").count()
    assert total > 1, "need more than one item under the tag"
    assert page.locator("#flickrEditGrid .deselected").count() == 0, (
        "items should start selected"
    )

    # deselect the first, then tag the rest
    dropped = page.locator("#flickrEditGrid .grid-item").first.get_attribute("data-id")
    page.locator("#flickrEditGrid .grid-item").first.click()
    page.wait_for_timeout(200)
    assert page.locator("#flickrEditGrid .deselected").count() == 1

    page.fill("#cityInput", "Testville")
    page.locator("#applyCity").click()
    page.wait_for_timeout(400)

    export = page.evaluate("MMEditor.buildExport()")
    tagged = export.get("flickr", {})
    assert tagged, "nothing exported under flickr"
    assert dropped not in [k for k, v in tagged.items() if v == "Testville"], (
        "the deselected item was tagged anyway"
    )
    assert sum(1 for v in tagged.values() if v == "Testville") == total - 1, (
        "wrong number of items tagged"
    )


def test_flickr_editor_bulk_favourites(page, base_url):
    page.goto(f"{base_url}/edit-flickr.html")
    page.wait_for_timeout(800)
    page.fill("#tagFilter", "filler")
    page.wait_for_timeout(300)
    page.locator("#tagIndex .city-chip:visible").first.click()
    page.wait_for_timeout(400)

    page.locator("#applyFav").click()
    page.wait_for_timeout(400)
    assert page.locator("#flickrEditGrid .fav-badge").count() > 0, "no ★ badges"

    export = page.evaluate("MMEditor.buildExport()")
    assert export.get("favorites", {}).get("flickr"), (
        "favourites did not reach the export"
    )
    assert "unexported" in page.locator("#editorCounts").inner_text(), (
        "pending-change count did not register the Flickr edits"
    )


def test_deselected_tiles_stay_clearly_visible(page, base_url):
    """
    A deselected tile must still be easy to look at.

    You are deciding which photos to exclude, so you have to be able to SEE
    the ones you are excluding. An earlier version dimmed them to opacity
    0.35, which made them nearly invisible; the state is now carried by
    desaturation plus an explicit tick, not by fading. This pins the
    legibility floor and the fact that the two states differ visibly.
    """
    page.goto(f"{base_url}/edit-flickr.html")
    page.locator("#tagIndex .city-chip").first.wait_for(timeout=5000)
    page.locator("#tagIndex .city-chip").first.click()
    page.wait_for_timeout(400)

    tiles = page.locator("#flickrEditGrid .grid-item")
    assert tiles.count() > 1, "need at least two tiles"
    tiles.first.click()          # deselect exactly one
    # Move the pointer away: hovering a tile deliberately restores full
    # colour so you can inspect what you are excluding, which would
    # otherwise be what this measures.
    page.mouse.move(0, 0)
    page.wait_for_timeout(250)

    state = page.evaluate("""() => {
        const off = document.querySelector('#flickrEditGrid .grid-item.deselected');
        const on = document.querySelector('#flickrEditGrid .grid-item:not(.deselected)');
        const tick = el => getComputedStyle(el.querySelector('.tile-media'), '::after');
        return {
            offOpacity: parseFloat(getComputedStyle(off).opacity),
            offFilter: getComputedStyle(off).filter,
            offTick: tick(off).content,
            onTick: tick(on).content,
            offOutline: tick(on).outlineColor !== getComputedStyle(
                off.querySelector('.tile-media')).outlineColor,
        };
    }""")

    assert state["offOpacity"] >= 0.6, (
        f"deselected tiles are too faint to read (opacity {state['offOpacity']})"
    )
    assert state["offFilter"] != "none", "no desaturation to distinguish the state"
    assert state["offTick"] != state["onTick"], (
        "selected and deselected tiles show the same tick — state is invisible"
    )
    assert state["offOutline"], "selection frame does not change with state"
