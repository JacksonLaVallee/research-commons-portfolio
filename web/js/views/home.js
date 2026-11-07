// Home: the research question, the trail from literature to report, the review queue, recent activity.
import * as api from '../api.js';
import { state, nodesOf } from '../store.js';
import { h, chip, typeBadge, statusBadge, reviewButtons, focusButton, section, empty, button, ago, toast } from '../ui.js';
import { head, live } from './common.js';

const TRAIL = [
  ['search', 'Find literature', () => `${nodesOf('search').length} searches`],
  ['library', 'Read & extract', () => `${nodesOf('paper').length} papers, ${nodesOf('claim').length} claims`],
  ['fieldmap', 'Map the field', () => `${nodesOf('topic').length} topics`],
  ['gaps', 'Find gaps', () => `${nodesOf('gap').length} gaps flagged`],
  ['experiments', 'Test with data', () => `${nodesOf('experiment').length} recipes, ${nodesOf('run').length} runs`],
  ['writing', 'Write & share', () => `${nodesOf('draft').length} drafts, ${nodesOf('report').length} reports`],
];

function eventLine(ev) {
  const ids = (ev.target_ids || []).filter((id) => /^[a-z]+-\d+$/.test(id) && !id.startsWith('job-') && !id.startsWith('e-')).slice(0, 4);
  return h('li', {}, h('div', { class: 'row between' }, h('code', {}, ev.type), h('span', { class: 'muted small' }, ago(ev.ts))),
    h('div', { class: 'row small' }, h('span', { class: 'muted' }, ev.actor), ids.map((id) => chip(id, { max: 30 }))));
}

export function render(el, { sub }) {
  const body = h('div');
  el.append(body);
  return live(body, sub, () => {
    const p = state.project;
    const queue = state.graph.nodes.filter((n) => n.review_status === 'unreviewed');
    const counts = p.counts || {};
    return [
      head(p.name, null,
        h('a', { href: '#/settings', class: 'btn ghost sm' }, 'Projects & settings')),
      h('div', { class: 'callout' }, h('strong', {}, 'Research question: '), p.question),
      h('div', { class: 'tiles' },
        [['papers', counts.paper, '#/library'], ['claims', counts.claim, '#/evidence'], ['assumptions', counts.assumption, '#/evidence?type=assumption'],
         ['gaps', counts.gap || 0, '#/gaps'], ['to review', p.unreviewed, '#/evidence?status=unreviewed'],
         ['approvals pending', p.pending_approvals, '#/experiments']].map(([t, n, href]) =>
          h('a', { class: 'tile', href }, h('b', {}, n ?? 0), h('span', {}, t)))),
      section('Research trail', h('p', { class: 'muted small' }, 'Every step reads and writes the same research graph, so results carry forward.'),
        h('div', { class: 'trail' }, TRAIL.map(([r, t, sub2]) => h('a', { href: `#/${r}` }, t, h('small', {}, sub2()))))),
      h('div', { class: 'grid2' },
        section(`Review queue (${queue.length})`,
          h('p', { class: 'muted small' }, 'AI-created items stay unreviewed until you accept or dismiss them.'),
          queue.length ? h('ul', { class: 'list' }, queue.slice(0, 10).map((n) => h('li', {},
            h('div', { class: 'row' }, typeBadge(n.type), chip(n.id, { full: true, max: 90 })),
            h('div', { class: 'row', style: 'margin-top:.3rem' }, statusBadge(n.review_status), reviewButtons(n.id, n.review_status), focusButton(n.id)))))
            : empty('Nothing waiting for review.'),
          queue.length > 10 ? h('a', { href: '#/evidence?status=unreviewed', class: 'small' }, `All ${queue.length} →`) : null),
        section('Recent activity',
          state.events.length ? h('ul', { class: 'list' }, state.events.slice(0, 12).map(eventLine)) : empty('No events yet.'),
          h('a', { href: '#/activity', class: 'small' }, 'Jobs and full log →'))),
      h('p', { class: 'muted small' }, `AI: ${p.llm_mode} · similarity: ${p.similarity} · source evidence, measured results and review decisions share one project graph.`),
    ];
  }, ["graph", "project"]);
}
