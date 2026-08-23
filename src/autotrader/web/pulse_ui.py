"""The client half of usage counting and error reporting.

Batched and sent once, on the way out. A request per interaction would be
both wasteful and noticeable in the network panel of a page that otherwise
makes almost none; a single keepalive beacon on page hide costs the reader
nothing and still arrives when the tab closes.

Nothing identifying is collected — no path, no session, no id, no timing. The
question this answers is "does anyone open the Evidence tab", which needs a
count and not a person.
"""

from __future__ import annotations

PULSE_JS = """
(function () {
  var cfg = window.__mpCfg || {};
  var API = (cfg.api_base || '/markets-pro/api') + '/pulse';
  var events = [];
  var errors = [];
  var sent = false;

  // A ceiling, so a runaway loop cannot turn telemetry into the heaviest
  // thing on the page.
  var MAX_EVENTS = 40, MAX_ERRORS = 5;

  function note(name) {
    if (events.length < MAX_EVENTS && events.indexOf(name) < 0) events.push(name);
  }
  window.__mpNote = note;

  function flush() {
    if (sent || (!events.length && !errors.length)) return;
    sent = true;
    try {
      fetch(API, {
        method: 'POST', keepalive: true,
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({events: events, errors: errors})
      }).catch(function () { /* telemetry never disturbs the page */ });
    } catch (e) { /* nor does its own failure */ }
  }

  // Which tabs anyone actually opens -- the thing eleven tabs shipped without.
  document.addEventListener('click', function (event) {
    var tab = event.target.closest('[data-tabbtn]');
    if (tab) note('tab.' + tab.getAttribute('data-tabbtn'));
    if (event.target.closest('[data-findopen]')) note('find.open');
    if (event.target.closest('[data-stock]')) note('detail.open');
    if (event.target.closest('[data-paper-buy]')) note('paper.buy');
    if (event.target.closest('[data-authslot] button')) note('auth.click');
  }, true);

  // A broken deploy should not depend on someone happening to open a console.
  window.addEventListener('error', function (event) {
    if (errors.length >= MAX_ERRORS) return;
    errors.push({
      message: String((event && event.message) || 'error').slice(0, 300),
      source: String((event && event.filename) || '').slice(0, 200),
      release: (cfg.release || ''),
      agent: (navigator.userAgent || '').slice(0, 80)
    });
    note('error.js');
  });
  window.addEventListener('unhandledrejection', function (event) {
    if (errors.length >= MAX_ERRORS) return;
    var reason = event && event.reason;
    errors.push({
      message: String((reason && reason.message) || reason || 'rejection').slice(0, 300),
      source: 'promise', release: (cfg.release || ''),
      agent: (navigator.userAgent || '').slice(0, 80)
    });
    note('error.promise');
  });

  note('visit');
  // pagehide rather than unload: it fires on mobile Safari, where unload
  // frequently does not.
  window.addEventListener('pagehide', flush);
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden') flush();
  });
})();
"""
