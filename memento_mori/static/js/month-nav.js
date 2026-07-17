// Month-by-month pagination, shared by the timeline and editor pages.
// Expects: #monthNav (with optional data-store for the persistence key),
// #monthSelect (options newest-first), #prevMonth / #nextMonth buttons,
// and one [data-month] panel per month (all but the active one hidden).
document.addEventListener('DOMContentLoaded', function () {
    var nav = document.getElementById('monthNav');
    var monthSelect = document.getElementById('monthSelect');
    var monthEls = document.querySelectorAll('[data-month]');
    if (!nav || !monthSelect || !monthEls.length) {
        return;
    }

    var storeKey = nav.dataset.store || 'mm_month';

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
        localStorage.setItem(storeKey, key);
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

    monthSelect.addEventListener('change', function () {
        showMonth(monthSelect.value);
    });
    document.getElementById('prevMonth').addEventListener('click', function () {
        stepMonth(-1);
    });
    document.getElementById('nextMonth').addEventListener('click', function () {
        stepMonth(1);
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

    showMonth(initial || localStorage.getItem(storeKey) || monthEls[0].dataset.month);
});
