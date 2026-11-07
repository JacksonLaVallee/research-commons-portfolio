// Activity: the job queue (with cancel and retry), the event log, and the tool catalog every view and the chat share.
import * as api from '../api.js';
import { state } from '../store.js';
import { h, chip, badge, section, empty, table, button, jobCard, ago, toast } from '../ui.js';
import { head, live } from './common.js';

const STATUS = { succeeded: 'ok', failed: 'bad', running: 'info', queued: 'muted', cancelled: 'muted', interrupted: 'warn', cancel_requested: 'warn' };

export async function render(el, { query, sub }) {
  const tab = query.tab || 'jobs';
  const body = h('div');
  el.append(head('Activity & tools', 'Background jobs, the event log that wires components together, and the one tool registry behind the UI and chat.'),
    h('div', { class: 'tabs' }, [['jobs', 'Jobs'], ['events', 'Event log'], ['tools', 'Tool catalog']].map(([k, t]) =>
      h('a', { href: `#/activity?tab=${k}`, class: k === tab ? 'active' : null }, t))),
    ...(tab === 'jobs' && query.job ? [jobCard(query.job, { open: true })] : []), body);
  if (tab === 'tools') return live(body, sub, tools, []);
  if (tab === 'events') return live(body, sub, events, ['jobs']);
  return live(body, sub, jobs, ['jobs']);
}

function jobs() {
  const js = state.jobs;
  return [
    section(`Jobs (${js.length})`, h('p', { class: 'muted small' }, 'Jobs run in a separate worker process. Events from one job queue follow-up jobs (for example, a saved paper triggers extraction).'),
      js.length ? h('div', { class: 'tbl-wrap' }, table(['Job', 'Status', 'Message', 'Caller', 'When', ''], js.map((j) => [
        h('div', {}, h('a', { href: `#/activity?tab=jobs&job=${j.id}` }, h('code', {}, j.id)), h('div', { class: 'small' }, j.kind)),
        badge(j.status, STATUS[j.status]),
        h('span', { class: 'small' }, j.message),
        h('span', { class: 'small muted' }, j.caller, j.parent_event_id ? ` (event ${j.parent_event_id})` : ''),
        h('span', { class: 'small muted' }, ago(j.created_at)),
        ['queued', 'running'].includes(j.status) ? button('Cancel', () => api.post(`/api/jobs/${j.id}/cancel`), 'sm ghost')
          : ['failed', 'interrupted', 'cancelled'].includes(j.status) ? button('Retry', async () => { const r = await api.post(`/api/jobs/${j.id}/retry`); toast(`Retrying as ${r.job_id}`); }, 'sm') : null,
      ]))) : empty('No jobs yet.')),
  ];
}

function events() {
  const evs = state.events;
  return section(`Events (${evs.length})`, evs.length ? h('div', { class: 'tbl-wrap' }, table(['#', 'Type', 'Actor', 'Targets', 'When'], evs.map((e) => [
    e.id, h('code', {}, e.type), h('span', { class: 'small' }, e.actor),
    h('div', { class: 'row' }, (e.target_ids || []).slice(0, 5).map((id) => (/^(job|e|snap)-/.test(id) ? h('code', { class: 'small muted' }, id) : chip(id, { max: 24 })))),
    h('span', { class: 'small muted' }, ago(e.ts)),
  ]))) : empty('No events yet.'));
}

async function tools() {
  const r = await api.get('/api/tools');
  const groups = {};
  r.tools.forEach((t) => (groups[t.component] = groups[t.component] || []).push(t));
  return [
    h('p', { class: 'muted small' }, `${r.tools.length} tools. Every tool is called through POST /api/tools/{name} and returns the same envelope. Researcher-only routes: ${r.not_in_catalog.join(', ')}.`),
    Object.entries(groups).map(([c, ts]) => section(c, table(['Tool', 'Mode', 'Effect', 'Description', 'Inputs'], ts.map((t) => [
      h('code', {}, t.name), badge(t.mode, t.mode === 'job' ? 'info' : ''),
      h('span', {}, badge(t.side_effect, t.side_effect === 'read' ? 'muted' : 'warn'), t.needs_approval ? badge('needs approval', 'bad') : null),
      h('span', { class: 'small' }, t.description),
      h('span', { class: 'small mono' }, Object.entries(t.inputs).map(([k, v]) => `${k}${v.required ? '*' : ''}: ${v.type}`).join(', ')),
    ])))),
  ];
}
