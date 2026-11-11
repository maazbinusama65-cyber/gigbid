# GigSim (stand-in) and the synthetic data generator

**This is a stand-in.** The instructor's `gigsim/` simulator and `data/personas/` corpora were not in
the starter kit we received. This package reproduces the contract in `docs/INTERFACES.md`
(sections 1 and 2) so the rest of the project can be built and evaluated. When the real GigSim is
provided, point `GIGSIM_BASE_URL` at it; nothing else should change. Results measured here are not
results on the instructor's hidden set.

## Run

```bash
python -m gigsim.datagen --seed 1337        # (re)generate data/personas, data/gigsim_seed, evals/datasets
python -m gigsim                            # serve on http://127.0.0.1:8081  (GIGSIM_PORT / GIGSIM_HOST)
pytest -q tests/unit/test_datagen.py tests/unit/test_gigsim_api.py
```

Auth: `Authorization: Bearer $GIGSIM_API_TOKEN` (default `replace_me`) and `X-Freelancer-Id:
ai_ml|fullstack|data_analyst`. Environment: `GIGSIM_ERROR_RATE`, `GIGSIM_ERROR_AFTER_COMMIT_RATE`,
`GIGSIM_RATE_LIMIT_RPM` (default from policy, 60), `GIGSIM_STATE_PATH` (JSON, survives restarts;
`""` = memory), `GIGSIM_SEED_DIR`, `GIGSIM_POLICY_PATH`, `GIGSIM_SEED`, `GIGSIM_EXTRA_JOBS`,
`GIGSIM_REQUIRE_IDEMPOTENCY`. The full endpoint contract is `docs/INTERFACES.md` section 2 (+2.1).

## What is simulated

* **Policy** is `gigsim/policy.json` (hot-reloaded): content rules (`forbid_regex`, `max_words`,
  `require_phrase`) and the Connects cost (`connects_cost` rule; otherwise each job's own cost).
  The instructor's later "policy update" is a data edit (flip `enabled`, change `value`/`version`).
* **Connects**: starting balance, weekly top-up on simulated week boundaries, 402 when short.
  Submitting spends once per `Idempotency-Key`, even if the first response was lost.
* **Clients** (`simmodel.py`, rule-based, no LLM; optional `Settings.decision_hook`): each client has
  hidden must-have skills (subset of the job's), a budget ceiling and a dislike of generic openings,
  derived deterministically from the seed. Reply odds rise with must-have skills mentioned (named or
  implied), concrete evidence (metrics, "shipped/delivered"), answered screening questions and price
  under the ceiling; they fall for generic openings, guarantees/off-platform talk and over-ceiling
  prices. Interview/hire follow; after a reply the freelancer must message for the process to continue.
  The outcome plan is fixed at submit time from (seed, freelancer, job, text): chunking ticks does not
  change results. One tick step = 1 simulated hour.

## Data generator (`datagen.py`)

Seeded, no LLM, no network; same seed -> byte-identical tree (PDFs included). Layout and fields:
`docs/INTERFACES.md` section 1 and `docs/DATA_CARD.md`. Modules: `catalog_skills.py` (skill lexicon:
named + implied phrasings + code), `catalog_projects.py` (project fact sheets), `docs_gen.py`
(case studies / READMEs / code / reviews / CV), `proposals_gen.py`, `jobgen.py` (requirement sets ->
jobs with exact gold labels, scams, injections with canary tokens, duplicates), `market.py` (clients,
history jobs, pricing stats), `kaggle_import.py`.

Real data: `python -m gigsim.kaggle_import --kaggle-dir <folder>` sniffs title/description/skills/
budget/hourly/category columns from CSV/zip files (parsed as untrusted data, screened) and writes
`data/gigsim_seed/kaggle_sample.jsonl`; `datagen` then uses real titles, budgets and hourly rates for
1000 of the 1500 history jobs. The dump we have has no descriptions or skills, so those stay
synthetic/keyword-derived. `--no-kaggle` ignores the sample.

The local stand-in test set (`data/processed/local_test_<persona>.jsonl`, other seed, git-ignored) is
**not** the instructor's hidden set.
