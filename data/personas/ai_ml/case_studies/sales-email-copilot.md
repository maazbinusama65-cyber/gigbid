# LLM Email Drafting Assistant

**Client industry:** B2B sales  
**Completed:** 2024-06  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: reps wrote near-identical follow-ups and answered slowly. They described what they wanted as a sales outreach copilot.

## What I built

I used OpenAI API for this part.
It relied on carefully versioned instructions and few-shot examples for a language model.
I used LangChain for this part.
Under the hood: FastAPI.
I set up an in-memory cache with expiry in front of the database.

## Outcome

Result: reply time halved and 71% of drafts were sent with light edits.

