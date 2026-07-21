// Client-side timeline month builder.
//
// The timeline page server-renders only the newest month; every other month
// is built on demand in the browser from window.postData / window.storiesData
// (the same data the in-page viewers already load). This keeps timeline.html
// small (one month of markup instead of ~150) while months materialise
// instantly on navigation.
//
// Window contract exposed for the other timeline scripts:
//   window.monthKeyOf(ts)        -> "YYYY-MM" (UTC) for a timestamp
//   window.mmTiles.post/.story/.flickr -> a single tile element (markup parity with
//                                   the Jinja tiles in templates/timeline.html)
//   window.mmBuildMonth(key)     -> the [data-month] panel (existing or built),
//                                   or null for an unknown key (no ghost month)
//   window.mmEnsureMonthFor(ts)  -> build (hidden) the month containing ts
//
// IMPORTANT: the tile markup here must stay byte-for-byte in step with the
// post/story tiles in templates/timeline.html (classes, data-*, href,
// indicators, .tile-place). If you change one, change the other.
(function () {
    var MONTH_NAMES = [
        'January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December'
    ];

    // Placeholder for a video with no thumbnail anywhere. Matches the SVG the
    // generator emits (see _get_display_media); base64 via btoa keeps parity.
    var VIDEO_SVG = 'data:image/svg+xml;base64,' + btoa(
        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400" viewBox="0 0 400 400">' +
        '<rect width="400" height="400" fill="#333333"/>' +
        '<circle cx="200" cy="200" r="60" fill="#ffffff" fill-opacity="0.8"/>' +
        '<polygon points="180,160 180,240 240,200" fill="#333333"/>' +
        '</svg>'
    );

    function pad2(n) {
        return n < 10 ? '0' + n : '' + n;
    }

    function isVideo(url) {
        return /\.(mp4|mov|avi|webm)$/i.test(url || '');
    }

    function monthKeyOf(ts) {
        var d = new Date(parseInt(ts, 10) * 1000);
        return d.getUTCFullYear() + '-' + pad2(d.getUTCMonth() + 1);
    }

    // Reconstruct the exact tile image URL the server resolved (th = md5
    // thumbnail, dm = any other resolved URL) with the same fallbacks.
    function postMedia(entry) {
        if (entry.th) return 'thumbnails/' + entry.th + '.webp';
        if (entry.dm) return entry.dm;
        var m0 = entry.m && entry.m[0];
        return isVideo(m0) ? VIDEO_SVG : (m0 || '');
    }

    function storyMedia(entry) {
        if (entry.th) return 'thumbnails/' + entry.th + '.webp';
        if (entry.dm) return entry.dm;
        return (entry.m && entry.m[0]) || '';
    }

    var mmTiles = {
        // Parity target: the post tile in templates/timeline.html
        post: function (ts, entry) {
            var a = document.createElement('a');
            a.className = 'grid-item timeline-tile';
            a.setAttribute('data-index', entry.i);
            a.setAttribute('data-timestamp', ts);
            a.setAttribute('href', 'index.html?post=' + ts);

            var media = document.createElement('div');
            media.className = 'tile-media';

            var img = document.createElement('img');
            img.src = postMedia(entry);
            img.alt = 'Instagram post';
            img.loading = 'lazy';
            media.appendChild(img);

            if (isVideo(entry.m && entry.m[0])) {
                var vi = document.createElement('div');
                vi.className = 'video-indicator';
                vi.textContent = '▶ Video';
                media.appendChild(vi);
            }
            if (entry.m && entry.m.length > 1) {
                var mi = document.createElement('div');
                mi.className = 'multi-indicator';
                mi.textContent = '⊞ ' + entry.m.length;
                media.appendChild(mi);
            }
            a.appendChild(media);

            var place = document.createElement('div');
            place.className = 'tile-place';
            place.textContent = entry.pl || '';   // user data — never innerHTML
            a.appendChild(place);
            return a;
        },
        // Parity target: the story tile in templates/timeline.html. The one
        // intentional difference from the server markup is that onerror is set
        // as a property (not an attribute) to avoid quoting the media path.
        story: function (ts, entry) {
            var a = document.createElement('a');
            a.className = 'story-item timeline-story-tile';
            a.setAttribute('data-index', entry.i);
            a.setAttribute('data-timestamp', ts);
            a.setAttribute('href', 'stories.html?story=' + ts);

            var img = document.createElement('img');
            img.src = storyMedia(entry);
            img.alt = 'Instagram story';
            img.loading = 'lazy';
            var original = (entry.m && entry.m[0]) || '';
            img.onerror = function () { this.onerror = null; this.src = original; };
            a.appendChild(img);

            if (isVideo(entry.m && entry.m[0])) {
                var vi = document.createElement('div');
                vi.className = 'video-indicator';
                vi.textContent = '▶';
                a.appendChild(vi);
            }
            return a;
        }
    };

    // Lazy, memoized index: monthKey -> dayKey -> {posts, stories, flickr}
    var monthIndex = null;

    function buildIndex() {
        if (monthIndex) return;
        monthIndex = {};
        function dayOf(epoch) {
            var d = new Date(epoch * 1000);
            var mk = d.getUTCFullYear() + '-' + pad2(d.getUTCMonth() + 1);
            var dk = mk + '-' + pad2(d.getUTCDate());
            var month = monthIndex[mk] || (monthIndex[mk] = {});
            return month[dk] || (month[dk] = {
                posts: [], stories: [], flickr: [], date: d
            });
        }
        function add(data, isStory) {
            if (!data) return;
            Object.keys(data).forEach(function (ts) {
                var day = dayOf(parseInt(ts, 10));
                (isStory ? day.stories : day.posts).push(ts);
            });
        }
        add(window.postData, false);
        add(window.storiesData, true);
        // Flickr items (id-keyed; epoch in entry.t) — third row per day
        if (window.flickrData) {
            Object.keys(window.flickrData).forEach(function (id) {
                dayOf(window.flickrData[id].t).flickr.push(id);
            });
        }
    }

    // Parity target: the flickr tile in templates/timeline.html
    function flickrTimelineTile(id, entry) {
        var alias = (window.flickrMeta && window.flickrMeta.path_alias) || '';
        var a = document.createElement('a');
        a.className = 'grid-item timeline-tile flickr-tile';
        a.setAttribute('data-id', id);
        a.setAttribute('href', 'https://www.flickr.com/photos/' + alias + '/' + id + '/');

        var media = document.createElement('div');
        media.className = 'tile-media';

        var img = document.createElement('img');
        img.src = entry.th ? 'thumbnails/' + entry.th + '.webp'
            : (entry.dm || (entry.m && entry.m[0]) || '');
        img.alt = 'Flickr photo';
        img.loading = 'lazy';
        media.appendChild(img);

        if (entry.vd) {
            var vi = document.createElement('div');
            vi.className = 'video-indicator';
            vi.textContent = '▶ Video';
            media.appendChild(vi);
        }
        a.appendChild(media);

        var place = document.createElement('div');
        place.className = 'tile-place';
        place.textContent = entry.tt || '';   // user data — never innerHTML
        a.appendChild(place);
        return a;
    }

    function descTs(a, b) {
        return parseInt(b, 10) - parseInt(a, 10);
    }

    function dayHeading(d) {
        return MONTH_NAMES[d.getUTCMonth()] + ' ' + pad2(d.getUTCDate()) + ', ' + d.getUTCFullYear();
    }

    function rowLabel(n, isStory) {
        var div = document.createElement('div');
        div.className = 'timeline-row-label';
        if (isStory) {
            div.textContent = n + ' stor' + (n !== 1 ? 'ies' : 'y');
        } else {
            div.textContent = n + ' post' + (n !== 1 ? 's' : '');
        }
        return div;
    }

    // Keep panels in descending month order so document order stays
    // chronological (viewer prev/next order + "newest is first" invariant).
    function insertMonthSorted(container, panel, key) {
        var panels = container.querySelectorAll('[data-month]');
        var before = null;
        for (var i = 0; i < panels.length; i++) {
            if (panels[i].getAttribute('data-month') < key) {
                before = panels[i];
                break;
            }
        }
        container.insertBefore(panel, before);  // before === null appends
    }

    function mmBuildMonth(key) {
        var container = document.querySelector('.timeline-container');
        if (!container) return null;

        var existing = container.querySelector('[data-month="' + key + '"]');
        if (existing) return existing;

        buildIndex();
        var month = monthIndex[key];
        if (!month) return null;   // unknown key -> don't manufacture a panel

        var panel = document.createElement('div');
        panel.className = 'timeline-month';
        panel.setAttribute('data-month', key);
        panel.hidden = true;

        var frag = document.createDocumentFragment();
        // JS enumerates object keys in ascending order — sort days descending
        var dayKeys = Object.keys(month).sort().reverse();
        dayKeys.forEach(function (dk) {
            var day = month[dk];
            var section = document.createElement('section');
            section.className = 'timeline-day';

            var h2 = document.createElement('h2');
            h2.className = 'timeline-day-header';
            h2.textContent = dayHeading(day.date);
            section.appendChild(h2);

            if (day.posts.length) {
                var posts = day.posts.slice().sort(descTs);
                section.appendChild(rowLabel(posts.length, false));
                var pr = document.createElement('div');
                pr.className = 'timeline-posts';
                posts.forEach(function (ts) {
                    pr.appendChild(mmTiles.post(ts, window.postData[ts]));
                });
                section.appendChild(pr);
            }
            if (day.stories.length) {
                var stories = day.stories.slice().sort(descTs);
                section.appendChild(rowLabel(stories.length, true));
                var sr = document.createElement('div');
                sr.className = 'timeline-stories';
                stories.forEach(function (ts) {
                    sr.appendChild(mmTiles.story(ts, window.storiesData[ts]));
                });
                section.appendChild(sr);
            }
            if (day.flickr.length) {
                // Third section, after posts and stories (matches the
                // server-rendered newest month in templates/timeline.html)
                var fl = day.flickr.slice().sort(function (a, b) {
                    return (window.flickrData[b].t - window.flickrData[a].t)
                        || (parseInt(b, 10) - parseInt(a, 10));
                });
                var flabel = document.createElement('div');
                flabel.className = 'timeline-row-label';
                flabel.textContent =
                    'Flickr photos and videos (' + fl.length + ')';
                section.appendChild(flabel);
                var fr = document.createElement('div');
                fr.className = 'timeline-posts';
                fl.forEach(function (id) {
                    fr.appendChild(
                        flickrTimelineTile(id, window.flickrData[id])
                    );
                });
                section.appendChild(fr);
            }
            frag.appendChild(section);
        });

        panel.appendChild(frag);
        insertMonthSorted(container, panel, key);
        return panel;
    }

    function mmEnsureMonthFor(ts) {
        return mmBuildMonth(monthKeyOf(ts));
    }

    // Deep-link month for non-timestamp targets (?photo=<flickr id>);
    // month-nav.js prefers this hook and falls back to timestamp math.
    function mmMonthKeyOfTarget(target) {
        var entry = window.flickrData && window.flickrData[target];
        return entry ? monthKeyOf(entry.t) : null;
    }

    // flickrTimelineTile is a hoisted declaration below; exposing it on
    // mmTiles lets On This Day build Flickr memories with the same
    // parity-maintained markup the timeline uses.
    mmTiles.flickr = flickrTimelineTile;

    window.monthKeyOf = monthKeyOf;
    window.mmTiles = mmTiles;
    window.mmBuildMonth = mmBuildMonth;
    window.mmEnsureMonthFor = mmEnsureMonthFor;
    window.mmMonthKeyOfTarget = mmMonthKeyOfTarget;
})();
