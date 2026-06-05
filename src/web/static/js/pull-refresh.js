/* Velora — Pull-to-Refresh für Mobile PWA
 *
 * Reagiert nur wenn:
 *  - Viewport < 768px
 *  - Scroll-Position ist am Top (scrollY === 0)
 *  - Touch-Gestik nach unten mit > 80px overshoot
 *
 * Visueller Indikator unter Safe-Area-Top, rotiert während Pull und spinnt
 * während Refresh.  Refresh = POST /api/refresh (holt FRISCHE Daten vom
 * Backend), danach kurzes Polling auf /api/refresh/status und reload.
 * Fällt bei Fehlern auf einen reload zurück, damit der Pull nie "hängt".
 */

(function () {
  'use strict';

  if (window.matchMedia && window.matchMedia('(min-width: 768px)').matches) return;
  if (!('ontouchstart' in window)) return;

  // Opt-out pro Seite über data-no-pull-refresh auf <body>
  if (document.body && document.body.dataset.noPullRefresh === 'true') return;

  const THRESHOLD = 80;
  const MAX_PULL = 160;
  const DAMPING = 0.45;

  let startY = 0;
  let pullDistance = 0;
  let pulling = false;
  let refreshing = false;

  const indicator = document.createElement('div');
  indicator.setAttribute('aria-hidden', 'true');
  indicator.style.cssText = [
    'position:fixed',
    'top:max(var(--safe-top, 0px), 0px)',
    'left:50%',
    'transform:translateX(-50%) translateY(-100%)',
    'width:42px',
    'height:42px',
    'border-radius:50%',
    'background:var(--glass-bg-strong, rgba(255,255,255,0.12))',
    'border:1px solid var(--glass-border, rgba(255,255,255,0.12))',
    'backdrop-filter:blur(20px) saturate(180%)',
    '-webkit-backdrop-filter:blur(20px) saturate(180%)',
    'display:flex',
    'align-items:center',
    'justify-content:center',
    'z-index:200',
    'pointer-events:none',
    'transition:transform 180ms cubic-bezier(0.16,1,0.3,1), opacity 180ms',
    'opacity:0',
    'color:var(--accent, #22d3ee)',
  ].join(';');
  indicator.innerHTML = `
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
      <polyline points="3 14 12 23 21 14"></polyline>
      <line x1="12" y1="23" x2="12" y2="2"></line>
    </svg>
  `;

  const svg = () => indicator.firstElementChild;

  document.addEventListener('DOMContentLoaded', () => {
    document.body.appendChild(indicator);
  });

  function setIndicator(progress) {
    const clamped = Math.min(1.2, progress);
    const y = Math.min(MAX_PULL, progress * THRESHOLD);
    const angle = progress * 180;
    indicator.style.transform = `translateX(-50%) translateY(${y}px) rotate(${angle}deg)`;
    indicator.style.opacity = String(Math.min(1, progress * 1.5));
    if (svg()) svg().style.color = progress >= 1 ? 'var(--accent, #22d3ee)' : 'var(--text-secondary, #94a3b8)';
  }

  function startSpin() {
    indicator.style.transform = `translateX(-50%) translateY(${THRESHOLD}px) rotate(0deg)`;
    indicator.style.opacity = '1';
    indicator.classList.add('pull-spin');
    if (!document.getElementById('velora-pull-refresh-style')) {
      const s = document.createElement('style');
      s.id = 'velora-pull-refresh-style';
      s.textContent = `@keyframes velora-pull-spin { from { transform: translateX(-50%) translateY(${THRESHOLD}px) rotate(0deg); } to { transform: translateX(-50%) translateY(${THRESHOLD}px) rotate(360deg); } } .pull-spin { animation: velora-pull-spin 650ms linear infinite; }`;
      document.head.appendChild(s);
    }
  }

  function reset() {
    pullDistance = 0;
    pulling = false;
    indicator.classList.remove('pull-spin');
    indicator.style.transform = 'translateX(-50%) translateY(-100%)';
    indicator.style.opacity = '0';
  }

  // Echter Refresh: triggert das Backend-Sammeln frischer Daten, pollt kurz
  // den Status und lädt dann neu. Robust — bei jedem Fehler einfach reload,
  // damit der Pull niemals dauerhaft im Spin hängt.
  function doRefresh() {
    const MAX_WAIT_MS = 60000;   // 1 min hard cap, dann trotzdem reload
    const POLL_MS = 2000;
    const startTime = Date.now();

    const finish = () => { location.reload(); };

    fetch('/api/refresh', { method: 'POST' })
      .then((r) => r.json())
      .then(() => {
        const poll = setInterval(() => {
          if (Date.now() - startTime > MAX_WAIT_MS) {
            clearInterval(poll);
            finish();
            return;
          }
          fetch('/api/refresh/status')
            .then((r) => r.json())
            .then((s) => {
              if (!s || !s.running) { clearInterval(poll); finish(); }
            })
            .catch(() => { clearInterval(poll); finish(); });
        }, POLL_MS);
      })
      .catch(() => {
        // /api/refresh nicht erreichbar — wenigstens neu laden (Cache)
        finish();
      });
  }

  document.addEventListener('touchstart', (e) => {
    if (refreshing) return;
    if (window.scrollY !== 0) return;
    if (e.touches.length !== 1) return;
    startY = e.touches[0].clientY;
    pulling = true;
  }, { passive: true });

  document.addEventListener('touchmove', (e) => {
    if (!pulling || refreshing) return;
    const dy = e.touches[0].clientY - startY;
    if (dy < 0) { reset(); return; }
    pullDistance = dy * DAMPING;
    setIndicator(pullDistance / THRESHOLD);
  }, { passive: true });

  document.addEventListener('touchend', () => {
    if (!pulling || refreshing) { reset(); return; }
    if (pullDistance >= THRESHOLD) {
      refreshing = true;
      startSpin();
      if (window.VeloraHaptics) window.VeloraHaptics.medium();
      // kleine Delay damit User den Spin sieht, dann echten Refresh auslösen
      setTimeout(doRefresh, 350);
    } else {
      reset();
    }
  }, { passive: true });
})();
