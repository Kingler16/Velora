/* Velora Push — Subscribe-Flow für die PWA.
 *
 * Usage:
 *   window.VeloraPush.subscribe()        → Permission-Dialog + Server-Registrierung
 *   window.VeloraPush.unsubscribe()      → Browser + Server unsubscriben
 *   window.VeloraPush.status()           → { permission, subscribed, supported }
 *   window.VeloraPush.test()             → Test-Push vom Server triggern
 *   window.VeloraPush.getPreferences()   → alle Kategorien
 *   window.VeloraPush.setPreferences(p)  → bulk-Update
 */

(function () {
  'use strict';

  function urlB64ToUint8Array(b64) {
    const pad = '='.repeat((4 - (b64.length % 4)) % 4);
    const raw = atob((b64 + pad).replace(/-/g, '+').replace(/_/g, '/'));
    return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
  }

  function toast(type, msg) {
    if (window.toast && window.toast[type]) window.toast[type](msg);
    else if (type === 'error') console.error('[push]', msg);
    else console.log('[push]', msg);
  }

  async function getRegistration() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) return null;
    return navigator.serviceWorker.ready;
  }

  async function status() {
    const supported = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
    if (!supported) return { supported: false, permission: 'unsupported', subscribed: false };
    const reg = await navigator.serviceWorker.getRegistration();
    const existing = reg ? await reg.pushManager.getSubscription() : null;
    return {
      supported: true,
      permission: Notification.permission,
      subscribed: Boolean(existing),
      endpoint: existing ? existing.endpoint : null,
    };
  }

  async function subscribe() {
    if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
      toast('error', 'Dein Browser unterstützt keine Push-Notifications.');
      return false;
    }

    const res = await fetch('/api/push/vapid-public-key').then((r) => r.json());
    if (!res.configured || !res.key) {
      toast('error', 'Server hat keinen VAPID-Key konfiguriert.');
      return false;
    }

    const perm = await Notification.requestPermission();
    if (perm !== 'granted') {
      toast('warn', 'Push-Benachrichtigungen nicht erlaubt.');
      return false;
    }

    const reg = await getRegistration();
    if (!reg) return false;

    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlB64ToUint8Array(res.key),
      });
    }

    const resp = await fetch('/api/push/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ subscription: sub.toJSON ? sub.toJSON() : sub }),
    });
    if (!resp.ok) {
      toast('error', 'Registrierung am Server fehlgeschlagen.');
      return false;
    }
    toast('success', 'Push aktiviert.');
    return true;
  }

  async function unsubscribe() {
    const reg = await getRegistration();
    if (!reg) return false;
    const sub = await reg.pushManager.getSubscription();
    if (!sub) return true;
    const endpoint = sub.endpoint;
    await sub.unsubscribe();
    await fetch('/api/push/unsubscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ endpoint }),
    }).catch(() => null);
    toast('info', 'Push deaktiviert.');
    return true;
  }

  async function test() {
    const resp = await fetch('/api/push/test', { method: 'POST' });
    const data = await resp.json().catch(() => ({}));
    if (data.sent > 0) toast('success', `Test gesendet an ${data.sent} Gerät(e).`);
    else toast('warn', 'Keine aktiven Push-Empfänger — erst „Aktivieren" klicken.');
  }

  async function getPreferences() {
    const r = await fetch('/api/push/preferences');
    return r.json();
  }

  async function setPreferences(prefs) {
    const r = await fetch('/api/push/preferences', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(prefs),
    });
    return r.json();
  }

  window.VeloraPush = { subscribe, unsubscribe, status, test, getPreferences, setPreferences };
})();
