/* ============================================
   Прощай, Вестфалия — Main JS
   Progressive enhancement only
   ============================================ */

(function () {
  'use strict';

  // --- Back to Top Button ---
  const backToTop = document.querySelector('.back-to-top');
  if (backToTop) {
    window.addEventListener('scroll', function () {
      backToTop.classList.toggle('visible', window.scrollY > 400);
    }, { passive: true });

    backToTop.addEventListener('click', function (e) {
      e.preventDefault();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  // --- Share Button (Copy URL) ---
  document.querySelectorAll('.share-btn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      navigator.clipboard.writeText(window.location.href).then(function () {
        btn.textContent = 'Скопировано';
        btn.classList.add('copied');
        setTimeout(function () {
          btn.textContent = 'Поделиться ↗';
          btn.classList.remove('copied');
        }, 2000);
      });
    });
  });

  // --- TOC Sidebar Active Highlight ---
  const tocLinks = document.querySelectorAll('.toc-sidebar a');
  if (tocLinks.length > 0) {
    const headings = [];
    tocLinks.forEach(function (link) {
      const id = link.getAttribute('href');
      if (id && id.startsWith('#')) {
        const el = document.querySelector(id);
        if (el) headings.push({ el: el, link: link });
      }
    });

    function updateTocHighlight() {
      let current = null;
      for (var i = 0; i < headings.length; i++) {
        if (headings[i].el.getBoundingClientRect().top <= 100) {
          current = headings[i];
        }
      }
      tocLinks.forEach(function (l) { l.classList.remove('active'); });
      if (current) current.link.classList.add('active');
    }

    window.addEventListener('scroll', updateTocHighlight, { passive: true });
    updateTocHighlight();
  }

  // --- Search ---
  var searchInput = document.getElementById('search-input');
  var searchResults = document.getElementById('search-results');
  var searchIndex = null;
  var activeResult = -1;

  if (searchInput) {
    fetch('assets/search-index.json')
      .then(function (r) { return r.json(); })
      .then(function (data) { searchIndex = data; })
      .catch(function () {
        // Try relative path from search page
        fetch('../assets/search-index.json')
          .then(function (r) { return r.json(); })
          .then(function (data) { searchIndex = data; });
      });

    searchInput.addEventListener('input', function () {
      var query = searchInput.value.trim().toLowerCase();
      if (!searchIndex || query.length < 2) {
        searchResults.innerHTML = '';
        activeResult = -1;
        return;
      }

      var results = [];
      searchIndex.forEach(function (chapter) {
        chapter.sections.forEach(function (section) {
          var text = section.text.toLowerCase();
          var idx = text.indexOf(query);
          if (idx !== -1) {
            var start = Math.max(0, idx - 60);
            var end = Math.min(text.length, idx + query.length + 60);
            var excerpt = (start > 0 ? '…' : '') +
              section.text.substring(start, end) +
              (end < text.length ? '…' : '');
            results.push({
              chapter: chapter.chapter,
              title: chapter.title,
              section_title: section.heading,
              url: chapter.url,
              excerpt: excerpt,
              query: query
            });
          }
        });
      });

      if (results.length === 0) {
        searchResults.innerHTML = '<li class="search-empty">Ничего не найдено</li>';
        activeResult = -1;
        return;
      }

      // Limit to 20 results
      results = results.slice(0, 20);
      activeResult = -1;

      searchResults.innerHTML = results.map(function (r, i) {
        var highlighted = escapeHtml(r.excerpt).replace(
          new RegExp('(' + escapeRegex(r.query) + ')', 'gi'),
          '<mark>$1</mark>'
        );
        return '<li class="search-result" data-index="' + i + '">' +
          '<a href="' + r.url + '">' +
          '<div class="search-result-chapter">' + escapeHtml(r.chapter) + '</div>' +
          '<div class="search-result-title">' + escapeHtml(r.section_title || r.title) + '</div>' +
          '<div class="search-result-excerpt">' + highlighted + '</div>' +
          '</a></li>';
      }).join('');
    });

    // Keyboard navigation
    searchInput.addEventListener('keydown', function (e) {
      var items = searchResults.querySelectorAll('.search-result');
      if (items.length === 0) return;

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        activeResult = Math.min(activeResult + 1, items.length - 1);
        updateActiveResult(items);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        activeResult = Math.max(activeResult - 1, 0);
        updateActiveResult(items);
      } else if (e.key === 'Enter' && activeResult >= 0) {
        e.preventDefault();
        var link = items[activeResult].querySelector('a');
        if (link) window.location.href = link.href;
      }
    });
  }

  function updateActiveResult(items) {
    items.forEach(function (item) { item.classList.remove('active'); });
    if (activeResult >= 0 && items[activeResult]) {
      items[activeResult].classList.add('active');
      items[activeResult].scrollIntoView({ block: 'nearest' });
    }
  }

  function escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function escapeRegex(str) {
    return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

})();
