# GraphQL API Gateway

**Client industry:** Media  
**Completed:** 2024-05  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: mobile and web teams called a dozen inconsistent endpoints. They described what they wanted as a one endpoint for mobile and web.

## What I built

It relied on a single query endpoint where clients pick the fields they need.
I set up a JavaScript server process handling concurrent requests.
Under the hood: TypeScript.
We ended up with an in-memory cache with expiry in front of the database.

## Outcome

Result: payload size down 55%; new screens needed no back-end changes.

## Stack

TypeScript

