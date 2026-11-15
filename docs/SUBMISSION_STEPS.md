# What is still manual (and how to do it)

These are the deliverables that need you, an account of yours, or your own judgement. Do them in this order.

## 1. Check the deadline first
The assignment says 12 Nov 2026, 11:59 PM PKT, one submission on Google Classroom. If that has passed, ask your
instructor about a late policy before anything else; the repo as pushed is the version to submit.

## 2. Label the 30 judge-calibration items (about 20 minutes, required for the kappa number)
```bash
python -m evals.runners.judge_calibration sample     # writes the 30 items to evals/results/
python -m evals.runners.judge_calibration label      # shows each proposal; type a score 1-5
python -m evals.runners.judge_calibration judge --provider groq   # needs GROQ_API_KEY in .env (optional)
python -m evals.runners.judge_calibration report     # kappa, or "awaiting human labels"
```
Rubric: 5 = specific, true to the portfolio, answers the client's need; 3 = relevant but generic or partly
unsupported; 1 = boilerplate, off-topic or fabricated. Label them yourself: the harness never invents labels or kappa.
Commit `evals/results/judge_calibration_*.json`, then run `python scripts/render_readme.py`.

## 3. Run the app once and look at it (10 minutes)
```bash
python -m venv .venv && .venv\Scripts\activate
make install && make seed
make gigsim          # terminal 1
make api             # terminal 2
make web             # terminal 3, then open http://localhost:5173
```
Sign in, open a job, analyse it, approve a draft. This is also your rehearsal for the demo video.

## 4. Record the 3-minute demo video
Show, in order: inbox, a job with its fit and risk, the proposal studio with evidence links, an edit, the approval
screen, the pipeline, the run viewer trace, one blocked scam or injected job. Use any screen recorder (Windows: Win+G).
Upload it (YouTube unlisted is fine), and add the link and a short GIF to `README.md` (the generator leaves it to you).

## 5. Deploy publicly with a reviewer login
The assignment wants a public URL. Simplest route: Render or Fly.io from `infra/docker/*.Dockerfile`
(`api`, `web`, `gigsim`, and the three `mcp-*` images). The images and `docker compose` file validate but **were not
built or run in my environment**, so expect to fix small build issues. Set env vars from `.env.example`
(`APP_SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`, `GIGSIM_API_TOKEN`, `MODEL_PROFILE=stub` unless you add an LLM key).
Create a reviewer account for the instructor and put the credentials in the Classroom submission, never in the repo.
Before sharing, check `GET /api/health`.

## 6. Real-LLM runs (optional but they make the report stronger)
Everything measured so far uses the offline `stub` profile. With a Groq key in `.env`:
```bash
python -m evals.runners.decision_eval --profile open --n 20 --tag groq-smoke
```
Watch your Groq quota. Report these separately from the stub numbers; do not mix them.

## 7. Write the report and the write-up
* R&D report PDF, at most 10 pages, 10 sections. The README plus `docs/ARCHITECTURE.md`, `docs/TOOLS.md`,
  `docs/EXTENSION.md`, `docs/AI_USAGE.md` and the tables in `evals/results/` hold the material. Cite only numbers
  that exist in `evals/results/`.
* Technical write-up (1,200 to 1,800 words) and publishing the Portfolio MCP server are separate deliverables.
* Answer R&D questions A (tool granularity), B (RAG ablation) and C (single agent vs supervisor vs graph). A and B
  have measured data; C is not measured yet. Say so rather than guessing.

## 8. Things I could not do and you should not skip
Live Upwork OAuth, the human panel, the viva, and the instructor's real `gigsim/`/personas/test set (swap them in and
re-run `python -m evals.runners.decision_eval --split dev`; keep `gigsim/` unmodified).

## 9. Submit
Public repo link, deployed URL plus reviewer login, video link, report PDF, write-up link: one Google Classroom post.
