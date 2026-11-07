// C3 Literature Search: run searches, browse the search history tree, screen and save results.
import * as api from '../api.js';
import { node, loadGraph } from '../store.js';
import { h, clear, chip, badge, section, empty, table, button, runInto, download, toast } from '../ui.js';
import { head, crumbs, live, go } from './common.js';

const SOURCES = ['semantic_scholar', 'openalex', 'arxiv'];

export async function render(el, { id, sub }) {
  const treeSlot = h('div');
  const main = h('div');
  el.append(head('Literature search', 'Searches several sources, merges and de-duplicates results, with source provenance for researcher screening. Every search is saved in a history tree.'),
    h('div', { class: 'grid-side' }, h('div', {}, newSearch(id), treeSlot), main));
  live(treeSlot, sub, tree.bind(null, id));
  return id ? live(main, sub, () => detail(id)) : clear(main, empty('Pick a search from the history, or run a new one.'));
}

function newSearch(parentId, preset = '') {
  const q = h('input', { type: 'search', placeholder: 'e.g. actigraphy sleep diary nurses', value: preset });
  const boxes = SOURCES.map((s) => h('input', { type: 'checkbox', checked: s === 'openalex' || null, value: s }));
  const refine = parentId ? h('input', { type: 'checkbox', checked: true }) : null;
  const slot = h('div');
  const run = async () => {
    if (!q.value.trim()) return toast('Type a query first', 'warn');
    const d = await runInto(slot, 'search.papers', {
      query: q.value, sources: boxes.filter((b) => b.checked).map((b) => b.value),
      parent_search_id: refine && refine.checked ? parentId : undefined,
    }, { title: 'Search', open: true });
    if (d) { await loadGraph(); go(`#/search/${d.search_id}`); }
  };
  q.addEventListener('keydown', (e) => e.key === 'Enter' && run());
  return section('New search', h('div', { class: 'stack' },
    h('div', { class: 'row' }, q),
    h('div', { class: 'row small' }, SOURCES.map((s, i) => h('label', { class: 'check' }, boxes[i], s.replace('_', ' ')))),
    refine ? h('label', { class: 'check small' }, refine, `Refine from ${parentId} (child in the tree)`) : null,
    button('Search', run, 'primary'), slot));
}

async function tree(selected) {
  const r = await api.tool('search.history', {});
  const rows = r.data.tree;
  const kids = (pid) => rows.filter((s) => (s.parent_id || null) === pid);
  const item = (s) => h('li', { class: s.search_id === selected ? 'sel' : null },
    h('a', { href: `#/search/${s.search_id}` }, s.query),
    h('div', { class: 'row small muted' }, `${s.result_count} results · ${s.included} included`, s.origin === 'ai' ? badge('AI', 'ai') : null,
      s.launched_from && s.launched_from.node_id ? h('span', {}, 'from ', chip(s.launched_from.node_id, { max: 18 })) : null),
    kids(s.search_id).length ? h('ul', { class: 'list', style: 'margin-left:1rem' }, kids(s.search_id).map(item)) : null);
  return section('Search history', rows.length ? h('ul', { class: 'list' }, kids(null).map(item)) : empty('No searches yet.'));
}

function detail(id) {
  const s = node(id);
  if (!s) return empty(`No search ${id}.`);
  const p = s.props;
  const picks = new Set(p.results.filter((r) => r.screen === 'include' && !r.paper_id).map((r) => r.candidate_id));
  const jobSlot = h('div');
  const exportSlot = h('span');
  const fmtSel = h('select', {}, ['bibtex', 'ris', 'apa'].map((f) => h('option', { value: f }, f)));
  const save = async () => {
    if (!picks.size) return toast('Select results to save', 'warn');
    const d = await runInto(jobSlot, 'search.save', { candidate_ids: [...picks], search_id: id }, { title: 'Save to library', open: true });
    if (d) toast(`${d.paper_ids.length} paper(s) saved; extraction and linking run in the background.`, 'ok');
  };
  const saved = p.results.filter((r) => r.paper_id).map((r) => r.paper_id);
  return [
    crumbs(['Search', '#/search'], [id]),
    h('h2', {}, `“${p.query}”`),
    h('dl', { class: 'kv' },
      h('dt', {}, 'Expanded'), h('dd', {}, p.expanded_queries.length ? p.expanded_queries.join(' · ') : '—'),
      h('dt', {}, 'Sources'), h('dd', {}, p.sources.join(', ')),
      p.parent_search_id ? [h('dt', {}, 'Refines'), h('dd', {}, chip(p.parent_search_id))] : null,
      p.launched_from && p.launched_from.node_id ? [h('dt', {}, 'Launched from'), h('dd', {}, chip(p.launched_from.node_id))] : null),
    p.source_failures.map((f) => h('div', { class: 'callout warn small' }, h('strong', {}, f.source), `: ${f.reason}`)),
    section(`Results (${p.results.length})`,
      h('div', { class: 'row', style: 'margin-bottom:.5rem' },
        button('Save selected to library', save, 'primary sm'),
        saved.length ? button('Summarize saved', () => runInto(jobSlot, 'search.summarize', { paper_ids: saved }, { title: 'Summarize' }), 'sm') : null,
        h('span', { class: 'muted small' }, 'Export citations'), fmtSel,
        button('Export', async () => {
          const r = await api.tool('search.export_citations', { paper_ids: saved, format: fmtSel.value });
          clear(exportSlot, download(r.data.artifact_id, `Download ${r.data.count} reference(s)`));
        }, 'sm'), exportSlot),
      jobSlot,
      h('div', { class: 'tbl-wrap' }, table(['', '#', 'Paper', 'Sources', 'Screen', 'Library'], p.results.map((r) => {
        const cb = h('input', { type: 'checkbox', checked: picks.has(r.candidate_id) || null, disabled: r.paper_id ? true : null,
                                'aria-label': `Select ${r.title}` });
        cb.addEventListener('change', () => (cb.checked ? picks.add(r.candidate_id) : picks.delete(r.candidate_id)));
        return [cb, r.rank,
          h('div', {}, h('strong', {}, r.title), h('div', { class: 'muted small' }, `${r.authors.join(', ')} (${r.year}) · doi:${r.doi}`)),
          h('span', { class: 'small' }, r.sources.join(', ')),
          h('div', {}, r.screen ? badge(r.screen, { include: 'ok', maybe: 'warn', exclude: 'muted' }[r.screen]) : null,
            h('div', { class: 'small muted' }, r.reason), r.full_text ? null : h('div', { class: 'small muted' }, 'abstract only')),
          r.paper_id ? chip(r.paper_id) : h('span', { class: 'muted small' }, 'not saved')];
      })))),
    newSearch(id, p.query),
  ];
}
