// C9 Experiments & Data: datasets, AI-drafted recipes built only from catalog tools,
// researcher approval of the exact recipe hash, runs in a child process, results and reproduction.
import * as api from '../api.js';
import { node, nodesOf, edgesOf, loadGraph, loadProject } from '../store.js';
import { h, clear, chip, badge, groundingBadge, focusButton, section, empty, table, button, runInto, download, toast, sayToChat } from '../ui.js';
import { head, crumbs, live, go, fmt } from './common.js';

let catalog = null;

function manualRecipe() {
  const ds=nodesOf('dataset');
  if(!ds.length)return section('Bring your data',h('a',{href:'#/library'},'Upload a CSV in Library to begin.'));
  const choice=h('select',{},ds.map(d=>h('option',{value:d.id},d.title)));
  const objective=h('input',{value:'Summarize the imported dataset'});
  const steps=h('textarea',{rows:7,class:'mono'},JSON.stringify([{tool:'aggregate',params:{group_by:[],metrics:[{fn:'count'}]}}],null,2));
  return section('Write a recipe',h('p',{class:'muted small'},'Use the same validated catalog without an AI call. You will review and approve the recipe before it runs.'),
    h('div',{class:'stack'},h('label',{},'Objective',objective),h('label',{},'Base dataset',choice),h('label',{},'Steps (JSON)',steps),
      button('Create recipe',async()=>{try{const d=ds.find(x=>x.id===choice.value);const r=await api.tool('experiment.create',{objective:objective.value,dataset_ids:ds.map(x=>x.id),base:d.props.name,steps:JSON.parse(steps.value)});if(r.status!=='ok')throw new Error(r.error.message);await loadGraph();go(`#/experiments/${r.data.recipe_id}`);}catch(e){toast(e.message,'bad');}},'sm')));
}

export async function render(el, { id, query, sub }) {
  if (!catalog) catalog = (await api.tool('experiment.catalog', {})).data.tools;
  const listSlot = h('div');
  const main = h('div');
  el.append(head('Experiments & data', 'The AI drafts a recipe from a fixed catalog of data tools (no arbitrary code). You approve the exact recipe; any edit resets approval. Runs produce results, diagnostics and a reproduction script.'),
    h('div', { class: 'grid-side' }, listSlot, main));
  live(listSlot, sub, () => sidebar(id));
  if (id) return live(main, sub, () => detail(id, query.run));
  if (query.dataset) return clear(main, await dataset(query.dataset));
  return clear(main, propose(), manualRecipe());
}

function sidebar(selected) {
  const exps = nodesOf('experiment');
  const ds = nodesOf('dataset');
  const state = (e) => e.props.approval.state === 'approved' && e.props.approval.hash === e.props.hash;
  return [
    section(`Recipes (${exps.length})`, h('a', { href: '#/experiments', class: 'small' }, '+ Propose a new experiment'),
      exps.length ? h('ul', { class: 'list' }, exps.map((e) => h('li', { class: e.id === selected ? 'sel' : null },
        h('a', { href: `#/experiments/${e.id}` }, e.title),
        h('div', { class: 'row small' }, state(e) ? badge('approved', 'ok') : badge('awaiting approval', 'warn'),
          `${edgesOf(e.id, 'produced').length} run(s)`)))) : empty('No recipes yet.')),
    section(`Datasets (${ds.length})`, h('ul', { class: 'list' }, ds.map((d) => h('li', {},
      h('a', { href: `#/experiments?dataset=${d.id}` }, d.title), h('div', { class: 'small muted' }, `${d.props.rows} rows · ${d.props.columns.length} columns`)))),
      h('a', {href:'#/library'}, 'Upload a CSV dataset')),
  ];
}

async function dataset(id) {
  const n = node(id);
  if (!n) return empty(`No dataset ${id}.`);
  const r = await api.get(`/api/datasets/${id}/rows?limit=15`);
  return [crumbs(['Experiments', '#/experiments'], [id]),
    section(n.title, n.props.description ? h('p', {}, n.props.description) : null,
      h('p', { class: 'muted small' }, `Showing ${r.rows.length} of ${r.total} rows. Imported dataset.`),
      h('div', { class: 'tbl-wrap' }, table(r.columns, r.rows.map((row) => r.columns.map((c) => fmt(row[c]))))))];
}

