"""Find any instrument, and keep the ones you care about.

Two gaps that read as one to a user. With 325 instruments there has to be a
way to reach a specific one without scrolling a table, and once you have
reached it there has to be a way to keep it. Before this the watchlist was a
fixed list chosen by the build: a reader could not add the stock they actually
own, which is the single most expected action in this category.

The search reuses the stock index the detail view already downloads rather
than shipping a second copy of it — the palette is free in bytes, and on a
page that is already 480 KB that matters.

The kept list rides the sync layer that settings and the paper book already
use, so a watchlist built on a laptop is there on a phone. Signed out it stays
in the browser, exactly like everything else.
"""

from __future__ import annotations

SEARCH_CSS = """
/* ---------------------------------------------------------------------------
   The finder. A command palette rather than a header input: at this width a
   permanent search box would crowd the masthead, and the shortcut is how
   people who use this daily will actually open it. The button stays for
   everyone else, because a shortcut nobody can see is not an affordance.
--------------------------------------------------------------------------- */
.findbtn{
  display:inline-flex;align-items:center;gap:8px;font:inherit;font-size:.8rem;
  color:var(--muted);background:var(--panel);border:1px solid var(--line);
  border-radius:999px;padding:6px 12px 6px 13px;cursor:pointer;
  box-shadow:var(--elev-1);
  transition:transform .18s var(--ease),border-color .18s var(--ease),
             color .18s var(--ease),box-shadow .18s var(--ease);
}
.findbtn:hover{transform:translateY(-1px);color:var(--ink);
  border-color:var(--accent);box-shadow:var(--elev-2)}
.findbtn kbd{
  font:inherit;font-size:.68rem;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  background:var(--tag);border:1px solid var(--line);border-bottom-width:2px;
  border-radius:4px;padding:1px 5px;color:var(--muted);
}
@media (max-width:520px){.findbtn kbd{display:none}}

dialog.finddlg{
  border:1px solid var(--line);border-radius:calc(var(--radius) * 1.5);
  background:var(--panel);color:var(--ink);padding:0;
  width:min(560px,calc(100vw - 24px));max-height:min(70vh,620px);
  margin-top:8vh;box-shadow:var(--elev-3);overflow:hidden;
}
dialog.finddlg::backdrop{background:rgba(10,12,16,.55);backdrop-filter:blur(3px)}
dialog.finddlg[open]{animation:findrise .26s var(--ease) both}
@keyframes findrise{
  from{opacity:0;transform:translateY(-10px) scale(.98)}
  to{opacity:1;transform:none}
}
.findbar{display:flex;align-items:center;gap:10px;padding:14px 16px;
  border-bottom:1px solid var(--line)}
.findbar input{
  flex:1;font:inherit;font-size:1rem;border:0;background:none;color:var(--ink);
  padding:2px 0;
}
.findbar input:focus{outline:none}
.findbar input::placeholder{color:var(--muted)}
.findcount{font-size:.72rem;color:var(--muted);white-space:nowrap;
  font-variant-numeric:tabular-nums}
.findlist{list-style:none;margin:0;padding:6px;overflow-y:auto;
  max-height:calc(70vh - 116px)}
.findrow{
  display:grid;grid-template-columns:1fr auto auto;gap:2px 12px;align-items:center;
  padding:9px 11px;border-radius:var(--radius);cursor:pointer;
}
.findrow:hover,.findrow[aria-selected="true"]{background:var(--tag)}
.findrow .sym{font-weight:700;font-size:.9rem}
.findrow .nm{grid-column:1;font-size:.76rem;color:var(--muted);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.findrow .px{font-size:.82rem;font-variant-numeric:tabular-nums;text-align:right}
.findrow .mv{font-size:.72rem;font-variant-numeric:tabular-nums;text-align:right;
  grid-column:2}
.findrow .star{
  grid-row:1 / span 2;font:inherit;font-size:1rem;line-height:1;background:none;
  border:0;cursor:pointer;color:var(--line);padding:6px;border-radius:50%;
  transition:color .16s var(--ease),transform .16s var(--ease);
}
.findrow .star:hover{transform:scale(1.15)}
.findrow .star[aria-pressed="true"]{color:var(--accent)}
.findempty{padding:26px 18px;text-align:center;color:var(--muted);font-size:.85rem}
.findfoot{display:flex;gap:14px;padding:9px 16px;border-top:1px solid var(--line);
  font-size:.7rem;color:var(--muted)}
.findfoot b{font-weight:600;color:var(--ink)}

/* The kept list, above the full watchlist. */
.kept{margin:0 0 18px}
.kepthead{display:flex;align-items:baseline;justify-content:space-between;gap:12px;
  margin-bottom:8px;flex-wrap:wrap}
.kepthead h3{margin:0;font-size:.95rem}
.keptgrid{display:grid;gap:8px;
  grid-template-columns:repeat(auto-fill,minmax(178px,1fr))}
.keptcard{
  display:grid;gap:2px;padding:11px 13px;border:1px solid var(--line);
  border-radius:var(--radius);background:var(--panel);box-shadow:var(--elev-1);
  cursor:pointer;position:relative;
  transition:transform .2s var(--ease),box-shadow .2s var(--ease);
}
.keptcard:hover{transform:translateY(-2px);box-shadow:var(--elev-2)}
.keptcard .sym{font-weight:700;font-size:.88rem}
.keptcard .nm{font-size:.72rem;color:var(--muted);overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.keptcard .px{font-size:.95rem;font-variant-numeric:tabular-nums;margin-top:3px}
.keptcard .drop{
  position:absolute;top:5px;right:6px;font:inherit;font-size:.85rem;line-height:1;
  background:none;border:0;color:var(--line);cursor:pointer;padding:3px 5px;
  border-radius:50%;
}
.keptcard:hover .drop{color:var(--muted)}
.keptcard .drop:hover{color:var(--neg);background:var(--tag)}
@media (prefers-reduced-motion:reduce){
  dialog.finddlg[open]{animation:none}
  .keptcard,.findbtn,.findrow .star{transition:none}
  .keptcard:hover,.findbtn:hover{transform:none}
}
"""


