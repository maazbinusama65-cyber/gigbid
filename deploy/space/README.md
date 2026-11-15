---
title: GigBid
sdk: docker
app_port: 7860
pinned: false
short_description: Multi-agent freelancer copilot with human-approved proposals
---

# GigBid (live demo)

A multi-agent copilot that scans a freelancer marketplace, scores fit and risk, drafts a proposal in which every claim
cites the freelancer's own portfolio, and **stops for a human decision before anything is sent**.

This demo runs against a **simulated marketplace** (synthetic jobs and clients) with the deterministic **`stub` model
profile**: it shows the workflow, retrieval, safety checks and the approval gate, not the prose quality of an LLM.

**Demo login (public on purpose):** email `reviewer@gigbid.demo`, password `gigbid-demo`. The account is preloaded with the
`ai_ml` persona. Open a job from the inbox, analyse it, review the evidence behind each claim, then approve or edit the draft.

Source, evaluation results and the R&D report: https://github.com/maazbinusama65-cyber/gigbid
