// C8 Funding: confirm the researcher, then rank open opportunities against them and the project's topics.
import * as api from '../api.js';
import { nodesOf, loadGraph } from '../store.js';
import { h, clear, chip, badge, section, empty, table, button, runInto, focusButton, toast } from '../ui.js';
import { head, live, fmt } from './common.js';

let researcherId = null;

export async function render(el, { query, sub }) {
  const res = h('div');
  const jobs = h('div');
  const body = h('div');
  el.append(head('Funding', 'Find researchers on OpenAlex and current opportunities on Grants.gov. Keyword fit is a screening aid; check eligibility in the official announcement.'),
    h('div', { class: 'grid-side' }, h('div', {}, identify(res), res, finder(jobs), jobs), body));
  return live(body, sub, () => grants(query.grant));
}

function identify(out) {
  const name = h('input', { type: 'text', placeholder: 'Researcher name' });
  return section('1. Who is applying?', h('div', { class: 'row' }, name, button('Find', async () => {
    const r = await api.tool('funding.identify', { name: name.value });
    if (r.status !== 'ok') return toast(r.error.message, 'bad');
    await loadGraph();
    clear(out, section('Pick the right person', r.data.candidates.length ? h('ul', { class: 'list' }, r.data.candidates.map((c) => {
      const pick = h('input', { type: 'radio', name: 'researcher', checked: researcherId === c.researcher_id || null });
      pick.addEventListener('change', () => { researcherId = c.researcher_id; });
      return h('li', {}, h('label', { class: 'check' }, pick, h('strong', {}, c.name)),
        h('div', { class: 'small muted' }, `${c.affiliation} · ORCID ${c.orcid} · ${c.works_count} works · ${c.topics.join(', ')}`));
    })) : empty('No match.')));
  }, 'sm')));
}

function finder(jobs) {
  return section('2. Find grants', h('div', { class: 'stack small' },
    h('p', {class:'muted'}, 'Search posted and forecasted opportunities using project topics or the selected researcher’s topics.'),
    button('Find grants', async () => {
      if (!researcherId) toast('No researcher picked; ranking on project topics only.', 'warn');
      const d = await runInto(jobs, 'funding.find', { researcher_id: researcherId || undefined },
        { title: 'GrantScout', open: true });
      if (d) toast(`${d.ranked.length} grant(s) ranked · ${d.usage.llm_calls} LLM calls`, 'ok');
    }, 'primary')));
}

function grants(selected) {
  const gs = nodesOf('grant').slice().sort((a, b) => b.props.fit_score - a.props.fit_score);
  return section(`Opportunities (${gs.length})`, gs.length ? h('div', { class: 'tbl-wrap' }, table(['Grant', 'Fit', 'Deadline', 'Why', ''], gs.map((g) => [
    h('div', { style: g.id === selected ? 'font-weight:700' : null }, g.title, h('div', { class: 'small muted' }, `${g.props.agency || ''} ${g.props.opportunity_id}`)),
    badge(fmt(g.props.fit_score) + '/100', g.props.fit_score >= 40 ? 'ok' : g.props.fit_score >= 25 ? 'warn' : 'muted'),
    g.props.deadline,
    h('span', { class: 'small' }, g.props.reason),
    h('div', { class: 'row' }, focusButton(g.id), h('a', { href: g.props.source_url, target: '_blank', rel: 'noopener', class: 'small' }, 'Source')),
  ]))) : empty('No grants yet. Pick a researcher and find grants.'),
  gs.length ? h('p', { class: 'small muted' }, 'Grants link to topics in the graph, so ', chip(gs[0].id), ' shows up next to the work it would fund.') : null);
}
