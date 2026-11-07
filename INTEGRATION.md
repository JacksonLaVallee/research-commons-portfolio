# Integration and code provenance

The individual repositories are preserved. This subfolder provides one runnable implementation of their selected research capabilities. It does **not** launch the original student applications as independent tabs.

| Class project / contribution | Reuse in this implementation | Code |
|---|---|---|
| Pair-01 Threadline UI/backend prototype | **Directly copied and extended:** browser shell/views, graph store, tool catalog, event/job runtime, bounded recipe engine, review/diff helpers. Fictional fixtures and seed/planner were removed. | `web/`, `backend/db.py`, `tools.py`, `runtime.py`, `recipe.py`, `grounding.py` |
| Jackson LaVallee, Evidence Mapper (a3) | **Direct source reuse:** exact evidence validation and conservative study-comparison safeguards. | `backend/evidence_rules.py`, consumed by `evidence.py` |
| Jackson LaVallee, Consistency Auditor (a4) | **Adapted:** Amplify response parsing, conservative reservations, cache/provenance pattern; inspect/retrieve/verify audit design. | `provider.py`, `evidence.py` |
| Gabe, LitReview Assistant | **Reimplemented behind shared contracts:** arXiv discovery, deduplication, collection-like saved sources, summaries, bibliography exports. Prototype donated the export implementation. | `sources.py`, `research.py`, `tools.py` |
| Cooper, Precedent | **Adapter concepts and normalized metadata:** OpenAlex/S2 search, result identity, search lineage. Full Precedent consensus-search engine is not embedded. | `sources.py`, `research.py` |
| Ryan, Automated Lit Review / DocAtlas | **Integrated capability:** source screening/retrieval, cross-document evidence, structured library and reports; not a wholesale copy of its CLI. | `ingest.py`, `research.py`, `evidence.py`, `writing.py` |
| Ibrahim, Paper Radar | **Schema/workflow integration:** claim/quote/page extraction, BM25 retrieval and conflict candidates. BM25 implementation comes through pair-01. | `evidence.py`, `grounding.py` |
| Nik, CiteCheck / Wayfinder | **Contract integration:** source resolution, citation judgments and a bounded tool-using chat with verified IDs. No claim of dual-judge agreement or a measured Cohen kappa. | `research.py`, `evidence.py`, `chat.py` |
| Varun, Research Atlas | **Graph design through pair-01:** generalized typed nodes/edges and neighborhood navigation. | `db.py`, `tools.py`, `web/js/views/graph.js` |
| Gabe orgnz / Layne DocSort / Ryan DocAtlas | **Merged library behavior:** content-hashed copy-on-import, hierarchy metadata, extraction, topic mapping; no duplicate folder-mover implementations. | `ingest.py`, `research.py` |
| Layne, Research Trend Tracker | **Reimplemented algorithm:** TF-IDF/KMeans topic snapshots with measured silhouette scores and size changes. | `research.py`, `tools.py` |
| Ron, Research Recipe Reviewer | **Execution pattern via pair-01 and extended:** catalog validation/execution, explicit approval, diagnostics, reproducible exports, bounded child process. | `recipe.py`, `workbench.py` |
| Ron, Portfolio Briefing | **Merged capability:** reports over actual run artifacts, produced automatically by `run.finished`. | `writing.py`, `runtime.py` |
| Haley, ReviseMate / Runawayfromearth Paper Review Agent | **Integrated workflow:** persona reviews, exact draft-target checks, selected revisions, version lineage, diff, response letter, Word/Markdown export. Reuses pair-01 revision machinery, not the old Streamlit UIs. | `writing.py`, `tools.py` |
| JP, GrantScout | **Adapted source contract:** Grants.gov `search2`, OpenAlex researcher identification, current source metadata and transparent fit screening. | `sources.py`, `research.py` |

All new integration code was written with LLM assistance in this Codex chat. The reusable modules above are credited separately from newly implemented adapters. The source repository snapshots retain their existing licensing notices; this integration does not relicense classmates' work. Select a class-wide license before redistributing the combined code as a separately licensed project.

## Contracts

`POST /api/tools/{name}?project=<id>` accepts `{input, caller}` and returns `{status, data?, job_id?, warnings, provenance, error?}`. The canonical catalog is `GET /api/tools`; job tools return immediately and publish progress through `/api/events`. The UI and chat call the same handlers. `POST /api/review` and `POST /api/approvals` are researcher routes, outside the planner's tool catalog.

Each imported source has a content hash or external identity. Papers own page/section-numbered passages. AI claims contain exact proof spans and model/prompt provenance. Runs store input hashes, recipe fingerprint, measured statistics, output tables and artifact IDs. Reviews retain the prior decision in the event log rather than destroying evidence.

## Primary external API references

- OpenAlex search: <https://help.openalex.org/api/searching/>
- Grants.gov search2: <https://www.grants.gov/api/common/search2>
- arXiv API: <https://info.arxiv.org/help/api/user-manual.html>
- Semantic Scholar API: <https://api.semanticscholar.org/api-docs/graph>
- Amplify endpoint and request shape: the class's existing adapters and authenticated `/available_models` response, checked during implementation.
