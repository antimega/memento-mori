// "On this day" view for the timeline page: items from today's calendar day
// (month + day) in previous years, across every imported source. Fully
// client-side and live — it uses the browser's current date, so it stays
// correct without regenerating the site.
//
// Matches are computed from the data files (cheap key scan, no DOM traversal)
// and the view's DOM is built on the first toggle from the same data, via the
// shared mmTiles builders — the matching timeline tiles are prior-year by
// definition and (post month-on-demand rework) generally not in the DOM to
// clone, so we build fresh rather than clone.
//
// Sources are described by the PROVIDERS array below. Adding a source to this
// view is one entry: where its data lives, how to read an item's timestamp,
// how to build and open a tile. Note that providers differ in how they key
// their data — Instagram is keyed by timestamp, Flickr by photo id with the
// timestamp inside the entry — which is exactly why `timeOf` is a hook.
document.addEventListener('DOMContentLoaded', function () {
    var container = document.getElementById('onThisDay');
    var btnTimeline = document.getElementById('viewTimeline');
    var btnOnThisDay = document.getElementById('viewOnThisDay');
    var monthNav = document.getElementById('monthNav');
    var timeline = document.querySelector('.timeline-container');
    if (!container || !btnOnThisDay || !btnTimeline) {
        return;
    }

    var PROVIDERS = [
        {
            key: 'posts',
            data: function () { return window.postData; },
            timeOf: function (key) { return parseInt(key, 10); },
            tile: function (key, entry) { return window.mmTiles.post(key, entry); },
            strip: ['grid-item'],
            add: ['otd-tile'],
            open: function (tile, key) {
                // openStory live-queries .story-item and navigatePost walks
                // .grid-item — both hit index -1 unless the item's real month
                // exists, so build it (hidden) first.
                if (window.mmEnsureMonthFor) window.mmEnsureMonthFor(key);
                var index = parseInt(tile.getAttribute('data-index'), 10);
                if (window.mmOpenPost) window.mmOpenPost(index);
            },
            rowClass: 'timeline-posts',
        },
        {
            key: 'stories',
            data: function () { return window.storiesData; },
            timeOf: function (key) { return parseInt(key, 10); },
            tile: function (key, entry) { return window.mmTiles.story(key, entry); },
            // No otd-tile here: it forces aspect-ratio 1/1, and story tiles
            // are 9:16. .timeline-story-tile already styles them fully.
            strip: ['story-item'],
            add: [],
            open: function (tile, key) {
                if (window.mmEnsureMonthFor) window.mmEnsureMonthFor(key);
                var index = parseInt(tile.getAttribute('data-index'), 10);
                if (window.mmOpenStory) window.mmOpenStory(index);
            },
            rowClass: 'timeline-stories',
        },
        {
            key: 'flickr',
            data: function () { return window.flickrData; },
            // Flickr entries are keyed by photo id, not timestamp — the date
            // lives in the entry itself.
            timeOf: function (key, entry) { return entry.t; },
            tile: function (key, entry) { return window.mmTiles.flickr(key, entry); },
            // Also drop flickr-tile: flickr-viewer.js delegates on it at the
            // document level, which would fire alongside our own handler.
            strip: ['grid-item', 'flickr-tile'],
            add: ['otd-tile'],
            open: function (tile, key) {
                // Scope the viewer's prev/next to the memories on screen,
                // the same way the tag and album pages do. Without this the
                // viewer falls back to "the visible month panel's tiles",
                // and an On This Day item is from a previous year by
                // definition — never in that panel — so the arrows did
                // nothing at all.
                window.mmFlickrOrder = flickrOrder();
                // No mmEnsureMonthFor here: openFlickr resolves and builds
                // its own month via mmMonthKeyOfTarget/mmBuildMonth.
                if (window.mmOpenFlickr) window.mmOpenFlickr(key);
            },
            // Same row class the timeline uses for its Flickr row
            rowClass: 'timeline-posts',
        },
    ];

    // Match the server's day grouping, which uses UTC (utcfromtimestamp)
    var today = new Date();
    var todayMonth = today.getUTCMonth();
    var todayDay = today.getUTCDate();
    var todayYear = today.getUTCFullYear();

    // Bucket matching keys by year (previous years only), straight from the
    // loaded data — no DOM work at load time
    var byYear = {};
    var total = 0;

    PROVIDERS.forEach(function (provider) {
        var data = provider.data();
        if (!data) return;                       // source not imported
        Object.keys(data).forEach(function (key) {
            var t = provider.timeOf(key, data[key]);
            if (!t) return;
            var d = new Date(t * 1000);
            if (d.getUTCMonth() !== todayMonth || d.getUTCDate() !== todayDay) return;
            var year = d.getUTCFullYear();
            if (year >= todayYear) return;
            var bucket = byYear[year] || (byYear[year] = {});
            (bucket[provider.key] || (bucket[provider.key] = [])).push({ key: key, t: t });
            total++;
        });
    });

    Object.keys(byYear).forEach(function (year) {
        // Newest-first within a year, matching the timeline's ordering
        Object.keys(byYear[year]).forEach(function (k) {
            byYear[year][k].sort(function (a, b) { return b.t - a.t; });
        });
    });

    var years = Object.keys(byYear).map(Number).sort(function (a, b) { return b - a; });
    if (total) {
        btnOnThisDay.textContent = 'On this day (' + total.toLocaleString() + ')';
    }

    function flickrOrder() {
        // Every Flickr memory currently shown, newest year first and newest
        // within each year — i.e. the order they appear on the page.
        var ids = [];
        years.forEach(function (year) {
            (byYear[year].flickr || []).forEach(function (item) {
                ids.push(item.key);
            });
        });
        return ids;
    }

    function buildTile(provider, item) {
        var data = provider.data();
        var entry = data && data[item.key];
        if (!entry || !window.mmTiles) return null;
        var tile = provider.tile(item.key, entry);
        if (!tile) return null;
        provider.strip.forEach(function (cls) { tile.classList.remove(cls); });
        provider.add.forEach(function (cls) { tile.classList.add(cls); });
        // Not the real tile: drop the identifiers the deep-link lookups use,
        // so a clone can never shadow the real tile.
        tile.removeAttribute('data-timestamp');
        tile.addEventListener('click', function (e) {
            e.preventDefault();
            provider.open(tile, item.key);
        });
        return tile;
    }

    function buildRow(provider, items) {
        var row = document.createElement('div');
        row.className = provider.rowClass;
        items.forEach(function (item) {
            var tile = buildTile(provider, item);
            if (tile) row.appendChild(tile);
        });
        return row;
    }

    var built = false;
    function buildView() {
        if (built) return;
        built = true;

        if (!total) {
            var empty = document.createElement('p');
            empty.className = 'otd-empty';
            empty.textContent = 'Nothing from previous years on this day. Check back tomorrow.';
            container.appendChild(empty);
            return;
        }

        years.forEach(function (year) {
            var ago = todayYear - year;
            var section = document.createElement('section');
            section.className = 'otd-year';

            var heading = document.createElement('h2');
            heading.className = 'otd-year-header';
            heading.textContent = year + ' · ' + ago + (ago === 1 ? ' year ago' : ' years ago');
            section.appendChild(heading);

            PROVIDERS.forEach(function (provider) {
                var items = byYear[year][provider.key];
                if (items && items.length) {
                    section.appendChild(buildRow(provider, items));
                }
            });
            container.appendChild(section);
        });
    }

    // View toggle
    function showView(onThisDay) {
        if (onThisDay) {
            buildView();
        } else {
            // Hand Flickr navigation back to the timeline, which walks the
            // visible month panel. Leaving our order in place would keep
            // prev/next cycling the memories after the user had left them.
            window.mmFlickrOrder = null;
        }
        container.hidden = !onThisDay;
        if (monthNav) monthNav.hidden = onThisDay;
        if (timeline) timeline.hidden = onThisDay;
        btnOnThisDay.classList.toggle('active', onThisDay);
        btnOnThisDay.setAttribute('aria-pressed', String(onThisDay));
        btnTimeline.classList.toggle('active', !onThisDay);
        btnTimeline.setAttribute('aria-pressed', String(!onThisDay));
        window.scrollTo({ top: 0 });
    }

    btnOnThisDay.addEventListener('click', function () { showView(true); });
    btnTimeline.addEventListener('click', function () { showView(false); });
    // Default view is Timeline (container starts hidden via markup).
});
