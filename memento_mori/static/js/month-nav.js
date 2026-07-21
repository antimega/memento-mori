// Month-by-month pagination, shared by the timeline and editor pages.
// Expects: #monthNav, #monthSelect (options newest-first), #olderMonth (←,
// back in time) and #newerMonth (→, forward in time) buttons, and at least the
// newest [data-month] panel present in the DOM.
//
// The timeline page server-renders only the newest month and builds the rest
// on demand: when a requested month's panel is absent, this calls the
// window.mmBuildMonth hook (from timeline-months.js) to materialise it. The
// editor page has every month rendered and no such hook, so it behaves exactly
// as before. showMonth() always re-queries the panels, so a panel built after
// load is still found and hidden correctly.
//
// If #monthNav has a data-store attribute, the selected month is persisted to
// localStorage under that key and restored on load; without it the page always
// opens on the newest month (unless a ?post=/?story= deep link points elsewhere).
document.addEventListener('DOMContentLoaded', function () {
    var nav = document.getElementById('monthNav');
    var monthSelect = document.getElementById('monthSelect');
    if (!nav || !monthSelect || !monthSelect.options.length) {
        return;
    }
    if (!document.querySelector('[data-month]')) {
        return;
    }

    var storeKey = nav.dataset.store || null;

    function isSelectOption(key) {
        for (var i = 0; i < monthSelect.options.length; i++) {
            if (monthSelect.options[i].value === key) return true;
        }
        return false;
    }

    // UTC month key ("YYYY-MM") for a timestamp — self-contained so this works
    // on the editor page too, where timeline-months.js is not loaded.
    function monthKeyFromTs(ts) {
        var d = new Date(parseInt(ts, 10) * 1000);
        var m = d.getUTCMonth() + 1;
        return d.getUTCFullYear() + '-' + (m < 10 ? '0' + m : m);
    }

    function showMonth(key) {
        // Ensure the target panel exists; build it on demand where supported.
        var panel = document.querySelector('[data-month="' + key + '"]');
        if (!panel && isSelectOption(key) && typeof window.mmBuildMonth === 'function') {
            panel = window.mmBuildMonth(key);
        }
        if (!panel) {
            // Unknown/absent month → fall back to the newest (first option),
            // whose panel is always server-rendered.
            key = monthSelect.options[0].value;
            panel = document.querySelector('[data-month="' + key + '"]');
        }

        // Re-query every time: show only the target, hide the rest (including
        // any panels built earlier). A stale NodeList would leave two visible.
        document.querySelectorAll('[data-month]').forEach(function (el) {
            el.hidden = el.dataset.month !== key;
        });

        monthSelect.value = key;
        if (storeKey) localStorage.setItem(storeKey, key);
        updateMonthButtons();
        window.scrollTo({ top: 0 });
    }

    function stepMonth(direction) {
        // Options are ordered newest-first: a higher index is older, so
        // +1 goes back in time and -1 goes forward.
        var index = monthSelect.selectedIndex + direction;
        if (index >= 0 && index < monthSelect.options.length) {
            showMonth(monthSelect.options[index].value);
        }
    }

    function updateMonthButtons() {
        // Older (←) is disabled at the oldest month; newer (→) at the newest
        document.getElementById('olderMonth').disabled =
            monthSelect.selectedIndex >= monthSelect.options.length - 1;
        document.getElementById('newerMonth').disabled = monthSelect.selectedIndex <= 0;
    }

    monthSelect.addEventListener('change', function () {
        showMonth(monthSelect.value);
    });
    document.getElementById('olderMonth').addEventListener('click', function () {
        stepMonth(1);   // ← back in time
    });
    document.getElementById('newerMonth').addEventListener('click', function () {
        stepMonth(-1);  // → forward in time
    });

    // A ?post= / ?story= / ?photo= deep link should open on that item's
    // month. Pages whose items aren't timestamp-keyed (flickr) expose a
    // mmMonthKeyOfTarget hook; otherwise resolve purely from the timestamp.
    // Both are validated against the available months.
    var params = new URLSearchParams(window.location.search);
    var target = params.get('post') || params.get('story') || params.get('photo');
    var initial = null;
    if (target) {
        var key = null;
        if (typeof window.mmMonthKeyOfTarget === 'function') {
            key = window.mmMonthKeyOfTarget(target);
        }
        // Hook miss (or no hook): ?post=/?story= targets are timestamps
        if (!key && /^\d+$/.test(target)) {
            key = monthKeyFromTs(target);
        }
        if (key && isSelectOption(key)) initial = key;
    }

    var stored = storeKey ? localStorage.getItem(storeKey) : null;
    showMonth(initial || stored || monthSelect.options[0].value);
});
