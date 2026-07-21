// Progressive Flickr grid (flickr.html) — looks like the posts page but
// renders client-side: the server ships only the first chunk of tiles
// (~30k at once would be a ~7 MB page), and this appends the rest in
// batches from window.flickrData as the user scrolls. Also provides the
// Newest/Oldest/Random sorting, mirroring index.html's sort row.
//
// Exposes window.mmFlickrOrder — the full id list in the current sort
// order — which flickr-viewer.js uses for prev/next (so navigation covers
// the whole archive even before tiles are appended).
//
// IMPORTANT: tile markup here must stay in step with the flickr tile in
// templates/flickr.html (classes, data-id, href, indicator, .tile-place).

// Grid-style flickr tile builder, shared with the tags page (tags.js) so
// the markup lives in one place. Defined at top-level eval — deferred
// scripts all run before DOMContentLoaded, in order.
(function () {
    function photopage(id) {
        var alias = (window.flickrMeta && window.flickrMeta.path_alias) || '';
        return 'https://www.flickr.com/photos/' + alias + '/' + id + '/';
    }

    // Parity target: the flickr tile in templates/flickr.html
    window.mmFlickrGridTile = function (id, entry) {
        var a = document.createElement('a');
        a.className = 'grid-item flickr-tile';
        a.setAttribute('data-id', id);
        a.setAttribute('href', photopage(id));

        var media = document.createElement('div');
        media.className = 'tile-media';

        var img = document.createElement('img');
        img.src = entry.th ? 'thumbnails/' + entry.th + '.webp'
            : (entry.dm || (entry.m && entry.m[0]) || '');
        img.alt = 'Flickr photo';
        img.loading = 'lazy';
        media.appendChild(img);

        if (entry.vd) {
            var vi = document.createElement('div');
            vi.className = 'video-indicator';
            vi.textContent = '▶ Video';
            media.appendChild(vi);
        }
        a.appendChild(media);

        var place = document.createElement('div');
        place.className = 'tile-place';
        place.textContent = entry.tt || '';   // user data — never innerHTML
        a.appendChild(place);
        return a;
    };
})();

document.addEventListener('DOMContentLoaded', function () {
    var grid = document.getElementById('flickrGrid');
    if (!grid || !window.flickrData) return;

    var BATCH = 300;
    var buildTile = window.mmFlickrGridTile;

    // Newest-first order = the stable import index i
    var newestFirst = Object.keys(window.flickrData).sort(function (a, b) {
        return window.flickrData[a].i - window.flickrData[b].i;
    });

    var order = newestFirst.slice();
    window.mmFlickrOrder = order;
    var appended = grid.querySelectorAll('.flickr-tile').length;

    // Sentinel that triggers the next batch as it approaches the viewport
    var sentinel = document.createElement('div');
    sentinel.setAttribute('aria-hidden', 'true');
    grid.parentNode.insertBefore(sentinel, grid.nextSibling);

    function appendBatch() {
        if (appended >= order.length) return;
        var frag = document.createDocumentFragment();
        var end = Math.min(appended + BATCH, order.length);
        for (var i = appended; i < end; i++) {
            frag.appendChild(buildTile(order[i], window.flickrData[order[i]]));
        }
        appended = end;
        grid.appendChild(frag);
    }

    // IntersectionObserver alone is not enough: if the sentinel is still
    // inside rootMargin after an append, the state never transitions and no
    // further callback fires. The scroll listener guarantees progress.
    function maybeAppend() {
        if (sentinel.getBoundingClientRect().top <
            window.innerHeight + 2000) {
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
    window.addEventListener('scroll', maybeAppend, { passive: true });
    window.addEventListener('resize', maybeAppend, { passive: true });

    // Sorting — same controls and aria-current handling as index.html
    function resort(kind) {
        if (kind === 'newest') {
            order = newestFirst.slice();
        } else if (kind === 'oldest') {
            order = newestFirst.slice().reverse();
        } else {
            order = newestFirst.slice();
            for (var i = order.length - 1; i > 0; i--) {  // Fisher-Yates
                var j = Math.floor(Math.random() * (i + 1));
                var t = order[i]; order[i] = order[j]; order[j] = t;
            }
        }
        window.mmFlickrOrder = order;
        grid.innerHTML = '';
        appended = 0;
        appendBatch();
        window.scrollTo({ top: 0 });
    }

    document.querySelectorAll('.sort-link').forEach(function (link) {
        link.addEventListener('click', function () {
            document.querySelectorAll('.sort-link').forEach(function (l) {
                l.classList.remove('active');
                l.removeAttribute('aria-current');
            });
            link.classList.add('active');
            link.setAttribute('aria-current', 'true');
            resort(link.getAttribute('data-sort'));
        });
    });

    // Top the grid up immediately: the server chunk is only ~60 tiles,
    // which may not fill a tall viewport enough to trigger the observer
    appendBatch();
});
