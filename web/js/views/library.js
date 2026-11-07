// C2 Core library: papers, staged uploads, passage search, and the paper reader.
import * as api from '../api.js';
import { node, nodesOf, edgesOf, loadGraph } from '../store.js';
import { h, clear, chip, badge, statusBadge, groundingBadge, originBadge, reviewButtons, focusButton, section, empty, table,
         button, runInto, toast, shortCite, sayToChat } from '../ui.js';
import { head, crumbs, live } from './common.js';

function uploadControls(refresh) {
  const files=h('input',{type:'file',multiple:true,accept:'.pdf,.docx,.txt,.md,.csv','aria-label':'Choose documents or datasets'});
  const folder=h('input',{type:'file',multiple:true,webkitdirectory:'',directory:'','aria-label':'Choose document folder'});
  const slot=h('div');
  const upload=async input=>{
    if(!input.files.length)return;
    const data=new FormData(); for(const f of input.files) data.append('files',f,f.webkitRelativePath||f.name);
    clear(slot,h('p',{},`Uploading ${input.files.length} files…`));
    try {
      const response=await fetch(api.scoped('/api/uploads'),{method:'POST',body:data}); const result=await response.json();
      if(!response.ok)throw new Error(result.detail||result.error?.message||'Upload failed');
      if(result.errors.length)clear(slot,h('div',{class:'callout warn'},result.errors.map(e=>`${e.file}: ${e.reason}`).join('; ')));
      if(result.upload_ids.length)await runInto(slot,'library.import',{upload_ids:result.upload_ids},{title:'Import uploaded files',open:true});
      await loadGraph(); await refresh(); input.value='';
    } catch(e){clear(slot,h('div',{class:'callout bad'},e.message));}
  };
  return h('div',{class:'stack'},h('label',{},'Files',files),button('Upload files',()=>upload(files),'primary sm'),
    h('details',{},h('summary',{},'Import a directory'),h('p',{class:'muted small'},'Folder paths are preserved as metadata. Supported files are copied; originals stay unchanged.'),folder,button('Upload folder',()=>upload(folder),'sm')),slot);
}

export function render(el, ctx) {
  return ctx.name === 'paper' && ctx.id ? paper(el, ctx) : list(el, ctx);
}

// ---------------------------------------------------------------- list
function list(el, { sub }) {
  const tableSlot = h('div');
  const uploads = h('div');
  const jobSlot = h('div');
  const hits = h('div');
  const q = h('input', { type: 'search', placeholder: 'Search passages in saved papers, e.g. diary overestimate sleep' });
  const doSearch = async () => {
    if (!q.value.trim()) return;
    const r = await api.tool('library.search_passages', { query: q.value, k: 8 });
    if (r.status !== 'ok') return toast(r.error.message, 'bad');
    clear(hits, r.data.hits.length ? h('ul', { class: 'list' }, r.data.hits.map((x) => h('li', {},
      h('div', { class: 'row' }, chip(x.document_id), h('span', { class: 'muted small' }, `p.${x.page} · score ${x.score}`),
        h('a', { href: `#/paper/${x.document_id}?passage=${x.passage_id}`, class: 'small' }, 'Open passage')),
      h('div', { class: 'quote small' }, x.snippet)))) : empty('No matching passages.'));
  };
  q.addEventListener('keydown', (e) => e.key === 'Enter' && doSearch());

  const paintUploads = async () => {
    const r = await api.get('/api/uploads');
    clear(uploads, h('ul', { class: 'list' }, r.uploads.map((u) => h('li', { class: 'row between' },
      h('span', {}, h('code', {}, u.file), ' ', u.dataset ? badge('CSV → dataset') : badge('document → library')),
      u.imported ? badge('imported', 'ok') : button('Import', async () => {
        const d = await runInto(jobSlot, 'library.import', { upload_ids: [u.upload_id] }, { title: `Import ${u.file}`, open: true });
        if (d && d.duplicates.length) toast(`Already in the library: ${d.duplicates[0].existing_id}`, 'warn');
        await loadGraph();
        paintUploads();
      }, 'sm primary')))));
  };

  el.append(
    head('Library', 'Papers saved to the project. Importing or saving a paper triggers link building, claim extraction and topic assignment automatically.'),
    h('div', { class: 'grid-side' },
      h('div', {},
        section('Import files', uploadControls(paintUploads), h('p', { class: 'muted small' }, 'Upload papers, notes, or CSV datasets. Original files are preserved.'), uploads, jobSlot),
        section('Search inside papers', h('div', { class: 'row' }, q, button('Search', doSearch, 'sm')), hits)),
      tableSlot));
  paintUploads();
  return live(tableSlot, sub, () => {
    const papers = nodesOf('paper');
    return section(`Papers (${papers.length})`, table(['Paper', 'Year', 'Claims', 'Status', ''], papers.map((p) => [
      h('div', {}, h('a', { href: `#/paper/${p.id}` }, p.title), h('div', { class: 'muted small' }, `${shortCite(p)} · ${p.props.venue || ''}`)),
      p.props.year,
      p.props.extracted ? String(edgesOf(p.id, 'derived_from').length) : badge('not extracted', 'warn'),
      h('div', {}, statusBadge(p.review_status), ' ', p.props.full_text ? badge('full text') : badge('abstract only', 'warn')),
      h('div', { class: 'row' }, focusButton(p.id), reviewButtons(p.id, p.review_status)),
    ])));
  });
}

