/* Velora Chat Widget — kompaktes, schwebendes Panel, seiten-übergreifend.
   Reuses dieselben Backend-Endpoints wie die Full-Page /chat. */

(function () {
  'use strict';

  const LAST_THREAD_KEY = 'velora_widget_thread';

  const state = {
    threadId: null,
    streaming: false,
    currentBubble: null,
    currentText: '',
    activeTools: new Map(),
  };

  let $toggle, $panel, $messages, $input, $sendBtn, $newBtn, $closeBtn;

  // ── Helpers ─────────────────────────────────────────
  const el = (tag, attrs = {}, ...children) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'class') n.className = v;
      else if (k.startsWith('on') && typeof v === 'function') n.addEventListener(k.slice(2), v);
      else if (v !== undefined && v !== null) n.setAttribute(k, v);
    }
    for (const c of children) {
      if (c === null || c === undefined) continue;
      n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    }
    return n;
  };

  const escapeHtml = (s) => (s || '').replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  const renderMarkdown = (text) => {
    if (typeof marked === 'undefined') return escapeHtml(text).replace(/\n/g, '<br>');
    try { marked.setOptions({ breaks: true, gfm: true }); return marked.parse(text || ''); }
    catch { return escapeHtml(text); }
  };

  const scroll = () => requestAnimationFrame(() => {
    if ($messages) $messages.scrollTop = $messages.scrollHeight;
  });

  // ── Page-Kontext (für context-aware Prompts) ────────
  const derivePageContext = () => {
    const body = document.body;
    const main = document.querySelector('main, .main-content');
    let page = (body && body.dataset.page) || null;
    // Fallback: aktive Sidebar-Link
    if (!page) {
      const active = document.querySelector('.sidebar-nav a.active');
      if (active) {
        const href = active.getAttribute('href') || '';
        page = href.replace(/^\//, '') || 'dashboard';
      }
    }
    return {
      page: page || 'unknown',
      focused_ticker: window.veloraFocusedTicker || null,
      url: location.pathname,
    };
  };

  // ── Panel-Steuerung ─────────────────────────────────
  const openPanel = async () => {
    $panel.classList.add('open');
    $panel.setAttribute('aria-hidden', 'false');
    $toggle.classList.add('active');

    if (!state.threadId) {
      // Zuletzt benutzten Thread laden oder neuen anlegen
      let lastId = null;
      try { lastId = localStorage.getItem(LAST_THREAD_KEY); } catch {}
      if (lastId) {
        const r = await fetch(`/api/chat/threads/${lastId}`).then(r => r.ok ? r.json() : null).catch(() => null);
        if (r && r.thread) {
          state.threadId = lastId;
          renderExistingMessages(r.messages || []);
        }
      }
      if (!state.threadId) {
        const t = await fetch('/api/chat/threads', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ title: 'Quick Chat' }),
        }).then(r => r.json());
        state.threadId = t.id;
        try { localStorage.setItem(LAST_THREAD_KEY, t.id); } catch {}
        renderEmpty();
      }
    }
    setTimeout(() => $input.focus(), 100);
  };

  const closePanel = () => {
    $panel.classList.remove('open');
    $panel.setAttribute('aria-hidden', 'true');
    $toggle.classList.remove('active');
  };

  const newThread = async () => {
    const t = await fetch('/api/chat/threads', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ title: 'Quick Chat' }),
    }).then(r => r.json());
    state.threadId = t.id;
    try { localStorage.setItem(LAST_THREAD_KEY, t.id); } catch {}
    renderEmpty();
    $input.focus();
  };

  const renderEmpty = () => {
    $messages.innerHTML = '';
    const ctx = derivePageContext();
    const hint = ctx.page && ctx.page !== 'unknown'
      ? `Du bist auf /${ctx.page}. Frag mich was zu dieser Seite.`
      : 'Frag mich was.';
    $messages.appendChild(el('div', { class: 'velora-widget-empty' },
      el('strong', {}, 'Velora'),
      el('br'),
      hint,
    ));
  };

  const renderExistingMessages = (msgs) => {
    $messages.innerHTML = '';
    if (!msgs.length) { renderEmpty(); return; }
    for (const m of msgs) {
      if (m.role === 'user' || m.role === 'assistant') {
        const b = el('div', { class: 'velora-widget-msg ' + m.role });
        b.innerHTML = m.role === 'assistant' ? renderMarkdown(m.content) : escapeHtml(m.content).replace(/\n/g, '<br>');
        $messages.appendChild(b);
      } else if (m.role === 'tool_use') {
        try {
          const d = JSON.parse(m.content);
          const name = (d.name || '').replace('mcp__velora__', '');
          $messages.appendChild(el('div', { class: 'velora-widget-tool done' }, '✓ ' + name));
        } catch {}
      }
    }
    scroll();
  };

  // ── Senden ──────────────────────────────────────────
  const send = async () => {
    if (state.streaming) return;
    const text = $input.value.trim();
    if (!text || !state.threadId) return;

    // Empty-State clearen
    if ($messages.querySelector('.velora-widget-empty')) $messages.innerHTML = '';

    const userBubble = el('div', { class: 'velora-widget-msg user' });
    userBubble.innerHTML = escapeHtml(text).replace(/\n/g, '<br>');
    $messages.appendChild(userBubble);

    $input.value = '';
    $input.style.height = 'auto';
    setStreaming(true);

    state.currentText = '';
    const assistantBubble = el('div', { class: 'velora-widget-msg assistant' },
      el('span', { class: 'velora-widget-cursor' }));
    $messages.appendChild(assistantBubble);
    state.currentBubble = assistantBubble;
    scroll();

    let response;
    try {
      response = await fetch(`/api/chat/threads/${state.threadId}/message`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ message: text, page_context: derivePageContext() }),
      });
    } catch (e) {
      assistantBubble.textContent = '⚠ Netzwerkfehler';
      setStreaming(false);
      return;
    }

    if (!response.ok) {
      assistantBubble.textContent = `⚠ Fehler ${response.status}`;
      setStreaming(false);
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buffer.indexOf('\n\n')) !== -1) {
          const ev = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          handleSse(ev);
        }
      }
    } finally {
      if (state.currentBubble) {
        state.currentBubble.innerHTML = renderMarkdown(state.currentText || '(keine Antwort)');
      }
      state.currentBubble = null;
      setStreaming(false);
    }
  };

  const handleSse = (raw) => {
    const lines = raw.split('\n');
    let event = 'message', data = '';
    for (const l of lines) {
      if (l.startsWith('event:')) event = l.slice(6).trim();
      else if (l.startsWith('data:')) data += (data ? '\n' : '') + l.slice(5).trim();
    }
    let parsed = data;
    try { parsed = JSON.parse(data); } catch {}

    if (event === 'token') {
      const chunk = typeof parsed === 'string' ? parsed : (parsed.text || '');
      if (chunk) {
        state.currentText += chunk;
        if (state.currentBubble) {
          state.currentBubble.innerHTML = renderMarkdown(state.currentText)
            + '<span class="velora-widget-cursor"></span>';
          scroll();
        }
      }
    } else if (event === 'tool_use') {
      const name = (parsed.name || '').replace('mcp__velora__', '');
      const card = el('div', { class: 'velora-widget-tool' }, '⟳ ' + name);
      state.activeTools.set(parsed.id, card);
      const parent = state.currentBubble;
      if (parent && parent.parentNode) parent.parentNode.insertBefore(card, parent);
      else $messages.appendChild(card);
      scroll();
    } else if (event === 'tool_result') {
      const c = state.activeTools.get(parsed.tool_use_id);
      if (c) {
        c.classList.add('done');
        c.textContent = c.textContent.replace('⟳', '✓');
        state.activeTools.delete(parsed.tool_use_id);
      }
    } else if (event === 'confirmation_required') {
      // Im Widget: einfache Confirmation inline
      showInlineConfirm(parsed);
    } else if (event === 'error' || event === 'fatal') {
      if (state.currentBubble) {
        state.currentBubble.innerHTML = '<span style="color: var(--red)">⚠ ' + escapeHtml(parsed.message || 'Fehler') + '</span>';
      }
    }
  };

  const showInlineConfirm = (d) => {
    const box = el('div', {
      class: 'velora-widget-msg assistant',
      style: 'border-left: 2px solid var(--yellow); background: rgba(234,179,8,0.08);'
    },
      el('div', { style: 'font-weight: 600; margin-bottom: 4px;' }, '⚠ Bestätigung nötig'),
      el('div', { style: 'margin-bottom: 6px;' }, d.summary || 'Aktion ausführen?'),
      el('div', { style: 'display: flex; gap: 6px;' },
        el('button', {
          class: 'btn-confirm',
          style: 'padding: 4px 10px; border-radius: 5px; background: var(--accent); color: white; border: none; cursor: pointer; font-size: 11px; font-weight: 600;',
          onclick: async () => {
            const r = await fetch('/api/chat/confirm', {
              method: 'POST', headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({ action_id: d.action_id, approved: true }),
            }).then(r => r.json());
            box.innerHTML = r.success
              ? '<div style="color: var(--green);">✓ ' + escapeHtml(r.message || 'Erledigt') + '</div>'
              : '<div style="color: var(--red);">⚠ ' + escapeHtml(r.message) + '</div>';
          }
        }, 'Ausführen'),
        el('button', {
          style: 'padding: 4px 10px; border-radius: 5px; background: var(--bg-secondary); color: var(--text-secondary); border: 1px solid var(--border); cursor: pointer; font-size: 11px;',
          onclick: async () => {
            await fetch('/api/chat/confirm', {
              method: 'POST', headers: {'Content-Type': 'application/json'},
              body: JSON.stringify({ action_id: d.action_id, approved: false }),
            });
            box.innerHTML = '<div style="color: var(--text-muted);">✕ Abgebrochen</div>';
          }
        }, 'Abbrechen'),
      ),
    );
    $messages.appendChild(box);
    scroll();
  };

  const setStreaming = (v) => {
    state.streaming = v;
    $sendBtn.disabled = v || $input.value.trim().length === 0;
    $input.disabled = v;
  };

  const autoResize = () => {
    $input.style.height = 'auto';
    $input.style.height = Math.min($input.scrollHeight, 140) + 'px';
    $sendBtn.disabled = state.streaming || $input.value.trim().length === 0;
  };

  // ── Init ────────────────────────────────────────────
  const init = () => {
    $toggle = document.getElementById('velora-widget-toggle');
    $panel = document.getElementById('velora-widget-panel');
    if (!$toggle || !$panel) return;

    $messages = document.getElementById('velora-widget-messages');
    $input = document.getElementById('velora-widget-input');
    $sendBtn = document.getElementById('velora-widget-send');
    $newBtn = document.getElementById('velora-widget-new');
    $closeBtn = document.getElementById('velora-widget-close');

    $toggle.addEventListener('click', () => {
      if ($panel.classList.contains('open')) closePanel();
      else openPanel();
    });
    $closeBtn.addEventListener('click', closePanel);
    $newBtn.addEventListener('click', newThread);
    $input.addEventListener('input', autoResize);
    $input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
      if (e.key === 'Escape') closePanel();
    });
    $sendBtn.addEventListener('click', send);

    // Keyboard-Shortcut: Cmd/Ctrl + / öffnet/schließt
    document.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === '/') {
        e.preventDefault();
        $toggle.click();
      }
    });
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // ── Öffentliche API ─────────────────────────────────
  // VeloraWidget.ask(text): öffnet das Panel, befüllt den Input mit `text`
  // und sendet ab. Genutzt z.B. von /recommendations ("Velora fragen").
  const ask = async (text) => {
    if (!text) return;
    // Falls init() noch nicht lief (DOM noch nicht ready), nachholen.
    if (!$panel || !$input) init();
    if (!$panel || !$input) return;
    if (!$panel.classList.contains('open')) {
      await openPanel();
    }
    $input.value = text;
    autoResize();
    send();
  };

  window.VeloraWidget = { ask, open: openPanel, close: closePanel };
})();
