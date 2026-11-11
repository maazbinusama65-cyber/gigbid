# Operations Admin Dashboard

**Client industry:** Logistics  
**Completed:** 2022-12  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: dispatchers juggled four spreadsheets. They described what they wanted as a internal back-office tool.

## What I built

This is where React came in.
A key piece was strictly typed JavaScript across client and server.
A key piece was versioned JSON endpoints with consistent errors and pagination.
Under the hood: Tailwind CSS.
A key piece was scripted real-browser checks of the main user journeys.

## Outcome

Result: order handling time cut by a third; 40 critical-path browser tests in CI.

## A snippet

```ts
import { useState } from 'react';

export function OperationsAdminDashboardItem({ items }: { items: string[] }) {
  const [q, setQ] = useState('');
  const shown = items.filter((i) => i.toLowerCase().includes(q.toLowerCase()));
  return (<div><input value={q} onChange={(e) => setQ(e.target.value)} /><ul>{shown.map((i) => <li key={i}>{i}</li>)}</ul></div>);
}
```