// ---------------------------------------------------------------- reader
async function paper(el, { id, query, sub }) {
  const passages = (await api.tool('library.read', { document_id: id })).data;
  const top = h('div');
  const side = h('div');
  const out = h('div');
  el.append(crumbs(['Library', '#/library'], [id]), top, h('div', { class: 'grid2' }, h('div', {}, out), side));

  // passages with optional highlight
  const passEl = h('div');
  const paintPassages = () => clear(passEl, passages ? passages.passages.map((p) => h('div', {
    id: p.id, class: 'card tight', style: query.passage === p.id ? 'outline:2px solid var(--accent)' : null,
  }, h('div', { class: 'row between small muted' }, `Page ${p.page}`, h('code', {}, p.id)), h('div', {}, p.text))) : empty('No text.'));
  paintPassages();

  const qIn = h('input', { type: 'text', placeholder: 'Paste a quote to check against this paper' });
  const qOut = h('div');
  const verify = async () => {
    const r = await api.tool('evidence.verify_quote', { quote: qIn.value, document_id: id });
    if (r.status !== 'ok') return toast(r.error.message, 'bad');
    clear(qOut, h('div', { class: 'row small' }, groundingBadge(r.data.match), `similarity ${r.data.ratio}`,
      r.data.page ? `· page ${r.data.page}` : '', r.data.passage_id ? h('a', { href: `#/paper/${id}?passage=${r.data.passage_id}` }, 'show') : null));
  };
  const jobs = h('div');
  const summary = h('div');
  const checks = h('div');

  out.append(
    section('Text by page', h('p', { class: 'muted small' }, 'Extracted with page numbers so every quote can be traced back.'), passEl),
    section('Grounding Guard', h('p', { class: 'muted small' }, 'Exact match = verified; close match = needs review; nothing = dropped.'),
      h('div', { class: 'row' }, qIn, button('Check', verify, 'sm')), qOut));

  live(top, sub, () => {
    const p = node(id);
    if (!p) return empty(`No paper ${id}.`);
    return [
      h('div', { class: 'view-head' },
        h('div', {}, h('h1', {}, p.title),
          h('p', {}, `${(p.props.authors || []).join(', ')} (${p.props.year}). ${p.props.venue || ''}. doi:${p.props.doi || 'n/a'}`),
          h('div', { class: 'row', style: 'margin-top:.4rem' }, statusBadge(p.review_status), originBadge(p.origin),
            p.props.full_text ? badge('full text') : badge('abstract only', 'warn'), p.props.via ? badge(`via ${p.props.via}`) : null)),
        h('div', { class: 'row' }, focusButton(p.id), reviewButtons(p.id, p.review_status),
          button('Ask chat', () => sayToChat(`Tell me about [${p.id}]`), 'sm ghost'))),
      h('div', { class: 'row' },
        button('Summarize', async () => {
          const d = await runInto(jobs, 'search.summarize', { paper_ids: [id] }, { title: 'Summarize' });
          if (d) {
            const f = d.summaries[0].fields;
            clear(summary, section(`Summary${d.summaries[0].cached ? ' (cached)' : ''}`,
              h('dl', { class: 'kv' }, Object.entries(f).map(([k, v]) => [h('dt', {}, k), h('dd', {}, v)]))));
          }
        }, 'sm'),
        p.props.extracted ? null : button('Extract claims', () => runInto(jobs, 'evidence.extract', { paper_ids: [id] }, { title: 'Extract claims', open: true }), 'sm primary'),
        button('Check its citations', async () => {
          const d = await runInto(jobs, 'evidence.check_citations', { paper_id: id }, { title: 'Check citations' });
          if (d) clear(checks, section('Citation checks · one model judgment', h('p', {class:'muted small'}, d.kappa_note || 'Semantic support requires researcher review.'), d.checks.length ? table(['Sentence', 'Cites', 'Verdict'],
            d.checks.map((c) => [c.sentence, chip(c.cited_id), h('div', {}, verdictBadge(c.verdict), c.why ? h('div', { class: 'small muted' }, c.why) : null)]))
            : empty('This paper cites nothing in the library.')));
        }, 'sm'),
        h('a', { class: 'btn sm ghost', href: `#/graph?node=${id}` }, 'Show in graph')),
      jobs, summary, checks,
      section('Abstract', h('p', {}, p.props.abstract)),
    ];
  });

  return live(side, sub, () => {
    const derived = edgesOf(id, 'derived_from').filter((e) => e.dst_id === id).map((e) => node(e.src_id)).filter(Boolean);
    const assumes = edgesOf(id, 'assumes').map((e) => node(e.dst_id)).filter(Boolean);
    const methods = edgesOf(id, 'uses_method').map((e) => node(e.dst_id)).filter(Boolean);
    const cites = edgesOf(id, 'cites');
    const topics = edgesOf(id, 'in_topic').map((e) => e.dst_id);
    const claimItem = (c) => {
      const q = c.type === 'assumption' ? (c.props.quotes || []).find((x) => x.paper_id === id) || {} : c.props;
      return h('li', {},
        h('div', { class: 'row' }, chip(c.id, { full: true, max: 120 })),
        q.quote ? h('blockquote', { class: 'quote small' }, `“${q.quote}”`,
          h('a', { href: `#/paper/${id}?passage=${q.passage_id}`, style: 'margin-left:.4rem' }, `p.${q.page}`)) : null,
        h('div', { class: 'row' }, groundingBadge(q.grounding), statusBadge(c.review_status), reviewButtons(c.id, c.review_status), focusButton(c.id)));
    };
    return [
      section(`Claims (${derived.length})`, derived.length ? h('ul', { class: 'list' }, derived.map(claimItem)) : empty('Not extracted yet.')),
      assumes.length ? section(`Assumptions (${assumes.length})`, h('ul', { class: 'list' }, assumes.map(claimItem))) : null,
      section('Connections',
        h('dl', { class: 'kv' },
          h('dt', {}, 'Methods'), h('dd', {}, methods.length ? methods.map((m) => chip(m.id)) : '—'),
          h('dt', {}, 'Topics'), h('dd', {}, topics.length ? topics.map((t) => chip(t)) : '—'),
          h('dt', {}, 'Cites'), h('dd', {}, cites.filter((e) => e.src_id === id).map((e) => h('span', {}, chip(e.dst_id), ' ', verdictBadge(e.props.cite_verdict), ' ')) || '—'),
          h('dt', {}, 'Cited by'), h('dd', {}, cites.filter((e) => e.dst_id === id).map((e) => chip(e.src_id))),
          h('dt', {}, 'Similar'), h('dd', {}, edgesOf(id, 'similar').map((e) => chip(e.src_id === id ? e.dst_id : e.src_id)))),
      ),
    ];
  });
}

export function verdictBadge(v) {
  if (!v) return null;
  return badge(v, { SUPPORTED: 'ok', PARTIAL: 'warn', NOT: 'bad', UNVERIFIABLE: 'muted', NEEDS_REVIEW: 'warn' }[v] || '');
}
