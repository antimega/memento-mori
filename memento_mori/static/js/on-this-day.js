// "On this day" view for the timeline page: posts and stories from today's
// calendar day (month + day) in previous years. Fully client-side and live —
// it uses the browser's current date, so it stays correct without
// regenerating the site.
//
// Matches are computed from the data files (cheap key scan, no DOM traversal)
// and the view's DOM is built on the first toggle from the same data, via the
// shared mmTiles builder — the matching timeline tiles are prior-year by
// definition and (post month-on-demand rework) generally not in the DOM to
// clone, so we build fresh rather than clone.
document.addEventListener('DOMContentLoaded', function () {
    var container = document.getElementById('onThisDay');
    var btnTimeline = document.getElementById('viewTimeline');
    var btnOnThisDay = document.getElementById('viewOnThisDay');
    var monthNav = document.getElementById('monthNav');
    var timeline = document.querySelector('.timeline-container');
    if (!container || !btnOnThisDay || !btnTimeline) {
        return;
    }

    // Match the server's day grouping, which uses UTC (utcfromtimestamp)
    var today = new Date();
    var todayMonth = today.getUTCMonth();
    var todayDay = today.getUTCDate();
    var todayYear = today.getUTCFullYear();

    // Bucket matching timestamps by year (previous years only), straight
    // from the loaded data — no DOM work at load time
    var byYear = {};
    var total = 0;

    function scan(data, isStory) {
        if (!data) return;
        Object.keys(data).forEach(function (ts) {
            var d = new Date(parseInt(ts, 10) * 1000);
            if (d.getUTCMonth() !== todayMonth || d.getUTCDate() !== todayDay) return;
            var year = d.getUTCFullYear();
            if (year >= todayYear) return;
            var bucket = byYear[year] || (byYear[year] = { posts: [], stories: [] });
            (isStory ? bucket.stories : bucket.posts).push(ts);
            total++;
        });
    }
    scan(window.postData, false);
    scan(window.storiesData, true);

    var years = Object.keys(byYear).map(Number).sort(function (a, b) { return b - a; });
    years.forEach(function (year) {
        // Newest-first within a year, matching the timeline's ordering
        var newestFirst = function (a, b) { return parseInt(b, 10) - parseInt(a, 10); };
        byYear[year].posts.sort(newestFirst);
        byYear[year].stories.sort(newestFirst);
    });
    if (total) {
        btnOnThisDay.textContent = 'On this day (' + total + ')';
    }

    function buildTile(ts, isStory) {
        var data = isStory ? window.storiesData : window.postData;
        var entry = data && data[ts];
        if (!entry || !window.mmTiles) return null;
        var tile = isStory ? window.mmTiles.story(ts, entry) : window.mmTiles.post(ts, entry);
        if (isStory) {
            tile.classList.remove('story-item');         // keep viewers from binding
        } else {
            tile.classList.remove('grid-item');
            tile.classList.add('otd-tile');              // restyle without grid-item
        }
        // Not the real tile: drop data-timestamp so it can't shadow the real
        // one in month-nav's deep-link lookup, and handle clicks ourselves.
        tile.removeAttribute('data-timestamp');
        tile.addEventListener('click', function (e) {
            e.preventDefault();
            var index = parseInt(tile.getAttribute('data-index'), 10);
            // Build the item's real month first (hidden) so the in-place
            // viewers can find the real tile: openStory live-queries
            // .story-item and navigatePost walks .grid-item — both hit index
            // -1 without it.
            if (window.mmEnsureMonthFor) window.mmEnsureMonthFor(ts);
            if (isStory) {
                if (window.mmOpenStory) window.mmOpenStory(index);
            } else {
                if (window.mmOpenPost) window.mmOpenPost(index);
            }
        });
        return tile;
    }

    function buildRow(timestamps, rowClass, isStory) {
        var row = document.createElement('div');
        row.className = rowClass;
        timestamps.forEach(function (ts) {
            var tile = buildTile(ts, isStory);
            if (tile) row.appendChild(tile);
        });
        return row;
    }

    var built = false;
    function buildView() {
        if (built) return;
        built = true;

        if (!total) {
            var empty = document.createElement('p');
            empty.className = 'otd-empty';
            empty.textContent = 'Nothing from previous years on this day. Check back tomorrow.';
            container.appendChild(empty);
            return;
        }

        years.forEach(function (year) {
            var ago = todayYear - year;
            var section = document.createElement('section');
            section.className = 'otd-year';

            var heading = document.createElement('h2');
            heading.className = 'otd-year-header';
            heading.textContent = year + ' · ' + ago + (ago === 1 ? ' year ago' : ' years ago');
            section.appendChild(heading);

            if (byYear[year].posts.length) {
                section.appendChild(buildRow(byYear[year].posts, 'timeline-posts', false));
            }
            if (byYear[year].stories.length) {
                section.appendChild(buildRow(byYear[year].stories, 'timeline-stories', true));
            }
            container.appendChild(section);
        });
    }

    // View toggle
    function showView(onThisDay) {
        if (onThisDay) buildView();
        container.hidden = !onThisDay;
        if (monthNav) monthNav.hidden = onThisDay;
        if (timeline) timeline.hidden = onThisDay;
        btnOnThisDay.classList.toggle('active', onThisDay);
        btnOnThisDay.setAttribute('aria-pressed', String(onThisDay));
        btnTimeline.classList.toggle('active', !onThisDay);
        btnTimeline.setAttribute('aria-pressed', String(!onThisDay));
        window.scrollTo({ top: 0 });
    }

    btnOnThisDay.addEventListener('click', function () { showView(true); });
    btnTimeline.addEventListener('click', function () { showView(false); });
    // Default view is Timeline (container starts hidden via markup).
});
