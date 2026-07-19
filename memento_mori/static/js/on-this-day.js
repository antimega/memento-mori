// "On this day" view for the timeline page: posts and stories from today's
// calendar day (month + day) in previous years. Fully client-side and live —
// it uses the browser's current date, so it stays correct without
// regenerating the site. Matching tiles are cloned from the (always-rendered)
// timeline DOM and open the real in-place viewers via the exposed hooks.
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

    function tileDate(tile) {
        var d = new Date(parseInt(tile.getAttribute('data-timestamp'), 10) * 1000);
        return { month: d.getUTCMonth(), day: d.getUTCDate(), year: d.getUTCFullYear() };
    }

    // Bucket matching tiles by year (previous years only)
    var byYear = {};
    [
        { sel: '.timeline-tile', story: false },
        { sel: '.timeline-story-tile', story: true }
    ].forEach(function (kind) {
        document.querySelectorAll('.timeline-container ' + kind.sel).forEach(function (tile) {
            var d = tileDate(tile);
            if (d.month !== todayMonth || d.day !== todayDay || d.year >= todayYear) {
                return;
            }
            var bucket = byYear[d.year] || (byYear[d.year] = { posts: [], stories: [] });
            (kind.story ? bucket.stories : bucket.posts).push(tile);
        });
    });

    var years = Object.keys(byYear).map(Number).sort(function (a, b) { return b - a; });
    var total = years.reduce(function (n, y) {
        return n + byYear[y].posts.length + byYear[y].stories.length;
    }, 0);

    function buildRow(tiles, rowClass, isStory) {
        var row = document.createElement('div');
        row.className = rowClass;
        tiles.forEach(function (orig) {
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
            row.appendChild(clone);
        });
        return row;
    }

    // Build the section eagerly, kept hidden until toggled
    if (!total) {
        var empty = document.createElement('p');
        empty.className = 'otd-empty';
        empty.textContent = 'Nothing from previous years on this day. Check back tomorrow.';
        container.appendChild(empty);
    } else {
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
        btnOnThisDay.textContent = 'On this day (' + total + ')';
    }

    // View toggle
    function showView(onThisDay) {
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