function propose() {
  const gaps = nodesOf('gap');
  const objective = h('textarea', { rows: 2 }, 'Describe group differences and associations in the selected dataset');
  const gap = h('select', {}, h('option', { value: '' }, 'No linked gap'), gaps.map((g) => h('option', { value: g.id }, `${g.id}: ${g.title.slice(0, 70)}`)));
  return section('Propose an experiment',
    h('p', { class: 'muted small' }, 'The AI drafts the steps, adds review notes backed by quotes, for your review before execution.'),
    h('div', { class: 'stack' }, h('label', {}, 'Objective', objective), h('label', {}, 'Tests gap ', gap),
      button('Draft recipe', async () => {
        const r = await api.tool('experiment.propose', { objective: objective.value, gap_id: gap.value || undefined });
        if (r.status !== 'ok') return toast(r.error.message, 'bad');
        await loadGraph();
        go(`#/experiments/${r.data.recipe_id}`);
      }, 'primary')));
}

function stepEditor(e) {
  const steps = JSON.parse(JSON.stringify(e.props.steps));
  const wrap = h('div');
  const paint = () => clear(wrap,
    h('ol', { class: 'list' }, steps.map((s, i) => {
      const ta = h('textarea', { rows: 2, class: 'mono', 'aria-label': `Step ${i + 1} parameters` }, JSON.stringify(s.params));
      ta.addEventListener('change', () => { try { s.params = JSON.parse(ta.value); ta.style.borderColor = ''; } catch { ta.style.borderColor = 'var(--bad)'; } });
      const info = catalog.find((c) => c.name === s.tool);
      return h('li', {},
        h('div', { class: 'row between' }, h('strong', {}, `${i + 1}. ${s.tool}`),
          h('span', { class: 'btn-group' },
            i ? button('↑', () => { steps.splice(i - 1, 0, steps.splice(i, 1)[0]); paint(); }, 'sm ghost') : null,
            button('Remove', () => { steps.splice(i, 1); paint(); }, 'sm ghost'))),
        info ? h('div', { class: 'small muted' }, info.limitations) : null, ta);
    })),
    h('div', { class: 'row' }, 'Add step', addSel(), button('Save & validate', save, 'sm primary')));
  const addSel = () => {
    const s = h('select', {}, h('option', { value: '' }, 'choose a catalog tool…'), catalog.map((c) => h('option', { value: c.name }, c.name)));
    s.addEventListener('change', () => {
      const c = catalog.find((x) => x.name === s.value);
      if (!c) return;
      steps.push({ tool: c.name, params: Object.fromEntries(Object.keys(c.params).map((k) => [k, ''])) });
      paint();
    });
    return s;
  };
  const save = async () => {
    const r = await api.tool('experiment.update_recipe', { recipe_id: e.id, steps });
    if (r.status !== 'ok') return toast(r.error.message, 'bad');
    toast(r.data.approval === 'pending' ? 'Saved. The recipe changed, so it needs approval again.' : 'Saved; nothing changed.', r.data.validation.errors.length ? 'bad' : 'ok');
    await Promise.all([loadGraph(), loadProject()]);
  };
  paint();
  return wrap;
}

