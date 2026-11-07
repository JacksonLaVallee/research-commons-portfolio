// C6 Gaps & Assumptions: run the budgeted gap agent, review flagged gaps, and turn one into an experiment.
import * as api from '../api.js';
import { state, node, nodesOf, edgesOf, loadGraph } from '../store.js';
import { h, clear, chip, badge, statusBadge, reviewButtons, focusButton, section, empty, button, runInto, toast, sayToChat } from '../ui.js';
import { head, crumbs, live, go } from './common.js';

const TYPES = { untested_condition: 'Untested condition', method_not_carried_over: 'Method not carried over', contradiction: 'Contradiction', missing_link: 'Missing link' };
const STATUS = { open: 'bad', partly_addressed: 'warn', addressed: 'ok' };

export async function render(el, { id, sub }) {
  const listSlot = h('div');
  const main = h('div');
  el.append(head('Gaps & assumptions', 'An agent inspects the graph, retrieves passages, verifies each candidate gap and checks the literature, within a call budget. It abstains when the evidence is thin.'),
    h('div', { class: 'grid-side' }, h('div', {}, finder(), listSlot), main));
  live(listSlot, sub, () => list(id));
  return id ? live(main, sub, () => detail(id)) : clear(main, intro());
}

function intro() {
  const asm = nodesOf('assumption');
  return section('Assumptions the library relies on', h('p', { class: 'muted small' }, 'Assumptions shared by several papers are where gaps usually hide.'),
    h('ul', { class: 'list' }, asm.map((a) => h('li', {}, chip(a.id, { full: true, max: 100 }),
      h('div', { class: 'row small' }, `${(a.props.quotes || []).length} paper(s) rely on it`, statusBadge(a.review_status), focusButton(a.id))))));
}

function finder() {
  const scope = h('input', { type: 'checkbox' });
  const lit = h('input', { type: 'checkbox', checked: true });
  const budget = h('input', { type: 'number', value: 3, min: 2, max: 6, style: 'width:5rem' });
  const types = Object.keys(TYPES).map((k) => h('input', { type: 'checkbox', checked: true, value: k }));
  const slot = h('div');
  const out = h('div');
  return section('Find gaps', h('div', { class: 'stack small' },
    h('label', { class: 'check' }, scope, 'Only around my focus set'),
    h('div', {}, types.map((b, i) => h('label', { class: 'check', style: 'margin-right:.6rem' }, b, Object.values(TYPES)[i]))),
    h('label', { class: 'check' }, 'LLM call budget', budget),
    h('label', { class: 'check' }, lit, 'Check the literature for each gap'),
    button('Run gap agent', async () => {
      const d = await runInto(slot, 'gaps.find', {
        scope_ids: scope.checked ? state.focus : [], check_literature: lit.checked,
        gap_types: types.filter((b) => b.checked).map((b) => b.value),
        budget: { llm_calls: Number(budget.value) || 3, searches: 2 },
      }, { title: 'Gap agent', open: true });
      if (!d) return;
      clear(out, h('div', { class: 'callout' }, `${d.gap_ids.length} gap(s) flagged, ${d.abstained.length} abstained. Budget used: ${d.budget_used.llm_calls}/${d.budget.llm_calls} LLM calls, ${d.budget_used.searches}/${d.budget.searches} searches.`,
        d.abstained.length ? h('ul', {}, d.abstained.map((a) => h('li', {}, h('strong', {}, a.title), ': ', a.reason))) : null));
    }, 'primary'), slot, out));
}

function list(selected) {
  const gaps = nodesOf('gap');
  return section(`Flagged gaps (${gaps.length})`, gaps.length ? h('ul', { class: 'list' }, gaps.map((g) => h('li', { class: g.id === selected ? 'sel' : null },
    h('a', { href: `#/gaps/${g.id}` }, g.title),
    h('div', { class: 'row small' }, badge(TYPES[g.props.gap_type] || g.props.gap_type), badge(g.props.status.replace('_', ' '), STATUS[g.props.status]), statusBadge(g.review_status)))))
    : empty('No gaps yet. Run the gap agent.'));
}

async function detail(id) {
  const r = await api.tool('gaps.explain', { gap_id: id });
  if (r.status !== 'ok') return empty(r.error.message);
  const g = node(id) || r.data.gap;
  const p = g.props;
  const slot = h('div');
  const exps = edgesOf(id, 'tests').map((e) => e.src_id);
  const gr = r.data.grounding;
  return [
    crumbs(['Gaps', '#/gaps'], [id]),
    h('h2', {}, g.title),
    h('div', { class: 'row' }, badge(TYPES[p.gap_type] || p.gap_type), badge(p.status.replace('_', ' '), STATUS[p.status]), statusBadge(g.review_status),
      reviewButtons(id, g.review_status), focusButton(id)),
    section('Why this is a gap', h('p', {}, p.rationale),
      h('div', { class: 'row small muted' }, `Grounding of quoted evidence: ${gr.exact} exact, ${gr.fuzzy_candidate} close, ${gr.none} not checked`,
        p.budget_used ? ` · used ${p.budget_used.llm_calls} LLM calls, ${p.budget_used.searches} search(es)` : '')),
    section(`Evidence (${r.data.evidence.length})`, h('ul', { class: 'list' }, r.data.evidence.map((e) => h('li', {},
      chip(e.node_id, { full: true, max: 100 }),
      e.quote ? h('blockquote', { class: 'quote small' }, `“${e.quote}”`) : null,
      e.passage_id ? h('a', { class: 'small', href: `#/paper/${e.passage_id.split('-p')[0]}?passage=${e.passage_id}` }, 'Open passage') : null)))),
    p.literature ? section('Literature check',
      h('p', { class: 'small' }, 'Search ', chip(p.literature.search_id), ` found ${p.literature.possible_matches.length} possible match(es) not yet in the library.`),
      p.literature.possible_matches.length ? h('ul', { class: 'list' }, p.literature.possible_matches.map((m) => h('li', { class: 'row between' },
        h('span', {}, m.title), button('Save to library', async () => {
          const d = await runInto(slot, 'search.save', { candidate_ids: [m.candidate_id], search_id: p.literature.search_id }, { title: 'Save paper' });
          if (d) toast('Saved. Re-run the gap agent to see if this changes the gap.', 'ok');
        }, 'sm')))) : null) : null,
    section('Act on it',
      h('div', { class: 'row' },
        exps.length ? exps.map((e) => h('a', { class: 'btn sm', href: `#/experiments/${e}` }, `Open ${e}`)) : null,
        button('Plan an experiment to test this', async () => {
          const d = await api.tool('experiment.propose', { objective: `Test: ${g.title}`, gap_id: id });
          if (d.status !== 'ok') return toast(d.error.message, 'bad');
          await loadGraph();
          go(`#/experiments/${d.data.recipe_id}`);
        }, 'primary sm'),
        button('Search further', async () => {
          const d = await runInto(slot, 'search.papers', { query: g.title.split(' ').slice(0, 8).join(' '), launched_from: { node_id: id }, limit: 10 }, { title: 'Search' });
          if (d) { await loadGraph(); go(`#/search/${d.search_id}`); }
        }, 'sm'),
        button('Ask chat', () => sayToChat(`Tell me about [${id}]`), 'sm ghost')),
      slot),
  ];
}
