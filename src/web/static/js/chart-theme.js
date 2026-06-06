/* Velora chart theme: live CSS-token readers + responsive helpers + Apex defaults. */
(function() {
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const isDark = () => window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;

  window.VeloraChartTheme = {
    colors: ['#3b82f6', '#93c5fd', '#1e40af', '#94a3b8', '#60a5fa', '#475569', '#bfdbfe', '#fbbf24', '#64748b'],
    bg:          () => css('--bg-canvas'),
    bodyBg:      () => css('--bg-body'),
    text:        () => css('--text-secondary'),
    textPrimary: () => css('--text-primary'),
    textMuted:   () => css('--text-muted'),
    accent:      () => css('--accent'),
    accentBg:    () => css('--accent-bg'),
    grid:        () => isDark() ? 'rgba(255,255,255,0.06)' : 'rgba(10,20,40,0.08)',
    border:      () => isDark() ? 'rgba(255,255,255,0.10)' : 'rgba(10,20,40,0.10)',
    tooltipBg:   () => isDark() ? 'rgba(10,15,31,0.92)' : 'rgba(255,255,255,0.95)',
    tooltipBorder: () => isDark() ? 'rgba(255,255,255,0.12)' : 'rgba(10,20,40,0.10)',
    green:       () => css('--gain'),
    red:         () => css('--loss'),
    yellow:      () => css('--warn'),
  };

  // Drei Stufen, identisch zur CSS-Breakpoint-Logik in responsive.css.
  const isPhone   = () => window.matchMedia && window.matchMedia('(max-width: 767.98px)').matches;
  const isTablet  = () => window.matchMedia && window.matchMedia('(min-width: 768px) and (max-width: 1023.98px)').matches;
  const isDesktop = () => window.matchMedia && window.matchMedia('(min-width: 1024px)').matches;
  const screenSize = () => isPhone() ? 'phone' : isTablet() ? 'tablet' : 'desktop';

  // Chart-Heights synchron zu .chart-h-{sm,md,lg} in responsive.css.
  // Gut, dass JS (ApexCharts.chart.height) und CSS-Klassen denselben Wert liefern.
  const HEIGHTS = {
    sm: { phone: 200, tablet: 240, desktop: 260 },
    md: { phone: 240, tablet: 300, desktop: 340 },
    lg: { phone: 280, tablet: 360, desktop: 420 },
  };
  const chartHeight = (size) => (HEIGHTS[size] || HEIGHTS.md)[screenSize()];

  window.VeloraApex = {
    baseOptions() {
      const dark = isDark();
      const phone = isPhone();
      const tablet = isTablet();
      const compact = phone || tablet;
      // ApexCharts liest viele Optionen tief in den Objekten weiter
      // (z. B. legend.itemMargin.vertical). Eine explizit auf `undefined`
      // gesetzte Property uebersteuert den ApexCharts-Default und fuehrt
      // dann zu TypeErrors ("reading 'vertical'") / "Legend position not
      // supported". Deshalb Properties nur setzen, wenn ein Wert existiert.
      // Padding immer explizit setzen — sobald wir ein `grid`-Objekt
      // ueberreichen, ueberschreibt ApexCharts den eigenen Default komplett.
      // Fehlt dann grid.padding, crasht der interne Aufruf (Safari: TypeError
      // "undefined is not an object (evaluating 'this.gridPad.top')"; Chrome
      // schluckt es bei Donut still). Daher hier Default-aequivalente Werte
      // fuer Desktop und ueberschrieben fuer Phone/Tablet.
      const grid = {
        borderColor: window.VeloraChartTheme.grid(),
        strokeDashArray: 4,
        xaxis: { lines: { show: false } },
        padding: phone ? { left: 4, right: 4, top: 0, bottom: 0 }
              : tablet ? { left: 8, right: 8, top: 0, bottom: 0 }
              :          { left: 12, right: 0, top: 0, bottom: 0 },
      };

      const legend = {
        labels: { colors: window.VeloraChartTheme.text() },
        fontFamily: 'Inter',
        fontSize: phone ? '10px' : tablet ? '11px' : '12px',
        markers: { width: phone ? 8 : 10, height: phone ? 8 : 10 },
      };
      if (compact) legend.itemMargin = { horizontal: 6, vertical: 2 };
      if (phone) legend.position = 'bottom';

      return {
        chart: {
          foreColor: window.VeloraChartTheme.text(),
          toolbar: { show: false },
          fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, sans-serif',
          background: 'transparent',
          width: '100%',
          // Mobile/Tablet: Animationen reduzieren (weniger GPU-Last, schnelleres Initial-Paint).
          animations: phone ? {
            enabled: false,
          } : {
            enabled: true,
            easing: 'easeout',
            speed: tablet ? 400 : 600,
            animateGradually: { enabled: !tablet, delay: 80 },
          },
          redrawOnWindowResize: true,
          redrawOnParentResize: true,
        },
        theme: { mode: dark ? 'dark' : 'light' },
        grid,
        tooltip: {
          theme: dark ? 'dark' : 'light',
          style: { fontSize: phone ? '11px' : '12px', fontFamily: 'Inter' },
          marker: { show: true },
        },
        colors: window.VeloraChartTheme.colors,
        dataLabels: { enabled: false },
        legend,
        stroke: {
          // Phone: gerade Linien (CPU-schonender, schärfer auf 375px).
          curve: phone ? 'straight' : 'smooth',
          width: 2,
        },
        // Hinweis: KEIN responsive-Array. ApexCharts merged die responsive-
        // Options beim Init in den globalen Config, und Safari crasht dann
        // tief in dCtx.gridPad.{top,left} weil das Merge die padding-Defaults
        // verschluckt (Chrome ignoriert es bei Donut/Pie still). Wir machen
        // Viewport-Branching ohnehin schon via isPhone()/isTablet() oben, das
        // responsive-Array war redundant.
      };
    },
    // Donut-/Pie-Defaults:
    // Phone: KEINE dataLabels in den Slices — bei vielen Positionen ueber-
    // lappen sie sich und kollidieren mit dem Center-Label. Werte stehen in
    // der Legende unten + per Tap-auf-Slice in der Touch-Tooltip.
    // Desktop: Standard-DataLabels mit Threshold (kleine Slices nicht
    // beschriften, sonst Cluster).
    donutDefaults() {
      const phone = isPhone();
      const minPct = 4;
      return {
        plotOptions: {
          pie: {
            donut: { size: phone ? '68%' : '65%' },
            expandOnClick: !phone,
          },
        },
        dataLabels: {
          enabled: !phone,
          formatter: function(val) {
            const n = Number(val);
            if (!isFinite(n) || n < minPct) return '';
            return n.toFixed(1) + '%';
          },
          style: { fontSize: '11px', fontFamily: 'Inter', fontWeight: 700, colors: ['#fff'] },
          dropShadow: { enabled: true, top: 1, left: 0, blur: 2, opacity: 0.45 },
        },
      };
    },
    // Labels auf Phone kürzen (Donut-Legenden bleiben so lesbar).
    truncateLabels(labels, max) {
      if (!isPhone()) return labels;
      const limit = max || 18;
      return labels.map(l => (typeof l === 'string' && l.length > limit) ? l.slice(0, limit - 1) + '…' : l);
    },
    // Sektor-Namen auf Phone als Kurzcode (fuer Treemap, wo Boxen zu schmal
    // sind fuer 15+ Zeichen). Bekannte Sektoren bekommen feste Abkuerzungen,
    // alles andere wird auf 8 Zeichen gekuerzt.
    shortSectorName(name) {
      if (!isPhone() || typeof name !== 'string') return name;
      const map = {
        'Communication Services': 'Comm Serv',
        'Consumer Cyclical': 'Cons Cyc',
        'Consumer Defensive': 'Cons Def',
        'Consumer Staples': 'Staples',
        'Consumer Discretionary': 'Cons Disc',
        'Financial Services': 'Financials',
        'Financials': 'Finance',
        'Real Estate': 'RE',
        'Basic Materials': 'Materials',
        'Industrials': 'Industry',
        'Information Technology': 'Tech',
        'Technology': 'Tech',
        'Healthcare': 'Health',
        'Health Care': 'Health',
        'Utilities': 'Utility',
        'Energy': 'Energy',
        'Unbekannt': 'Sonst.',
      };
      if (map[name]) return map[name];
      return name.length > 9 ? name.slice(0, 8) + '…' : name;
    },
    chartHeight,
    screenSize,
    isMobile: isPhone,    // Backwards-compat alias
    isPhone,
    isTablet,
    isDesktop,
  };
})();
