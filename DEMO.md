# Demonstration guide

Start `commons.py` and open the browser. Create the examples with `python scripts/demo.py --run --live`. The script prints URLs and saves `.workspace/demo-report.json`. It preserves old projects and never substitutes fictional results for a failed live service.

## Suggested five-minute walkthrough

**0:00–0:35 — The problem and connected workspace.** Research work often loses the link between a source, an interpretation, an experiment and the final claim. Research Commons gives those objects stable graph IDs. Show the project question and research trail. Explain that class proposals supplied the design basis; this is an implementation of those proposals, not the missing final voting document.

**0:35–1:20 — Real sources and evidence.** In Library, open a paper or protocol. Identify whether it is an abstract, full text, or a researcher-authored protocol. Show a claim with its exact quotation and source location. Quote matching proves provenance, not that the interpretation is scientifically sound. Show the review state. In the graph, dismiss a proposed relation and show that the visible edge disappears while its review event remains in Activity.

**1:20–2:05 — An agent that investigates.** Open the diabetes gap audit. It proposed candidates, retrieved relevant passages, searched current literature within a budget, then reconsidered each candidate. Show a flagged gap and its source evidence. Explain that missing evidence in this corpus is not proof that no paper exists anywhere. The agent can abstain and cannot accept its own conclusions.

**2:05–3:05 — An experiment with reproducible results.** Show the diabetes recipe: Pearson correlation followed by an aggregate summary. Explain BMI as body mass index. The input is 442 real observations from the scikit-learn diabetes dataset; its features use the loader's default scaling. Show the exact recipe/input fingerprint and approval. The measured run produced Pearson r = 0.586 and mean progression = 152.133 in the implementation validation. These are descriptive associations, not causal effects. Download the reproduction bundle; it contains actual input CSVs, a manifest and a standalone Python script. Editing a recipe resets approval.

**3:05–3:40 — A very different domain.** Switch to the handwritten-digit project. These are 1,797 real 8-by-8 images represented by 64 pixel-intensity columns. Show the recipe that groups by digit, counts class representation and compares central-pixel means. The exact same catalog, graph and result-export mechanism works here. This example measures dataset characteristics; it does not pretend to measure classifier accuracy.

**3:40–4:25 — Communicate and question.** Show the automatic run brief and the AI-generated research draft. Open reviewer comments, apply a selected correction, and show the diff/response letter. Explain that source-ID validation and semantic citation judgment are separate. In chat, ask what the completed experiment found; the assistant calls the same graph tool and links its answer to the run.

**4:25–5:00 — Architecture and engineering evidence.** Show Activity & tools: 41 tool contracts, durable jobs, progress, retry/cancel, and event-triggered follow-ups. Summarize FastAPI + SQLite + a separate worker and an Amplify gateway. Show the budget reservation total and explain it is not an invoice. Mention the integration tests, live source/AI checks, and the clear boundaries: local single tenant, bounded experiment tools, human research review.

## Dataset provenance

- Digits: <https://scikit-learn.org/stable/modules/generated/sklearn.datasets.load_digits.html>. This is scikit-learn's copy of the UCI optical recognition test subset, not a generated dataset. The demo transforms rows into CSV without adding artificial observations.
- Diabetes: <https://scikit-learn.org/stable/modules/generated/sklearn.datasets.load_diabetes.html>. The demo uses `load_diabetes()` defaults. The source documentation notes uncertainty in some feature meanings; the demo avoids interpreting ambiguous serum columns.

The protocol documents are authored for the demo and labelled as such. Saved publications come from live OpenAlex metadata. They are not presented as downloaded full-text papers. All counts and result metrics in the app come from actual imports and executions.

## If a service is unavailable during class

Use the already-completed project artifacts; they are persisted in SQLite and can be inspected without another paid call. Explain that they are saved results of a prior real execution. Run the deterministic recipe again if needed. A source/provider outage is visible in the job log; do not describe offline saved output as a new live response.
