"""Sign-in, and the state it makes portable.

Two constraints shaped everything here.

The first is the page's own Content-Security-Policy: ``script-src`` permits
inline script and nothing else, so no third-party bundle can be loaded. That
rules out ``supabase-js``. What it does not rule out is Supabase itself, whose
auth surface is an ordinary REST API; this module speaks to it with ``fetch``
and a publishable key, which is the same thing the library would have done
with several hundred kilobytes more ceremony. The one policy change required
is an entry in ``connect-src`` for the project origin.

The second is that signing in has to *earn* itself. An account that only
proves who you are is a toll gate. This one moves the two documents that took
the reader effort to build -- their capital and cap settings, and their paper
book -- off a single browser and onto their account, so the phone shows the
same portfolio as the laptop. Everything continues to work signed out, exactly
as before, because most readers will never sign in and the app is not entitled
to punish them for it.

Which sign-in methods appear is decided at runtime, not at build time. The
page asks ``/auth/v1/settings`` -- a public endpoint -- which reports the
providers the project actually has enabled. Enabling Google in the Supabase
dashboard therefore makes the Google button appear on the next page load with
no redeploy, and a provider that is *not* configured never renders a button
that would fail when pressed.
"""

from __future__ import annotations

import json

#: Keys whose contents follow the reader between devices once signed in. The
#: watchlist is deliberately absent: it is rendered from the signal snapshot
#: rather than stored, so there is nothing device-specific to carry.
SYNCED_DOCUMENTS = ("settings", "paper")


