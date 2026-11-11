# Regional Sales KPI Dashboard

**Client industry:** Retail  
**Completed:** 2023-02  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: area managers waited for a weekly emailed spreadsheet. They described what they wanted as a weekly revenue scorecard.

## What I built

I used Tableau for this part.
SQL did the heavy lifting here.
We ended up with targets versus actuals with traffic-light status.
This is where Excel came in.

## Outcome

Result: dashboard adopted by 45 managers; reporting prep time cut from 12 hours to 1.

## Stack

Tableau, SQL, Excel

## A snippet

```sql
-- custom SQL behind the workbook
SELECT region, store_id, DATE_TRUNC('week', sold_at) AS week, SUM(net_amount) AS revenue
FROM sales WHERE sold_at >= CURRENT_DATE - INTERVAL '26 weeks'
GROUP BY 1, 2, 3;
```

