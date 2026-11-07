// C10 Writing, Review & Reports: drafts with live citation chips, unsupported-sentence checks,
// model-backed reviewer personas with grounded quotes, revision with a diff and response letter, briefs, exports.
import * as api from '../api.js';
import { state, node, nodesOf, loadGraph } from '../store.js';
import { h, clear, chip, badge, groundingBadge, focusButton, section, empty, table, button, runInto, download, toast, rich, ago, shortCite } from '../ui.js';
import { head, crumbs, live, go } from './common.js';
import { verdictBadge } from './library.js';

export async function render(el, { id, query, sub }) {
  const side = h('div');
  const main = h('div');
  el.append(head('Writing & reports', 'Drafts cite graph IDs like [pap-2], so every citation can be checked against extracted claims. Reviews, revisions, briefs and exports are saved as reports and downloadable files.'),
    h('div', { class: 'grid-side' }, side, main));
  live(side, sub, () => sidebar(id, query.report));
  if (id) return draftView(main, id, query.review, sub);
  if (query.report) return live(main, sub, () => report(query.report));
  return clear(main, synthesize());
}

async function sidebar(selected, rep) {
  const drafts = nodesOf('draft').slice().reverse();
  const reports = nodesOf('report').slice().reverse();
  const arts = (await api.get('/api/artifacts')).artifacts;
  return [
    section(`Drafts (${drafts.length})`, h('a', { href: '#/writing', class: 'small' }, '+ New synthesis from papers'),
      h('ul', { class: 'list' }, drafts.map((d) => h('li', { class: d.id === selected ? 'sel' : null },
        h('a', { href: `#/writing/${d.id}` }, d.title), h('div', { class: 'small muted' }, `v${d.props.version} · ${d.origin === 'ai' ? 'AI draft' : 'yours'}`))))),
    section(`Reports (${reports.length})`, reports.length ? h('ul', { class: 'list' }, reports.map((r) => h('li', { class: r.id === rep ? 'sel' : null },
      h('a', { href: r.props.kind === 'review' ? `#/writing/${r.props.draft_id}?review=${r.id}` : `#/writing?report=${r.id}` }, r.title),
      h('div', { class: 'small muted' }, r.props.kind)))) : empty('No reports yet.')),
    section(`Files (${arts.length})`, arts.length ? h('ul', { class: 'list' }, arts.slice(0, 12).map((a) => h('li', { class: 'row between' },
      h('span', { class: 'small' }, h('code', {}, a.name), h('div', { class: 'muted' }, `${a.kind} · ${ago(a.created_at)}`)), download(a.id)))) : empty('Nothing exported yet.')),
  ];
}

function synthesize() {
  const papers = nodesOf('paper');
  const picks = new Set(state.focus.filter((id) => id.startsWith('pap-')));
  if (!picks.size) papers.slice(0, 3).forEach((p) => picks.add(p.id));
  const q = h('input', { type: 'text', value: state.project.question });
  const slot = h('div');
  return section('Draft a grounded synthesis',
    h('p', { class: 'muted small' }, 'Writes from the selected evidence and completed runs. Missing or unverified citations are flagged for review. Papers in your focus set are preselected.'),
    h('div', { class: 'stack' },
      h('label', {}, 'Question ', q),
      h('ul', { class: 'list' }, papers.map((p) => {
        const cb = h('input', { type: 'checkbox', checked: picks.has(p.id) || null });
        cb.addEventListener('change', () => (cb.checked ? picks.add(p.id) : picks.delete(p.id)));
        return h('li', {}, h('label', { class: 'check' }, cb, `${shortCite(p)}: ${p.title}`));
      })),
      button('Draft synthesis', async () => {
        if (!picks.size) return toast('Pick at least one paper', 'warn');
        const d = await runInto(slot, 'chat.synthesize', { paper_ids: [...picks], question: q.value }, { title: 'Synthesis', open: true });
        if (d) {
          if (d.unsupported_sentences) toast(`${d.unsupported_sentences.length} sentence(s) need citation review`, 'warn');
          await loadGraph();
          go(`#/writing/${d.draft_id}`);
        }
      }, 'primary'), slot));
}

async function report(id) {
  const r = node(id);
  if (!r) return empty(`No report ${id}.`);
  return [crumbs(['Writing', '#/writing'], [id]),
    section(r.title, h('div', { class: 'row' }, r.props.artifact_id ? download(r.props.artifact_id, 'Download Markdown') : null, focusButton(id),
      (r.props.run_ids || []).map((x) => chip(x))),
    h('div', { class: 'draft-preview', style: 'margin-top:.6rem' }, rich(r.props.text || '')))];
}

