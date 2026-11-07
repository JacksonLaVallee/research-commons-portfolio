// Shared client state: project, graph snapshot, focus set (research context), jobs and events.
import { get, PROJECT_ID } from './api.js';

const subs = {};
export function on(topic, fn) {
  (subs[topic] = subs[topic] || new Set()).add(fn);
  return () => subs[topic].delete(fn);
}
export function emit(topic, data) { (subs[topic] || []).forEach((fn) => { try { fn(data); } catch (e) { console.error(e); } }); }

function load(key, fallback) {
  try { const v = localStorage.getItem(`commons.${PROJECT_ID}.${key}`); return v ? JSON.parse(v) : fallback; } catch { return fallback; }
}
function save(key, value) { try { localStorage.setItem(`commons.${PROJECT_ID}.${key}`, JSON.stringify(value)); } catch { /* storage unavailable */ } }

export const state = {
  project: null,
  graph: { nodes: [], edges: [] },
  byId: new Map(),
  focus: load('focus', []),
  jobs: [],
  events: [],
  connected: false,
};

export const node = (id) => state.byId.get(id);
export const nodesOf = (type) => state.graph.nodes.filter((n) => n.type === type);
export const edgesOf = (id, type) => state.graph.edges.filter((e) => (e.src_id === id || e.dst_id === id) && (!type || e.type === type));

export async function loadGraph() {
  const g = await get('/api/graph');
  state.graph = g;
  state.byId = new Map(g.nodes.map((n) => [n.id, n]));
  state.focus = state.focus.filter((id) => state.byId.has(id));
  emit('graph');
}
export async function loadProject() { state.project = await get('/api/project'); emit('project'); }
export async function loadJobs() { state.jobs = (await get('/api/jobs?limit=60')).jobs; emit('jobs'); }

// ---- focus set: the research context carried across every view and into chat
export function isFocused(id) { return state.focus.includes(id); }
export function toggleFocus(id) {
  state.focus = isFocused(id) ? state.focus.filter((x) => x !== id) : [...state.focus, id].slice(-8);
  save('focus', state.focus);
  emit('focus');
}
export function setFocus(ids) { state.focus = ids.slice(-8); save('focus', state.focus); emit('focus'); }

// ---- live updates
let timer = null;
const GRAPH_EVENTS = /^(node|edge|note|approval|draft|fieldmap|paper|claims|run)\./;
export function handleEvent(ev) {
  if (ev.type === 'workspace.reset') { location.hash = '#/home'; location.reload(); return; }
  if (ev.type !== 'job.progress') {
    state.events.unshift(ev);
    state.events = state.events.slice(0, 150);
  }
  emit('event', ev);
  const graphy = GRAPH_EVENTS.test(ev.type) || ev.type === 'job.finished';
  clearTimeout(timer);
  timer = setTimeout(async () => {
    if (graphy) { await loadGraph(); await loadProject(); }
    await loadJobs();
  }, ev.type === 'job.progress' ? 400 : 200);
}

export const prefs = { get: load, set: save };
