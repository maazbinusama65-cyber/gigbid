# Two-sided Service Marketplace Backend

**Client industry:** Online marketplace  
**Completed:** 2022-06  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: an MVP built on spreadsheets could not take bookings. They described what they wanted as a gig listing and booking platform.

## What I built

We ended up with a JavaScript server process handling concurrent requests.
I used Express for this part.
A key piece was SQL tables with constraints, not loose files.
This is where REST API design came in.
Under the hood: JWT authentication.
The stack included Docker.

## Outcome

Result: launched in 9 weeks and handled 4,000 bookings in the first month.

## Stack

Express, REST API design, JWT authentication, Docker

## A snippet

```ts
import http from 'node:http';

const server = http.createServer((req, res) => {
  res.setHeader('content-type', 'application/json');
  res.end(JSON.stringify({ ok: true, path: req.url }));
});
server.listen(3000);
```