AUTH_CSS = """
/* ---------------------------------------------------------------------------
   Sign-in. The header slot is a single control that swaps between "Sign in"
   and an account chip; the dialog is a native <dialog>, which brings focus
   trapping, Escape-to-close and inertness of the page behind it without a
   line of script. Its motion matches the rest of the app: a short rise on
   the same easing curve, and nothing at all under reduced-motion.
--------------------------------------------------------------------------- */
.authslot{position:absolute;top:0;right:0;display:flex;align-items:center;gap:8px}
@media (max-width:640px){.authslot{position:static;margin-top:10px;justify-content:flex-end}}
header{position:relative}

.authbtn{
  font:inherit;font-size:.82rem;font-weight:600;color:var(--ink);
  background:var(--panel);border:1px solid var(--line);border-radius:999px;
  padding:7px 15px;cursor:pointer;box-shadow:var(--elev-1);
  transition:transform .2s var(--ease),box-shadow .2s var(--ease),
             border-color .2s var(--ease);
}
.authbtn:hover{transform:translateY(-1px);box-shadow:var(--elev-2);
  border-color:var(--accent)}
.authbtn:active{transform:translateY(0)}
.authbtn:focus-visible{outline:2px solid var(--accent);outline-offset:2px}

.authchip{display:flex;align-items:center;gap:8px;background:var(--panel);
  border:1px solid var(--line);border-radius:999px;padding:4px 5px 4px 4px;
  box-shadow:var(--elev-1)}
.authchip .avatar{
  width:26px;height:26px;border-radius:50%;display:grid;place-items:center;
  font-size:.72rem;font-weight:700;color:#fff;letter-spacing:.02em;
  background:linear-gradient(135deg,var(--accent),color-mix(in srgb,var(--accent) 55%,#000));
  box-shadow:inset 0 1px 0 rgba(255,255,255,.25);
}
.authchip .who{font-size:.76rem;color:var(--muted);max-width:15ch;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
@media (max-width:520px){.authchip .who{display:none}}
.authchip button{font:inherit;font-size:.74rem;font-weight:600;cursor:pointer;
  color:var(--muted);background:none;border:0;padding:4px 8px;border-radius:999px}
.authchip button:hover{color:var(--ink);background:var(--tag)}

/* The sync pip: a quiet, honest indicator. Solid when the account copy is
   current, spinning while a write is in flight, red when the last attempt
   failed -- because a sync that silently stopped working is worse than one
   that never started. */
.syncpip{width:7px;height:7px;border-radius:50%;background:var(--pos);
  flex:none;transition:background .3s var(--ease)}
.syncpip[data-state="busy"]{background:var(--muted);animation:syncspin 1s linear infinite}
.syncpip[data-state="error"]{background:var(--neg)}
@keyframes syncspin{50%{opacity:.25}}

dialog.authdlg{
  border:1px solid var(--line);border-radius:calc(var(--radius) * 1.6);
  background:var(--panel);color:var(--ink);padding:0;width:min(420px,calc(100vw - 32px));
  box-shadow:var(--elev-3);
}
dialog.authdlg::backdrop{background:rgba(10,12,16,.55);backdrop-filter:blur(3px)}
dialog.authdlg[open]{animation:authrise .32s var(--ease) both}
@keyframes authrise{
  from{opacity:0;transform:translateY(14px) scale(.97)}
  to{opacity:1;transform:none}
}
.authdlg .body{padding:26px 26px 22px}
.authdlg h2{margin:0 0 4px;font-size:1.15rem;letter-spacing:-.01em}
.authdlg .lede{margin:0 0 18px;color:var(--muted);font-size:.85rem;line-height:1.5}
.authdlg label{display:block;font-size:.76rem;font-weight:600;color:var(--muted);
  margin:0 0 6px}
.authdlg input{
  font:inherit;width:100%;padding:11px 13px;border-radius:var(--radius);
  border:1px solid var(--line);background:var(--bg);color:var(--ink);
  transition:border-color .18s var(--ease),box-shadow .18s var(--ease);
}
.authdlg input:focus{outline:none;border-color:var(--accent);
  box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 22%,transparent)}
.authdlg input[data-code]{text-align:center;letter-spacing:.5em;font-size:1.3rem;
  font-weight:600;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  padding-left:.5em}
.authdlg .go{
  font:inherit;font-weight:600;width:100%;margin-top:14px;padding:12px;
  border-radius:var(--radius);border:0;cursor:pointer;color:#fff;
  background:linear-gradient(135deg,var(--accent),
             color-mix(in srgb,var(--accent) 60%,#000));
  box-shadow:var(--elev-1);
  transition:transform .18s var(--ease),box-shadow .18s var(--ease),filter .18s;
}
.authdlg .go:hover:not(:disabled){transform:translateY(-1px);box-shadow:var(--elev-2)}
.authdlg .go:disabled{opacity:.55;cursor:progress}
.authdlg .alt{
  font:inherit;font-size:.85rem;font-weight:600;width:100%;margin-top:9px;
  padding:11px;border-radius:var(--radius);border:1px solid var(--line);
  background:var(--bg);color:var(--ink);cursor:pointer;
  display:flex;align-items:center;justify-content:center;gap:9px;
  transition:transform .18s var(--ease),border-color .18s var(--ease),
             box-shadow .18s var(--ease);
}
.authdlg .alt:hover{transform:translateY(-1px);border-color:var(--accent);
  box-shadow:var(--elev-1)}
.authdlg .sep{display:flex;align-items:center;gap:10px;margin:18px 0 4px;
  color:var(--muted);font-size:.72rem;text-transform:uppercase;letter-spacing:.08em}
.authdlg .sep::before,.authdlg .sep::after{content:"";flex:1;height:1px;
  background:var(--line)}
.authdlg .msg{margin:12px 0 0;font-size:.8rem;line-height:1.5;min-height:1.2em}
.authdlg .msg[data-kind="error"]{color:var(--neg)}
.authdlg .msg[data-kind="ok"]{color:var(--pos)}
.authdlg .fine{margin:16px 0 0;color:var(--muted);font-size:.72rem;line-height:1.5}
.authdlg .back{font:inherit;font-size:.76rem;color:var(--muted);background:none;
  border:0;padding:0;margin-top:14px;cursor:pointer;text-decoration:underline}
.authdlg .back:hover{color:var(--ink)}
.authdlg .close{position:absolute;top:12px;right:12px;font:inherit;font-size:1.1rem;
  line-height:1;color:var(--muted);background:none;border:0;cursor:pointer;
  padding:6px;border-radius:50%}
.authdlg .close:hover{color:var(--ink);background:var(--tag)}
.authpane[hidden]{display:none}
/* The hidden attribute is a user-agent rule of display:none, which any class
   here that sets its own display silently outranks. Script toggles .hidden on
   the provider buttons and their separator, so each needs saying explicitly --
   without this a reader is offered a Google button for a provider the project
   has not enabled, and pressing it can only fail. */
.authdlg .alt[hidden],.authdlg .sep[hidden]{display:none}

.acct{display:grid;gap:12px}
.acct .row{display:flex;align-items:center;justify-content:space-between;gap:14px;
  flex-wrap:wrap}
.acct .val{font-weight:600}
.acct .muted{color:var(--muted);font-size:.82rem;line-height:1.55}
/* A grid stretches its items. Left alone the button becomes a full-width bar
   that reads as a banner rather than something to press. */
.acct .authbtn{justify-self:start}

@media (prefers-reduced-motion:reduce){
  dialog.authdlg[open]{animation:none}
  .authbtn,.authdlg .go,.authdlg .alt{transition:none}
  .authbtn:hover,.authdlg .go:hover,.authdlg .alt:hover{transform:none}
  .syncpip[data-state="busy"]{animation:none}
}
"""


