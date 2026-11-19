/* Heart / favorite buttons (shared by home, detail and saved pages).
   A button looks like:  <button class="fav-btn" data-id="12" data-fav="0"> <svg>…</svg> </button> */
(function () {
  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  var LABELS = window.FAV_T || {};

  var HEART_PATH = 'M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z';

  function paint(btn, on) {
    btn.dataset.fav = on ? '1' : '0';
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    var label = on ? LABELS.remove : LABELS.add;
    if (label) { btn.title = label; btn.setAttribute('aria-label', label); }
    var svg = btn.querySelector('svg');
    if (svg) {
      svg.setAttribute('fill', on ? '#ef4444' : 'none');
      svg.setAttribute('stroke', on ? '#ef4444' : '#475569');
    }
  }

  /* HTML for a heart button (used by the JS-rendered cards on the home page) */
  window.heartButton = function (id, on, extraClass) {
    var label = on ? LABELS.remove : LABELS.add;
    return '<button type="button" class="fav-btn inline-flex items-center justify-center w-10 h-10 rounded-full bg-white/90 shadow hover:bg-white ' +
      (extraClass || '') + '" data-id="' + Number(id) + '" data-fav="' + (on ? 1 : 0) + '" aria-pressed="' + (on ? 'true' : 'false') +
      '" title="' + (label || '') + '" aria-label="' + (label || '') + '">' +
      '<svg class="pointer-events-none" width="22" height="22" viewBox="0 0 24 24" fill="' + (on ? '#ef4444' : 'none') +
      '" stroke="' + (on ? '#ef4444' : '#475569') + '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="' +
      HEART_PATH + '"/></svg></button>';
  };

  async function toggle(btn) {
    if (btn.dataset.busy === '1') return;
    btn.dataset.busy = '1';
    try {
      var res = await fetch('/favorite/' + btn.dataset.id, {
        method: 'POST',
        headers: { 'X-CSRF-Token': csrf, 'X-Requested-With': 'fetch' },
        credentials: 'same-origin'
      });
      if (res.status === 401) {                       // not logged in -> go to login
        var data = await res.json();
        window.location.href = data.login_url;
        return;
      }
      if (!res.ok) throw new Error('HTTP ' + res.status);
      var out = await res.json();
      paint(btn, out.favorited);
      if (!out.favorited && btn.dataset.removeOnUnfav === '1') {
        var card = btn.closest('[data-card]');
        if (card) {
          card.remove();
          if (!document.querySelector('[data-card]')) window.location.reload();
        }
      }
    } catch (err) {
      console.error(err);
    } finally {
      btn.dataset.busy = '0';
    }
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.fav-btn');
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    toggle(btn);
  });
})();
