// Progressive stories grid (stories.html) — the same trick posts-grid.js and
// flickr-grid.js play.
//
// The server used to ship every story tile: on a large archive that is
// thousands of tiles and tens of thousands of DOM nodes, which the browser
// must parse and lay out on EVERY load — CPU work that HTTP caching cannot
// avoid, so the page painted quickly but took seconds to become clickable.
// Now the server seeds only the first chunk (see GRID_SEED in generator.py)
// and this appends the rest from window.storiesData as the reader scrolls.
//
// Exposes window.mmStoriesOrder — every story index in display order — which
// stories.js uses for prev/next, so the viewer still walks the whole archive
// even before the matching tiles have been appended.
//
// There is no sort row on stories.html, so unlike posts-grid.js this file has
// no sorting to own.
//
// IMPORTANT: tile markup here must stay in step with the story tile in
// templates/stories_page.html (classes, data-*, href, indicator, .story-info).

(function () {
    function storyMedia(entry) {
        // Same resolution as timeline-months.js: story thumbnails live under
        // thumbnails/stories/<md5>.webp, which is not a plain md5 thumbnail
        // URL, so it arrives in `dm` rather than `th`.
        if (entry.th) return 'thumbnails/' + entry.th + '.webp';
        if (entry.dm) return entry.dm;
        return (entry.m && entry.m[0]) || '';
    }
    function isVideo(url) {
        return /\.(mp4|mov|avi|webm)$/i.test(url || '');
    }

    // Parity target: the story tile in templates/stories_page.html. The one
    // intentional difference from the server markup is that onerror is set as
    // a property (not an attribute) to avoid quoting the media path.
    window.mmStoriesGridTile = function (timestamp, entry) {
        var a = document.createElement('a');
        a.className = 'story-item';
        a.setAttribute('data-index', entry.i);
        a.setAttribute('data-timestamp', timestamp);
        a.setAttribute('href', 'stories.html?story=' + timestamp);

        var media = document.createElement('div');
        media.className = 'story-media';

        if (isVideo(entry.m && entry.m[0])) {
            var vi = document.createElement('div');
            vi.className = 'video-indicator';
            // The server markup uses an inline SVG play triangle here, so it
            // has to be built in the SVG namespace to render at all.
            var NS = 'http://www.w3.org/2000/svg';
            var svg = document.createElementNS(NS, 'svg');
            svg.setAttribute('viewBox', '0 0 24 24');
            svg.setAttribute('width', '24');
            svg.setAttribute('height', '24');
            var path = document.createElementNS(NS, 'path');
            path.setAttribute('d', 'M8 5v14l11-7z');
            path.setAttribute('fill', 'white');
            svg.appendChild(path);
            vi.appendChild(svg);
            media.appendChild(vi);
        }

        var img = document.createElement('img');
        img.src = storyMedia(entry);
        img.alt = entry.tt || 'Instagram Story';   // user data — set, not parsed
        img.loading = 'lazy';                      // appended tiles are below the fold
        var original = (entry.m && entry.m[0]) || '';
        img.onerror = function () { this.onerror = null; this.src = original; };
        media.appendChild(img);
        a.appendChild(media);

        var info = document.createElement('div');
        info.className = 'story-info';
        var date = document.createElement('div');
        date.className = 'story-date';
        date.textContent = entry.d || '';          // user data — never innerHTML
        info.appendChild(date);
        a.appendChild(info);
        return a;
    };
})();

document.addEventListener('DOMContentLoaded', function () {
    var grid = document.getElementById('storiesGrid');
    if (!grid || !window.storiesData) return;

    var BATCH = 300;
    var buildTile = window.mmStoriesGridTile;

    // Display order = the stable import index i, matching the order the
    // generator writes tiles in.
    var order = Object.keys(window.storiesData).sort(function (a, b) {
        return window.storiesData[a].i - window.storiesData[b].i;
    });

    // Published for stories.js's prev/next. Holds TIMESTAMPS (the storiesData
    // keys) because that is what the viewer looks entries up by — note this
    // differs from posts-grid.js's mmPostsOrder, which holds post indexes
    // because modal.js navigates by index.
    window.mmStoriesOrder = order.slice();

    var appended = grid.querySelectorAll('.story-item').length;

    // Sentinel that triggers the next batch as it approaches the viewport
    var sentinel = document.createElement('div');
    sentinel.setAttribute('aria-hidden', 'true');
    grid.parentNode.insertBefore(sentinel, grid.nextSibling);

    function appendBatch() {
        if (appended >= order.length) return;
        var frag = document.createDocumentFragment();
        var end = Math.min(appended + BATCH, order.length);
        for (var i = appended; i < end; i++) {
            frag.appendChild(buildTile(order[i], window.storiesData[order[i]]));
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

    // Top the grid up immediately: the server chunk is small and may not fill
    // a tall viewport enough to trigger the observer.
    appendBatch();
});
