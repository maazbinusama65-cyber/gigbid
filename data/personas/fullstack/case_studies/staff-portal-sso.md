# Single Sign-on Rollout

**Client industry:** Education  
**Completed:** 2023-10  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: staff kept a separate password for every internal tool. They described what they wanted as a login overhaul for the staff portal.

## What I built

The stack included OAuth 2.0 / SSO.
I set up login sessions carried in short-lived signed tokens.
The stack included Node.js.
We ended up with a relational store with proper indexes and migrations.

## Outcome

Result: password-reset tickets fell 80%; 1,200 accounts migrated with no downtime.

## A snippet

```ts
export const authorizeUrl = (clientId: string, redirect: string, state: string) =>
  'https://accounts.example.com/oauth/authorize?' + new URLSearchParams({ response_type: 'code', client_id: clientId, redirect_uri: redirect, scope: 'openid email', state });
```

