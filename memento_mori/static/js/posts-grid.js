// Progressive posts grid (posts.html) — the same trick flickr-grid.js plays.
//
// The server used to ship every post tile: on a large archive that is
// thousands of tiles and tens of thousands of DOM nodes, which the browser
// must parse and lay out on EVERY load. No amount of HTTP caching helps —
// the bytes cache fine, the layout work does not — so the page painted
// quickly but took seconds to become clickable. Now the server seeds only
// the first chunk (see GRID_SEED in generator.py) and this appends the rest
// from window.postData as the reader scrolls.
//
// Exposes window.mmPostsOrder — every post index in the current sort order —
// which modal.js uses for prev/next, so the viewer still walks the whole
// archive even before the matching tiles have been appended.
//
// This file also owns the Newest/Oldest/Random sort row on posts.html
// (modal.js used to, back when every tile was already in the DOM).
//
// IMPORTANT: tile markup here must stay in step with templates/grid.html
// (classes, data-index, data-timestamp, href, indicators, .tile-place).

(function () {
    var VIDEO_RE = /\.(mp4|mov|avi|webm)$/i;

    // Parity target: the post tile in templates/grid.html
    window.mmPostsGridTile = function (timestamp, entry) {
        var a = document.createElement('a');
        a.className = 'grid-item';
        a.setAttribute('data-index', entry.i);
        a.setAttribute('data-timestamp', timestamp);
        a.setAttribute('href', 'posts.html?post=' + timestamp);

        var media = document.createElement('div');
        media.className = 'tile-media';

        var first = (entry.m && entry.m[0]) || '';
        var img = document.createElement('img');
        img.src = entry.th ? 'thumbnails/' + entry.th + '.webp' : (entry.dm || first);
        img.alt = 'Instagram post';
        img.loading = 'lazy';       // every appended tile is below the fold
        media.appendChild(img);

        if (VIDEO_RE.test(first)) {
            var vi = document.createElement('div');
            vi.className = 'video-indicator';
            vi.textContent = '▶ Video';
            media.appendChild(vi);
        }

        // Mirrors grid.html's if/elif: the multi-image count wins over likes
        var count = (entry.m && entry.m.length) || 0;
        if (count > 1) {
            var mi = document.createElement('div');
            mi.className = 'multi-indicator';
            mi.textContent = '⊞ ' + count;
            media.appendChild(mi);
        } else if (entry.l) {
            var li = document.createElement('div');
            li.className = 'likes-indicator';
            li.textContent = '♥ ' + entry.l;
            media.appendChild(li);
        }
        a.appendChild(media);

        var place = document.createElement('div');
        place.className = 'tile-place';
        place.textContent = entry.pl || '';   // user data — never innerHTML
        a.appendChild(place);
        return a;
    };
})();

document.addEventListener('DOMContentLoaded', function () {
    var grid = document.getElementById('postsGrid');
    if (!grid || !window.postData) return;

    var BATCH = 300;
    var buildTile = window.mmPostsGridTile;

    // Newest-first order = the stable import index i, matching the order the
    // generator writes tiles in.
    var newestFirst = Object.keys(window.postData).sort(function (a, b) {
        return window.postData[a].i - window.postData[b].i;
    });

    var order = newestFirst.slice();
    publishOrder();
    var appended = grid.querySelectorAll('.grid-item').length;

    // modal.js navigates by post index, not timestamp, so publish indexes.
    function publishOrder() {
        window.mmPostsOrder = order.map(function (ts) {
            return window.postData[ts].i;
        });
    }

    // Sentinel that triggers the next batch as it approaches the viewport
    var sentinel = document.createElement('div');
    sentinel.setAttribute('aria-hidden', 'true');
    grid.parentNode.insertBefore(sentinel, grid.nextSibling);

    function appendBatch() {
        if (appended >= order.length) return;
        var frag = document.createDocumentFragment();
        var end = Math.min(appended + BATCH, order.length);
        for (var i = appended; i < end; i++) {
            frag.appendChild(buildTile(order[i], window.postData[order[i]]));
        }
        appended = end;
        grid.appendChild(frag);
    }

    // IntersectionObserver alone is not enough: if the sentinel is still
    // inside rootMargin after an append, the state never transitions and no
    // further callback fires. The scroll listener guarantees progress.
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
    window.addEventListener('scroll', maybeAppend, { passive: true });
    window.addEventListener('resize', maybeAppend, { passive: true });

    // Sorting — same controls and aria-current handling as flickr.html
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
        publishOrder();
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

    // Top the grid up immediately: the server chunk is small and may not fill
    // a tall viewport enough to trigger the observer.
    appendBatch();
});
