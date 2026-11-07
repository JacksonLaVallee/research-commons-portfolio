// Shared UI building blocks.
import * as api from './api.js';
import { state, node, toggleFocus, isFocused, on, loadGraph, loadProject } from './store.js';

export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'class') el.className = v;
    else if (k === 'html') el.innerHTML = v;
    else if (v === true) el.setAttribute(k, '');
    else el.setAttribute(k, v);
  }
  append(el, children);
  return el;
}
function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}
export function clear(el, ...children) { el.replaceChildren(); append(el, children); return el; }
export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export const TYPES = {
  paper: 'Paper', claim: 'Claim', assumption: 'Assumption', method: 'Method', topic: 'Topic', gap: 'Gap',
  search: 'Search', note: 'Note', experiment: 'Experiment', run: 'Run', dataset: 'Dataset', grant: 'Grant',
  researcher: 'Researcher', draft: 'Draft', report: 'Report',
};

export function shortCite(n) {
  const raw = n?.props?.authors;
  const a = (Array.isArray(raw) ? raw : raw ? [raw] : []).filter(s => typeof s === 'string' && s.trim());
  if (!a.length) {
    const title = n?.title || 'Untitled source';
    return title.length > 48 ? title.slice(0, 47) + '…' : title;
  }
  const last = (s) => s.trim().split(/\s+/).slice(-1)[0];
  const who = a.length > 2 ? `${last(a[0])} et al.` : a.length === 2 ? `${last(a[0])} & ${last(a[1])}` : last(a[0]);
  return `${who} ${n.props.year || ''}`.trim();
}

export function label(n, max = 48) {
  if (!n) return '';
  if (n.type === 'paper') return shortCite(n);
  return n.title.length > max ? n.title.slice(0, max - 1) + '…' : n.title;
}

export function hrefFor(id) {
  const n = node(id);
  if (!n) return `#/graph?node=${id}`;
  switch (n.type) {
    case 'paper': return `#/paper/${id}`;
    case 'gap': return `#/gaps/${id}`;
    case 'experiment': return `#/experiments/${id}`;
    case 'run': return `#/experiments/${n.props.experiment_id}?run=${id}`;
    case 'draft': return `#/writing/${id}`;
    case 'report': return n.props.kind === 'review' ? `#/writing/${n.props.draft_id}?review=${id}` : `#/writing?report=${id}`;
    case 'search': return `#/search/${id}`;
    case 'topic': return `#/fieldmap/${id}`;
    case 'grant': case 'researcher': return `#/funding?grant=${id}`;
    case 'dataset': return `#/experiments?dataset=${id}`;
    default: return `#/graph?node=${id}`;
  }
}

export function chip(id, opts = {}) {
  const n = node(id);
  if (!n) return h('span', { class: 'chip missing', title: 'Not in the graph' }, id);
  return h('a', { class: `chip t-${n.type}`, href: hrefFor(id), title: `${TYPES[n.type]} ${id}: ${n.title}` },
    h('span', { class: 'dot' }), opts.full ? n.title : label(n, opts.max || 42));
}

export function badge(text, kind = '') { return h('span', { class: `badge ${kind}` }, text); }
export function typeBadge(t) { return h('span', { class: `badge type t-${t}` }, TYPES[t] || t); }
export function statusBadge(s) {
  return badge(s, { unreviewed: 'warn', accepted: 'ok', dismissed: 'muted', auto: 'muted' }[s] || '');
}
export function groundingBadge(g) {
  if (!g) return null;
  const map = { exact: ['verified quote', 'ok'], fuzzy_candidate: ['fuzzy: needs review', 'warn'], none: ['not found', 'bad'], dropped: ['dropped', 'bad'] };
  const [t, k] = map[g] || [g, ''];
  return badge(t, `ground ${k}`);
}
export function originBadge(o) { return badge(o === 'ai' ? 'AI' : o, o === 'ai' ? 'ai' : 'muted'); }

export function toast(msg, kind = '') {
  const t = h('div', { class: `toast ${kind}` }, msg);
  document.getElementById('toasts').append(t);
  setTimeout(() => t.classList.add('gone'), 3800);
  setTimeout(() => t.remove(), 4300);
}

export function button(text, onclick, cls = '') {
  const b = h('button', { class: `btn ${cls}`, type: 'button' }, text);
  b.addEventListener('click', async (e) => {
    if (b.disabled) return;
    b.disabled = true;
    try { await onclick(e); } catch (err) { console.error(err); toast(err.message || String(err), 'bad'); } finally { b.disabled = false; }
  });
  return b;
}

function paintFocus(b) {
  const f = isFocused(b.dataset.focusId);
  b.textContent = f ? '★ In focus' : '☆ Focus';
  b.classList.toggle('on', f);
}
on('focus', () => document.querySelectorAll('[data-focus-id]').forEach(paintFocus));

export function focusButton(id) {
  const b = h('button', { class: 'btn ghost sm focus-btn', type: 'button', 'data-focus-id': id,
                          title: 'Add to or remove from the focus set (carried to every view and to chat)' });
  b.addEventListener('click', () => toggleFocus(id));
  paintFocus(b);
  return b;
}

export async function review(ids, decision, reason) {
  const r = await api.post('/api/review', { target_ids: ids, decision, reason });
  await Promise.all([loadGraph(), loadProject()]);
  toast(`${r.updated.length} item(s) ${r.status}`, decision === 'accept' ? 'ok' : '');
  return r;
}

