// Helpers shared by the views.
import { h, clear, button, sayToChat } from '../ui.js';

export function head(title, desc, ...actions) {
  return h('div', { class: 'view-head' },
    h('div', {}, h('h1', {}, title), desc ? h('p', {}, desc) : null),
    actions.length ? h('div', { class: 'row' }, actions) : null);
}

export function crumbs(...parts) {
  return h('div', { class: 'crumbs' }, parts.map(([text, href], i) => [i ? ' / ' : '', href ? h('a', { href }, text) : text]));
}

/** Paint into `el` now and again when the graph changes, unless the user is typing inside it. */
export function live(el, sub, paint, topics = ['graph']) {
  let pending = false;
  const go = async () => {
    const a = document.activeElement;
    if (a && el.contains(a) && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName)) {
      if (!pending) { pending = true; a.addEventListener('blur', () => { pending = false; go(); }, { once: true }); }
      return;
    }
    const keepScroll = document.getElementById('view').scrollTop;
    clear(el, await paint());
    document.getElementById('view').scrollTop = keepScroll;
  };
  topics.forEach((t) => sub(t, go));
  return go();
}

export function askButton(text, label = 'Ask chat') {
  return button(label, () => sayToChat(text), 'sm ghost');
}

export function go(hash) { location.hash = hash; }

export const fmt = (v) => (typeof v === 'number' ? (Number.isInteger(v) ? String(v) : v.toFixed(2)) : v ?? '');
