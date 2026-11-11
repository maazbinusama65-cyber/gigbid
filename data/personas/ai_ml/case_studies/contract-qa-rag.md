# Contract Q&A over 40k PDFs

**Client industry:** Legal tech  
**Completed:** 2024-02  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: lawyers searched contracts with keyword search and missed clauses phrased differently. They described what they wanted as a legal document assistant.

## What I built

The stack included RAG.
I used embeddings for this part.
This is where Pinecone came in.
It relied on an orchestration layer for multi-step language-model calls.
We ended up with hosted large-language-model calls with retries and cost caps.
On the engineering side I put in place a typed async HTTP service with auto-generated docs.

## Outcome

Result: answers cited the right clause 91% of the time on a 300-question audit set.