AUTH_JS = """
(function () {
  var node = document.getElementById('auth-data');
  if (!node) return;
  var cfg;
  try { cfg = JSON.parse(node.textContent); } catch (e) { return; }
  if (!cfg.url || !cfg.key) return;

  var AUTH = cfg.url + '/auth/v1';
  var REST = cfg.url + '/rest/v1';
  var SESSION_KEY = 'markets-pro.session.v1';
  var SYNC_KEY = 'markets-pro.sync.v1';
  // Local store -> the row key it occupies on the account. Order is the order
  // they are adopted in, which matters only in that settings should land
  // before the paper book that spends against it.
  var DOCS = [
    {key: 'settings', store: 'markets-pro.settings.v1'},
    {key: 'paper', store: 'markets-pro.paper.v1'}
  ];

  var session = null;
  var providers = {email: true};
  var slot = document.querySelector('[data-authslot]');
  var dlg = document.getElementById('auth-dialog');
  var pending = null;   // {channel: 'email'|'phone', address: string}
  var pushTimer = null;

  function ls(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
  function lset(key, value) {
    try { localStorage.setItem(key, value); return true; } catch (e) { return false; }
  }
  function readJSON(key, fallback) {
    var raw = ls(key);
    if (!raw) return fallback;
    try { return JSON.parse(raw); } catch (e) { return fallback; }
  }

  // ---- transport -----------------------------------------------------------
  // Supabase reports failures as JSON with the human-readable text under one of
  // several field names depending on which subsystem rejected the call, so the
  // reader is shown whichever one is present rather than a status code.
  function unwrap(response) {
    return response.text().then(function (text) {
      var body = {};
      if (text) { try { body = JSON.parse(text); } catch (e) { body = {}; } }
      if (!response.ok) {
        var message = body.msg || body.error_description || body.message ||
                      body.error || ('request failed (' + response.status + ')');
        var error = new Error(message);
        error.status = response.status;
        throw error;
      }
      return body;
    });
  }
  function headers(token, extra) {
    var h = {'apikey': cfg.key, 'Content-Type': 'application/json'};
    if (token) h['Authorization'] = 'Bearer ' + token;
    if (extra) { for (var k in extra) { if (extra.hasOwnProperty(k)) h[k] = extra[k]; } }
    return h;
  }
  function post(path, body, token) {
    return fetch(AUTH + path, {
      method: 'POST', headers: headers(token), body: JSON.stringify(body)
    }).then(unwrap);
  }

  // ---- session -------------------------------------------------------------
  function store(raw) {
    if (!raw || !raw.access_token) return null;
    var user = raw.user || {};
    var expiresAt = raw.expires_at
      ? Number(raw.expires_at) * 1000
      : Date.now() + (Number(raw.expires_in || 3600) * 1000);
    session = {
      access_token: raw.access_token,
      refresh_token: raw.refresh_token || (session && session.refresh_token) || '',
      expires_at: expiresAt,
      user: {
        id: user.id || (session && session.user && session.user.id) || '',
        email: user.email || (session && session.user && session.user.email) || '',
        phone: user.phone || (session && session.user && session.user.phone) || ''
      }
    };
    lset(SESSION_KEY, JSON.stringify(session));
    return session;
  }
  function forget() {
    session = null;
    try { localStorage.removeItem(SESSION_KEY); } catch (e) { /* blocked */ }
  }

  // A refresh token is single-use: two callers racing on an expired session
  // would have one of them redeem a token the other already spent, and the
  // loser would be signed out for no reason. One shared promise avoids that.
  var refreshing = null;
  function refresh() {
    if (refreshing) return refreshing;
    if (!session || !session.refresh_token) return Promise.resolve(null);
    refreshing = post('/token?grant_type=refresh_token',
                      {refresh_token: session.refresh_token})
      .then(function (raw) { return store(raw) ? session.access_token : null; })
      .catch(function () { forget(); paint(); return null; })
      .then(function (token) { refreshing = null; return token; });
    return refreshing;
  }
  function token() {
    if (!session) return Promise.resolve(null);
    // A minute of headroom: a token that expires mid-flight fails the request
    // it was attached to, and the reader sees a sync error for a clock edge.
    if (session.expires_at - Date.now() > 60000) {
      return Promise.resolve(session.access_token);
    }
    return refresh();
  }

  // ---- state sync ----------------------------------------------------------
  // What the account holds is a mirror, not the master: the app reads and
  // writes localStorage exactly as it always has, and this carries copies
  // across. That keeps every existing module working untouched and keeps the
  // signed-out experience identical.
  function pip(state) {
    var el = slot && slot.querySelector('[data-syncpip]');
    if (el) {
      el.setAttribute('data-state', state);
      el.title = state === 'error' ? 'Last sync failed'
               : state === 'busy' ? 'Syncing...'
               : 'Saved to your account';
    }
  }
  function syncedAt() { return readJSON(SYNC_KEY, {}); }
  function markSynced(key, when) {
    var marks = syncedAt();
    marks[key] = when || new Date().toISOString();
    lset(SYNC_KEY, JSON.stringify(marks));
  }

  function pull(access) {
    return fetch(REST + '/mp_state?select=key,value,updated_at',
                 {headers: headers(access)}).then(unwrap);
  }
  function upload(access, rows) {
    if (!rows.length) return Promise.resolve();
    return fetch(REST + '/mp_state?on_conflict=user_id,key', {
      method: 'POST',
      headers: headers(access, {'Prefer': 'resolution=merge-duplicates,return=minimal'}),
      body: JSON.stringify(rows)
    }).then(unwrap);
  }

  function localRows() {
    var rows = [];
    DOCS.forEach(function (doc) {
      var raw = ls(doc.store);
      if (!raw) return;
      var value;
      try { value = JSON.parse(raw); } catch (e) { return; }
      rows.push({user_id: session.user.id, key: doc.key, value: value});
    });
    return rows;
  }

  // Reconcile once, at sign-in. The rule is deliberately dull: adopt the
  // account's copy when it is newer than the last copy this browser is known
  // to have sent, otherwise send this browser's. A device that has never
  // synced has no claim to be newer, so a fresh phone inherits rather than
  // overwrites -- which is the failure that would actually cost someone their
  // paper book.
  function reconcile(access) {
    return pull(access).then(function (rows) {
      var cloud = {};
      (rows || []).forEach(function (row) { cloud[row.key] = row; });
      var marks = syncedAt();
      var adopted = [];
      DOCS.forEach(function (doc) {
        var remote = cloud[doc.key];
        if (!remote) return;
        var mine = marks[doc.key];
        if (mine && remote.updated_at <= mine) return;
        if (lset(doc.store, JSON.stringify(remote.value))) {
          markSynced(doc.key, remote.updated_at);
          adopted.push(doc.key);
        }
      });
      if (adopted.length) return adopted;
      return upload(access, localRows()).then(function () {
        DOCS.forEach(function (doc) { if (ls(doc.store)) markSynced(doc.key); });
        return [];
      });
    });
  }

  function push(options) {
    if (!session) return Promise.resolve();
    pip('busy');
    return token().then(function (access) {
      if (!access) return;
      var rows = localRows();
      if (!rows.length) { pip('ok'); return; }
      // keepalive lets the last write survive the page being closed, which is
      // exactly when an unsaved paper trade would otherwise be lost.
      if (options && options.beacon) {
        return fetch(REST + '/mp_state?on_conflict=user_id,key', {
          method: 'POST', keepalive: true,
          headers: headers(access, {'Prefer': 'resolution=merge-duplicates,return=minimal'}),
          body: JSON.stringify(rows)
        });
      }
      return upload(access, rows).then(function () {
        rows.forEach(function (row) { markSynced(row.key); });
        pip('ok');
        renderAccountPanel();
      });
    }).catch(function () { pip('error'); });
  }

  // Called by the settings and paper modules the moment they write. Debounced
  // because dragging a capital slider writes on every input event and each one
  // does not deserve its own round trip.
  window.__mpStateChanged = function () {
    if (!session) return;
    pip('busy');
    if (pushTimer) clearTimeout(pushTimer);
    pushTimer = setTimeout(function () { pushTimer = null; push(); }, 1200);
  };
  window.addEventListener('pagehide', function () {
    if (pushTimer) { clearTimeout(pushTimer); pushTimer = null; push({beacon: true}); }
  });

  // ---- header ----------------------------------------------------------------
  function initials(who) {
    var name = who.email || who.phone || '?';
    return name.replace(/^[+]/, '').slice(0, 2).toUpperCase();
  }
  function paint() {
    if (!slot) return;
    slot.textContent = '';
    if (!session) {
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'authbtn';
      button.textContent = 'Sign in';
      button.addEventListener('click', function () { open(); });
      slot.appendChild(button);
      renderAccountPanel();
      return;
    }
    var chip = document.createElement('div');
    chip.className = 'authchip';
    var avatar = document.createElement('span');
    avatar.className = 'avatar';
    avatar.textContent = initials(session.user);
    var who = document.createElement('span');
    who.className = 'who';
    who.textContent = session.user.email || session.user.phone || 'Signed in';
    var pipEl = document.createElement('span');
    pipEl.className = 'syncpip';
    pipEl.setAttribute('data-syncpip', '');
    pipEl.setAttribute('data-state', 'ok');
    pipEl.title = 'Saved to your account';
    var out = document.createElement('button');
    out.type = 'button';
    out.textContent = 'Sign out';
    out.addEventListener('click', signOut);
    chip.appendChild(avatar);
    chip.appendChild(who);
    chip.appendChild(pipEl);
    chip.appendChild(out);
    slot.appendChild(chip);
    renderAccountPanel();
  }

  function renderAccountPanel() {
    var panel = document.querySelector('[data-authacct]');
    if (!panel) return;
    if (!session) {
      panel.innerHTML =
        '<p class="muted">You are not signed in. Everything works without an ' +
        'account &mdash; your amounts and paper trades live in this browser ' +
        'alone. Signing in copies those two documents to your account so a ' +
        'second device opens on the same setup.</p>';
      var cta = document.createElement('button');
      cta.type = 'button';
      cta.className = 'authbtn';
      cta.textContent = 'Sign in';
      cta.addEventListener('click', function () { open(); });
      panel.appendChild(cta);
      return;
    }
    var marks = syncedAt();
    var last = DOCS.map(function (d) { return marks[d.key]; })
                   .filter(Boolean).sort().pop();
    panel.innerHTML =
      '<div class="row"><span class="muted">Signed in as</span>' +
      '<span class="val"></span></div>' +
      '<div class="row"><span class="muted">Synced to your account</span>' +
      '<span class="val">' + (DOCS.length) + ' documents' +
      (last ? ' &middot; last ' + new Date(last).toLocaleString() : '') +
      '</span></div>' +
      '<p class="muted">Your capital and cap settings and your paper book are ' +
      'copied to your account whenever they change. Nothing else leaves this ' +
      'browser &mdash; there is no broker connection behind this sign-in, and ' +
      'no real money can move through it.</p>';
    // textContent, not markup: an address is user-supplied and has no business
    // being parsed as HTML.
    panel.querySelector('.val').textContent =
      session.user.email || session.user.phone || session.user.id;
    var now = document.createElement('button');
    now.type = 'button';
    now.className = 'authbtn';
    now.textContent = 'Sync now';
    now.addEventListener('click', function () {
      now.disabled = true;
      push().then(function () { now.disabled = false; renderAccountPanel(); });
    });
    panel.appendChild(now);
  }

  // ---- dialog ----------------------------------------------------------------
  function pane(name) {
    Array.prototype.forEach.call(dlg.querySelectorAll('.authpane'), function (p) {
      p.hidden = p.getAttribute('data-pane') !== name;
    });
  }
  function say(text, kind) {
    var msg = dlg.querySelector('[data-authmsg]');
    if (!msg) return;
    msg.textContent = text || '';
    msg.setAttribute('data-kind', kind || '');
  }
  function open() {
    if (!dlg) return;
    say('');
    pane('choose');
    if (typeof dlg.showModal === 'function') { dlg.showModal(); } else { dlg.open = true; }
    var first = dlg.querySelector('.authpane:not([hidden]) input');
    if (first) first.focus();
  }
  function close() {
    if (!dlg) return;
    if (typeof dlg.close === 'function') { dlg.close(); } else { dlg.open = false; }
  }

  function busy(on) {
    Array.prototype.forEach.call(dlg.querySelectorAll('button'), function (b) {
      if (b.classList.contains('close')) return;
      b.disabled = !!on;
    });
  }

  function sendCode(channel, address) {
    var body = channel === 'phone' ? {phone: address} : {email: address};
    body.create_user = true;
    busy(true);
    say('Sending a code to ' + address + '...', '');
    post('/otp', body).then(function () {
      pending = {channel: channel, address: address};
      busy(false);
      pane('code');
      say('Code sent to ' + address + '. It expires in 15 minutes.', 'ok');
      var input = dlg.querySelector('[data-code]');
      if (input) { input.value = ''; input.focus(); }
    }).catch(function (error) {
      busy(false);
      say(error.message, 'error');
    });
  }

  function verify(code) {
    if (!pending) return;
    var body = pending.channel === 'phone'
      ? {phone: pending.address, token: code, type: 'sms'}
      : {email: pending.address, token: code, type: 'email'};
    busy(true);
    say('Checking...', '');
    post('/verify', body).then(function (raw) {
      if (!store(raw)) throw new Error('no session returned');
      busy(false);
      return afterSignIn();
    }).catch(function (error) {
      busy(false);
      say(error.message, 'error');
    });
  }

  function google() {
    // A full-page redirect, not a popup: a popup here would be blocked as
    // often as not, and the return trip carries the session in the URL
    // fragment which this module picks up on the next load.
    var back = location.origin + location.pathname;
    location.href = AUTH + '/authorize?provider=google&redirect_to=' +
                    encodeURIComponent(back);
  }

  function afterSignIn() {
    say('Signed in. Checking your saved setup...', 'ok');
    paint();
    return token().then(function (access) {
      if (!access) return;
      return reconcile(access);
    }).then(function (adopted) {
      if (adopted && adopted.length) {
        // The settings and paper modules read localStorage once, at load. A
        // reload is the honest way to show the copy that was just adopted;
        // repainting each module from here would mean this file quietly owning
        // the render path of two others.
        say('Restoring your saved setup...', 'ok');
        setTimeout(function () { location.reload(); }, 700);
        return;
      }
      pip('ok');
      close();
    }).catch(function (error) {
      say('Signed in, but your saved setup could not be loaded: ' +
          error.message, 'error');
      pip('error');
    });
  }

  function signOut() {
    var had = session;
    token().then(function (access) {
      if (!access) return null;
      return post('/logout', {}, access).catch(function () { return null; });
    }).then(function () {
      forget();
      // The synced copies stay on the account and the local copies stay in
      // this browser. Wiping either on sign-out would be a surprising way to
      // lose a portfolio, and this button does not deserve that power.
      paint();
    });
    if (!had) paint();
  }

  // ---- boot ------------------------------------------------------------------
  // An OAuth return arrives as a URL fragment. It is consumed and stripped
  // before anything else runs, so a refresh cannot replay it and the tokens
  // never sit in a URL the reader might copy.
  function adoptHash() {
    if (!location.hash || location.hash.length < 2) return false;
    var params = new URLSearchParams(location.hash.slice(1));
    var failed = params.get('error_description') || params.get('error');
    var access = params.get('access_token');
    if (!failed && !access) return false;
    history.replaceState(null, '', location.pathname + location.search);
    if (failed) {
      open();
      say(failed.replace(/[+]/g, ' '), 'error');
      return false;
    }
    store({
      access_token: access,
      refresh_token: params.get('refresh_token'),
      expires_in: params.get('expires_in'),
      expires_at: params.get('expires_at')
    });
    return true;
  }

  function loadProviders() {
    return fetch(AUTH + '/settings', {headers: {'apikey': cfg.key}})
      .then(unwrap)
      .then(function (settings) { providers = settings.external || providers; })
      .catch(function () { /* keep the email default; it is always enabled */ });
  }

  function wire() {
    if (!dlg) return;
    dlg.querySelector('[data-authclose]').addEventListener('click', close);
    dlg.querySelector('[data-authgoogle]').addEventListener('click', google);
    dlg.querySelector('[data-authphonego]').addEventListener('click', function () {
      pane('phone');
      say('');
      var input = dlg.querySelector('[data-phone]');
      if (input) input.focus();
    });
    dlg.querySelector('[data-authemail]').addEventListener('submit', function (event) {
      event.preventDefault();
      var value = (dlg.querySelector('[data-email]').value || '').trim();
      if (!value) { say('Enter your email address.', 'error'); return; }
      sendCode('email', value);
    });
    dlg.querySelector('[data-authphone]').addEventListener('submit', function (event) {
      event.preventDefault();
      var value = (dlg.querySelector('[data-phone]').value || '').trim().replace(/\\s+/g, '');
      if (!/^[+][1-9]\\d{7,14}$/.test(value)) {
        say('Enter the number in international form, like +919876543210.', 'error');
        return;
      }
      sendCode('phone', value);
    });
    dlg.querySelector('[data-authcode]').addEventListener('submit', function (event) {
      event.preventDefault();
      var code = (dlg.querySelector('[data-code]').value || '').replace(/\\D/g, '');
      if (code.length < 6) { say('Enter the 6-digit code.', 'error'); return; }
      verify(code);
    });
    Array.prototype.forEach.call(dlg.querySelectorAll('[data-authback]'), function (b) {
      b.addEventListener('click', function () { pane('choose'); say(''); });
    });
    dlg.querySelector('[data-authresend]').addEventListener('click', function () {
      if (pending) sendCode(pending.channel, pending.address);
    });
  }

  function applyProviders() {
    if (!dlg) return;
    var g = dlg.querySelector('[data-authgoogle]');
    var p = dlg.querySelector('[data-authphonego]');
    if (g) g.hidden = !providers.google;
    if (p) p.hidden = !providers.phone;
    var sep = dlg.querySelector('[data-authsep]');
    if (sep) sep.hidden = !(providers.google || providers.phone);
  }

  session = readJSON(SESSION_KEY, null);
  if (session && !session.access_token) session = null;
  var returned = adoptHash();
  wire();
  paint();
  loadProviders().then(applyProviders);

  if (session) {
    token().then(function (access) {
      if (!access) { paint(); return; }
      // A redirect return has no user attached to the fragment, so identity
      // is fetched once before the chip claims to know who is signed in.
      var identify = (returned || !session.user.id)
        ? fetch(AUTH + '/user', {headers: headers(access)}).then(unwrap)
            .then(function (user) { store({access_token: session.access_token,
                                           expires_at: session.expires_at / 1000,
                                           user: user}); })
        : Promise.resolve();
      return identify.then(function () {
        paint();
        return reconcile(access);
      }).then(function (adopted) {
        if (returned && adopted && adopted.length) { location.reload(); return; }
        pip('ok');
        renderAccountPanel();
      });
    }).catch(function () { pip('error'); });
  }
})();
"""


