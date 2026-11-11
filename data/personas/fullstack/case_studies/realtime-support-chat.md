# Realtime Support Chat

**Client industry:** SaaS  
**Completed:** 2022-10  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: email-only support left customers waiting hours. They described what they wanted as a live customer messaging widget.

## What I built

I set up a component-based single-page interface with hooks.
On the engineering side I put in place backend services written in server-side JavaScript.
I used WebSockets for this part.
On the engineering side I put in place an in-memory cache with expiry in front of the database.
TypeScript did the heavy lifting here.

## Outcome

Result: median first response of 90 seconds; 1,800 concurrent chats on one small instance.

## Stack

WebSockets, TypeScript

