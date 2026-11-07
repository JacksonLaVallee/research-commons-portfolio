// C5 Claims & Evidence: review extracted claims and assumptions, and labelled relations between claims.
import { state, node, nodesOf } from '../store.js';
import { h, chip, badge, statusBadge, groundingBadge, reviewButtons, focusButton, section, empty, table, button, runInto, review } from '../ui.js';
import { head, live, go } from './common.js';

const RELATIONS = ['conflict', 'scope_difference', 'measured_gap', 'equivalent', 'unresolved', 'supports', 'contradicts'];
const REL_KIND = { conflict: 'bad', contradicts: 'bad', scope_difference: 'warn', measured_gap: 'info', equivalent: 'ok', supports: 'ok' };

export async function render(el, { query, sub }) {
  const type = query.type || 'all';
  const status = query.status || 'all';
  const jobs = h('div');
  const filters = h('div', { class: 'row' },
    'Show', select(['all', 'claim', 'assumption'], type, (v) => go(`#/evidence?type=${v}&status=${status}`)),
    'with status', select(['all', 'unreviewed', 'accepted', 'dismissed'], status, (v) => go(`#/evidence?type=${type}&status=${v}`)));
  const body = h('div');
  el.append(head('Claims & evidence',
    'Claims and assumptions extracted from papers, each with a verbatim quote and page. A skeptic pass drops claims whose quote is not found in the paper.',
    button('Compare all claims', () => runInto(jobs, 'evidence.compare', { claim_ids: [] }, { title: 'Compare claims', open: true }), 'primary')),
  jobs, filters, body);
  return live(body, sub, () => view(type, status));
}

function select(opts, cur, onchange) {
  const s = h('select', {}, opts.map((o) => h('option', { value: o, selected: o === cur || null }, o)));
  s.addEventListener('change', () => onchange(s.value));
  return s;
}

function view(type, status) {
  let items = [...nodesOf('claim'), ...nodesOf('assumption')];
  if (type !== 'all') items = items.filter((n) => n.type === type);
  if (status !== 'all') items = items.filter((n) => n.review_status === status);
  const unrev = items.filter((n) => n.review_status === 'unreviewed').map((n) => n.id);
  const rels = state.graph.edges.filter((e) => RELATIONS.includes(e.type) && e.review_status !== 'dismissed');
  return [
    section(h('span', {}, `Relations between claims (${rels.length})`),
      h('p', { class: 'muted small' }, 'Conditions are compared before labelling, so a difference in population or adjustment is not called a conflict.'),
      rels.length ? h('ul', { class: 'list' }, rels.map((e) => h('li', {},
        h('div', { class: 'row' }, chip(e.src_id, { max: 60 }), badge(e.type.replace('_', ' '), REL_KIND[e.type] || ''), chip(e.dst_id, { max: 60 })),
        e.props.note ? h('p', { class: 'small', style: 'margin:.3rem 0' }, e.props.note) : null,
        e.props.conditions ? h('details', {}, h('summary', {}, 'Conditions compared'),
          table(['', node(e.src_id) ? e.src_id : 'A', node(e.dst_id) ? e.dst_id : 'B'],
            Object.entries(e.props.conditions).map(([k, v]) => [k.replace('_', ' '), ...(Array.isArray(v) ? v : [v, ''])]))) : null,
        h('div', { class: 'row' }, statusBadge(e.review_status), reviewButtons(e.id, e.review_status))))) : empty('No relations yet. Run a comparison.')),
    section(h('span', {}, `${type === 'all' ? 'Claims and assumptions' : `${type}s`} (${items.length})`,
      unrev.length ? button(`Accept all ${unrev.length} unreviewed`, () => review(unrev, 'accept'), 'sm ok') : null),
      items.length ? h('div', { class: 'tbl-wrap' }, table(['Item', 'Source and quote', 'Review'], items.map((n) => {
        const quotes = n.type === 'assumption' ? n.props.quotes || [] : [n.props];
        return [
          h('div', {}, h('div', { class: 'row' }, badge(n.type, n.type === 'assumption' ? 'warn' : ''), n.props.explicit === false ? badge('implicit') : null),
            h('div', { style: 'margin-top:.2rem' }, n.title)),
          h('div', {}, quotes.map((q) => h('div', { style: 'margin-bottom:.35rem' },
            h('div', { class: 'row' }, chip(q.paper_id, { max: 24 }), h('a', { href: `#/paper/${q.paper_id}?passage=${q.passage_id}`, class: 'small' }, `p.${q.page}`), groundingBadge(q.grounding)),
            h('div', { class: 'quote small muted' }, `“${q.quote}”`)))),
          h('div', { class: 'stack' }, statusBadge(n.review_status), reviewButtons(n.id, n.review_status), focusButton(n.id),
            n.type === 'assumption' ? h('a', { class: 'small', href: `#/graph?node=${n.id}` }, 'See what relies on it') : null),
        ];
      }))) : empty('Nothing matches these filters.')),
  ];
}
