// C4 Field Map: topic clusters, their trend since the last snapshot, and the papers in each.
import * as api from '../api.js';
import { node, edgesOf } from '../store.js';
import { h, chip, badge, section, empty, button, runInto, focusButton, sayToChat } from '../ui.js';
import { head, live } from './common.js';

const TREND = { grew: ['▲ grew', 'ok'], shrank: ['▼ shrank', 'bad'], new: ['new', 'info'], stable: ['stable', 'muted'] };

export async function render(el, { id, sub }) {
  const jobs = h('div');
  const body = h('div');
  el.append(head('Field map', 'Papers clustered into topics. Each rebuild saves a snapshot, so you can see which topics grew since last time.',
    button('Rebuild map', () => runInto(jobs, 'fieldmap.build', { scope: 'project' }, { title: 'Rebuild field map', open: true }), 'primary')),
  jobs, body);
  return live(body, sub, () => view(id));
}

async function view(id) {
  const r = (await api.tool('fieldmap.trends', {})).data;
  if (!r.topics.length) return empty('No snapshot yet. Rebuild the map.');
  const max = Math.max(...r.topics.map((t) => t.size), 1);
  const sel = id && r.topics.find((t) => t.topic_id === id);
  const compareSlot = h('div');
  return h('div', { class: 'grid2' },
    section(`${r.topics.length} topics`,
      h('p', { class: 'muted small' }, `Snapshot ${r.snapshot_id}${r.compared_to ? ` compared with ${r.compared_to}` : ''} · k=${r.k} · silhouette ${r.silhouette}`),
      r.topics.map((t) => h('a', { class: `hbar ${sel && sel.topic_id === t.topic_id ? 'sel' : ''}`, href: `#/fieldmap/${t.topic_id}` },
        h('span', { class: 'name' }, t.label),
        h('span', { class: 'track' }, h('span', { class: 'fill', style: `display:block;width:${(100 * t.size) / max}%` })),
        h('span', { class: 'row' }, h('b', {}, t.size), badge(TREND[t.trend][0] + (t.delta && t.trend !== 'new' ? ` ${t.delta > 0 ? '+' : ''}${t.delta}` : ''), TREND[t.trend][1]))))),
    sel ? section(sel.label,
      h('div', { class: 'row' }, focusButton(sel.topic_id),
        button('Compare claims in this topic', () => runInto(compareSlot, 'evidence.compare', { topic_id: sel.topic_id }, { title: 'Compare claims', open: true }), 'sm'),
        button('Ask chat', () => sayToChat(`What is trending in the field map? Tell me about [${sel.topic_id}]`), 'sm ghost')),
      compareSlot,
      h('ul', { class: 'list' }, sel.paper_ids.map((pid) => {
        const p = node(pid);
        const claims = edgesOf(pid, 'derived_from').length;
        return h('li', {}, chip(pid, { full: true, max: 100 }), h('div', { class: 'small muted' }, p ? `${p.props.year} · ${claims} claim(s)` : ''));
      })))
      : section('Topic', empty('Pick a topic to see its papers.')));
}
