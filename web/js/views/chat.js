// C7 Unified Chat. One conversation shared by the side dock and the full-page view.
// The chat sends the focus set and the current route as context, shows each tool call
// as it happens, and renders only citations that exist in the graph.
import * as api from '../api.js';
import { state, on } from '../store.js';
import { h, clear, chip, rich, badge, toast } from '../ui.js';

const conversationId = `conv-${Date.now().toString(36)}`;
const messages = [];
const roots = new Set();
let busy = false;

const SUGGESTIONS = [
  'What gaps are there?',
  'Are there conflicts between the claims?',
  'Search for papers about the research question',
  'save the first 2',
  'propose an experiment',
  'run the experiment',
  'Which grants fit this project?',
  'Check the draft for unsupported citations',
  'Tell me about these',
  'What evidence is missing?',
];

export async function ask(text) {
  text = (text || '').trim();
  if (!text || busy) return;
  busy = true;
  const bot = { role: 'bot', steps: [], answer: null };
  messages.push({ role: 'user', text, context: [...state.focus] }, bot);
  paintAll();
  try {
    await api.chat({ message: text, conversation_id: conversationId,
                     context: { node_ids: state.focus, route: location.hash } }, (ev, data) => {
      if (ev === 'step') {
        const i = bot.steps.findIndex((s) => s.step === data.step);
        if (i >= 0) bot.steps[i] = { ...bot.steps[i], ...data }; else bot.steps.push(data);
      } else if (ev === 'answer') {
        bot.answer = data;
      }
      paintAll();
    });
  } catch (err) {
    bot.answer = { answer: `Chat failed: ${err.message}`, citations: [], removed_citations: [], actions: [] };
    toast(err.message, 'bad');
  } finally {
    busy = false;
    paintAll();
  }
}

function stepLine(s) {
  const st = s.status || 'running';
  const kind = { ok: 'ok', error: 'bad', needs_approval: 'warn', running: 'info', queued: 'info' }[st] || '';
  return h('li', {}, badge(st === 'ok' ? '✓' : st === 'needs_approval' ? 'approval' : st, kind),
    h('span', {}, h('code', {}, s.action), ' ', s.summary || s.thought || ''));
}

function messageEl(m) {
  if (m.role === 'user') {
    return h('div', { class: 'msg user' }, m.text,
      m.context.length ? h('div', { class: 'small muted' }, `with ${m.context.length} focused item(s)`) : null);
  }
  const a = m.answer;
  return h('div', { class: 'msg bot' },
    m.steps.length ? h('ul', { class: 'steps', 'aria-label': 'Tool calls' }, m.steps.map(stepLine)) : null,
    a ? rich(a.answer, { chipMax: 30 }) : h('div', { class: 'muted small' }, 'Working…'),
    a && a.actions && a.actions.length ? h('div', { class: 'row' }, a.actions.map((x) => h('a', { class: 'btn sm', href: x.href }, x.label))) : null,
    a && a.removed_citations && a.removed_citations.length
      ? h('div', { class: 'removed', title: 'Answers may only cite IDs that exist in the research graph' },
        `Removed ${a.removed_citations.length} citation(s) not in the graph: ${a.removed_citations.join(', ')}`) : null);
}

function chatEl(full) {
  const input = h('textarea', { rows: 2, placeholder: 'Ask about the project, or tell it to search, find gaps, propose an experiment…', 'aria-label': 'Message' });
  const send = () => { const v = input.value; input.value = ''; ask(v); };
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } });
  const log = h('div', { class: 'chat-log', 'aria-live': 'polite' });
  const ctx = h('div', { class: 'ctx' });
  const root = h('div', { class: 'chat' },
    h('div', { class: 'chat-head' },
      h('div', { class: 'row between' }, h('strong', {}, 'Unified chat'), full ? null : h('a', { href: '#/chat', class: 'small' }, 'Full page')),
      ctx),
    log,
    h('div', { class: 'suggest' }, SUGGESTIONS.slice(0, full ? 10 : 5).map((s) =>
      h('button', { class: 'btn sm ghost', type: 'button', onclick: () => ask(s) }, s))),
    h('div', { class: 'chat-form' }, input, h('button', { class: 'btn primary', type: 'button', onclick: send }, 'Send')));
  root._paint = () => {
    clear(ctx, 'Context: ', state.focus.length ? state.focus.map((id) => chip(id, { max: 20 })) : h('span', {}, 'no focus set'),
      h('span', {}, ` · ${(location.hash || '#/home').split('?')[0]}`));
    clear(log, messages.length ? messages.map(messageEl)
      : h('div', { class: 'muted small' }, 'The chat uses the same tools as the views, under the same approval rules. It can propose and request, but never approve, experiment runs.'));
    log.scrollTop = log.scrollHeight;
  };
  root._paint();
  return root;
}

function paintAll() { roots.forEach((r) => (r.isConnected ? r._paint() : roots.delete(r))); }
on('focus', paintAll);
on('graph', paintAll);
window.addEventListener('hashchange', () => setTimeout(paintAll));

export function mountDock(el) {
  const r = chatEl(false);
  roots.add(r);
  clear(el, r);
}

export function render(el) {
  const r = chatEl(true);
  roots.add(r);
  clear(el, r);
}
