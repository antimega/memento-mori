// Album navigator (albums.html): every Flickr album as a chip (newest
// activity first, filterable), and the selected album's photos/videos as a
// progressively-rendered grid. A structural sibling of tags.js — change
// them in step. Built client-side from window.flickrData +
// window.flickrAlbums (the album-id -> title map).
//
// Reuses window.mmFlickrGridTile from flickr-grid.js for tile markup, and
// sets window.mmFlickrOrder to the selected album's id list so
// flickr-viewer.js's prev/next cycles within the album.
document.addEventListener('DOMContentLoaded', function () {
    var index = document.getElementById('albumIndex');
    var grid = document.getElementById('albumGrid');
    var title = document.getElementById('albumTitle');
    var filter = document.getElementById('albumFilter');
    if (!index || !grid || !window.flickrData || !window.flickrAlbums ||
        !window.mmFlickrGridTile) {
        return;
    }

    var BATCH = 300;

    // album id -> [item ids], newest-first (entries iterated in i order)
    var byAlbum = {};
    Object.keys(window.flickrData)
        .sort(function (a, b) {
            return window.flickrData[a].i - window.flickrData[b].i;
        })
        .forEach(function (id) {
            (window.flickrData[id].al || []).forEach(function (aid) {
                (byAlbum[aid] || (byAlbum[aid] = [])).push(id);
            });
        });

    function albumTitle(aid) {
        return (window.flickrAlbums[aid] || {}).t || '';
    }

    // Chips: newest album activity first (an album's first member is its
    // newest item, since members were collected in i order)
    var albums = Object.keys(byAlbum).filter(albumTitle).sort(function (a, b) {
        return window.flickrData[byAlbum[a][0]].i -
            window.flickrData[byAlbum[b][0]].i;
    });

    var chipByAlbum = {};
    var chipFrag = document.createDocumentFragment();
    albums.forEach(function (aid) {
        var chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'city-chip';       // reuse the cities chip styling
        chip.setAttribute('data-album', aid);
        chip.appendChild(document.createTextNode(albumTitle(aid) + ' '));
        var count = document.createElement('span');
        count.className = 'city-chip-count';
        count.textContent = byAlbum[aid].length;
        chip.appendChild(count);
        chipByAlbum[aid] = chip;
        chipFrag.appendChild(chip);
    });
    index.appendChild(chipFrag);

    // Progressive grid for the selected album
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
            frag.appendChild(
                window.mmFlickrGridTile(order[i], window.flickrData[order[i]])
            );
        }
        appended = end;
        grid.appendChild(frag);
    }

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

    function selectAlbum(aid, updateHash) {
        if (!byAlbum[aid]) return;
        albums.forEach(function (a) {
            var isActive = a === aid;
            chipByAlbum[a].classList.toggle('active', isActive);
            if (isActive) {
                chipByAlbum[a].setAttribute('aria-current', 'true');
            } else {
                chipByAlbum[a].removeAttribute('aria-current');
            }
        });
        title.textContent = albumTitle(aid) + ' — ' + byAlbum[aid].length +
            (byAlbum[aid].length !== 1 ? ' photos and videos' : ' photo');
        order = byAlbum[aid];
        window.mmFlickrOrder = order;   // viewer prev/next follows the album
        appended = 0;
        grid.innerHTML = '';
        appendBatch();
        if (updateHash) {
            // Written only on user selection (matches the cities pattern)
            history.replaceState(
                {}, '', '#album=' + encodeURIComponent(aid)
            );
        }
    }

    index.addEventListener('click', function (e) {
        var chip = e.target.closest('.city-chip');
        if (chip) selectAlbum(chip.getAttribute('data-album'), true);
    });

    // Filter box: hides albums whose title doesn't match
    if (filter) {
        filter.addEventListener('input', function () {
            var q = filter.value.trim().toLowerCase();
            albums.forEach(function (aid) {
                chipByAlbum[aid].hidden = q !== '' &&
                    albumTitle(aid).toLowerCase().indexOf(q) === -1;
            });
        });
    }

    // Initial album: #album=... deep link, else the most recent album
    var initial = null;
    var m = window.location.hash.match(/^#album=(.+)$/);
    if (m) {
        try {
            var decoded = decodeURIComponent(m[1]);
            if (byAlbum[decoded]) initial = decoded;
        } catch (e) { /* malformed hash — fall through */ }
    }
    selectAlbum(initial || albums[0], false);

    window.addEventListener('hashchange', function () {
        var m = window.location.hash.match(/^#album=(.+)$/);
        if (!m) return;
        try {
            var aid = decodeURIComponent(m[1]);
            if (byAlbum[aid]) selectAlbum(aid, false);
        } catch (e) { /* ignore malformed hash */ }
    });
});
