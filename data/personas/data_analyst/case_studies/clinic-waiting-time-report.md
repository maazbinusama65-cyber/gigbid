# Clinic Waiting Time Report

**Client industry:** Healthcare  
**Completed:** 2024-08  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: managers sensed long waits but had no numbers. They described what they wanted as a patient flow reporting.

## What I built

The stack included SQL.
It relied on interactive drill-down dashboards for area managers.
A key piece was careful inference instead of eyeballing charts.
I used data cleaning for this part.

## Outcome

Result: identified two peak-hour bottlenecks; average wait fell 22%.

## A snippet

```sql
WITH monthly AS (
    SELECT date_trunc('month', created_at) AS m, customer_id, SUM(amount) AS spend
    FROM orders GROUP BY 1, 2
)
SELECT m, COUNT(*) AS buyers, AVG(spend) AS avg_spend,
       SUM(spend) OVER (ORDER BY m) AS running_total
FROM monthly GROUP BY m ORDER BY m;
```

