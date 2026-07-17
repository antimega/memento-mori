// City text page: write per-city Markdown shown on the cities page.
// Shared state lives in editor-common.js (window.MMEditor).
document.addEventListener('DOMContentLoaded', function () {
    var list = document.getElementById('cityTextList');
    if (!list || !window.MMEditor || !MMEditor.init()) {
        return;
    }

    var counts = document.getElementById('editorCounts');

    function renderCounts() {
        var pending = MMEditor.pendingCount();
        var withText = MMEditor.cityNames().filter(function (name) {
            return MMEditor.effectiveCityText(name);
        }).length;
        counts.textContent = withText + ' cit' + (withText !== 1 ? 'ies' : 'y') + ' with text'
            + (pending ? ' · ' + pending + ' unexported change' + (pending !== 1 ? 's' : '') : '');
    }

    function renderPreview(preview, text) {
        if (text.trim() && typeof marked !== 'undefined') {
            preview.innerHTML = marked.parse(text);
            preview.hidden = false;
        } else {
            preview.innerHTML = '';
            preview.hidden = true;
        }
    }

    function buildCard(name) {
        var card = document.createElement('section');
        card.className = 'city-card';

        var heading = document.createElement('h2');
        heading.className = 'city-card-title';
        heading.textContent = name;

        var meta = document.createElement('span');
        meta.className = 'city-card-meta';
        var posts = MMEditor.taggedCount('posts', name);
        var stories = MMEditor.taggedCount('stories', name);
        meta.textContent = ' ' + posts + ' post' + (posts !== 1 ? 's' : '')
            + ', ' + stories + ' stor' + (stories !== 1 ? 'ies' : 'y');
        heading.appendChild(meta);

        var pip = document.createElement('span');
        pip.className = 'city-card-pip';
        pip.title = 'Unexported change';
        pip.textContent = '●';
        heading.appendChild(pip);

        var textarea = document.createElement('textarea');
        textarea.placeholder = 'Write something about ' + name + '… (Markdown supported)';
        textarea.value = MMEditor.effectiveCityText(name);

        var preview = document.createElement('div');
        preview.className = 'city-text-preview city-text';

        function refresh() {
            pip.style.display = MMEditor.cityTextPending(name) ? 'inline' : 'none';
            renderPreview(preview, textarea.value);
        }

        var debounce = null;
        textarea.addEventListener('input', function () {
            MMEditor.setCityText(name, textarea.value);
            MMEditor.persist();
            renderCounts();
            pip.style.display = MMEditor.cityTextPending(name) ? 'inline' : 'none';
            clearTimeout(debounce);
            debounce = setTimeout(function () {
                renderPreview(preview, textarea.value);
            }, 200);
        });

        card.appendChild(heading);
        card.appendChild(textarea);
        card.appendChild(preview);
        refresh();
        return card;
    }

    function renderAll() {
        list.innerHTML = '';
        var names = MMEditor.cityNames();
        if (!names.length) {
            var empty = document.createElement('p');
            empty.className = 'editor-intro';
            empty.textContent = 'No cities yet — tag some posts or stories first.';
            list.appendChild(empty);
            return;
        }
        names.forEach(function (name) {
            list.appendChild(buildCard(name));
        });
    }

    document.getElementById('exportTags').addEventListener('click', function () {
        MMEditor.download();
    });

    document.getElementById('clearLocal').addEventListener('click', function () {
        if (!confirm('Discard all unexported editing changes in this browser?')) {
            return;
        }
        MMEditor.clearOverlay();
        renderAll();
        renderCounts();
    });

    renderAll();
    renderCounts();
});
