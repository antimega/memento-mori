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
        // Keep panning inside a single world: no infinite east/west scroll,
        // and no grey void past the poles. 85.0511° is the Web Mercator
        // latitude limit (matches the tile coverage). The cities map uses the
        // same constraint.
        var worldBounds = L.latLngBounds([-85.0511, -180], [85.0511, 180]);
        var map = L.map('pinMap', {
            fadeAnimation: false,
            maxBounds: worldBounds,
            maxBoundsViscosity: 1.0,
        });
        L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            noWrap: true,   // don't repeat the world horizontally
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        }).addTo(map);
        // Don't let zoom-out go below where one world fills the viewport (else
        // grey shows around it). getBoundsZoom(..., true) is the smallest zoom
        // whose view still fits inside the world; recompute it on resize so it
        // adapts to the container width.
        function clampMinZoom() { map.setMinZoom(map.getBoundsZoom(worldBounds, true)); }
        clampMinZoom();
        map.on('resize', clampMinZoom);

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

        // Blue-dot pin (🔵) replacing Leaflet's default teardrop; the look
        // lives in .mm-emoji-pin (css/style.css). The same icon is used by
        // modal.js, flickr-viewer.js and cities.html — keep them in step. One
        // shared instance across all ~14k markers (Leaflet allows reuse).
        var pin = L.divIcon({
            html: '🔵',
            className: 'mm-emoji-pin',
            iconSize: [18, 18],   // box padded around the ~12px glyph (no clip)
            iconAnchor: [9, 9],   // centre the dot on the point
            popupAnchor: [0, -9],
        });
        var markers = points.map(function (point) {
            var marker = L.marker([point.la, point.lo], { icon: pin });
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
        // Frame the default view on where the pins mostly are, not the full
        // extent: outliers on other continents otherwise zoom the map right
        // out and leave it centred over open ocean. Fit to the central 80% of
        // points on each axis (trimming a full 10% per side is enough to drop
        // a secondary cluster — e.g. an Americas trip — that would otherwise
        // drag the centre out into the Atlantic). The extremities are meant to
        // sit outside the initial view; panning/zooming still reaches them.
        var las = points.map(function (p) { return p.la; }).sort(function (a, b) { return a - b; });
        var los = points.map(function (p) { return p.lo; }).sort(function (a, b) { return a - b; });
        var lop = function (a) { return a[Math.floor((a.length - 1) * 0.10)]; };
        var hip = function (a) { return a[Math.ceil((a.length - 1) * 0.90)]; };
        map.fitBounds([[lop(las), lop(los)], [hip(las), hip(los)]], { padding: [30, 30] });
        // Then back well out, keeping that centre: a wide, zoomed-out default
        // reads better here than a tight one — you get the whole surrounding
        // world and the trimmed-off extremities come back into view. Clamped to
        // minZoom (the world-fills-the-viewport floor set above).
        map.setZoom(Math.max(map.getMinZoom(), map.getZoom() - 2));
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
