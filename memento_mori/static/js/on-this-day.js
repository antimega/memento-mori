// "On this day" view for the timeline page: posts and stories from today's
// calendar day (month + day) in previous years. Fully client-side and live —
// it uses the browser's current date, so it stays correct without
// regenerating the site.
//
// For load performance the matches are computed from the data files (cheap
// key scan, no DOM traversal) and the view's DOM is only built on the first
// toggle, by cloning the matching timeline tiles.
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

    function cloneTile(ts, isStory) {
        var orig = document.querySelector(
            '.timeline-container [data-timestamp="' + ts + '"]'
        );
        if (!orig) return null;
        var clone = orig.cloneNode(true);
        if (isStory) {
            clone.classList.remove('story-item');       // keep viewers from binding
        } else {
            clone.classList.remove('grid-item');
            clone.classList.add('otd-tile');             // restyle without grid-item
        }
        // Avoid a duplicate data-timestamp that would shadow the real tile
        // in month-nav's deep-link lookup
        clone.removeAttribute('data-timestamp');
        clone.addEventListener('click', function (e) {
            e.preventDefault();
            var index = parseInt(clone.getAttribute('data-index'), 10);
            if (isStory) {
                if (window.mmOpenStory) window.mmOpenStory(index);
            } else {
                if (window.mmOpenPost) window.mmOpenPost(index);
            }
        });
        return clone;
    }

    function buildRow(timestamps, rowClass, isStory) {
        var row = document.createElement('div');
        row.className = rowClass;
        timestamps.forEach(function (ts) {
            var clone = cloneTile(ts, isStory);
            if (clone) row.appendChild(clone);
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
