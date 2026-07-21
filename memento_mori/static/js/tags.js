// Tag navigator (tags.html): every Flickr tag as a chip (count-sorted,
// filterable — there are ~8k), and the selected tag's photos/videos as a
// progressively-rendered grid. Entirely client-built from window.flickrData
// (the chips and tiles derive from the same data the viewer needs anyway).
//
// Reuses window.mmFlickrGridTile from flickr-grid.js for tile markup, and
// sets window.mmFlickrOrder to the selected tag's id list so
// flickr-viewer.js's prev/next cycles within the tag.
document.addEventListener('DOMContentLoaded', function () {
    var index = document.getElementById('tagIndex');
    var grid = document.getElementById('tagGrid');
    var title = document.getElementById('tagTitle');
    var filter = document.getElementById('tagFilter');
    if (!index || !grid || !window.flickrData || !window.mmFlickrGridTile) {
        return;
    }

    var BATCH = 300;

    // tag -> [ids], ids kept newest-first (entries iterated in i order)
    var byTag = {};
    Object.keys(window.flickrData)
        .sort(function (a, b) {
            return window.flickrData[a].i - window.flickrData[b].i;
        })
        .forEach(function (id) {
            (window.flickrData[id].tg || []).forEach(function (tag) {
                (byTag[tag] || (byTag[tag] = [])).push(id);
            });
        });

    // Chips: most-used first, then alphabetical (junk singletons sink)
    var tags = Object.keys(byTag).sort(function (a, b) {
        return (byTag[b].length - byTag[a].length) || a.localeCompare(b);
    });

    var chipByTag = {};
    var chipFrag = document.createDocumentFragment();
    tags.forEach(function (tag) {
        var chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'city-chip';       // reuse the cities chip styling
        chip.setAttribute('data-tag', tag);
        chip.appendChild(document.createTextNode(tag + ' '));
        var count = document.createElement('span');
        count.className = 'city-chip-count';
        count.textContent = byTag[tag].length.toLocaleString();
        chip.appendChild(count);
        chipByTag[tag] = chip;
        chipFrag.appendChild(chip);
    });
    index.appendChild(chipFrag);

    // Progressive grid for the selected tag
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

    function selectTag(tag, updateHash) {
        if (!byTag[tag]) return;
        tags.forEach(function (t) {
            var isActive = t === tag;
            chipByTag[t].classList.toggle('active', isActive);
            if (isActive) {
                chipByTag[t].setAttribute('aria-current', 'true');
            } else {
                chipByTag[t].removeAttribute('aria-current');
            }
        });
        var n = byTag[tag].length;
        title.textContent = tag + ' — ' + n.toLocaleString() +
            (n !== 1 ? ' photos and videos' : ' photo');
        order = byTag[tag];
        window.mmFlickrOrder = order;   // viewer prev/next follows the tag
        appended = 0;
        grid.innerHTML = '';
        appendBatch();
        if (updateHash) {
            // Written only on user selection (matches the cities pattern)
            history.replaceState(
                {}, '', '#tag=' + encodeURIComponent(tag)
            );
        }
    }

    index.addEventListener('click', function (e) {
        var chip = e.target.closest('.city-chip');
        if (chip) selectTag(chip.getAttribute('data-tag'), true);
    });

    // Filter box: hides non-matching chips (case-insensitive substring)
    if (filter) {
        filter.addEventListener('input', function () {
            var q = filter.value.trim().toLowerCase();
            tags.forEach(function (t) {
                chipByTag[t].hidden = q !== '' && t.toLowerCase().indexOf(q) === -1;
            });
        });
    }

    // Initial tag: #tag=... deep link, else the most-used tag
    var initial = null;
    var m = window.location.hash.match(/^#tag=(.+)$/);
    if (m) {
        try {
            var decoded = decodeURIComponent(m[1]);
            if (byTag[decoded]) initial = decoded;
        } catch (e) { /* malformed hash — fall through */ }
    }
    selectTag(initial || tags[0], false);

    window.addEventListener('hashchange', function () {
        var m = window.location.hash.match(/^#tag=(.+)$/);
        if (!m) return;
        try {
            var tag = decodeURIComponent(m[1]);
            if (byTag[tag]) selectTag(tag, false);
        } catch (e) { /* ignore malformed hash */ }
    });
});