async function draftView(main, id, reviewId, sub) {
  const d = node(id);
  if (!d || d.type !== 'draft') return clear(main, empty(`No draft ${id}.`));
  const ta = h('textarea', { rows: 9, 'aria-label': 'Draft text' }, d.props.text);
  const preview = h('div', { class: 'draft-preview' });
  const paintPreview = () => clear(preview, rich(ta.value));
  ta.addEventListener('input', paintPreview);
  paintPreview();
  const out = h('div');
  const jobs = h('div');
  const reviewSlot = h('div');
  const save = async () => {
    const r = await api.tool('writing.save', { draft_id: id, text: ta.value });
    if (r.status === 'ok') toast('Saved', 'ok');
    return r;
  };
  clear(main,
    crumbs(['Writing', '#/writing'], [id]),
    h('div', { class: 'view-head' }, h('div', {}, h('h2', {}, d.title),
      h('div', { class: 'row small muted' }, `version ${d.props.version}`, d.props.previous_id ? h('span', {}, 'revised from ', chip(d.props.previous_id)) : null)),
    h('div', { class: 'row' }, focusButton(id))),
    section('Draft',
      h('p', { class: 'muted small' }, 'Cite with graph IDs in brackets, e.g. [pap-2]. Chips below link to the source.'),
      ta,
      h('div', { class: 'row', style: 'margin:.5rem 0' },
        button('Save', save, 'primary sm'),
        button('Find sentences needing review', async () => {
          await save();
          const r = await api.tool('writing.flag_unsupported', { draft_id: id });
          if (r.status !== 'ok') return;
          clear(out, section(`Citation review: ${r.data.sentences.length} of ${r.data.total_sentences} sentences`,
            r.data.sentences.length ? h('ul', { class: 'list' }, r.data.sentences.map((s) => h('li', {},
              h('div', { class: 'sent-flag' }, s.text), h('div', { class: 'row small' }, badge(s.reason.replace('_', ' '), 'warn'), s.cited_id ? chip(s.cited_id) : null))))
              : empty('No sentences were flagged. Scientific support still requires review.')));
        }, 'sm'),
        button('Check citations', async () => {
          await save();
          const r = await runInto(jobs, 'evidence.check_citations', { draft_id: id }, { title: 'Check citations' });
          if (r) clear(out, section('Citation checks · one model judgment', h('p', {class:'muted small'}, r.kappa_note || 'Semantic support requires researcher review.'), table(['Sentence', 'Cites', 'Verdict'],
            r.checks.map((c) => [c.sentence, chip(c.cited_id), verdictBadge(c.verdict)]))));
        }, 'sm'),
        button('Get reviews', async () => {
          await save();
          const r = await runInto(jobs, 'writing.review', { draft_id: id }, { title: 'Reviewer personas', open: true });
          if (r) { await loadGraph(); go(`#/writing/${id}?review=${r.review_id}`); }
        }, 'sm'),
        button('Export Markdown', async () => {
          await save();
          const r = await api.tool('writing.export', { draft_id: id });
          if (r.status === 'ok') clear(out, h('div', { class: 'callout ok' }, 'Exported with a reference list. ', download(r.data.artifact_id, 'Download')));
        }, 'sm'),
        button('Export Word', async () => {
          const saved = await save();
          if (saved.status !== 'ok') return;
          const r = await api.tool('writing.export', { draft_id: id, format: 'docx' });
          if (r.status === 'ok') clear(out, h('div', { class: 'callout ok' }, 'Word document exported with references. ', download(r.data.artifact_id, 'Download Word')));
        }, 'sm')),
      jobs, h('h4', {}, 'Preview'), preview),
    out, reviewSlot);
  if (reviewId) return live(reviewSlot, sub, () => reviewPanel(id, reviewId));
  return null;
}

function reviewPanel(draftId, reviewId) {
  const r = node(reviewId);
  if (!r) return empty(`No review ${reviewId}.`);
  const comments = r.props.comments;
  const accept = new Set(comments.filter((c) => c.fix && c.grounding === 'exact').map((c) => c.id));
  const slot = h('div');
  return section(h('span', {}, `Review ${reviewId} · ${comments.length} comments`),
    h('p', { class: 'muted small' }, 'Each quoted comment is checked by the Grounding Guard. Tick the comments to apply, then revise.'),
    h('ul', { class: 'list' }, comments.map((c) => {
      const cb = h('input', { type: 'checkbox', checked: accept.has(c.id) || null, 'aria-label': `Accept ${c.id}` });
      cb.addEventListener('change', () => (cb.checked ? accept.add(c.id) : accept.delete(c.id)));
      return h('li', {},
        h('div', { class: 'row' }, cb, badge(c.persona), h('strong', {}, c.text)),
        h('div', { class: 'small muted', style: 'margin:.2rem 0' }, 'On: ', h('em', {}, c.target)),
        c.quote ? h('div', { class: 'small' }, h('span', { class: 'row' }, chip(c.paper_id), c.page ? `p.${c.page}` : '', groundingBadge(c.grounding)),
          h('div', { class: 'quote muted' }, `“${c.quote}”`)) : null,
        c.fix ? h('div', { class: 'small' }, 'Suggested: ', h('span', { class: 'quote' }, c.fix)) : null);
    })),
    h('div', { class: 'row' }, button('Revise with ticked comments', async () => {
      const d = await runInto(slot, 'writing.revise', { draft_id: draftId, review_id: reviewId, accept_comment_ids: [...accept] }, { title: 'Revise', open: true });
      if (!d) return;
      toast(`Applied ${d.applied_comment_ids.length} edit(s). Diff and response letter are under Files.`, 'ok');
      await loadGraph();
      go(`#/writing/${d.new_draft_id}`);
    }, 'primary')), slot);
}