function detail(id, runId) {
  const e = node(id);
  if (!e || e.type !== 'experiment') return empty(`No experiment ${id}.`);
  const p = e.props;
  const approved = p.approval.state === 'approved' && p.approval.hash === p.hash;
  const v = p.validation;
  const runs = edgesOf(id, 'produced').map((x) => node(x.dst_id)).filter(Boolean).reverse();
  const run = runs.find((r) => r.id === runId) || runs[0];
  const jobs = h('div');
  return [
    crumbs(['Experiments', '#/experiments'], [id]),
    h('div', { class: 'view-head' }, h('div', {}, h('h2', {}, e.title),
      h('div', { class: 'row' }, p.gap_id ? h('span', {}, 'Tests ', chip(p.gap_id, { max: 60 })) : null, 'Data: ', p.dataset_ids.map((d) => chip(d)))),
    h('div', { class: 'row' }, focusButton(id), button('Ask chat', () => sayToChat(`run the experiment [${id}]`), 'sm ghost'))),
    section('Approval and run',
          approved
            ? h('div', { class: 'callout ok' }, `Approved by ${p.approval.by} for hash `, h('code', {}, p.approval.hash), '. Any edit to the recipe resets this.')
            : h('div', { class: 'callout warn' }, 'Not approved. Chat and automation can request a run but cannot approve one.'),
          h('div', { class: 'row' },
            approved ? null : button('Approve this exact recipe', async () => {
              const r = await api.post('/api/approvals', { recipe_id: id, hash: p.hash });
              if (r.error) return toast(r.message || r.error, 'bad');
              toast('Approved', 'ok');
              await Promise.all([loadGraph(), loadProject()]);
            }, 'primary', null),
            button('Run', async () => {
              const d = await runInto(jobs, 'experiment.run', { recipe_id: id }, { title: 'Run recipe', open: true });
              if (d && d.run_id) { await loadGraph(); go(`#/experiments/${id}?run=${d.run_id}`); }
            }, approved ? 'primary' : '')),
          jobs),
        run ? runPanel(run, runs) : section('Results', empty('No runs yet.')),
        section('Recipe', h('p', { class: 'muted small' }, `Base table ${p.base} · hash `, h('code', {}, p.hash)), stepEditor(e),
          v.errors.length ? h('div', { class: 'callout bad small' }, v.errors.map((x) => h('div', {}, x))) : h('div', { class: 'callout ok small' }, 'Valid. Output columns: ', v.output_columns.join(', ')),
          v.warnings.length ? h('div', { class: 'callout warn small' }, v.warnings.map((x) => h('div', {}, x))) : null),
        (p.review || []).length ? section('AI review notes', h('ul', { class: 'list' }, (p.review || []).map((r) => h('li', {},
          h('div', { class: 'row' }, badge(r.level, r.level === 'warning' ? 'warn' : 'info'), r.text),
          r.evidence ? h('div', { class: 'small', style: 'margin-top:.3rem' }, chip(r.evidence.paper_id), ` p.${r.evidence.page} `, groundingBadge(r.evidence.grounding),
            h('div', { class: 'quote muted' }, `“${r.evidence.quote}”`)) : null)))) : null,
  ];
}

function runPanel(r, runs) {
  const p = r.props;
  const briefs = edgesOf(r.id).filter(x=>['about','derived_from'].includes(x.type)).map((x) => node(x.src_id)).filter((n) => n && n.type === 'report');
  const slot = h('div');
  return section(h('span', {}, 'Results ', chip(r.id)),
    runs.length > 1 ? h('div', { class: 'row small' }, 'Runs:', runs.map((x) => h('a', { href: `#/experiments/${p.experiment_id}?run=${x.id}`, class: `btn sm ${x.id === r.id ? 'on' : 'ghost'}` }, x.id))) : null,
    h('p', { class: 'small muted' }, `Recipe hash ${p.recipe_hash} · ${p.row_count} output rows`),
    p.stats.length ? h('div', { class: 'tiles' }, p.stats.map((s) => h('div', { class: 'tile' }, h('b', {}, fmt(s.value)), h('span', {}, `${s.name} (n=${s.n})`)))) : null,
    p.diagnostics.map((d) => h('div', { class: `callout small ${d.level === 'warning' ? 'warn' : ''}`, style: 'margin-top:.5rem' }, `Step ${d.step}: ${d.text}`)),
    h('div', { class: 'tbl-wrap' }, table(p.columns, p.rows.map((row) => p.columns.map((c) => fmt(row[c]))))),
    h('div', { class: 'row', style: 'margin-top:.6rem' },
      download(p.artifact_ids.results, 'Results CSV'), download(p.artifact_ids.repro, 'Reproduction script (.py)'), download(p.artifact_ids.log, 'Run log'),
      p.artifact_ids.bundle ? download(p.artifact_ids.bundle, 'Reproducible bundle (.zip)') : null,
      briefs.length ? briefs.map((b) => h('a', { class: 'btn sm', href: `#/writing?report=${b.id}` }, `Brief ${b.id}`))
        : button('Write a brief', async () => {
          const d = await runInto(slot, 'writing.brief', { kind: 'thread', run_ids: [r.id] }, { title: 'Brief' });
          if (d) go(`#/writing?report=${d.report_id}`);
        }, 'sm')),
    slot);
}
