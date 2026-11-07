// Client for the pair-01 Step 3 contract: one tool route, jobs, SSE events, streamed chat.
export const PROJECT_ID = new URLSearchParams(location.search).get('project') || 'default';
export const scoped = path => path + (path.includes('?') ? '&' : '?') + 'project=' + encodeURIComponent(PROJECT_ID);

async function parse(r) {
  const text = await r.text();
  let body;
  try { body = text ? JSON.parse(text) : {}; } catch { body = { error: { message: text } }; }
  if (!r.ok && !body.status) throw new Error(body.message || (body.error && (body.error.message || body.error)) || r.statusText);
  return body;
}

export async function get(path) { return parse(await fetch(scoped(path))); }

export async function post(path, body = {}) {
  return parse(await fetch(scoped(path), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }));
}

/** POST /api/tools/{name} -> envelope {status, data?, job_id?, warnings, provenance, error?} */
export function tool(name, input = {}) {
  return post(`/api/tools/${name}`, { project_id: PROJECT_ID, input, caller: 'ui' });
}

export function job(id) { return get(`/api/jobs/${id}`); }

const DONE = new Set(['succeeded', 'failed', 'cancelled', 'interrupted']);

/** Poll a job until it finishes. onProgress(job) on every change. */
export async function waitJob(id, onProgress) {
  let last = '';
  for (;;) {
    const j = await job(id);
    const sig = `${j.status}|${j.message}|${(j.steps || []).length}`;
    if (sig !== last) { last = sig; onProgress && onProgress(j); }
    if (DONE.has(j.status)) return j;
    await new Promise((r) => setTimeout(r, 350));
  }
}

/** Call a tool; if it is a job, wait for it. Resolves to {status, data, job, env}. */
export async function run(name, input, onProgress) {
  const env = await tool(name, input);
  if (env.status !== 'queued') return { status: env.status, data: env.data, env };
  onProgress && onProgress({ id: env.job_id, kind: name, status: 'queued', message: 'Queued', steps: [] });
  const j = await waitJob(env.job_id, onProgress);
  return { status: j.status === 'succeeded' ? 'ok' : 'error', data: j.result, job: j, env,
           error: j.error || (j.status !== 'succeeded' ? { message: j.message } : null) };
}

/** Live event stream (SSE). Reconnects with ?since= so nothing is missed. */
export function events(sinceId, onEvent, onStatus) {
  let since = sinceId || 0;
  let es;
  const open = () => {
    es = new EventSource(scoped(`/api/events?since=${since}`));
    es.addEventListener('message', (e) => {
      const ev = JSON.parse(e.data);
      since = Math.max(since, ev.id);
      onEvent(ev);
    });
    es.onopen = () => onStatus && onStatus(true);
    es.onerror = () => { onStatus && onStatus(false); es.close(); setTimeout(open, 1500); };
  };
  open();
  return () => es && es.close();
}

/** POST /api/chat and read the SSE stream of steps, then the answer. */
export async function chat(body, onEvent) {
  const r = await fetch(scoped('/api/chat'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, i);
      buf = buf.slice(i + 2);
      let ev = 'message';
      let data = '';
      for (const line of chunk.split('\n')) {
        if (line.startsWith('event: ')) ev = line.slice(7);
        else if (line.startsWith('data: ')) data += line.slice(6);
      }
      if (data) onEvent(ev, JSON.parse(data));
    }
  }
}
