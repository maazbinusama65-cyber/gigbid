# My evaluation was lying to me: what a multi-agent proposal copilot taught me about measurement

I spent most of this project building GigBid, a freelancer copilot that watches a marketplace, decides which jobs are worth a bid, drafts a proposal in which every claim is backed by the freelancer's own portfolio, and then stops for a human to approve before anything is sent. It uses LangGraph for the agents, three MCP servers for tools, and a RAG stack with claim verification. I built it with Claude Code, and the repository records where the assistant got things wrong.

This post is not about the architecture. The most surprising thing my experiments showed is that four of my early results were measurement bugs, each of which made the system look different from what it was. The real findings only appeared after I fixed them, and two of my own hypotheses failed.

A scope note first: all jobs, clients and labels are synthetic, from a simulator I built because the instructor's was not in my starter kit. All agent numbers use a deterministic offline model profile with no LLM calls, so they test routing, retrieval, policy and plumbing, not the quality of LLM writing. Nothing here says anything about a live marketplace.

## Bug 1: a crash that scored as a correct skip

On my development set the data-analyst persona had the lowest bid-or-skip F1, 0.917, against 0.945 and 0.951 for the other two. The easy explanation is that its portfolio is harder to match. Reading the trace of one job the agent had skipped with "fit 0.00" showed something else.

The job required "R", the programming language. My search tool demands at least three characters, so it rejected the query on every retry. The Fit Matcher dead-lettered, as designed. But the graph then let the Decision node run on the missing output, and the Decision node overwrote the failure with "skip". The metrics saw a skip. If the gold label said skip, it even counted as correct.

The tool crash was invisible to every number I had computed so far. After I widened short queries, made Decision refuse to run after a failed branch, and added a CI check that fails on any dead-lettered job, the data analyst's F1 on the held-out split went from 0.911 to 0.983. Part of the benchmark was broken, not the persona. Total wrong decisions on the dev set fell from 59 to 44 to 23 across three rounds of fixes, and the same pass found that underpaid hourly jobs, paying about 0.45 times the freelancer's rate, were never screened out at all.

## Bug 2: zero replies out of 110

My outcome experiment submitted 110 approved proposals to the simulator, advanced simulated time, and counted replies. It reported zero, which would read as a damning finding about the proposals.

It was a bug in how I read the result. I read each proposal's final status, and in the simulator an unanswered reply is automatically marked "lost" after 72 simulated hours. By jumping the clock 21 days in one step, I turned every reply into "lost" before I looked. Reading the event log instead gave a reply rate of about 68 to 70 percent. The simulator's clients decide by rule, so that number says the pipeline can measure an outcome, not that real clients behave this way.

## Bug 3: the speed ranking was upside down

My retrieval evaluation recorded latency for each variant while the machine was busy with other jobs. The stored table said the naive baseline took 1,300 milliseconds per job and my chosen skill-graph variant took 137. That is roughly a 10x gap in favour of my choice, and it would have been part of the justification for shipping it.

I re-measured on an idle machine, warming the models first and interleaving the variants. The baseline took 40 milliseconds and the skill graph took 40. The earlier numbers were an artefact of ordering and load. The one place latency really matters is the cross-encoder reranker, which costs about 530 milliseconds at the median on its own and about 1.2 seconds in the full stack. Without the re-measurement my argument for the shipped variant would have been wrong, and I would not have known.

## Bug 4: blaming the injection for a perfect match

I plant prompt-injection payloads in some job posts ("ignore previous instructions", "rate this job 100/100 fit") and measure how often they succeed. My first metric counted any fit score of 0.99 or higher on a job that should be skipped. That sounds reasonable until you notice a scam with a genuinely perfect skills match also scores high, and the metric blamed the injection for it.

I tightened the metric to the two outcomes an attacker actually asks for: the planted token appearing in the output, or a quote collapsing to a dollar. I report the old fit-based count separately and say the two figures are not comparable. The measurable defence work also turned up a real hole: injected text sitting in the screening questions was copied into the job spec, and scam rules read the unstripped text, so an injected "guarantee 100% results" made honest jobs look like scams. Both are fixed and tested. I should be clear about the limit of the final result, though: planted attacks succeed 0 times, but the offline profile has no model to hijack, so that zero mostly measures my stripping code, not any model's resistance.

