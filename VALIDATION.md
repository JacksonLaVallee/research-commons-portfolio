# Validation record

Implementation checked on November 1, 2026, on Windows with Python 3.12 and the pinned dependency versions in `requirements-lock.txt`.

## Automated integration checks

`python -m pytest -q`: **15 passed**. One non-failing upstream deprecation warning from Starlette's current TestClient/httpx integration.

Coverage includes:

- Upload, immutable content hashing, deduplication and directory metadata.
- Project isolation and rejection of invalid project paths/cross-origin writes.
- Exact evidence admission, fabricated-quote rejection and idempotent extraction.
- Comparison safeguards that prevent unsupported contradiction labels.
- Rejected edges disappear from active graph neighborhoods while review events remain.
- Validated CSV recipes, hash-bound approvals, stale approval rejection and worker-time rechecks.
- Real child-process execution, measured results, downloadable ZIP and independent reproduction.
- Automatic run-to-brief event chaining.
- Partial source failure, search saving, deduplication and search-history identity.
- Persistent provider budget reservation, cache reuse and no fabricated response without credentials.
- Planner rejection of nonexistent approval tools, citation filtering and saved conversation history.
- Word export, actual clustering, funding-source persistence and invalid-settings rejection.

All browser JavaScript modules passed `node --check`. Python modules compiled successfully. Model responses and source requests in unit tests are explicitly mocked; those tests do not demonstrate model quality.

## Separate live checks

- Authenticated Amplify `/available_models` and a real `/chat` JSON request succeeded. Used the available `us.openai.gpt-5.6-luna` model with the verified deployment's prices configured locally.
- OpenAlex literature search and Grants.gov funding search returned actual current records.
- Two real dataset projects were imported and executed through the HTTP API and separate job worker.
- Digit dataset: 1,797 rows; actual ten-class aggregate output and reproduction artifacts produced.
- Diabetes dataset: 442 rows; Pearson correlation of BMI with progression **0.586**, with the measured mean progression **152.133**. These numbers are properties of this dataset/recipe, not clinical advice or causal estimates.
- Live Amplify extraction admitted **6 claims** in the digit project and **3 claims** in the diabetes project at the demo checkpoint. Outputs remained unreviewed.
- Live assumption audit, two reviewer personas, revision/diff/response letter, semantic citation checks, Word export and an AI-drafted recipe succeeded. The additional AI recipe remained pending human approval.
- Browser chat retrieved the completed diabetes run through `graph.get`, cited it and described the observational limitation. No browser console errors were observed in that check.
- Final browser checks covered the graph, experiment results, revised drafts and the Word-export button. A missing-author citation-label error was corrected; the fresh-session check completed without console errors. Imported notes now use their title as the citation label.
- At the live validation checkpoint, **28 provider calls reserved $0.19028064** under the $5 local ceiling. Reservations are conservative estimates, not measured provider billing. Later interactive calls may change the current ledger.

The local `.workspace/demo-report.json` and `.workspace/live-validation.json` record object IDs and results. Credentials and local workspaces are excluded from source archives and Git.

## Practical limits

arXiv and Semantic Scholar adapter request paths are implemented but not claimed as independently live-validated in this record. macOS/Linux launcher files are supplied, but this validation ran on Windows. Scanned-PDF OCR, hosted multi-user access, chemistry execution plugins, exhaustive funding sweeps and unrestricted model-generated code execution are outside this implementation. Citation existence is checked deterministically; semantic support remains a model judgment for researcher review.

## Submission checkpoint — November 2, 2026

The exact source copy prepared for `Vanderbilt-research-Jackson-LaVallee/` passed all 15 integration tests and all JavaScript syntax checks. The submission contains source and documentation only; live AI checks above were performed on the original working installation.
