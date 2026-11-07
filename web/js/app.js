// App shell: hash router, side navigation, focus tray, live event stream, chat dock.
import * as api from './api.js';
import { state, on, loadGraph, loadProject, loadJobs, handleEvent, toggleFocus, prefs } from './store.js';
import { h, clear, chip, toast, empty } from './ui.js';
import * as chat from './views/chat.js';

const VIEWS = {
  settings: () => import('./views/settings.js'),
  home: () => import('./views/home.js'),
  chat: () => import('./views/chat.js'),
  library: () => import('./views/library.js'),
  paper: () => import('./views/library.js'),
  search: () => import('./views/search.js'),
  fieldmap: () => import('./views/fieldmap.js'),
  graph: () => import('./views/graph.js'),
  evidence: () => import('./views/evidence.js'),
  gaps: () => import('./views/gaps.js'),
  experiments: () => import('./views/experiments.js'),
  writing: () => import('./views/writing.js'),
  funding: () => import('./views/funding.js'),
  activity: () => import('./views/activity.js'),
};

const NAV = [
  ['Workspace', [['home', 'Overview'], ['activity', 'Activity & tools'], ['settings', 'Projects & settings']]],
  ['Research', [['library', 'Library'], ['search', 'Literature search'], ['fieldmap', 'Field map'], ['graph', 'Research graph'],
                ['evidence', 'Claims & evidence'], ['gaps', 'Gaps & assumptions']]],
  ['Experiment', [['experiments', 'Experiments & data']]],
  ['Communicate', [['writing', 'Writing & reports'], ['funding', 'Funding']]],
  ['Assistant', [['chat', 'Chat (full page)']]],
];
const NAV_ALIAS = { paper: 'library' };

export function parseHash() {
  const raw = location.hash.replace(/^#\/?/, '') || 'home';
  const [path, qs] = raw.split('?');
  const [name, id] = path.split('/');
  return { name: VIEWS[name] ? name : 'home', id: id ? decodeURIComponent(id) : null, query: Object.fromEntries(new URLSearchParams(qs || '')) };
}

// ---- navigation
function navCount(name) {
  const p = state.project;
  if (!p) return null;
  const unrev = (t) => state.graph.nodes.filter((n) => n.type === t && n.review_status === 'unreviewed').length;
  const n = { evidence: unrev('claim') + unrev('assumption'), gaps: unrev('gap'), experiments: p.pending_approvals,
              library: unrev('paper') }[name];
  return n ? h('span', { class: 'count', title: 'Waiting for your review or approval' }, n) : null;
}
function paintNav() {
  const cur = NAV_ALIAS[parseHash().name] || parseHash().name;
  clear(document.getElementById('sidenav'), NAV.map(([group, items]) => [
    h('h6', {}, group),
    items.map(([name, text]) => h('a', { href: `#/${name}`, class: cur === name ? 'active' : null }, h('span', {}, text), navCount(name))),
  ]));
}

// ---- focus tray: the research context that follows you
function paintFocus() {
  const tray = document.getElementById('focus-tray');
  if (!state.focus.length) {
    clear(tray, h('span', { class: 'label' }, 'Focus set empty. Use ☆ Focus on any item to carry it across views and into chat.'));
    return;
  }
  clear(tray, h('span', { class: 'label' }, `Focus (${state.focus.length}):`),
    state.focus.map((id) => {
      const c = chip(id, { max: 26 });
      c.append(h('span', { class: 'x', title: 'Remove from focus', onclick: (e) => { e.preventDefault(); e.stopPropagation(); toggleFocus(id); } }, '×'));
      return c;
    }));
}

// ---- router
let cleanups = [];
let renderSeq = 0;
async function route() {
  const seq = ++renderSeq;
  cleanups.forEach((f) => f());
  cleanups = [];
  const r = parseHash();
  paintNav();
  document.querySelector('.shell').classList.toggle('on-chat-page', r.name === 'chat');
  document.getElementById('sidenav').classList.remove('open');
  const el = document.getElementById('view');
  const mod = await VIEWS[r.name]();
  if (seq !== renderSeq) return;
  el.replaceChildren();
  const sub = (topic, fn) => cleanups.push(on(topic, fn));
  try {
    await mod.render(el, { ...r, sub, rerender: route });
  } catch (err) {
    console.error(err);
    clear(el, h('div', { class: 'callout bad' }, `This view failed to load: ${err.message}`));
  }
  if (!r.query.keep) el.scrollTop = 0;
}

// ---- boot
async function boot() {
  const shell = document.querySelector('.shell');
  const narrow = matchMedia('(max-width: 1450px)').matches;
  if (prefs.get('chatClosed', narrow)) shell.classList.add('chat-closed');
  document.getElementById('chat-toggle').addEventListener('click', () => {
    shell.classList.toggle('chat-closed');
    prefs.set('chatClosed', shell.classList.contains('chat-closed'));
  });
  document.getElementById('nav-toggle').addEventListener('click', () => document.getElementById('sidenav').classList.toggle('open'));
  window.addEventListener('vrp:ask', (e) => {
    shell.classList.remove('chat-closed');
    chat.ask(e.detail);
  });

  try {
    await Promise.all([loadProject(), loadGraph(), loadJobs()]);
  } catch (err) {
    clear(document.getElementById('view'), empty(`Could not reach the API: ${err.message}. Is python commons.py running?`));
    return;
  }
  const recent = await api.get('/api/events/recent?limit=60');
  state.events = recent.events;
  document.getElementById('project-name').textContent = state.project.name;
  document.title = `${state.project.name} · Research Commons`;

  on('focus', paintFocus);
  on('graph', paintFocus);
  on('graph', paintNav);
  on('project', paintNav);
  paintFocus();
  chat.mountDock(document.getElementById('chat-dock'));

  const conn = document.getElementById('conn');
  api.events(recent.last_id, (ev) => {
    handleEvent(ev);
    if (ev.type === 'run.finished') toast('Experiment run finished; a brief is being written.', 'ok');
    if (ev.type === 'claims.added' && ev.actor !== 'researcher') toast(`${ev.target_ids.length} new claim(s) to review`, '');
  }, (ok) => {
    state.connected = ok;
    conn.classList.toggle('on', ok);
    conn.title = ok ? 'Live: receiving events' : 'Reconnecting to the event stream…';
  });

  window.addEventListener('hashchange', route);
  route();
}

boot();
