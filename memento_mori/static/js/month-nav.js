// Month-by-month pagination, shared by the timeline and editor pages.
// Expects: #monthNav, #monthSelect (options newest-first), #olderMonth (←,
// back in time) and #newerMonth (→, forward in time) buttons, and one
// [data-month] panel per month (all but the active one hidden).
// If #monthNav has a data-store attribute, the selected month is persisted to
// localStorage under that key and restored on load; without it the page
// always opens on the newest month (unless a ?post=/?story= deep link points
// elsewhere).
document.addEventListener('DOMContentLoaded', function () {
    var nav = document.getElementById('monthNav');
    var monthSelect = document.getElementById('monthSelect');
    var monthEls = document.querySelectorAll('[data-month]');
    if (!nav || !monthSelect || !monthEls.length) {
        return;
    }

    var storeKey = nav.dataset.store || null;

    function showMonth(key) {
        var found = false;
        monthEls.forEach(function (el) {
            var match = el.dataset.month === key;
            el.hidden = !match;
            if (match) found = true;
        });
        if (!found) {
            // Fall back to the newest month
            key = monthEls[0].dataset.month;
            monthEls[0].hidden = false;
        }
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

    // A ?post= / ?story= deep link should open on that item's month
    var params = new URLSearchParams(window.location.search);
    var target = params.get('post') || params.get('story');
    var initial = null;
    if (target && /^\d+$/.test(target)) {
        var tile = document.querySelector('[data-timestamp="' + target + '"]');
        var panel = tile && tile.closest('[data-month]');
        if (panel) initial = panel.dataset.month;
    }

    var stored = storeKey ? localStorage.getItem(storeKey) : null;
    showMonth(initial || stored || monthEls[0].dataset.month);
});