SEARCH_JS = """
(function () {
  var dlg = document.getElementById('find-dialog');
  if (!dlg || !window.__mpStocks) return;
  var input = dlg.querySelector('[data-findinput]');
  var list = dlg.querySelector('[data-findlist]');
  var count = dlg.querySelector('[data-findcount]');
  var KEY = 'markets-pro.watchlist.v1';
  var rows = [];        // flattened index, built once
  var shown = [];
  var cursor = 0;

  function kept() {
    try { return JSON.parse(localStorage.getItem(KEY)) || []; }
    catch (e) { return []; }
  }
  function setKept(list) {
    try { localStorage.setItem(KEY, JSON.stringify(list)); } catch (e) { /* full */ }
    if (window.__mpStateChanged) window.__mpStateChanged('watchlist');
    renderKept();
  }
  function toggle(key) {
    var list = kept();
    var at = list.indexOf(key);
    if (at >= 0) { list.splice(at, 1); } else { list.push(key); }
    setKept(list);
    return at < 0;
  }

  function build(stocks) {
    if (rows.length) return rows;
    Object.keys(stocks).forEach(function (key) {
      var s = stocks[key];
      rows.push({
        key: key, symbol: s.symbol || '', name: s.name || '',
        last: s.last, change: s.change_1d, currency: s.currency || '',
        hay: ((s.symbol || '') + ' ' + (s.name || '')).toLowerCase()
      });
    });
    rows.sort(function (a, b) { return a.symbol.localeCompare(b.symbol); });
    return rows;
  }

  function score(row, q) {
    var sym = row.symbol.toLowerCase();
    if (sym === q) return 0;                       // exact ticker first
    if (sym.indexOf(q) === 0) return 1;            // ticker prefix
    if (row.name.toLowerCase().indexOf(q) === 0) return 2;
    if (row.hay.indexOf(q) >= 0) return 3;
    return -1;
  }

  function money(row) {
    if (row.last == null || row.last === '') return '';
    return Number(row.last).toLocaleString(
      row.currency === 'INR' ? 'en-IN' : 'en-US', {maximumFractionDigits: 2});
  }
  function pct(v) {
    if (v == null || v === '') return '';
    var n = Number(v) * 100;
    return (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
  }

  function render() {
    list.textContent = '';
    var saved = kept();
    if (!shown.length) {
      var empty = document.createElement('li');
      empty.className = 'findempty';
      empty.textContent = input.value.trim()
        ? 'Nothing matches \\u201c' + input.value.trim() + '\\u201d.'
        : 'Type a company name or ticker.';
      list.appendChild(empty);
      count.textContent = '';
      return;
    }
    count.textContent = shown.length + ' of ' + rows.length;
    shown.forEach(function (row, i) {
      var li = document.createElement('li');
      li.className = 'findrow';
      li.setAttribute('role', 'option');
      li.setAttribute('aria-selected', i === cursor ? 'true' : 'false');
      li.innerHTML =
        '<span class="sym"></span>' +
        '<span class="px"></span>' +
        '<button type="button" class="star" aria-label="Keep in watchlist"></button>' +
        '<span class="nm"></span><span class="mv"></span>';
      // textContent throughout: a company name is data, not markup.
      li.querySelector('.sym').textContent = row.symbol;
      li.querySelector('.nm').textContent = row.name;
      li.querySelector('.px').textContent = money(row);
      var mv = li.querySelector('.mv');
      mv.textContent = pct(row.change);
      if (row.change != null && row.change !== '') {
        mv.className = 'mv ' + (Number(row.change) >= 0 ? 'pos' : 'neg');
      }
      var star = li.querySelector('.star');
      var on = saved.indexOf(row.key) >= 0;
      star.setAttribute('aria-pressed', on ? 'true' : 'false');
      star.textContent = on ? '\\u2605' : '\\u2606';
      star.addEventListener('click', function (event) {
        event.stopPropagation();
        var nowOn = toggle(row.key);
        star.setAttribute('aria-pressed', nowOn ? 'true' : 'false');
        star.textContent = nowOn ? '\\u2605' : '\\u2606';
      });
      li.addEventListener('click', function () { open(row.key); });
      list.appendChild(li);
    });
  }

  function search() {
    var q = input.value.trim().toLowerCase();
    if (!q) { shown = rows.slice(0, 12); cursor = 0; render(); return; }
    var hits = [];
    for (var i = 0; i < rows.length; i++) {
      var s = score(rows[i], q);
      if (s >= 0) hits.push([s, rows[i]]);
    }
    hits.sort(function (a, b) { return a[0] - b[0]; });
    shown = hits.slice(0, 40).map(function (h) { return h[1]; });
    cursor = 0;
    render();
  }

  function open(key) {
    close();
    location.hash = '#stock/' + key;
  }
  function show() {
    window.__mpStocks().then(function (stocks) {
      build(stocks);
      input.value = '';
      search();
      if (typeof dlg.showModal === 'function') { dlg.showModal(); } else { dlg.open = true; }
      input.focus();
    });
  }
  function close() {
    if (typeof dlg.close === 'function') { dlg.close(); } else { dlg.open = false; }
  }

  input.addEventListener('input', search);
  dlg.addEventListener('keydown', function (event) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (!shown.length) return;
      cursor = (cursor + (event.key === 'ArrowDown' ? 1 : -1) + shown.length) % shown.length;
      render();
      var active = list.children[cursor];
      if (active && active.scrollIntoView) active.scrollIntoView({block: 'nearest'});
    } else if (event.key === 'Enter') {
      event.preventDefault();
      if (shown[cursor]) open(shown[cursor].key);
    }
  });
  Array.prototype.forEach.call(document.querySelectorAll('[data-findopen]'), function (b) {
    b.addEventListener('click', show);
  });
  document.addEventListener('keydown', function (event) {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      dlg.open ? close() : show();
    }
    // "/" is the other convention people try, but not while they are typing.
    if (event.key === '/' && !dlg.open) {
      var tag = (event.target.tagName || '').toLowerCase();
      if (tag !== 'input' && tag !== 'textarea' && !event.target.isContentEditable) {
        event.preventDefault();
        show();
      }
    }
  });

  // ---- the kept list, rendered into the Watchlist tab ---------------------
  function renderKept() {
    var mount = document.querySelector('[data-kept]');
    if (!mount) return;
    var saved = kept();
    var grid = mount.querySelector('[data-keptgrid]');
    var note = mount.querySelector('[data-keptnote]');
    grid.textContent = '';
    if (!saved.length) {
      note.textContent = 'Nothing kept yet. Press \\u2318K or the Find button, '
        + 'then the star beside any company.';
      mount.querySelector('[data-keptcount]').textContent = '';
      return;
    }
    note.textContent = '';
    mount.querySelector('[data-keptcount]').textContent =
      saved.length + ' kept';
    window.__mpStocks().then(function (stocks) {
      grid.textContent = '';
      saved.forEach(function (key) {
        var s = stocks[key];
        var card = document.createElement('div');
        card.className = 'keptcard';
        card.setAttribute('data-stock', key);
        card.innerHTML = '<span class="sym"></span><span class="nm"></span>' +
          '<span class="px"></span>' +
          '<button type="button" class="drop" aria-label="Remove">\\u00d7</button>';
        card.querySelector('.sym').textContent = s ? s.symbol : key;
        card.querySelector('.nm').textContent = s ? s.name : 'not in this build';
        card.querySelector('.px').textContent = s ? money({
          last: s.last, currency: s.currency}) : '';
        card.querySelector('.drop').addEventListener('click', function (event) {
          event.stopPropagation();
          toggle(key);
        });
        grid.appendChild(card);
      });
    });
  }

  window.__mpRenderKept = renderKept;
  renderKept();
})();
"""


def find_button() -> str:
    """The visible half of the shortcut."""
    return ('<button type="button" class="findbtn" data-findopen '
            'aria-label="Find a company">Find <kbd>⌘K</kbd></button>')


def find_dialog() -> str:
    return """
<dialog class="finddlg" id="find-dialog" aria-label="Find a company">
  <div class="findbar">
    <span aria-hidden="true">&#128269;</span>
    <input data-findinput type="text" autocomplete="off" spellcheck="false"
           placeholder="Company name or ticker" aria-label="Company name or ticker">
    <span class="findcount" data-findcount></span>
  </div>
  <ul class="findlist" data-findlist role="listbox"></ul>
  <div class="findfoot">
    <span><b>&uarr;&darr;</b> move</span><span><b>&crarr;</b> open</span>
    <span><b>&#9734;</b> keep</span><span><b>esc</b> close</span>
  </div>
</dialog>"""


def kept_section() -> str:
    """The user's own list, above the full one the strategies read."""
    return """<div class="kept" data-kept>
  <div class="kepthead">
    <h3>Your watchlist</h3>
    <span class="sigmeta" data-keptcount></span>
  </div>
  <p class="caption" data-keptnote></p>
  <div class="keptgrid" data-keptgrid></div>
</div>"""
