# Event Ingestion API

**Client industry:** Ad tech  
**Completed:** 2022-08  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: partners needed to send millions of events a day. They described what they wanted as a usage tracking backend.

## What I built

I used MongoDB for this part.
I set up an HTTP API assembled from small route handlers.
I used Node.js for this part.
The stack included Docker.
On the engineering side I put in place cloud hosting with managed queues, storage and load balancing.

## Outcome

Result: sustained 4k events/s on two small containers.

## Stack

MongoDB, Node.js, Docker

## A snippet

```ts
import { MongoClient } from 'mongodb';

const col = new MongoClient(process.env.MONGO_URL!).db('event_ingestion_api').collection('events');
export const buildEvent = async () => { await col.createIndex({ ts: 1 }, { expireAfterSeconds: 7776000 }); };
```

