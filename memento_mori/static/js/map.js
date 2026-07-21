// Map page: every geotagged item from every source as clustered markers,
// with the selected cluster's items listed underneath.
//
// Interaction model: a single click on a cluster SELECTS it (renders its
// items below); a double-click zooms into it. Scroll/pinch/+- also zoom.
// Selecting rather than zooming is the point of the page — with 14k pins the
// interesting question is "what happened here", not "how do I split this
// bubble" — but drill-down still has to exist, hence the double-click.
//
// Sources are described by the PROVIDERS array, the same registry shape
// on-this-day.js uses. Adding a source to this map is one entry: where its
// data lives, how to read a point's coordinates and date, and how to build
// its tile. Note the two sources key their data differently — Instagram by
// timestamp, Flickr by photo id with the date inside the entry — which is
// why coordsOf/timeOf are hooks rather than fixed field reads.
//
// No data file of its own: la/lo already ship in posts-data.js and
// flickr-data.js, so this page is built entirely from what other pages load.
document.addEventListener('DOMContentLoaded', function () {
    var mapEl = document.getElementById('pinMap');
    var grid = document.getElementById('mapGrid');
    var title = document.getElementById('mapTitle');
    var hint = document.getElementById('mapHint');
    if (!mapEl || !grid || typeof L === 'undefined') return;

    var BATCH = 300;

    var PROVIDERS = [
        {
            key: 'posts',
            data: function () { return window.postData; },
            timeOf: function (key) { return parseInt(key, 10); },
            tile: function (key, entry) {
                return window.mmTiles && window.mmTiles.post(key, entry);
            },
        },
        {
            key: 'flickr',
            data: function () { return window.flickrData; },
            timeOf: function (key, entry) { return entry.t; },
            tile: function (key, entry) {
                return window.mmFlickrGridTile && window.mmFlickrGridTile(key, entry);
            },
        },
    ];

    // ---------------------------------------------------------------------
    // Points
    // ---------------------------------------------------------------------

    var points = [];
    PROVIDERS.forEach(function (provider) {
        var data = provider.data();
        if (!data) return;                       // source not imported
        Object.keys(data).forEach(function (key) {
            var entry = data[key];
            var la = entry.la;
            var lo = entry.lo;
            // Coordinates are already 4-5dp and null-island-filtered at
            // import; guard only against the field being absent.
            if (typeof la !== 'number' || typeof lo !== 'number') return;
            points.push({
                provider: provider,
                key: key,
                la: la,
                lo: lo,
                t: provider.timeOf(key, entry) || 0,
            });
        });
    });

    if (!points.length) {
        if (hint) hint.textContent = 'No geotagged photos or posts to map.';
        return;
    }

    // ---------------------------------------------------------------------
    // Selection grid
    // ---------------------------------------------------------------------

    var order = [];
    var appended = 0;

    var sentinel = document.createElement('div');
    sentinel.setAttribute('aria-hidden', 'true');
    grid.parentNode.insertBefore(sentinel, grid.nextSibling);

    function appendBatch() {
        if (appended >= order.length) return;
        var frag = document.createDocumentFragment();
        var end = Math.min(appended + BATCH, order.length);
        for (var i = appended; i < end; i++) {
            var point = order[i];
            var entry = point.provider.data()[point.key];
            var tile = entry && point.provider.tile(point.key, entry);
            if (tile) frag.appendChild(tile);
        }
        appended = end;
        grid.appendChild(frag);
    }

    function maybeAppend() {
        if (sentinel.getBoundingClientRect().top < window.innerHeight + 2000) {
            appendBatch();
        }
    }
    if ('IntersectionObserver' in window) {
        new IntersectionObserver(function (entries) {
            if (entries.some(function (e) { return e.isIntersecting; })) {
                appendBatch();
            }
        }, { rootMargin: '2000px' }).observe(sentinel);
    }
    // IntersectionObserver alone stalls when the sentinel never leaves the
    // root margin; the scroll listener is the safety net (same pairing as
    // the flickr grid and the tag/album navigators).
    window.addEventListener('scroll', maybeAppend, { passive: true });
    window.addEventListener('resize', maybeAppend, { passive: true });

    function yearOf(t) {
        return new Date(t * 1000).getUTCFullYear();
    }

    function describe(selection) {
        var n = selection.length;
        var label = n.toLocaleString() + ' item' + (n === 1 ? '' : 's');
        var times = selection.map(function (p) { return p.t; })
            .filter(function (t) { return t; });
        if (!times.length) return label;
        var lo = yearOf(Math.min.apply(null, times));
        var hi = yearOf(Math.max.apply(null, times));
        return label + ' · ' + (lo === hi ? lo : lo + '–' + hi);
    }

    function select(selection) {
        // Newest first, matching every other view in the site
        order = selection.slice().sort(function (a, b) { return b.t - a.t; });

        // Scope the Flickr viewer's prev/next to this selection (its
        // navIds() prefers mmFlickrOrder over walking the DOM). Post arrows
        // walk the grid live, so rebuilding the grid is enough for those.
        window.mmFlickrOrder = order
            .filter(function (p) { return p.provider.key === 'flickr'; })
            .map(function (p) { return p.key; });

        appended = 0;
        grid.innerHTML = '';
        title.textContent = describe(order);
        title.hidden = false;
        if (hint) hint.hidden = true;
        appendBatch();

        // Make the result discoverable — especially on mobile, where the
        // grid starts below the fold.
        var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        title.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
        title.focus({ preventScroll: true });
    }

    // ---------------------------------------------------------------------
    // Map
    // ---------------------------------------------------------------------

    function initMap() {
        var map = L.map('pinMap', { fadeAnimation: false });
        L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        }).addTo(map);

        var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        var group = L.markerClusterGroup({
            // Chunked so adding thousands of markers never blocks the main
            // thread in one go.
            chunkedLoading: true,
            // Click selects instead of zooming (see the file header);
            // clusterdblclick below restores drill-down.
            zoomToBoundsOnClick: false,
            // Spiderfy would fan out coincident points at max zoom; here the
            // selection grid below the map is the better answer.
            spiderfyOnMaxZoom: false,
            showCoverageOnHover: false,
            animate: !reduce,
        });

        var markers = points.map(function (point) {
            var marker = L.marker([point.la, point.lo]);
            marker.mmPoint = point;
            return marker;
        });
        // One bulk add: markercluster's batch path is dramatically faster
        // than adding markers one at a time.
        group.addLayers(markers);

        group.on('clusterclick', function (e) {
            select(e.layer.getAllChildMarkers().map(function (m) {
                return m.mmPoint;
            }));
        });
        group.on('click', function (e) {
            if (e.layer && e.layer.mmPoint) select([e.layer.mmPoint]);
        });
        // Drill-down. The two single clicks that precede a double-click
        // harmlessly re-select first; zoomToBounds no-ops at max zoom.
        group.on('clusterdblclick', function (e) {
            e.layer.zoomToBounds({ padding: [30, 30] });
        });

        map.addLayer(group);
        map.invalidateSize();
        map.fitBounds(group.getBounds(), { padding: [30, 30] });
    }

    // Initialize only after layout is final, so Leaflet measures the real
    // container size when fitting bounds. setTimeout rather than
    // requestAnimationFrame: rAF never fires in a background tab.
    if (document.readyState === 'complete') {
        setTimeout(initMap, 0);
    } else {
        window.addEventListener('load', function () {
            setTimeout(initMap, 0);
        });
    }
});
