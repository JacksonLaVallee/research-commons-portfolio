// C1 Research Graph: find nodes, explore a node's neighbourhood, add notes, export.
import * as api from '../api.js';
import { state, node } from '../store.js';
import { h, clear, chip, typeBadge, statusBadge, originBadge, reviewButtons, focusButton, section, empty, button,
         runInto, download, hrefFor, label, TYPES, toast, sayToChat } from '../ui.js';
import { head, live, go } from './common.js';

const SVG = 'http://www.w3.org/2000/svg';
const s = (tag, attrs, ...kids) => {
  const el = document.createElementNS(SVG, tag);
  Object.entries(attrs || {}).forEach(([k, v]) => v !== null && v !== undefined && el.setAttribute(k, v));
  kids.forEach((k) => el.append(k));
  return el;
};
const color = (t) => getComputedStyle(document.documentElement).getPropertyValue(`--t-${t}`).trim() || '#888';

export async function render(el, { query, sub }) {
  const center = query.node || state.focus[0] || (state.graph.nodes.find((n) => n.type === 'assumption') || state.graph.nodes[0] || {}).id;
  const hops = Number(query.hops || 1);
  const side = h('div');
  const main = h('div');
  const jobs = h('div');
  el.append(head('Research graph', 'Every paper, claim, assumption, gap, experiment and draft is a node. Dashed orange edges were added by AI and wait for review.',
    button('Rebuild links', () => runInto(jobs, 'graph.rebuild_links', { node_ids: [] }, { title: 'Rebuild links', open: true }), 'sm')),
  jobs, h('div', { class: 'grid-side' }, side, main));
  side.append(finder(), exporter());
  return live(main, sub, () => explore(center, hops));
}

function finder() {
  const q = h('input', { type: 'search', placeholder: 'Find nodes, e.g. self-report sleep' });
  const type = h('select', {}, h('option', { value: '' }, 'All types'), Object.entries(TYPES).map(([k, v]) => h('option', { value: k }, v)));
  const out = h('div');
  const run = async () => {
    const r = await api.tool('graph.find', { text: q.value || undefined, types: type.value ? [type.value] : undefined, limit: 15 });
    clear(out, r.data.nodes.length ? h('ul', { class: 'list' }, r.data.nodes.map((n) => h('li', {},
      h('a', { href: `#/graph?node=${n.id}` }, n.title), h('div', { class: 'row small muted' }, typeBadge(n.type), n.score != null ? `score ${n.score}` : '')))) : empty('No matches.'));
  };
  q.addEventListener('keydown', (e) => e.key === 'Enter' && run());
  type.addEventListener('change', run);
  return section('Find', h('div', { class: 'stack' }, h('div', { class: 'row' }, q), h('div', { class: 'row' }, type, button('Find', run, 'sm'))), out);
}

function exporter() {
  const slot = h('span');
  return section('Export', h('div', { class: 'row' },
    ['graphml', 'cytoscape_json'].map((f) => button(f === 'graphml' ? 'GraphML' : 'Cytoscape JSON', async () => {
      const r = await api.tool('graph.export', { format: f });
      clear(slot, download(r.data.artifact_id, `Download (${r.data.nodes} nodes, ${r.data.edges} edges)`));
    }, 'sm')), slot));
}

async function explore(id, hops) {
  if (!id) return empty('The graph is empty.');
  const r = await api.tool('graph.neighbors', { node_id: id, hops, limit: 60 });
  if (r.status !== 'ok') return empty(r.error.message);
  const { nodes, edges } = r.data;
  const n = node(id);
  return [
    section(h('span', {}, 'Neighbourhood of ', chip(id, { max: 50 })),
      h('div', { class: 'row small', style: 'margin-bottom:.4rem' }, 'Hops:',
        [1, 2].map((k) => h('a', { class: `btn sm ${k === hops ? 'on' : 'ghost'}`, href: `#/graph?node=${id}&hops=${k}` }, k)),
        h('span', { class: 'muted' }, `${nodes.length} nodes · ${edges.length} edges · click a node to recentre`)),
      svg(id, nodes, edges)),
    n ? details(n, edges) : null,
  ];
}

