// Tagging page: tag posts/stories with city names and mark favourites.
// Shared state lives in editor-common.js (window.MMEditor).
document.addEventListener('DOMContentLoaded', function () {
    var grid = document.getElementById('editorGrid');
    var panel = document.getElementById('editorPanel');
    if (!grid || !panel || !window.MMEditor || !MMEditor.init()) {
        return;
    }

    var CITY_KEY = 'mm_city_current';

    var cityInput = document.getElementById('cityInput');
    var datalist = document.getElementById('cityNames');
    var counts = document.getElementById('editorCounts');
    var warning = document.getElementById('editorWarning');

    cityInput.value = localStorage.getItem(CITY_KEY) || '';

    // ---- edit mode (tag city vs favourite) ----

    var MODE_KEY = 'mm_editor_mode';
    var mode = localStorage.getItem(MODE_KEY) === 'fav' ? 'fav' : 'tag';

    function applyMode() {
        document.body.classList.toggle('fav-mode', mode === 'fav');
        cityInput.disabled = mode === 'fav';
        document.querySelectorAll('input[name="editMode"]').forEach(function (radio) {
            radio.checked = radio.value === mode;
        });
    }

    document.querySelectorAll('input[name="editMode"]').forEach(function (radio) {
        radio.addEventListener('change', function () {
            mode = this.value;
            localStorage.setItem(MODE_KEY, mode);
            applyMode();
        });
    });

    function currentCity() {
        return cityInput.value.trim();
    }

    function showWarning(message) {
        warning.textContent = message;
        clearTimeout(showWarning.timer);
        showWarning.timer = setTimeout(function () {
            warning.textContent = '';
        }, 2500);
    }

    // ---- rendering ----

    function renderBadge(tile) {
        var kind = tile.dataset.kind;
        var ts = tile.dataset.timestamp;

        // Badges live in the image box (post tiles have a caption below it)
        var host = tile.querySelector('.tile-media') || tile;

        var city = MMEditor.effective(kind, ts);
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

        var fav = MMEditor.effectiveFav(kind, ts);
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
    }

    function allTiles() {
        return grid.querySelectorAll('[data-kind][data-timestamp]');
    }

    function renderAll() {
        allTiles().forEach(renderBadge);
        renderCounts();
        renderDatalist();
    }

    function renderCounts() {
        var favs = MMEditor.favCount();
        var pending = MMEditor.pendingCount();
        counts.textContent = MMEditor.taggedCount('posts') + ' posts, '
            + MMEditor.taggedCount('stories') + ' stories tagged'
            + ' · ' + favs + ' favourite' + (favs !== 1 ? 's' : '')
            + (pending ? ' · ' + pending + ' unexported change' + (pending !== 1 ? 's' : '') : '');
    }

    function renderDatalist() {
        datalist.innerHTML = '';
        MMEditor.cityNames().forEach(function (name) {
            var option = document.createElement('option');
            option.value = name;
            datalist.appendChild(option);
        });
    }

    // ---- interactions ----

    function toggleTile(tile) {
        var kind = tile.dataset.kind;
        var ts = tile.dataset.timestamp;

        if (mode === 'fav') {
            MMEditor.setFav(kind, ts, !MMEditor.effectiveFav(kind, ts));
            MMEditor.persist();
            renderBadge(tile);
            renderCounts();
            return;
        }

        var city = currentCity();
        var current = MMEditor.effective(kind, ts);

        if (!city) {
            if (current) {
                MMEditor.setTag(kind, ts, null);
            } else {
                showWarning('Type a city name first');
                return;
            }
        } else if (current === city) {
            MMEditor.setTag(kind, ts, null);
        } else {
            MMEditor.setTag(kind, ts, city);
        }
        MMEditor.persist();
        renderBadge(tile);
        renderCounts();
        renderDatalist();
    }

    grid.addEventListener('click', function (e) {
        var dayBtn = e.target.closest('.tag-day-btn');
        if (dayBtn) {
            tagDay(dayBtn);
            return;
        }
        var tile = e.target.closest('[data-kind][data-timestamp]');
        if (tile) {
            toggleTile(tile);
        }
    });

    function tagDay(button) {
        if (mode === 'fav') {
            return;
        }
        var city = currentCity();
        if (!city) {
            showWarning('Type a city name first');
            return;
        }
        var kind = button.dataset.kind;
        var section = button.closest('.timeline-day');
        var tiles = section.querySelectorAll('[data-kind="' + kind + '"][data-timestamp]');

        var allTagged = Array.prototype.every.call(tiles, function (tile) {
            return MMEditor.effective(kind, tile.dataset.timestamp) === city;
        });

        tiles.forEach(function (tile) {
            MMEditor.setTag(kind, tile.dataset.timestamp, allTagged ? null : city);
        });
        MMEditor.persist();
        tiles.forEach(renderBadge);
        renderCounts();
        renderDatalist();
    }

    cityInput.addEventListener('input', function () {
        localStorage.setItem(CITY_KEY, cityInput.value);
        // Refresh the tagged-with-current-city highlight
        allTiles().forEach(function (tile) {
            var city = MMEditor.effective(tile.dataset.kind, tile.dataset.timestamp);
            tile.classList.toggle('tagged-current', !!city && city === currentCity());
        });
    });

    document.getElementById('exportTags').addEventListener('click', function () {
        MMEditor.download();
    });

    document.getElementById('clearLocal').addEventListener('click', function () {
        if (!confirm('Discard all unexported editing changes in this browser?')) {
            return;
        }
        MMEditor.clearOverlay();
        renderAll();
    });

    // Month pagination is handled by the shared month-nav.js

    applyMode();
    renderAll();
});
