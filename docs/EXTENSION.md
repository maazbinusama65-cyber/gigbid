# Signature extension: X2 Proposal experiments

GigBid can run two proposal *strategies* as an A/B test inside GigSim and report whether the difference in reply
rate is statistically significant. The point is that the freelancer learns which style works for their niche
instead of trusting an LLM judge.

## Strategies (config, not code: `agent/config.yaml: experiments`)
| id | Description |
|---|---|
| `evidence_dense` (A) | Opens with the client's problem, cites up to 3 portfolio items with figures, closes with a question |
| `concise_question` (B) | Opens with the client's problem, one strongest evidence item, two sentences on approach, closes with a question |

Both strategies still pass the same Verifier, Critic and Compliance Guard, so the experiment varies *style*, never
truthfulness. Strategy is a writer-node parameter (`style_variant` in the writer prompt context and the
deterministic composer), so adding a third strategy is a config edit.

## Design
* Fixed job set per persona (the local stand-in test set, seeded), each job is bid on **once under each strategy**
  in separate simulator resets with the same seed, so client decisions differ only because of the proposal.
* Outcome: GigSim reply (reply, interview or hire). Test: two-proportion z-test (`evals/metrics.two_proportion_z`)
  with Wilson intervals; effect sizes are reported even when p >= 0.05.
* Assignment is randomised per job (paired design) to avoid ordering effects; the seed is recorded in the results.

## Run
`python -m evals.runners.x2_experiment` writes `evals/results/x2_experiment.json`. The Analytics screen shows
the table; the report (section 7) cites that file only.

## Limits
GigSim clients are rule-based and deterministic given a seed, so a significant result here shows the *pipeline* can
detect an effect, not that the effect exists on a real marketplace. No claim is made about live Upwork.