export function reviewButtons(id, status) {
  if (status === 'auto') return null;
  return h('span', { class: 'btn-group' },
    button('Accept', () => review([id], 'accept'), status === 'accepted' ? 'sm ok on' : 'sm ok'),
    button('Dismiss', () => review([id], 'dismiss'), status === 'dismissed' ? 'sm on' : 'sm'));
}

/** Inline markdown-lite: **bold**, `code`, _em_, "- " lists, # headings, and [node-id] citation chips. */
export function rich(text, opts = {}) {
  const wrap = h('div', { class: 'rich' });
  let list = null;
  for (const raw of String(text || '').split('\n')) {
    const line = raw.trimEnd();
    if (/^\s*[-*] /.test(line)) {
      if (!list) { list = h('ul'); wrap.append(list); }
      list.append(h('li', {}, inline(line.replace(/^\s*[-*] /, ''), opts)));
      continue;
    }
    list = null;
    if (!line.trim()) continue;
    const m = line.match(/^(#{1,3}) (.*)/);
    if (m) wrap.append(h(`h${m[1].length + 2}`, {}, inline(m[2], opts)));
    else if (line.startsWith('> ')) wrap.append(h('blockquote', {}, inline(line.slice(2), opts)));
    else wrap.append(h('p', {}, inline(line, opts)));
  }
  return wrap;
}
export function inline(text, opts = {}) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|_[^_]+_|\[\[?[a-z]+-\d+\]?\])/g;
  let last = 0;
  let m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const t = m[0];
    if (t.startsWith('**')) out.push(h('strong', {}, t.slice(2, -2)));
    else if (t.startsWith('`')) out.push(h('code', {}, t.slice(1, -1)));
    else if (t.startsWith('_')) out.push(h('em', {}, t.slice(1, -1)));
    else out.push(chip(t.replace(/[[\]]/g, ''), { max: opts.chipMax || 34 }));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function ago(iso) {
  if (!iso) return '';
  const s = (Date.now() - Date.parse(iso)) / 1000;
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

/** Live job card: status, progress bar, latest message, step trace, cancel. */
export function jobCard(jobOrId, { onDone, title, open } = {}) {
  const id = typeof jobOrId === 'string' ? jobOrId : jobOrId.id;
  const el = h('div', { class: 'job-card' });
  let finished = false;
  const paint = (j) => {
    const steps = j.steps || [];
    const pct = j.status === 'succeeded' ? 100 : Math.round((j.progress || 0) * 100);
    clear(el,
      h('div', { class: 'job-head' },
        h('strong', {}, title || j.kind), h('span', { class: 'muted mono' }, id), badge(j.status, { succeeded: 'ok', failed: 'bad', running: 'info', queued: 'muted', cancelled: 'muted', interrupted: 'warn' }[j.status] || ''),
        ['queued', 'running'].includes(j.status) ? button('Cancel', () => api.post(`/api/jobs/${id}/cancel`), 'sm ghost') : null),
      h('div', { class: `bar ${j.status}` }, h('span', { style: `width:${Math.max(4, pct)}%` })),
      h('div', { class: 'job-msg' }, j.message || ''),
      steps.length ? h('details', { class: 'trace', open: open || null }, h('summary', {}, `${steps.length} step(s)`),
        h('ol', {}, steps.map((s) => h('li', {}, s.msg)))) : null,
      j.error ? h('div', { class: 'err' }, j.error.message) : null);
  };
  paint(typeof jobOrId === 'string' ? { id, kind: title || 'job', status: 'queued', message: 'Queued', steps: [] } : jobOrId);
  api.waitJob(id, paint).then((j) => { if (!finished) { finished = true; onDone && onDone(j); } });
  return el;
}

/** Run a tool and show its job card in `slot`. Resolves to data (or null on error). */
export async function runInto(slot, name, input, { title, open, quiet } = {}) {
  const env = await api.tool(name, input);
  if (env.status === 'error') { toast(env.error.message, 'bad'); return null; }
  if (env.status === 'needs_approval') { toast(env.data.message, 'warn'); return { needs_approval: env.data }; }
  if (env.status === 'ok') return env.data;
  return new Promise((resolve) => {
    const card = jobCard(env.job_id, {
      title: title || name, open,
      onDone: (j) => {
        if (j.status === 'succeeded') { if (!quiet) toast(`${title || name}: done`, 'ok'); resolve(j.result); }
        else { toast(`${title || name}: ${j.status}`, 'bad'); resolve(null); }
      },
    });
    if (slot) clear(slot, card);
  });
}

export function section(title, ...children) {
  return h('section', { class: 'card' }, title ? h('h3', {}, title) : null, ...children);
}

export function empty(text) { return h('div', { class: 'empty' }, text); }

export function table(cols, rows) {
  return h('table', { class: 'tbl' }, h('thead', {}, h('tr', {}, cols.map((c) => h('th', {}, c)))),
    h('tbody', {}, rows.map((r) => h('tr', {}, r.map((c) => h('td', {}, c))))));
}

export function download(artifactId, text) {
  return h('a', { class: 'btn sm ghost', href: api.scoped(`/api/artifacts/${artifactId}?download=1`) }, text || 'Download');
}

export function sayToChat(text) {
  window.dispatchEvent(new CustomEvent('vrp:ask', { detail: text }));
}

export { state };