def auth_blob(supabase: dict | None) -> str:
    """The ``<script type="application/json">`` the module reads its origin from.

    Empty when no project is configured, which is what makes the whole feature
    opt-in: the module returns immediately if the element is absent, so a build
    without Supabase credentials renders exactly the page it rendered before.
    """
    if not supabase or not supabase.get("url") or not supabase.get("anon_key"):
        return ""
    payload = {"url": supabase["url"].rstrip("/"), "key": supabase["anon_key"]}
    blob = json.dumps(payload).replace("<", "\\u003c")
    return f'<script type="application/json" id="auth-data">{blob}</script>'


def auth_slot() -> str:
    """The header control. Filled by script; empty and harmless without it."""
    return '<div class="authslot" data-authslot></div>'


def auth_dialog() -> str:
    """The sign-in dialog.

    Rendered as markup rather than built in script so that it is present for a
    reader whose extension blocks the module, and so the copy lives somewhere
    a person can find and edit. Google and phone start hidden and are revealed
    only if the project reports those providers enabled.
    """
    return """
<dialog class="authdlg" id="auth-dialog" aria-labelledby="auth-title">
  <div class="body">
    <button type="button" class="close" data-authclose aria-label="Close">&times;</button>

    <div class="authpane" data-pane="choose">
      <h2 id="auth-title">Sign in</h2>
      <p class="lede">So your capital settings and paper book follow you to
      your phone. No password to remember &mdash; we email you a code.</p>
      <form data-authemail>
        <label for="auth-email">Email address</label>
        <input id="auth-email" data-email type="email" autocomplete="email"
               inputmode="email" placeholder="you@example.com" required>
        <button type="submit" class="go">Email me a code</button>
      </form>
      <div class="sep" data-authsep hidden>or</div>
      <button type="button" class="alt" data-authgoogle hidden>
        Continue with Google</button>
      <button type="button" class="alt" data-authphonego hidden>
        Continue with a phone number</button>
      <p class="msg" data-authmsg></p>
      <p class="fine">This account stores only your settings and paper
      trades. It is not a broker login, it holds no money, and nothing here
      can place a real trade.</p>
    </div>

    <div class="authpane" data-pane="phone" hidden>
      <h2>Sign in by phone</h2>
      <p class="lede">We text you a six-digit code. Include your country
      code.</p>
      <form data-authphone>
        <label for="auth-phone">Mobile number</label>
        <input id="auth-phone" data-phone type="tel" autocomplete="tel"
               inputmode="tel" placeholder="+91 98765 43210" required>
        <button type="submit" class="go">Text me a code</button>
      </form>
      <p class="msg" data-authmsg></p>
      <button type="button" class="back" data-authback>Use email instead</button>
    </div>

    <div class="authpane" data-pane="code" hidden>
      <h2>Enter your code</h2>
      <p class="lede">Six digits, valid for fifteen minutes.</p>
      <form data-authcode>
        <label for="auth-code">Code</label>
        <input id="auth-code" data-code type="text" inputmode="numeric"
               autocomplete="one-time-code" maxlength="6" pattern="[0-9]*"
               placeholder="000000" required>
        <button type="submit" class="go">Sign in</button>
      </form>
      <p class="msg" data-authmsg></p>
      <button type="button" class="back" data-authresend>Send another code</button>
      <button type="button" class="back" data-authback>Start over</button>
    </div>
  </div>
</dialog>"""


def auth_account_section() -> str:
    """The Settings-tab account block, filled by script."""
    return """<h3 class="papersub">Your account</h3>
<div class="acct" data-authacct></div>"""
