// Editor page functionality: tag posts/stories with city names.
// State = the site-embedded tags (window.cityTags) plus a localStorage
// overlay of unexported changes. Export merges the two into city_tags.json.
document.addEventListener('DOMContentLoaded', function () {
    var grid = document.getElementById('editorGrid');
    var panel = document.getElementById('editorPanel');
    if (!grid || !panel || typeof window.cityTags === 'undefined') {
        return;
    }

    var STORAGE_KEY = 'mm_city_tags';
    var CITY_KEY = 'mm_city_current';

    var base = window.cityTags;
    base.posts = base.posts || {};
    base.stories = base.stories || {};
    base.cities = base.cities || {};
    base.favorites = base.favorites || {};
    base.favorites.posts = base.favorites.posts || {};
    base.favorites.stories = base.favorites.stories || {};

    var overlay;
    try {
        overlay = JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};
    } catch (e) {
        overlay = {};
    }
    overlay.posts = overlay.posts || {};
    overlay.stories = overlay.stories || {};
    overlay.favorites = overlay.favorites || {};
    overlay.favorites.posts = overlay.favorites.posts || {};
    overlay.favorites.stories = overlay.favorites.stories || {};

    var cityInput = document.getElementById('cityInput');
    var datalist = document.getElementById('cityNames');
    var counts = document.getElementById('editorCounts');
    var warning = document.getElementById('editorWarning');

    cityInput.value = localStorage.getItem(CITY_KEY) || '';

    // Prune overlay entries that match base (after an export + regenerate
    // cycle the overlay becomes redundant)
    ['posts', 'stories'].forEach(function (kind) {
        Object.keys(overlay[kind]).forEach(function (ts) {
            var baseVal = base[kind][ts] || null;
            if (overlay[kind][ts] === baseVal) {
                delete overlay[kind][ts];
            }
        });
        Object.keys(overlay.favorites[kind]).forEach(function (ts) {
            var baseFav = base.favorites[kind][ts] ? true : null;
            if (overlay.favorites[kind][ts] === baseFav) {
                delete overlay.favorites[kind][ts];
            }
        });
    });

    function persist() {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(overlay));
    }
    persist();

    function effective(kind, ts) {
        if (Object.prototype.hasOwnProperty.call(overlay[kind], ts)) {
            return overlay[kind][ts];
        }
        return base[kind][ts] || null;
    }

    function setTag(kind, ts, city) {
        var baseVal = base[kind][ts] || null;
        if (city === baseVal) {
            delete overlay[kind][ts];
        } else {
            overlay[kind][ts] = city;
        }
    }

    function effectiveFav(kind, ts) {
        if (Object.prototype.hasOwnProperty.call(overlay.favorites[kind], ts)) {
            return !!overlay.favorites[kind][ts];
        }
        return !!base.favorites[kind][ts];
    }

    function setFav(kind, ts, fav) {
        var baseFav = !!base.favorites[kind][ts];
        if (fav === baseFav) {
            delete overlay.favorites[kind][ts];
        } else {
            overlay.favorites[kind][ts] = fav ? true : null;
        }
    }

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

        var city = effective(kind, ts);
        var badge = tile.querySelector('.city-badge');
        if (city) {
            if (!badge) {
                badge = document.createElement('div');
                badge.className = 'city-badge';
                tile.appendChild(badge);
            }
            badge.textContent = city;
            tile.classList.toggle('tagged-current', city === currentCity());
        } else {
            if (badge) badge.remove();
            tile.classList.remove('tagged-current');
        }

        var fav = effectiveFav(kind, ts);
        var favBadge = tile.querySelector('.fav-badge');
        if (fav) {
            if (!favBadge) {
                favBadge = document.createElement('div');
                favBadge.className = 'fav-badge';
                favBadge.textContent = '★';
                tile.appendChild(favBadge);
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
        var tagged = { posts: 0, stories: 0 };
        var favs = 0;
        ['posts', 'stories'].forEach(function (kind) {
            var seen = {};
            Object.keys(base[kind]).forEach(function (ts) { seen[ts] = true; });
            Object.keys(overlay[kind]).forEach(function (ts) { seen[ts] = true; });
            Object.keys(seen).forEach(function (ts) {
                if (effective(kind, ts)) tagged[kind]++;
            });

            var seenFav = {};
            Object.keys(base.favorites[kind]).forEach(function (ts) { seenFav[ts] = true; });
            Object.keys(overlay.favorites[kind]).forEach(function (ts) { seenFav[ts] = true; });
            Object.keys(seenFav).forEach(function (ts) {
                if (effectiveFav(kind, ts)) favs++;
            });
        });
        var pending = Object.keys(overlay.posts).length + Object.keys(overlay.stories).length
            + Object.keys(overlay.favorites.posts).length + Object.keys(overlay.favorites.stories).length;
        counts.textContent = tagged.posts + ' posts, ' + tagged.stories + ' stories tagged'
            + ' · ' + favs + ' favourite' + (favs !== 1 ? 's' : '')
            + (pending ? ' · ' + pending + ' unexported change' + (pending !== 1 ? 's' : '') : '');
    }

    function renderDatalist() {
        var names = {};
        ['posts', 'stories'].forEach(function (kind) {
            Object.keys(base[kind]).forEach(function (ts) {
                var c = effective(kind, ts);
                if (c) names[c] = true;
            });
            Object.keys(overlay[kind]).forEach(function (ts) {
                var c = overlay[kind][ts];
                if (c) names[c] = true;
            });
        });
        Object.keys(base.cities).forEach(function (c) { names[c] = true; });

        datalist.innerHTML = '';
        Object.keys(names).sort().forEach(function (name) {
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
            setFav(kind, ts, !effectiveFav(kind, ts));
            persist();
            renderBadge(tile);
            renderCounts();
            return;
        }

        var city = currentCity();
        var current = effective(kind, ts);

        if (!city) {
            if (current) {
                setTag(kind, ts, null);
            } else {
                showWarning('Type a city name first');
                return;
            }
        } else if (current === city) {
            setTag(kind, ts, null);
        } else {
            setTag(kind, ts, city);
        }
        persist();
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
            return effective(kind, tile.dataset.timestamp) === city;
        });

        tiles.forEach(function (tile) {
            setTag(kind, tile.dataset.timestamp, allTagged ? null : city);
        });
        persist();
        tiles.forEach(renderBadge);
        renderCounts();
        renderDatalist();
    }

    cityInput.addEventListener('input', function () {
        localStorage.setItem(CITY_KEY, cityInput.value);
        // Refresh the tagged-with-current-city highlight
        allTiles().forEach(function (tile) {
            var city = effective(tile.dataset.kind, tile.dataset.timestamp);
            tile.classList.toggle('tagged-current', !!city && city === currentCity());
        });
    });

    document.getElementById('exportTags').addEventListener('click', function () {
        var merged = {
            version: 1,
            posts: {},
            stories: {},
            cities: base.cities || {},
            favorites: { posts: {}, stories: {} }
        };
        ['posts', 'stories'].forEach(function (kind) {
            var seen = {};
            Object.keys(base[kind]).forEach(function (ts) { seen[ts] = true; });
            Object.keys(overlay[kind]).forEach(function (ts) { seen[ts] = true; });
            Object.keys(seen)
                .sort(function (a, b) { return Number(b) - Number(a); })
                .forEach(function (ts) {
                    var city = effective(kind, ts);
                    if (city) merged[kind][ts] = city;
                });

            var seenFav = {};
            Object.keys(base.favorites[kind]).forEach(function (ts) { seenFav[ts] = true; });
            Object.keys(overlay.favorites[kind]).forEach(function (ts) { seenFav[ts] = true; });
            Object.keys(seenFav)
                .sort(function (a, b) { return Number(b) - Number(a); })
                .forEach(function (ts) {
                    if (effectiveFav(kind, ts)) merged.favorites[kind][ts] = true;
                });
        });

        var blob = new Blob([JSON.stringify(merged, null, 1)], { type: 'application/json' });
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'city_tags.json';
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(a.href);
    });

    document.getElementById('clearLocal').addEventListener('click', function () {
        if (!confirm('Discard all unexported tagging changes in this browser?')) {
            return;
        }
        overlay = { posts: {}, stories: {}, favorites: { posts: {}, stories: {} } };
        persist();
        renderAll();
    });

    // ---- month pagination ----

    var MONTH_KEY = 'mm_editor_month';
    var monthSelect = document.getElementById('monthSelect');
    var monthEls = grid.querySelectorAll('.editor-month');

    function showMonth(key) {
        var found = false;
        monthEls.forEach(function (el) {
            var match = el.dataset.month === key;
            el.hidden = !match;
            if (match) found = true;
        });
        if (!found && monthEls.length) {
            // Fall back to the newest month
            key = monthEls[0].dataset.month;
            monthEls[0].hidden = false;
        }
        monthSelect.value = key;
        localStorage.setItem(MONTH_KEY, key);
        updateMonthButtons();
        window.scrollTo({ top: 0 });
    }

    function stepMonth(direction) {
        // Options are ordered newest-first, matching the select
        var index = monthSelect.selectedIndex + direction;
        if (index >= 0 && index < monthSelect.options.length) {
            showMonth(monthSelect.options[index].value);
        }
    }

    function updateMonthButtons() {
        document.getElementById('prevMonth').disabled = monthSelect.selectedIndex <= 0;
        document.getElementById('nextMonth').disabled =
            monthSelect.selectedIndex >= monthSelect.options.length - 1;
    }

    if (monthEls.length) {
        monthSelect.addEventListener('change', function () {
            showMonth(monthSelect.value);
        });
        document.getElementById('prevMonth').addEventListener('click', function () {
            stepMonth(-1);
        });
        document.getElementById('nextMonth').addEventListener('click', function () {
            stepMonth(1);
        });
        showMonth(localStorage.getItem(MONTH_KEY) || monthEls[0].dataset.month);
    }

    applyMode();
    renderAll();
});
