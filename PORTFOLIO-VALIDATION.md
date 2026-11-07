# Portfolio snapshot validation

Checked November 7, 2026 on Windows with Python 3.12.14 in a fresh virtual environment, using this repository's `requirements.txt`.

Command: `python -m pytest -q`

Result: **15 passed**, one dependency deprecation warning. The existing tests use mocked model/provider responses and temporary projects; they include actual child-process recipe execution and reproduction exports. This check did not make live Amplify requests or evaluate generated research conclusions.

Selected installed versions: pytest 9.2.0, FastAPI 0.162.0, httpx 0.28.1, scikit-learn 1.9.1, NumPy 2.5.4, pandas 3.1.1. The warning concerns Starlette's future TestClient transport dependency. Application source and tests were not modified for this publication.

The original [VALIDATION.md](VALIDATION.md) remains the historical record of the course project's earlier automated and live checks. This page records the later portfolio publication check separately.

The public source was copied from the class submission's tracked files. A scan for common credential formats and literal secrets found no matches. No `.env`, private workspace, uploaded documents, API cache or Git history is included. Detailed class attribution is preserved in [INTEGRATION.md](INTEGRATION.md); this snapshot adds no new license.
