/* Velora command palette: Cmd+K launcher with nav actions + custom registration. */
(function() {
  const el = document.getElementById('cmd-palette');
  const input = document.getElementById('cmd-input');
  const resultsEl = document.getElementById('cmd-results');

  const actions = [
    { id: 'nav-dashboard',       label: 'Dashboard',                icon: '\u25CB', action: () => { location.href = '/'; },                keywords: 'home uebersicht start' },
    { id: 'nav-portfolio',       label: 'Portfolio',                icon: '\u25C6', action: () => { location.href = '/portfolio'; },       keywords: 'holdings positionen bestand' },
    { id: 'nav-analysis',        label: 'Analyse',                  icon: '\u25B3', action: () => { location.href = '/analysis'; },        keywords: 'analysis ki' },
    { id: 'nav-market',          label: 'Markt',                    icon: '\u25A1', action: () => { location.href = '/market'; },          keywords: 'indizes ticker news' },
    { id: 'nav-briefings',       label: 'Briefings',                icon: '\u2630', action: () => { location.href = '/briefings'; },       keywords: 'reports morning' },
    { id: 'nav-recommendations', label: 'Empfehlungen',             icon: '\u2605', action: () => { location.href = '/recommendations'; }, keywords: 'recommendations ideas trades' },
    { id: 'nav-chat',            label: 'Chat',                     icon: '\u2302', action: () => { location.href = '/chat'; },            keywords: 'velora ask ai' },
    { id: 'nav-settings',        label: 'Einstellungen',            icon: '\u2699', action: () => { location.href = '/settings'; },        keywords: 'config preferences' },
    { id: 'act-trade',           label: 'Trade loggen',             icon: '\u002B', action: () => {
        if (location.pathname !== '/portfolio') {
          location.href = '/portfolio?trade=1';
        } else if (window.TradeModal && typeof window.TradeModal.open === 'function') {
          window.TradeModal.open();
        } else {
          const modal = document.getElementById('tradeModal');
          if (modal) modal.classList.add('open');
        }
      }, keywords: 'kauf verkauf buy sell log' },
    { id: 'act-refresh',         label: 'Portfolio aktualisieren',  icon: '\u21BB', action: () => {
        fetch('/api/refresh', { method: 'POST' })
          .then(() => location.reload())
          .catch(() => { if (window.toast) window.toast.error('Refresh fehlgeschlagen'); });
      }, keywords: 'refresh reload sync' },
    { id: 'act-newchat',         label: 'Neuer Chat',               icon: '\u270E', action: () => { location.href = '/chat?new=1'; }, keywords: 'chat velora ask neu new' },
  ];

  let filtered = actions.slice();
  let filteredIdx = 0;

  function render() {
    if (!resultsEl) return;
    if (!filtered.length) {
      resultsEl.innerHTML = '<li class="cmd-result" style="opacity:0.5;"><span class="cmd-result-icon">\u00D8</span><span class="cmd-result-label">Keine Treffer</span><span class="cmd-result-hint"></span></li>';
      return;
    }
    resultsEl.innerHTML = filtered.map((a, i) => `
      <li class="cmd-result${i === filteredIdx ? ' active' : ''}" data-idx="${i}">
        <span class="cmd-result-icon">${a.icon || ''}</span>
        <span class="cmd-result-label">${a.label}</span>
        <span class="cmd-result-hint">${a.hint || ''}</span>
      </li>
    `).join('');
    resultsEl.querySelectorAll('.cmd-result[data-idx]').forEach(li => {
      li.addEventListener('click', () => {
        const idx = parseInt(li.getAttribute('data-idx'), 10);
        const a = filtered[idx];
        if (a) { close(); a.action(); }
      });
      li.addEventListener('mousemove', () => {
        const idx = parseInt(li.getAttribute('data-idx'), 10);
        if (idx !== filteredIdx) { filteredIdx = idx; render(); }
      });
    });
  }

  function filter(q) {
    const needle = (q || '').trim().toLowerCase();
    filtered = actions.filter(a => {
      if (!needle) return true;
      const hay = (a.label + ' ' + (a.keywords || '')).toLowerCase();
      return hay.includes(needle);
    });
    filteredIdx = 0;
    render();
  }

  function open() {
    if (!el) return;
    el.hidden = false;
    if (input) input.value = '';
    filter('');
    setTimeout(() => input && input.focus(), 0);
  }

  function close() {
    if (!el) return;
    el.hidden = true;
  }

  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      if (!el) return;
      e.preventDefault();
      if (el.hidden) open(); else close();
      return;
    }
    if (!el || el.hidden) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      close();
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      filteredIdx = Math.min(filteredIdx + 1, filtered.length - 1);
      render();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      filteredIdx = Math.max(filteredIdx - 1, 0);
      render();
    } else if (e.key === 'Enter' && filtered[filteredIdx]) {
      e.preventDefault();
      const a = filtered[filteredIdx];
      close();
      a.action();
    }
  });

  if (input) {
    input.addEventListener('input', () => filter(input.value));
  }

  const overlay = el && el.querySelector('.cmd-overlay');
  if (overlay) overlay.addEventListener('click', close);

  window.VeloraCmd = {
    open,
    close,
    register(a) {
      if (!a || !a.id || !a.label || typeof a.action !== 'function') return;
      actions.push(a);
    },
  };
})();
