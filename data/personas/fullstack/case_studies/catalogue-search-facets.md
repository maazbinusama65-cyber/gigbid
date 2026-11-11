# Product Search with Facets

**Client industry:** Retail  
**Completed:** 2022-04  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: SQL LIKE search returned irrelevant results slowly. They described what they wanted as a fast filterable catalogue.

## What I built

I set up an inverted-index search service beside the main database.
It relied on an interactive front end split into reusable components.
It relied on backend services written in server-side JavaScript.
On the engineering side I put in place a relational store with proper indexes and migrations.

## Outcome

Result: search p95 of 80 ms over 600k products; zero-result queries cut by 45%.

## A snippet

```ts
export const query = (q: string, brand?: string) => ({
  query: { bool: { must: [{ multi_match: { query: q, fields: ['title^3', 'body'], fuzziness: 'AUTO' } }], filter: brand ? [{ term: { brand } }] : [] } },
  aggs: { brands: { terms: { field: 'brand' } } },
});
```

