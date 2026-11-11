# Internal Docs Chatbot

**Client industry:** Consulting  
**Completed:** 2024-01  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: staff pinged the same three people for policy answers. They described what they wanted as a knowledge base assistant.

## What I built

Under the hood: RAG.
It relied on chained prompts, tools and memory wired into one assistant.
We ended up with a managed nearest-neighbour index holding millions of vectors.
The stack included OpenAI API.
We ended up with a fast key-value layer for sessions and rate limits.

## Outcome

Result: deflected 58% of internal questions; median answer time under 6 seconds.

## Stack

RAG, OpenAI API

