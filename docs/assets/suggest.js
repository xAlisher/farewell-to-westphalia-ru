/* «Предложить улучшение» — выделение текста → popup → оверлей → GitHub issue.
   Прямое создание issue идёт через SUGGEST_API (микрофункция с токеном);
   если endpoint недоступен — фолбэк: предзаполненный черновик issue на GitHub. */
(function () {
  'use strict';

  var SUGGEST_API = window.SUGGEST_API ||
    'https://ftw-suggest.vercel.app/api/suggest';
  var REPO_NEW_ISSUE =
    'https://github.com/xAlisher/farewell-to-westphalia-ru/issues/new';
  var MIN_SEL = 10;
  var MAX_SEL = 1500;

  var css = [
    '.ftw-sg-pop{position:absolute;z-index:9998;background:#1a1a1f;color:#fff;',
    'border:1px solid #3a3a44;border-radius:8px;padding:7px 12px;font-size:14px;',
    'cursor:pointer;box-shadow:0 4px 14px rgba(0,0,0,.35);user-select:none;',
    'font-family:inherit;line-height:1.2;white-space:nowrap}',
    '.ftw-sg-pop:hover{background:#2a2a33}',
    '.ftw-sg-ov{position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.55);',
    'display:flex;align-items:center;justify-content:center;padding:16px}',
    '.ftw-sg-box{background:#fff;color:#1a1a1f;max-width:560px;width:100%;',
    'max-height:92vh;overflow-y:auto;border-radius:12px;padding:24px;',
    'box-shadow:0 12px 40px rgba(0,0,0,.4);font-family:inherit}',
    '@media (prefers-color-scheme:dark){.ftw-sg-box{background:#1e1e24;color:#e8e8ec}',
    '.ftw-sg-quote{background:#2a2a33!important;border-color:#4a4a55!important}',
    '.ftw-sg-box textarea,.ftw-sg-box input{background:#141419;color:#e8e8ec;border-color:#4a4a55!important}}',
    '.ftw-sg-box h3{margin:0 0 14px;font-size:20px}',
    '.ftw-sg-quote{border-left:3px solid #b8b8c4;background:#f4f4f7;padding:10px 14px;',
    'margin:0 0 14px;font-style:italic;font-size:14.5px;max-height:130px;overflow-y:auto;',
    'border-radius:0 6px 6px 0;white-space:pre-wrap}',
    '.ftw-sg-box label{display:block;font-size:13px;margin:0 0 4px;opacity:.75}',
    '.ftw-sg-box textarea{width:100%;min-height:110px;resize:vertical;padding:10px;',
    'border:1px solid #c8c8d0;border-radius:8px;font:inherit;font-size:15px;box-sizing:border-box;margin-bottom:12px}',
    '.ftw-sg-box input[type=email]{width:100%;padding:9px 10px;border:1px solid #c8c8d0;',
    'border-radius:8px;font:inherit;font-size:15px;box-sizing:border-box;margin-bottom:16px}',
    '.ftw-sg-row{display:flex;gap:10px;justify-content:flex-end;flex-wrap:wrap}',
    '.ftw-sg-btn{padding:9px 18px;border-radius:8px;border:1px solid transparent;',
    'font:inherit;font-size:15px;cursor:pointer}',
    '.ftw-sg-btn-pri{background:#1a1a1f;color:#fff}',
    '.ftw-sg-btn-pri:disabled{opacity:.5;cursor:default}',
    '.ftw-sg-btn-sec{background:transparent;border-color:#c8c8d0;color:inherit}',
    '.ftw-sg-ok{display:flex;flex-direction:column;gap:12px}',
    '.ftw-sg-ok a{word-break:break-all}',
    '.ftw-sg-err{color:#c0392b;font-size:14px;margin:0 0 10px}',
    '@media (max-width:600px){.ftw-sg-box{padding:18px;border-radius:10px}}'
  ].join('');

  var style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);

  var pop = null, overlay = null, savedSel = '', savedChunk = '';

  function removePop() {
    if (pop) { pop.remove(); pop = null; }
  }

  function getSelectionInfo() {
    var sel = window.getSelection();
    if (!sel || sel.isCollapsed || sel.rangeCount === 0) return null;
    var text = sel.toString().replace(/\s+/g, ' ').trim();
    if (text.length < MIN_SEL) return null;
    var node = sel.anchorNode;
    var el = node && (node.nodeType === 1 ? node : node.parentElement);
    if (!el) return null;
    if (!el.closest('.chapter-content, .footnotes, main')) return null;
    if (el.closest('.ftw-sg-ov, .ftw-sg-pop')) return null;
    var rect = sel.getRangeAt(0).getBoundingClientRect();
    var chunkEl = el.closest('[data-chunk]');
    return {
      text: text.slice(0, MAX_SEL),
      rect: rect,
      chunk: chunkEl ? chunkEl.getAttribute('data-chunk') : ''
    };
  }

  function showPop(info) {
    removePop();
    pop = document.createElement('div');
    pop.className = 'ftw-sg-pop';
    pop.textContent = '✍ Предложить улучшение';
    pop.style.top = (window.scrollY + info.rect.bottom + 8) + 'px';
    var left = window.scrollX + info.rect.left + info.rect.width / 2 - 90;
    pop.style.left = Math.max(8, Math.min(left, window.innerWidth - 200)) + 'px';
    pop.addEventListener('mousedown', function (e) { e.preventDefault(); });
    pop.addEventListener('click', function () {
      savedSel = info.text;
      savedChunk = info.chunk || '';
      removePop();
      openOverlay();
    });
    document.body.appendChild(pop);
  }

  document.addEventListener('mouseup', function () {
    setTimeout(function () {
      var info = getSelectionInfo();
      if (info) showPop(info); else removePop();
    }, 10);
  });
  // мобильные: выделение без mouseup
  document.addEventListener('selectionchange', function () {
    clearTimeout(window.__ftwSgT);
    window.__ftwSgT = setTimeout(function () {
      var info = getSelectionInfo();
      if (info && !overlay) showPop(info);
      else if (!info) removePop();
    }, 400);
  });

  function esc(s) {
    return s.replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function pageInfo() {
    var h1 = document.querySelector('h1');
    return {
      title: h1 ? h1.textContent.trim() : document.title,
      url: location.href.split('#')[0]
    };
  }

  function issuePayload(suggestion, email) {
    var p = pageInfo();
    var title = 'Предложение: ' + p.title.slice(0, 60) + ' — «' +
      savedSel.slice(0, 40) + (savedSel.length > 40 ? '…' : '') + '»';
    var body = '**Страница:** ' + p.url +
      (savedChunk ? '\n**Чанк:** `' + savedChunk + '`' : '') +
      '\n\n**Фрагмент:**\n\n> ' +
      savedSel.replace(/\n/g, '\n> ') + '\n\n**Предложение:**\n\n' + suggestion +
      (email ? '\n\n**Email:** ' + email : '') +
      '\n\n---\n_Отправлено через форму «Предложить улучшение» на сайте._';
    return { title: title, body: body };
  }

  function openOverlay() {
    closeOverlay();
    overlay = document.createElement('div');
    overlay.className = 'ftw-sg-ov';
    overlay.innerHTML =
      '<div class="ftw-sg-box" role="dialog" aria-modal="true">' +
      '<h3>Предложить улучшение</h3>' +
      '<div class="ftw-sg-quote">' + esc(savedSel) + '</div>' +
      '<div class="ftw-sg-err" style="display:none"></div>' +
      '<label>Ваше предложение</label>' +
      '<textarea placeholder="Как улучшить этот фрагмент перевода?"></textarea>' +
      '<label>Email (необязательно)</label>' +
      '<input type="email" placeholder="для ответа, если понадобится">' +
      '<div class="ftw-sg-row">' +
      '<button class="ftw-sg-btn ftw-sg-btn-sec" data-a="close">Отмена</button>' +
      '<button class="ftw-sg-btn ftw-sg-btn-pri" data-a="send">Отправить</button>' +
      '</div></div>';
    document.body.appendChild(overlay);
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) closeOverlay();
    });
    overlay.querySelector('[data-a=close]').addEventListener('click', closeOverlay);
    overlay.querySelector('[data-a=send]').addEventListener('click', submit);
    overlay.querySelector('textarea').focus();
    document.addEventListener('keydown', escClose);
  }

  function escClose(e) { if (e.key === 'Escape') closeOverlay(); }

  function closeOverlay() {
    if (overlay) { overlay.remove(); overlay = null; }
    document.removeEventListener('keydown', escClose);
  }

  function showError(msg) {
    var el = overlay && overlay.querySelector('.ftw-sg-err');
    if (el) { el.textContent = msg; el.style.display = 'block'; }
  }

  function submit() {
    var ta = overlay.querySelector('textarea');
    var em = overlay.querySelector('input[type=email]');
    var suggestion = ta.value.trim();
    if (!suggestion) { showError('Напишите, что улучшить.'); ta.focus(); return; }
    if (em.value && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(em.value.trim())) {
      showError('Похоже, в email опечатка.'); em.focus(); return;
    }
    var btn = overlay.querySelector('[data-a=send]');
    btn.disabled = true;
    btn.textContent = 'Отправка…';
    var payload = issuePayload(suggestion, em.value.trim());

    var ctrl = new AbortController();
    var t = setTimeout(function () { ctrl.abort(); }, 8000);
    fetch(SUGGEST_API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: payload.title, body: payload.body,
        page: pageInfo().url
      }),
      signal: ctrl.signal
    }).then(function (r) {
      clearTimeout(t);
      if (!r.ok) throw new Error('http ' + r.status);
      return r.json();
    }).then(function (d) {
      if (!d || !d.url) throw new Error('bad response');
      showSuccess(d.url, false);
    }).catch(function () {
      clearTimeout(t);
      // фолбэк: черновик issue на GitHub
      var u = REPO_NEW_ISSUE + '?labels=reader-suggestion&title=' +
        encodeURIComponent(payload.title) + '&body=' +
        encodeURIComponent(payload.body);
      window.open(u, '_blank', 'noopener');
      showSuccess(u, true);
    });
  }

  function showSuccess(url, isFallback) {
    var box = overlay.querySelector('.ftw-sg-box');
    box.innerHTML =
      '<h3>' + (isFallback ? 'Почти готово' : 'Issue создан') + '</h3>' +
      '<div class="ftw-sg-ok">' +
      (isFallback
        ? '<p>Мы открыли черновик issue на GitHub в соседней вкладке — ' +
          'проверьте текст и нажмите «Create». Понадобится аккаунт GitHub.</p>'
        : '<p>Спасибо! Ваше предложение сохранено:</p>') +
      '<a href="' + url + '" target="_blank" rel="noopener">' + url + '</a>' +
      '<div class="ftw-sg-row">' +
      '<button class="ftw-sg-btn ftw-sg-btn-sec" data-a="copy">Скопировать ссылку</button>' +
      '<button class="ftw-sg-btn ftw-sg-btn-pri" data-a="close">Закрыть</button>' +
      '</div></div>';
    box.querySelector('[data-a=copy]').addEventListener('click', function () {
      navigator.clipboard.writeText(url).then(function () {
        box.querySelector('[data-a=copy]').textContent = 'Скопировано ✓';
      });
    });
    box.querySelector('[data-a=close]').addEventListener('click', closeOverlay);
  }
})();
