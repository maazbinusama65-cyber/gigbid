# Clinic Appointment Booking

**Client industry:** Healthcare  
**Completed:** 2023-05  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: receptionists booked by phone and no-shows were 18%. They described what they wanted as a patient scheduling web app.

## What I built

A key piece was an interactive front end split into reusable components.
This is where Django came in.
A key piece was a relational store with proper indexes and migrations.
This is where Celery came in.
On the engineering side I put in place stateless signed tokens with refresh rotation.

## Outcome

Result: no-shows fell to 9% with SMS and email reminders; 70% of bookings made online.

## A snippet

```ts
import { useState } from 'react';

export function ClinicAppointmentBookingItem({ items }: { items: string[] }) {
  const [q, setQ] = useState('');
  const shown = items.filter((i) => i.toLowerCase().includes(q.toLowerCase()));
  return (<div><input value={q} onChange={(e) => setQ(e.target.value)} /><ul>{shown.map((i) => <li key={i}>{i}</li>)}</ul></div>);
}
```

