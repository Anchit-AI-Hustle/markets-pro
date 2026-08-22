"""Connecting a real broker account, and showing what is in it.

The page never holds a broker token. Everything here goes through
``/api/broker/link``, authenticated with the reader's own Supabase access
token; the relay on the other side is what holds the credential and what
enforces the caps. That division is the point of the design, not an
implementation detail: a token that can place trades has no business in a
static page that anyone can read the source of.

Which brokers appear is answered by the relay at runtime, from the credentials
the deployment actually holds. A broker nobody has configured renders no
button, for the same reason a disabled sign-in provider renders none.
"""

from __future__ import annotations

BROKER_CSS = """
.brokers{display:grid;gap:10px;margin:10px 0 4px}
.brokerrow{display:flex;align-items:center;justify-content:space-between;gap:14px;
  flex-wrap:wrap;padding:13px 15px;border:1px solid var(--line);
  border-radius:var(--radius);background:var(--panel);box-shadow:var(--elev-1);
  transition:transform .2s var(--ease),box-shadow .2s var(--ease)}
.brokerrow:hover{transform:translateY(-1px);box-shadow:var(--elev-2)}
.brokerrow .who{display:flex;flex-direction:column;gap:3px;min-width:0}
.brokerrow .nm{font-weight:600}
.brokerrow .sub{color:var(--muted);font-size:.78rem;line-height:1.45}
.brokerstate{font-size:.72rem;font-weight:700;text-transform:uppercase;
  letter-spacing:.06em;padding:3px 9px;border-radius:999px;white-space:nowrap}
.brokerstate.on{color:var(--pos);background:color-mix(in srgb,var(--pos) 15%,transparent)}
.brokerstate.off{color:var(--muted);background:var(--tag)}
.brokerstate.warn{color:var(--neg);background:color-mix(in srgb,var(--neg) 15%,transparent)}
.brokeract{display:flex;align-items:center;gap:8px}
.realbook{margin-top:14px}
.realbook h4{margin:16px 0 6px;font-size:.9rem}
.realbook .acctline{display:flex;justify-content:space-between;gap:12px;
  font-size:.8rem;color:var(--muted);margin-bottom:6px}
@media (prefers-reduced-motion:reduce){
  .brokerrow{transition:none}.brokerrow:hover{transform:none}
}
"""


