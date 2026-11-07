# Vanderbilt Research Commons

**Jackson LaVallee — November 2, 2026 hackathon submission.**

A local research platform built from the first four class shared design documents. One browser workspace connects literature discovery, a typed research graph, document ingestion, grounded evidence, assumption auditing, experiments, writing, funding and a tool-using assistant.

These are **implementation choices derived from proposals**, not a claim that the blank `shared/05-decisions.md` contains approved votes. See [DECISIONS.md](DECISIONS.md) and [INTEGRATION.md](INTEGRATION.md).

## MS portfolio source snapshot

Public source for Jackson La Vallee's Vanderbilt MS Computer Science portfolio, Section 4b. This is the individual Research Commons course submission from CS 8395, Fall 2026.

Jackson's contribution centers on integrating the research workflow and carrying forward his Evidence Mapper and Consistency Auditor work. The application also copies, extends, adapts or reimplements credited class contributions, including the pair-01 Threadline prototype. New integration code used LLM assistance. See [INTEGRATION.md](INTEGRATION.md) for the detailed attribution; this repository does not claim sole authorship or relicense those contributions.

The snapshot comes from `white-genai-swe-fall26/combined-repo`, commit `f50997b1f3ef0d65022d91e74cc37119fcd9eb81`, directory `Vanderbilt-research-Jackson-LaVallee`. Application code is unchanged. The README was adapted for this standalone repository, and portfolio provenance/validation notes were added. Credentials and private runtime workspaces are not included.

## Run

Requires Python 3.11+ and a modern browser. Windows: double-click `Start-Research-Commons.cmd` (or run the `.ps1` launcher in PowerShell). macOS/Linux: `bash start-mac-linux.sh`.

Run the launchers and commands from this repository's root folder. A fresh checkout starts with an empty workspace; the demo scripts below create the two real-data projects. No credentials or private workspace are included.

Manual setup:

```sh
python -m venv .venv
# Windows:
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python commons.py
# macOS/Linux: replace .venv/Scripts/python with .venv/bin/python
```

Open <http://127.0.0.1:8000>. The launcher runs an API process and a separate durable-job worker. `python commons.py serve` and `python commons.py worker` can also run separately. Use `--port 8001` to change the API port.

## Configure Amplify

Use **Projects & settings**, enter your key, check available models, and select an accessible model and its current input/output prices **per million tokens**. Alternatively copy `.env.example` to `.env`. Keys are kept in the ignored local `.env`, never sent to the browser in a read response, and never included in source archives.

The persistent ledger reserves conservative token-cost bounds across **all projects** before a call starts. Failed/uncertain calls keep their reservation. A model/prompt/input cache avoids repeat calls. The default ceiling is $5 and 100 requests. This is a local reservation limit, **not** a statement of actual provider charges or remaining credit. Other apps using the same provider key consume its quota independently. Changing token prices requires accurate provider information.

Source searches and deterministic data tools work without an Amplify key. AI tools report `llm_unavailable` when unconfigured; there is no automatic fake-result fallback.

## A research workflow

1. Create a project with a research question.
2. Search OpenAlex, arXiv or Semantic Scholar and save selected results. Metadata and abstracts are explicitly labelled; upload full-text PDFs separately.
3. Upload PDF, DOCX, Markdown, text or CSV files, individually or as a folder. Files are copied by content hash; directory paths survive as metadata. Papers trigger link building, claim extraction and topic assignment.
4. Review extracted claims and assumptions, inspect exact source spans, compare study conditions, and audit potential gaps. Rejected graph links disappear from active neighborhoods; the decision remains in the event history.
5. Draft an experiment with AI, or write a recipe from the same catalog. Review and approve its hash and input hashes, then execute it. Editing the recipe resets approval.
6. Download measured results, the audit manifest and a ZIP containing inputs plus a standalone reproduction script. A run automatically produces a brief.
7. Create an evidence-linked synthesis, run reviewer personas, apply selected changes, and export Markdown or Word. Citation checks distinguish missing sources from model judgments about support.
8. Search funding opportunities with provenance and deadlines. Chat uses the same registered tools and cannot approve its own experiments.

## Two real-data demonstrations

With the app running:

```sh
.venv/Scripts/python scripts/demo.py
.venv/Scripts/python scripts/demo.py --run --live
```

The first command creates new projects and pending recipes. `--run` explicitly approves and runs the **predefined demonstration recipes**. `--live` also searches current papers and uses your configured Amplify budget. Every invocation creates new projects and leaves existing work intact.

- **Computer vision:** 1,797 handwritten digits, 64 pixel features. Compare class representation and central-pixel intensity. This is descriptive analysis, not a classifier accuracy evaluation.
- **Clinical research methods:** 442 diabetes observations, ten baseline features. Measure the association of baseline BMI with progression, with explicit confounding and generalization limitations.

Data comes from scikit-learn's redistributed real datasets; provenance links and researcher-authored protocol documents are imported alongside the CSVs. Live search results and AI output are separate from these protocol documents. See [DEMO.md](DEMO.md).

## Verify

```sh
.venv/Scripts/python -m pytest -q
```

Integration tests use explicitly mocked provider responses and temporary projects. They execute real CSV recipes in child processes and rerun exported reproduction bundles. See [VALIDATION.md](VALIDATION.md) for actual live checks and their limits. OpenAPI is available at `/docs` and `/openapi.json`; `/api/tools` describes the tool catalog.

## Storage and portability

`.workspace/projects/<id>/platform.sqlite` holds each project's graph, passages, jobs, events, drafts and artifacts. Immutable uploaded files live in that project's `data/` directory. `.workspace/usage.sqlite` contains the shared API ledger and cache. Focus preferences are namespaced by project in browser local storage.

Back up the whole `.workspace` directory with the app stopped. Source-only ZIPs omit it and omit credentials; recreate the demo on another laptop or transfer your workspace privately. Use relative data paths in transferred workspaces (the included `scripts/relocate.py` repairs stored paths after a move).

## Boundaries

- Single-tenant, loopback-only app; no new authentication or public hosting. It is not an internet-facing multi-user service.
- PDF OCR is not included; image-only PDFs produce a clear import error. DOCX uses text-section numbers, not original Word pagination.
- Funding uses current keyword search and deterministic title-overlap screening. Eligibility and final fit need researcher review; no applications are submitted.
- Topic labels are deterministic TF-IDF terms; small collections may have no valid silhouette score. Topic identity can change after a rebuild.
- Bounded catalog recipes support filtering, selecting, filling missing data, unique-key left joins, paired differences, aggregation and Pearson correlation. No arbitrary generated code or chemistry plug-in is executed.
- External providers can rate-limit or fail. Partial source failures are visible, and jobs can be cancelled/retried. Provider calls are bounded, but a cancellation may wait for an in-flight network response.
- Quote validation proves that text occurs in a source. Scientific support, causal claims, novelty and generalization still require review. AI-created research interpretations remain unreviewed.