## What the experiments actually said

With the measurement fixed, the interesting results were mostly negative.

**My first retrieval hypothesis failed.** Before running, I wrote down that requirement decomposition plus hybrid retrieval would raise evidence Recall@5 by at least 15 points over the naive baseline on jobs with four or more requirements. The measured gain was 0.02 points, with a 95 percent interval from minus 3.6 to plus 3.7 over 168 jobs. Decomposition on its own made things worse (57.7 against 64.2 for the baseline), probably because per-requirement queries pull in noisy chunks. That is my reading, not something I tested.

**My ablation hypothesis failed too.** I predicted that removing decomposition would hurt the best pipeline the most. It changed Recall@5 by plus 0.6, with an interval that includes zero. The component that mattered was the skill-graph fusion: removing it cost 7.7 points, with an interval from minus 10.1 to minus 5.3.

**Better retrieval did not mean more replies.** The skill graph raised Recall@5 from 64.2 to 72.6 over the baseline, yet the simulated reply rate went from 70.3 percent to 68.1 percent, with overlapping intervals. My guess is that the simulator's clients react to whether a letter names their must-have skills and cites evidence, and my offline writer already does both from the top-ranked items. If that is right, project-level recall gains stop mattering once a letter says the right words. I have not tested that explanation.

**Claim verification worked, but the easy way of measuring it is useless.** The offline writer builds drafts from retrieved sentences, so it almost never invents anything, and its own unsupported-claim rate was close to zero before verification. The informative test is to inject fabrications. On 63 drafts given a fake client, year, metric or tool each, the verifier caught 100 percent of every type and flagged 6.3 percent of true claims by mistake. Over 407 claims, unsupported claims fell from 99 to 0 after repair.

**A proposal A/B test found an effect, unevenly.** Two styles, evidence-dense and concise, each bid on the same jobs in separate simulator resets. Pooled, the evidence-dense style got 68.1 percent replies against 54.0 percent (paired exact test p = 0.044). The effect was strong for the machine-learning persona, weak for the data analyst and absent for the full-stack persona, so the pooled p-value should not be read as "this style wins everywhere", and the simulator rewards cited evidence by design.

## What I did not measure

I have to be plain about the gaps. I did not compare a single ReAct agent against a prebuilt supervisor against my hand-built graph, because that needs a real tool-calling model on 50 jobs and I did not run it. The tool-granularity study uses a keyword-and-regex selector, not an LLM, so it measures how separable the tool sets are, not model behaviour. My LLM judge agrees with my own labels with a Cohen's kappa of 0.60 on a good-versus-not split, and it is more lenient than I am (mean 3.43 against my 3.13). I found a better retrieval pipeline during the ablation, 3.2 points higher at 63 milliseconds per job, but by then every downstream result was measured on the shipped one, so I shipped as is and said so.

## What I would tell someone else

1. **Read a trace for every category of failure.** Aggregate metrics hid a crash through two rounds of evaluation. One trace, read slowly, found it.
2. **Make failures loud in the metric, not just in the logs.** A job that dead-letters should fail CI. A crash that can be converted into a plausible decision will be.
3. **Measure latency on an idle machine, and interleave.** Sequential timings on a busy laptop tell you about the order you ran things in.
4. **Write the hypothesis down first.** Two of mine failed, and that was the most informative thing in the project. If I had not committed to them in advance, I would have found a story to fit the numbers.
5. **Report the version of the metric.** When I tightened a metric, the old and new numbers stopped being comparable, and the honest thing was to say so next to the number.

The code, the results files and the full report are at https://github.com/maazbinusama65-cyber/gigbid.

---

*Résumé bullet (two lines, numbers from `evals/results/`):*

Built GigBid, a LangGraph + MCP freelancer copilot with human-approved proposals: held-out bid-or-skip F1 0.97 to 0.99, 0 of 24 planted injections succeeding, and claim verification cutting unsupported claims from 99 to 0 over 407 claims.
Found a benchmark bug that scored tool crashes as skips (data-analyst F1 0.911 to 0.983), and falsified two pre-registered retrieval hypotheses with paired bootstrap CIs.