BROKER_JS = """
(function () {
  var mount = document.querySelector('[data-brokers]');
  if (!mount) return;
  var API = ((window.__mpCfg || {}).api_base || '/markets-pro/api') + '/broker/link';

  function call(action, extra) {
    var body = {action: action};
    if (extra) { for (var k in extra) { if (extra.hasOwnProperty(k)) body[k] = extra[k]; } }
    var tokenPromise = window.__mpAuthToken
      ? window.__mpAuthToken() : Promise.resolve(null);
    return tokenPromise.then(function (token) {
      var headers = {'Content-Type': 'application/json'};
      if (token) headers['Authorization'] = 'Bearer ' + token;
      return fetch(API, {method: 'POST', headers: headers, body: JSON.stringify(body)});
    }).then(function (response) {
      return response.text().then(function (text) {
        var data = {};
        try { data = text ? JSON.parse(text) : {}; } catch (e) { data = {}; }
        if (!response.ok) throw new Error(data.message || ('HTTP ' + response.status));
        return data;
      });
    });
  }

  function note(text, kind) {
    var el = mount.querySelector('[data-brokernote]');
    if (!el) return;
    el.textContent = text || '';
    el.setAttribute('data-kind', kind || '');
  }

  function row(provider) {
    var wrap = document.createElement('div');
    wrap.className = 'brokerrow';
    var who = document.createElement('div');
    who.className = 'who';
    var name = document.createElement('span');
    name.className = 'nm';
    name.textContent = provider.label;
    var sub = document.createElement('span');
    sub.className = 'sub';
    who.appendChild(name);
    who.appendChild(sub);

    var act = document.createElement('div');
    act.className = 'brokeract';
    var state = document.createElement('span');
    state.className = 'brokerstate';
    act.appendChild(state);

    if (!provider.configured) {
      state.className += ' off';
      state.textContent = 'not set up';
      // Named explicitly: the fix is one environment variable, and a vague
      // "unavailable" sends the owner looking in the wrong place.
      sub.textContent = 'Add this broker\\u2019s API key to the deployment to offer it.';
    } else if (provider.linked && !provider.stale) {
      state.className += ' on';
      state.textContent = 'connected';
      sub.textContent = (provider.account ? provider.account + ' \\u00b7 ' : '') +
                        provider.note;
      var off = document.createElement('button');
      off.type = 'button';
      off.className = 'authbtn';
      off.textContent = 'Disconnect';
      off.addEventListener('click', function () {
        off.disabled = true;
        call('disconnect', {provider: provider.provider})
          .then(load).catch(function (e) { note(e.message, 'error'); off.disabled = false; });
      });
      act.appendChild(off);
    } else {
      var expired = provider.linked && provider.stale;
      state.className += expired ? ' warn' : ' off';
      state.textContent = expired ? 'expired' : 'not connected';
      sub.textContent = provider.note;
      var go = document.createElement('button');
      go.type = 'button';
      go.className = 'authbtn';
      go.textContent = expired ? 'Reconnect' : 'Connect';
      go.addEventListener('click', function () {
        if (window.__mpSignedIn && !window.__mpSignedIn()) {
          note('Sign in first \\u2014 a broker connection is stored against your account.',
               'error');
          if (window.__mpOpenSignIn) window.__mpOpenSignIn();
          return;
        }
        go.disabled = true;
        note('Opening ' + provider.label + '\\u2026', '');
        call('connect', {provider: provider.provider}).then(function (data) {
          // A full-page redirect to the broker's own domain. The reader types
          // their credentials there and nowhere else.
          location.href = data.url;
        }).catch(function (e) { note(e.message, 'error'); go.disabled = false; });
      });
      act.appendChild(go);
    }
    wrap.appendChild(who);
    wrap.appendChild(act);
    return wrap;
  }

  function money(value, currency) {
    var n = Number(value) || 0;
    return n.toLocaleString(currency === 'INR' ? 'en-IN' : 'en-US',
      {maximumFractionDigits: 0});
  }

  function renderBook(data) {
    var book = mount.querySelector('[data-realbook]');
    if (!book) return;
    book.textContent = '';
    (data.problems || []).forEach(function (problem) {
      var p = document.createElement('p');
      p.className = 'caption';
      p.textContent = problem.label + ': ' + problem.note;
      book.appendChild(p);
    });
    (data.accounts || []).forEach(function (account) {
      var h = document.createElement('h4');
      h.textContent = account.label + (account.account ? ' \\u00b7 ' + account.account : '');
      book.appendChild(h);
      var line = document.createElement('div');
      line.className = 'acctline';
      var left = document.createElement('span');
      left.textContent = account.holdings.length + ' holding' +
                         (account.holdings.length === 1 ? '' : 's');
      var right = document.createElement('span');
      var pnl = Number(account.pnl) || 0;
      right.textContent = money(account.value, account.currency) + ' ' + account.currency +
        ' \\u00b7 ' + (pnl >= 0 ? '+' : '') + money(pnl, account.currency);
      line.appendChild(left);
      line.appendChild(right);
      book.appendChild(line);
      if (!account.holdings.length) return;
      var table = document.createElement('table');
      table.className = 'tbl';
      table.innerHTML = '<thead><tr><th>Symbol</th><th class="num">Qty</th>' +
        '<th class="num">Avg</th><th class="num">Last</th><th class="num">Value</th>' +
        '<th class="num">P&amp;L</th></tr></thead>';
      var body = document.createElement('tbody');
      account.holdings.forEach(function (holding) {
        var tr = document.createElement('tr');
        // Every symbol opens its detail page, the same as everywhere else.
        var sym = '<a class="tickerlink" href="#stock/' + encodeURIComponent(holding.symbol) +
                  '" data-stock="' + holding.symbol + '">' + holding.symbol + '</a>';
        var p = Number(holding.pnl) || 0;
        tr.innerHTML = '<td>' + sym + '</td>' +
          '<td class="num">' + holding.quantity + '</td>' +
          '<td class="num">' + money(holding.average_price, holding.currency) + '</td>' +
          '<td class="num">' + money(holding.last_price, holding.currency) + '</td>' +
          '<td class="num">' + money(holding.value, holding.currency) + '</td>' +
          '<td class="num ' + (p >= 0 ? 'pos' : 'neg') + '">' +
          (p >= 0 ? '+' : '') + money(p, holding.currency) + '</td>';
        body.appendChild(tr);
      });
      table.appendChild(body);
      book.appendChild(table);
    });
  }

  function load() {
    return call('providers').then(function (data) {
      var list = mount.querySelector('[data-brokerlist]');
      list.textContent = '';
      (data.providers || []).forEach(function (p) { list.appendChild(row(p)); });
      note('');
      var anyLinked = (data.providers || []).some(function (p) {
        return p.linked && !p.stale;
      });
      if (anyLinked || (data.alpaca && data.alpaca.configured)) {
        return call('portfolio').then(renderBook).catch(function (e) {
          note(e.message, 'error');
        });
      }
      var book = mount.querySelector('[data-realbook]');
      if (book) book.textContent = '';
    }).catch(function (e) {
      note(e.message, 'error');
    });
  }

  // A returning OAuth redirect says what happened in the query string.
  var query = new URLSearchParams(location.search);
  if (query.get('status')) {
    var tab = document.querySelector('[data-tabbtn="setup"]');
    if (tab) tab.click();
    if (query.get('status') === 'linked') {
      note(query.get('broker') + ' connected.', 'ok');
    } else {
      note(query.get('message') || 'that connection did not complete', 'error');
    }
    history.replaceState(null, '', location.pathname);
  }
  load();
})();
"""


def broker_section() -> str:
    """The Settings-tab block. Filled by script from what the relay reports."""
    return """<h3 class="papersub">Your broker accounts</h3>
<p class="caption">Connect a real account to see your actual holdings beside the
paper book. You log in on your broker's own site &mdash; this app never sees your
password, PIN or TOTP, and never holds anything that could be read out of this
page. Indian brokers expire API access every morning by regulation, so a
connection lasts one trading day.</p>
<div class="brokers" data-brokers>
  <div data-brokerlist></div>
  <p class="msg" data-brokernote></p>
  <div class="realbook" data-realbook></div>
</div>"""
