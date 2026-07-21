// Flickr city tagging: pick a tag, get everything under it selected, drop
// the ones you don't want, then apply a city (or a favourite) to the rest.
//
// The tag index, filter box and progressive grid are the tags.js navigator
// with a selection layer on top — change them in step. What is genuinely
// different here is the bulk model: on the Instagram editor a click tags the
// tile it lands on, whereas here a click only toggles whether the tile is
// included, and the toolbar buttons apply the change to everything selected.
//
// Selection is tracked as a Set of ids over the WHOLE tag, not over the
// rendered tiles. The grid appends in batches as you scroll, so "everything
// is selected" has to mean the ids, or the first bulk action would silently
// skip whatever had not been built yet.
document.addEventListener('DOMContentLoaded', function () {
    if (!window.MMEditor || !MMEditor.init()) {
        return;
    }
    var index = document.getElementById('tagIndex');
    var grid = document.getElementById('flickrEditGrid');
    var filter = document.getElementById('tagFilter');
    var bar = document.getElementById('selectionBar');
    var title = document.getElementById('selectionTitle');
    var countEl = document.getElementById('selectionCount');
    var cityInput = document.getElementById('cityInput');
    var warning = document.getElementById('editorWarning');
    if (!index || !grid || !window.flickrData || !window.mmFlickrGridTile) {
        return;
    }

    var BATCH = 300;
    var CITY_KEY = 'mm_city_current';

    var currentTag = null;
    var order = [];            // ids of the selected tag, newest-first
    var selected = new Set();  // ids currently ticked
    var appended = 0;

    // ---- tag index (mirrors tags.js) ----

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

    if (filter) {
        filter.addEventListener('input', function () {
            var q = filter.value.trim().toLowerCase();
            tags.forEach(function (t) {
                chipByTag[t].hidden = q !== '' && t.toLowerCase().indexOf(q) === -1;
            });
        });
    }

    // ---- city input ----

    function currentCity() {
        return (cityInput.value || '').trim();
    }
    cityInput.value = localStorage.getItem(CITY_KEY) || '';
    cityInput.addEventListener('input', function () {
        localStorage.setItem(CITY_KEY, currentCity());
        renderAllBadges();
    });

    function renderDatalist() {
        var list = document.getElementById('cityNames');
        list.innerHTML = '';
        MMEditor.cityNames().forEach(function (name) {
            var opt = document.createElement('option');
            opt.value = name;
            list.appendChild(opt);
        });
    }

    var warnTimer = null;
    function warn(message) {
        warning.textContent = message;
        clearTimeout(warnTimer);
        warnTimer = setTimeout(function () { warning.textContent = ''; }, 2500);
    }

    // ---- tiles ----

    function renderBadge(tile) {
        var id = tile.getAttribute('data-id');
        var host = tile.querySelector('.tile-media') || tile;

        var city = MMEditor.effective('flickr', id);
        var badge = tile.querySelector('.city-badge');
        if (city) {
            if (!badge) {
                badge = document.createElement('div');
                badge.className = 'city-badge';
                host.appendChild(badge);
            }
            badge.textContent = city;
            tile.classList.toggle('tagged-current', city === currentCity());
        } else {
            if (badge) badge.remove();
            tile.classList.remove('tagged-current');
        }

        var fav = MMEditor.effectiveFav('flickr', id);
        var favBadge = tile.querySelector('.fav-badge');
        if (fav) {
            if (!favBadge) {
                favBadge = document.createElement('div');
                favBadge.className = 'fav-badge';
                favBadge.textContent = '★';
                host.appendChild(favBadge);
            }
        } else if (favBadge) {
            favBadge.remove();
        }

        tile.classList.toggle('deselected', !selected.has(id));
    }

    function renderAllBadges() {
        Array.prototype.forEach.call(
            grid.querySelectorAll('[data-id]'), renderBadge
        );
    }

    var sentinel = document.createElement('div');
    sentinel.setAttribute('aria-hidden', 'true');
    grid.parentNode.insertBefore(sentinel, grid.nextSibling);

    function appendBatch() {
        if (appended >= order.length) return;
        var frag = document.createDocumentFragment();
        var end = Math.min(appended + BATCH, order.length);
        for (var i = appended; i < end; i++) {
            var id = order[i];
            var tile = window.mmFlickrGridTile(id, window.flickrData[id]);
            renderBadge(tile);
            frag.appendChild(tile);
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
    window.addEventListener('scroll', maybeAppend, { passive: true });
    window.addEventListener('resize', maybeAppend, { passive: true });

    // ---- selection ----

    function updateCounts() {
        countEl.textContent = selected.size.toLocaleString() + ' of '
            + order.length.toLocaleString() + ' selected';
        var pending = MMEditor.pendingCount();
        document.getElementById('editorCounts').textContent = pending
            ? pending.toLocaleString() + ' unexported change'
                + (pending === 1 ? '' : 's')
            : 'No unexported changes';
    }

    function selectTag(tag) {
        currentTag = tag;
        tags.forEach(function (t) {
            var active = t === tag;
            chipByTag[t].classList.toggle('active', active);
            if (active) {
                chipByTag[t].setAttribute('aria-current', 'true');
            } else {
                chipByTag[t].removeAttribute('aria-current');
            }
        });

        order = byTag[tag] || [];
        // Everything starts selected: the workflow is "take this tag, minus
        // the few that don't belong".
        selected = new Set(order);
        appended = 0;
        grid.innerHTML = '';
        bar.hidden = false;
        title.textContent = tag;
        appendBatch();
        updateCounts();
        title.focus({ preventScroll: true });
    }

    index.addEventListener('click', function (e) {
        var chip = e.target.closest('.city-chip');
        if (chip) selectTag(chip.getAttribute('data-tag'));
    });

    // Tiles are links to Flickr (the no-JS fallback on the public pages);
    // here a click only toggles membership of the selection.
    grid.addEventListener('click', function (e) {
        var tile = e.target.closest('[data-id]');
        if (!tile) return;
        e.preventDefault();
        var id = tile.getAttribute('data-id');
        if (selected.has(id)) {
            selected.delete(id);
        } else {
            selected.add(id);
        }
        renderBadge(tile);
        updateCounts();
    });

    document.getElementById('selectAll').addEventListener('click', function () {
        selected = new Set(order);
        renderAllBadges();
        updateCounts();
    });
    document.getElementById('selectNone').addEventListener('click', function () {
        selected = new Set();
        renderAllBadges();
        updateCounts();
    });

    // ---- bulk actions ----

    function applyToSelection(fn) {
        if (!selected.size) {
            warn('Nothing selected.');
            return false;
        }
        selected.forEach(fn);
        MMEditor.persist();
        renderAllBadges();
        renderDatalist();
        updateCounts();
        return true;
    }

    document.getElementById('applyCity').addEventListener('click', function () {
        var city = currentCity();
        if (!city) {
            warn('Type a city name first.');
            return;
        }
        if (applyToSelection(function (id) {
            MMEditor.setTag('flickr', id, city);
        })) {
            warn('Tagged ' + selected.size.toLocaleString() + ' as ' + city + '.');
        }
    });

    document.getElementById('clearCity').addEventListener('click', function () {
        if (applyToSelection(function (id) {
            MMEditor.setTag('flickr', id, '');
        })) {
            warn('Untagged ' + selected.size.toLocaleString() + '.');
        }
    });

    document.getElementById('applyFav').addEventListener('click', function () {
        if (applyToSelection(function (id) {
            MMEditor.setFav('flickr', id, true);
        })) {
            warn('Favourited ' + selected.size.toLocaleString() + '.');
        }
    });

    document.getElementById('clearFav').addEventListener('click', function () {
        if (applyToSelection(function (id) {
            MMEditor.setFav('flickr', id, false);
        })) {
            warn('Unfavourited ' + selected.size.toLocaleString() + '.');
        }
    });

    // ---- export bar ----

    document.getElementById('exportTags').addEventListener('click', function () {
        MMEditor.download();
    });
    document.getElementById('clearLocal').addEventListener('click', function () {
        if (!window.confirm('Discard all unexported changes in this browser?')) {
            return;
        }
        MMEditor.clearOverlay();
        renderAllBadges();
        renderDatalist();
        updateCounts();
    });

    renderDatalist();
    updateCounts();
});
