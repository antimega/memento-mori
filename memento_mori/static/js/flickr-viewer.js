// Flickr viewer: opens items by photo id into the #flickrModal dialog.
//
// A deliberately trimmed sibling of modal.js (flickr items are single-media,
// so no carousel/slideshow; no grid sorting). Duplicates only the small
// focus-trap/inert/scroll plumbing rather than widening modal.js's contract.
// Deep link: ?photo=<id>. Prev/next walk the visible month panel's tiles.
document.addEventListener('DOMContentLoaded', function () {
    var modal = document.getElementById('flickrModal');
    if (!modal || !window.flickrData) return;

    var mediaEl = document.getElementById('flickrMedia');
    var titleEl = document.getElementById('flickrTitle');
    var descEl = document.getElementById('flickrDesc');
    var tagsEl = document.getElementById('flickrTags');
    var albumsEl = document.getElementById('flickrAlbums');
    var statsEl = document.getElementById('flickrStats');
    var dateEl = document.getElementById('flickrDate');
    var closeBtn = document.getElementById('closeFlickr');

    var currentId = null;
    var viewerOpen = false;
    var lastFocused = null;
    var flickrMap = null;          // Lazily-created Leaflet map, reused
    var flickrMapMarker = null;

    function alias() {
        return (window.flickrMeta && window.flickrMeta.path_alias) || '';
    }

    function isVideoFile(url) {
        return /\.(mp4|mov|avi|webm|m4v)$/i.test(url || '');
    }

    // A remote playback URL is only usable in <video> if it's an actual
    // media stream. Flash-era videos (2008-2010) have only a stewart.swf
    // player URL — for those, show the poster; the photopage link is the
    // way to watch.
    function playableRemote(url) {
        if (!url) return false;
        return !/\.swf(\?|$)/i.test(url) && url.indexOf('/apps/video/') === -1;
    }

    function setBackgroundInert(on) {
        ['header', 'main', 'footer'].forEach(function (sel) {
            var el = document.querySelector(sel);
            if (!el) return;
            if (on) {
                el.setAttribute('inert', '');
                el.setAttribute('aria-hidden', 'true');
            } else {
                el.removeAttribute('inert');
                el.removeAttribute('aria-hidden');
            }
        });
    }

    function trapFocus(e) {
        if (!viewerOpen || e.key !== 'Tab') return;
        var focusable = Array.prototype.filter.call(
            modal.querySelectorAll('button, a[href], video, [tabindex]:not([tabindex="-1"])'),
            function (el) { return el.offsetParent !== null; }
        );
        if (!focusable.length) return;
        var first = focusable[0];
        var last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
            e.preventDefault();
            last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first.focus();
        }
    }

    function updateMap(entry) {
        var mapEl = document.getElementById('flickrMap');
        if (!mapEl) return;
        var la = parseFloat(entry.la);
        var lo = parseFloat(entry.lo);
        if (!isFinite(la) || !isFinite(lo) || typeof L === 'undefined') {
            mapEl.style.display = 'none';
            return;
        }
        mapEl.style.display = 'block';
        if (!flickrMap) {
            flickrMap = L.map(mapEl, { scrollWheelZoom: false, fadeAnimation: false });
            L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
                maxZoom: 19,
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            }).addTo(flickrMap);
        }
        var latlng = [la, lo];
        flickrMap.setView(latlng, 14);
        if (flickrMapMarker) {
            flickrMapMarker.setLatLng(latlng);
        } else {
            flickrMapMarker = L.marker(latlng).addTo(flickrMap);
        }
        setTimeout(function () {
            flickrMap.invalidateSize();
            flickrMap.setView(latlng, 14);
        }, 60);
    }

    function buildMedia(entry) {
        mediaEl.innerHTML = '';
        var slide = document.createElement('div');
        slide.className = 'media-slide active';
        var m0 = (entry.m && entry.m[0]) || '';

        if (entry.vd && (isVideoFile(m0) || playableRemote(entry.vu))) {
            var video = document.createElement('video');
            video.controls = true;
            video.autoplay = false;
            video.playsInline = true;
            video.preload = 'metadata';
            if (isVideoFile(m0)) {
                video.src = m0;               // fully local video
                if (entry.vp) video.poster = entry.vp;
            } else {
                video.src = entry.vu;         // remote playback (poster local)
                video.poster = m0;            // m0 IS the converted poster
            }
            slide.appendChild(video);
        } else {
            var img = document.createElement('img');
            img.src = m0;
            img.alt = entry.tt || 'Flickr photo';
            slide.appendChild(img);
        }
        mediaEl.appendChild(slide);
    }

    function updateUrl(id) {
        var url = new URL(window.location.href);
        if (id) {
            url.searchParams.set('photo', id);
        } else {
            url.searchParams.delete('photo');
        }
        window.history.pushState({}, '', url);
    }

    function openFlickr(id) {
        var entry = window.flickrData[id];
        if (!entry) return;
        currentId = id;

        if (!viewerOpen) {
            lastFocused = document.activeElement;
        }
        // Timeline page: make sure the item's month panel exists so the
        // DOM-walking prev/next has tiles (the grid page navigates by data
        // order instead — see mmFlickrOrder)
        if (window.mmMonthKeyOfTarget && window.mmBuildMonth) {
            var mk = window.mmMonthKeyOfTarget(id);
            if (mk) window.mmBuildMonth(mk);
        }

        modal.style.display = 'block';
        document.body.style.overflow = 'hidden';

        buildMedia(entry);

        titleEl.textContent = entry.tt || '';
        titleEl.style.display = entry.tt ? 'block' : 'none';
        descEl.textContent = entry.ds || '';
        descEl.style.display = entry.ds ? 'block' : 'none';

        // Tag chips — each links to the tag navigator opened on that tag
        // (user data — createElement/textContent only)
        tagsEl.innerHTML = '';
        (entry.tg || []).forEach(function (tag) {
            var chip = document.createElement('a');
            chip.className = 'flickr-tag';
            chip.textContent = tag;
            chip.href = 'tags.html#tag=' + encodeURIComponent(tag);
            chip.addEventListener('click', function () {
                // On the tags page this is a same-document hash change (no
                // reload): close the viewer and let tags.js's hashchange
                // handler switch the tag. On other pages the navigation
                // replaces the document anyway.
                closeFlickr();
            });
            tagsEl.appendChild(chip);
        });
        tagsEl.style.display = (entry.tg || []).length ? 'flex' : 'none';

        // Album links
        albumsEl.innerHTML = '';
        (entry.al || []).forEach(function (aid) {
            var info = (window.flickrAlbums || {})[aid];
            if (!info) return;
            var a = document.createElement('a');
            a.href = 'https://www.flickr.com/photos/' + alias() + '/albums/' + aid;
            a.target = '_blank';
            a.rel = 'noopener noreferrer';
            a.textContent = info.t;
            albumsEl.appendChild(a);
        });
        albumsEl.style.display = albumsEl.children.length ? 'block' : 'none';

        // License only (view/fave counts are not imported)
        statsEl.innerHTML = '';
        if (entry.lic) {
            var div = document.createElement('div');
            div.className = 'post-stat';
            var i = document.createElement('span');
            i.className = 'post-stat-icon';
            i.textContent = '©';
            var t = document.createElement('span');
            t.textContent = entry.lic;
            div.appendChild(i);
            div.appendChild(t);
            statsEl.appendChild(div);
        }
        statsEl.style.display = statsEl.children.length ? 'flex' : 'none';

        updateMap(entry);

        dateEl.textContent = entry.d;

        updateUrl(id);

        viewerOpen = true;
        setBackgroundInert(true);
        closeBtn.focus();
    }
    // Hook for other views (and symmetry with mmOpenPost/mmOpenStory)
    window.mmOpenFlickr = openFlickr;

    function navIds() {
        // Grid page: navigate the full data order for the current sort
        // (works even for tiles not yet appended by the progressive grid)
        if (window.mmFlickrOrder) return window.mmFlickrOrder;
        // Timeline page: walk the visible month panel's flickr tiles
        var panel = document.querySelector('.timeline-month:not([hidden])');
        if (!panel) return [];
        return Array.prototype.map.call(
            panel.querySelectorAll('.flickr-tile'),
            function (t) { return t.getAttribute('data-id'); }
        );
    }

    function navigate(direction) {
        var video = mediaEl.querySelector('video');
        if (video) video.pause();
        var ids = navIds();
        var pos = ids.indexOf(currentId);
        if (pos === -1 || !ids.length) return;
        openFlickr(ids[(pos + direction + ids.length) % ids.length]);
    }

    function closeFlickr() {
        var video = mediaEl.querySelector('video');
        if (video) video.pause();
        modal.style.display = 'none';
        document.body.style.overflow = '';
        viewerOpen = false;
        setBackgroundInert(false);
        updateUrl(null);
        if (lastFocused && typeof lastFocused.focus === 'function') {
            lastFocused.focus();
        }
    }

    // One delegated listener for every .flickr-tile (thousands on this page)
    document.addEventListener('click', function (e) {
        var tile = e.target.closest('.flickr-tile');
        if (!tile) return;
        e.preventDefault();   // tiles are links to Flickr (no-JS fallback)
        openFlickr(tile.getAttribute('data-id'));
    });

    closeBtn.addEventListener('click', closeFlickr);
    document.getElementById('flickrPrev').addEventListener('click', function (e) {
        e.stopPropagation();
        navigate(-1);
    });
    document.getElementById('flickrNext').addEventListener('click', function (e) {
        e.stopPropagation();
        navigate(1);
    });
    modal.addEventListener('click', function (e) {
        if (e.target === modal) closeFlickr();
    });

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Tab') {
            trapFocus(e);
            return;
        }
        if (!viewerOpen) return;
        if (e.key === 'Escape') {
            closeFlickr();
        } else if (e.key === 'ArrowLeft') {
            navigate(-1);
        } else if (e.key === 'ArrowRight') {
            navigate(1);
        }
    });

    // Deep link: ?photo=<id>. Delayed so month-nav's DCL handler has shown
    // the right month first (its deep-link resolution uses our
    // mmMonthKeyOfTarget hook).
    var params = new URLSearchParams(window.location.search);
    var target = params.get('photo');
    if (target && window.flickrData[target]) {
        setTimeout(function () { openFlickr(target); }, 100);
    }
});