function svg(centerId, nodes, edges) {
  const W = 560, H = 420, cx = W / 2, cy = H / 2;
  const others = nodes.filter((n) => n.id !== centerId);
  const direct = new Set(edges.flatMap((e) => (e.src_id === centerId ? [e.dst_id] : e.dst_id === centerId ? [e.src_id] : [])));
  const ring1 = others.filter((n) => direct.has(n.id));
  const ring2 = others.filter((n) => !direct.has(n.id));
  const pos = { [centerId]: [cx, cy] };
  const place = (arr, r, off) => arr.forEach((n, i) => {
    const a = off + (2 * Math.PI * i) / Math.max(arr.length, 1);
    pos[n.id] = [cx + r * 1.25 * Math.cos(a), cy + r * Math.sin(a)];
  });
  place(ring1, ring2.length ? 95 : 150, -Math.PI / 2);
  place(ring2, 175, -Math.PI / 2 + 0.25);
  const root = s('svg', { class: 'graph-svg', viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Node neighbourhood graph' });
  edges.forEach((e) => {
    const a = pos[e.src_id], b = pos[e.dst_id];
    if (!a || !b) return;
    root.append(s('line', { x1: a[0], y1: a[1], x2: b[0], y2: b[1], class: `edge ${e.review_status === 'unreviewed' ? 'unreviewed' : ''}` }));
    if (e.src_id === centerId || e.dst_id === centerId) {
      root.append(s('text', { x: (a[0] + b[0]) / 2, y: (a[1] + b[1]) / 2 - 3, 'text-anchor': 'middle', class: 'elabel' }, e.type.replace('_', ' ')));
    }
  });
  [nodes.find((n) => n.id === centerId), ...others].filter(Boolean).forEach((n) => {
    const [x, y] = pos[n.id];
    const g = s('g', { class: `gnode ${n.id === centerId ? 'center' : ''}`, tabindex: 0, role: 'link', 'aria-label': `${TYPES[n.type]}: ${n.title}` },
      s('title', {}, `${TYPES[n.type]} ${n.id}: ${n.title}`),
      s('circle', { cx: x, cy: y, r: n.id === centerId ? 13 : 9, fill: color(n.type) }),
      s('text', { x, y: y + (n.id === centerId ? 26 : 21), 'text-anchor': 'middle' }, label(n, 26)));
    const open = () => go(`#/graph?node=${n.id}`);
    g.addEventListener('click', open);
    g.addEventListener('keydown', (e) => e.key === 'Enter' && open());
    root.append(g);
  });
  return root;
}

function details(n, edges) {
  const note = h('textarea', { rows: 2, placeholder: `Note about ${n.id}. Use [[id]] to link more nodes.` });
  const mine = edges.filter((e) => e.src_id === n.id || e.dst_id === n.id);
  const text = n.props.text || n.props.rationale || n.props.abstract || n.props.objective || n.props.body_md || n.props.query || '';
  const page = hrefFor(n.id);
  return section(h('span', {}, typeBadge(n.type), ' ', n.title),
    h('div', { class: 'row' }, statusBadge(n.review_status), originBadge(n.origin), h('code', { class: 'muted' }, n.id),
      focusButton(n.id), reviewButtons(n.id, n.review_status),
      page.startsWith('#/graph') ? null : h('a', { class: 'btn sm', href: page }, 'Open in its view'),
      button('Ask chat', () => sayToChat(`Tell me about [${n.id}]`), 'sm ghost')),
    text ? h('p', { style: 'margin-top:.6rem' }, text) : null,
    h('p', { class: 'small muted' }, `Created by ${n.created_by}`),
    h('h4', {}, `Edges (${mine.length})`),
    h('ul', { class: 'list' }, mine.map((e) => {
      const other = e.src_id === n.id ? e.dst_id : e.src_id;
      return h('li', { class: 'row between' },
        h('span', { class: 'row' }, e.src_id === n.id ? '→' : '←', h('code', {}, e.type), chip(other, { max: 50 }),
          e.props.note ? h('span', { class: 'small muted' }, e.props.note) : null),
        h('span', { class: 'row' }, statusBadge(e.review_status), h('span', { class: 'small muted' }, `conf ${e.confidence}`), reviewButtons(e.id, e.review_status)));
    })),
    h('h4', {}, 'Add a note'),
    note,
    h('div', { class: 'row', style: 'margin-top:.4rem' }, button('Add note', async () => {
      if (!note.value.trim()) return;
      const r = await api.tool('graph.add_note', { body_md: note.value, about_ids: [n.id] });
      if (r.status === 'ok') { note.value = ''; toast(`Note ${r.data.node_id} linked to ${r.data.edge_ids.length} node(s)`, 'ok'); }
    }, 'sm primary')));
}
