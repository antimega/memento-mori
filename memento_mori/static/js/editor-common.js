// Shared editor state: the site-embedded tags (window.cityTags) plus a
// localStorage overlay of unexported changes. Both editor pages (tagging
// and city text) read and mutate the same state; Export merges base +
// overlay into a fresh city_tags.json.
window.MMEditor = (function () {
    var STORAGE_KEY = 'mm_city_tags';

    var base = null;
    var overlay = null;

    function init() {
        if (typeof window.cityTags === 'undefined') {
            return false;
        }

        base = window.cityTags;
        base.posts = base.posts || {};
        base.stories = base.stories || {};
        base.cities = base.cities || {};
        base.favorites = base.favorites || {};
        base.favorites.posts = base.favorites.posts || {};
        base.favorites.stories = base.favorites.stories || {};

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
        overlay.cityText = overlay.cityText || {};

        // Prune overlay entries that match base (after an export +
        // regenerate cycle the overlay becomes redundant)
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
        Object.keys(overlay.cityText).forEach(function (name) {
            var baseText = (base.cities[name] || {}).text || null;
            if (overlay.cityText[name] === baseText) {
                delete overlay.cityText[name];
            }
        });

        persist();
        return true;
    }

    function persist() {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(overlay));
    }

    // ---- tags ----

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

    // ---- favourites ----

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

    // ---- per-city text ----

    function effectiveCityText(name) {
        if (Object.prototype.hasOwnProperty.call(overlay.cityText, name)) {
            return overlay.cityText[name] || '';
        }
        return (base.cities[name] || {}).text || '';
    }

    function setCityText(name, text) {
        text = (text || '').trim() ? text : null;
        var baseText = (base.cities[name] || {}).text || null;
        if (text === baseText) {
            delete overlay.cityText[name];
        } else {
            overlay.cityText[name] = text;
        }
    }

    function cityTextPending(name) {
        return Object.prototype.hasOwnProperty.call(overlay.cityText, name);
    }

    // ---- derived state ----

    function cityNames() {
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
        Object.keys(overlay.cityText).forEach(function (c) { names[c] = true; });
        return Object.keys(names).sort();
    }

    function taggedCount(kind, city) {
        var seen = {};
        Object.keys(base[kind]).forEach(function (ts) { seen[ts] = true; });
        Object.keys(overlay[kind]).forEach(function (ts) { seen[ts] = true; });
        var count = 0;
        Object.keys(seen).forEach(function (ts) {
            var c = effective(kind, ts);
            if (city === undefined ? c : c === city) count++;
        });
        return count;
    }

    function favCount() {
        var count = 0;
        ['posts', 'stories'].forEach(function (kind) {
            var seen = {};
            Object.keys(base.favorites[kind]).forEach(function (ts) { seen[ts] = true; });
            Object.keys(overlay.favorites[kind]).forEach(function (ts) { seen[ts] = true; });
            Object.keys(seen).forEach(function (ts) {
                if (effectiveFav(kind, ts)) count++;
            });
        });
        return count;
    }

    function pendingCount() {
        return Object.keys(overlay.posts).length
            + Object.keys(overlay.stories).length
            + Object.keys(overlay.favorites.posts).length
            + Object.keys(overlay.favorites.stories).length
            + Object.keys(overlay.cityText).length;
    }

    // ---- export ----

    function buildExport() {
        var merged = {
            version: 1,
            posts: {},
            stories: {},
            cities: {},
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

        // Cities map: preserve manual pins, apply effective text; keep an
        // entry only when it still carries something
        var names = {};
        Object.keys(base.cities).forEach(function (n) { names[n] = true; });
        Object.keys(overlay.cityText).forEach(function (n) { names[n] = true; });
        Object.keys(names).sort().forEach(function (name) {
            var entry = {};
            var baseCity = base.cities[name] || {};
            if (typeof baseCity.lat === 'number' && typeof baseCity.lng === 'number') {
                entry.lat = baseCity.lat;
                entry.lng = baseCity.lng;
            }
            var text = effectiveCityText(name);
            if (text) {
                entry.text = text;
            }
            if (Object.keys(entry).length) {
                merged.cities[name] = entry;
            }
        });

        return merged;
    }

    function download() {
        var blob = new Blob([JSON.stringify(buildExport(), null, 1)], {
            type: 'application/json'
        });
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'city_tags.json';
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(a.href);
    }

    function clearOverlay() {
        overlay = {
            posts: {},
            stories: {},
            favorites: { posts: {}, stories: {} },
            cityText: {}
        };
        persist();
    }

    return {
        init: init,
        persist: persist,
        effective: effective,
        setTag: setTag,
        effectiveFav: effectiveFav,
        setFav: setFav,
        effectiveCityText: effectiveCityText,
        setCityText: setCityText,
        cityTextPending: cityTextPending,
        cityNames: cityNames,
        taggedCount: taggedCount,
        favCount: favCount,
        pendingCount: pendingCount,
        buildExport: buildExport,
        download: download,
        clearOverlay: clearOverlay
    };
})();
